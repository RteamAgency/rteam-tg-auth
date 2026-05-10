"""Integration tests for purchase.order Telegram-gated confirm flow."""

from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPurchaseGate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("rteam_tg_auth.bot_token", "TEST_TOKEN")
        params.set_param("rteam_tg_auth.webhook_secret", "deadbeef" * 4)
        params.set_param("rteam_tg_auth.bot_username", "test_bot")

        cls.requester = cls.env["res.users"].create({"name": "Buyer Joe", "login": "buyer_joe_t4"})
        cls.approver = cls.env["res.users"].create({"name": "CFO Anna", "login": "cfo_anna_t4"})
        cls.env["rteam.tg.binding"].create(
            {
                "user_id": cls.approver.id,
                "state": "active",
                "chat_id": "555555",
                "bound_at": fields.Datetime.now(),
            }
        )
        cls.vendor = cls.env["res.partner"].create({"name": "Vendor X", "supplier_rank": 1})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Widget",
                "type": "consu",
                "purchase_ok": True,
                "list_price": 50.0,
                "standard_price": 40.0,
            }
        )

    def _po(self, qty, price, requester=None):
        po = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "user_id": (requester or self.requester).id,
                "order_line": [
                    (0, 0, {"product_id": self.product.id, "product_qty": qty, "price_unit": price})
                ],
            }
        )
        return po

    def _set_gate(self, threshold, approver_id):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("rteam_tg_purchase.threshold", str(threshold))
        params.set_param("rteam_tg_purchase.approver_user_id", str(approver_id))

    def _patched_tg(self):
        return patch.multiple(
            "odoo.addons.rteam_tg_auth.models.rteam_tg_approval_request",
            send_message_with_buttons=MagicMock(return_value={"message_id": 100}),
            answer_callback_query=MagicMock(return_value=True),
            edit_message_reply_markup=MagicMock(return_value=True),
        )

    # --------------------------------------------------------------- pass-through

    def test_below_threshold_confirms_normally(self):
        self._set_gate(threshold=10000, approver_id=self.approver.id)
        po = self._po(qty=1, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        po.refresh()
        self.assertEqual(po.state, "purchase")
        # No approval row created.
        self.assertEqual(
            self.env["rteam.tg.approval.request"].search_count(
                [("source_model", "=", "purchase.order"), ("source_id", "=", po.id)]
            ),
            0,
        )

    def test_no_approver_configured_passes_through(self):
        self._set_gate(threshold=10, approver_id=0)  # no approver set
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        po.refresh()
        self.assertEqual(po.state, "purchase")

    def test_self_approve_passes_through(self):
        self._set_gate(threshold=10, approver_id=self.requester.id)  # buyer == approver
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        po.refresh()
        self.assertEqual(po.state, "purchase")

    def test_self_approve_posts_explanation_to_chatter(self):
        # Same scenario as above, but assert that the gate explains
        # itself to the chatter so the user does not wonder why no
        # Telegram message arrived.
        self._set_gate(threshold=10, approver_id=self.requester.id)
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        msgs = self.env["mail.message"].search(
            [("model", "=", "purchase.order"), ("res_id", "=", po.id)]
        )
        bodies = " ".join(m.body or "" for m in msgs)
        self.assertIn("self-approval", bodies)

    def test_below_threshold_posts_no_skip_explanation(self):
        # Below-threshold orders should NOT spam the chatter with a
        # "no approval requested" note -- silence is correct here.
        self._set_gate(threshold=10000, approver_id=self.approver.id)
        po = self._po(qty=1, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        msgs = self.env["mail.message"].search(
            [("model", "=", "purchase.order"), ("res_id", "=", po.id)]
        )
        bodies = " ".join(m.body or "" for m in msgs)
        self.assertNotIn("self-approval", bodies)
        self.assertNotIn("No Telegram approval", bodies)

    # --------------------------------------------------------------- gated

    def test_above_threshold_creates_pending_request_and_holds_state(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        po.refresh()
        self.assertEqual(po.state, "draft", "PO must be held in draft until approval")
        req = self.env["rteam.tg.approval.request"].search(
            [("source_model", "=", "purchase.order"), ("source_id", "=", po.id)],
            order="create_date desc",
            limit=1,
        )
        self.assertTrue(req)
        self.assertEqual(req.state, "pending")
        self.assertEqual(req.approver_user_id, self.approver)
        self.assertEqual(req.requester_user_id, self.requester)

    def test_re_confirm_with_pending_raises(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        with self._patched_tg():
            with self.assertRaises(UserError):
                po.with_user(self.requester).button_confirm()

    def test_approve_callback_confirms_po(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        req = self.env["rteam.tg.approval.request"].search(
            [("source_model", "=", "purchase.order"), ("source_id", "=", po.id)],
            limit=1,
        )
        with self._patched_tg():
            ok = req._resolve("y", callback_query_id="cbq", actor_chat_id="555555")
        self.assertTrue(ok)
        po.refresh()
        self.assertEqual(po.state, "purchase", "Approve must trigger super().button_confirm")
        # Chatter note exists.
        msgs = self.env["mail.message"].search(
            [("model", "=", "purchase.order"), ("res_id", "=", po.id)]
        )
        bodies = " ".join(m.body or "" for m in msgs)
        self.assertIn("Approved via Telegram", bodies)

    def test_reject_callback_keeps_po_in_draft(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        req = self.env["rteam.tg.approval.request"].search(
            [("source_model", "=", "purchase.order"), ("source_id", "=", po.id)],
            limit=1,
        )
        with self._patched_tg():
            ok = req._resolve("n", callback_query_id="cbq", actor_chat_id="555555")
        self.assertTrue(ok)
        po.refresh()
        self.assertEqual(po.state, "draft", "Reject must NOT confirm")
        msgs = self.env["mail.message"].search(
            [("model", "=", "purchase.order"), ("res_id", "=", po.id)]
        )
        bodies = " ".join(m.body or "" for m in msgs)
        self.assertIn("Rejected via Telegram", bodies)

    def test_pending_request_reflected_on_po_form(self):
        self._set_gate(threshold=100, approver_id=self.approver.id)
        po = self._po(qty=10, price=100.0)
        with self._patched_tg():
            po.with_user(self.requester).button_confirm()
        po.refresh()
        self.assertTrue(po.rteam_tg_has_pending)
        self.assertTrue(po.rteam_tg_pending_request_id)
