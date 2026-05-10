"""Tests for rteam.tg.approval.request signed callback + state machine."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestApprovalSignature(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("rteam_tg_auth.bot_token", "TEST_TOKEN")
        params.set_param("rteam_tg_auth.webhook_secret", "deadbeef" * 4)
        cls.Approval = cls.env["rteam.tg.approval.request"]

    def test_sign_is_deterministic_per_secret_payload(self):
        a = self.Approval._sign(42, "y")
        b = self.Approval._sign(42, "y")
        c = self.Approval._sign(42, "n")
        d = self.Approval._sign(43, "y")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)
        self.assertEqual(len(a), 8)

    def test_sign_returns_empty_when_secret_missing(self):
        self.env["ir.config_parameter"].sudo().set_param("rteam_tg_auth.webhook_secret", "")
        self.assertEqual(self.Approval._sign(42, "y"), "")

    def test_verify_signed_callback_rejects_garbage(self):
        for bad in ("", None, "not_signed", "a:abc:y:deadbeef", "wrong:1:y:" + "0" * 8):
            req, action = self.Approval._verify_signed_callback(bad)
            self.assertIsNone(req)
            self.assertIsNone(action)

    def test_verify_signed_callback_rejects_unknown_action(self):
        req_id = 999  # any id
        sig = self.Approval._sign(req_id, "z")
        req, action = self.Approval._verify_signed_callback(f"a:{req_id}:z:{sig}")
        self.assertIsNone(req)
        self.assertIsNone(action)

    def test_verify_signed_callback_rejects_forged_signature(self):
        # Pretend the attacker knows request 1 and the format but not the secret.
        req, action = self.Approval._verify_signed_callback("a:1:y:00000000")
        self.assertIsNone(req)
        self.assertIsNone(action)


class TestApprovalLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("rteam_tg_auth.bot_token", "TEST_TOKEN")
        params.set_param("rteam_tg_auth.webhook_secret", "deadbeef" * 4)
        cls.requester = cls.env["res.users"].create({"name": "Req User", "login": "req_user_t2"})
        cls.approver = cls.env["res.users"].create({"name": "Appr User", "login": "appr_user_t2"})
        cls.env["rteam.tg.binding"].create(
            {
                "user_id": cls.approver.id,
                "state": "active",
                "chat_id": "999999",
                "bound_at": fields.Datetime.now(),
            }
        )
        # Use res.partner as a stand-in source record (any singleton with display_name).
        cls.source = cls.env["res.partner"].create({"name": "Source Partner"})

    def _patched(self):
        return patch.multiple(
            "odoo.addons.rteam_tg_auth.models.rteam_tg_approval_request",
            send_message_with_buttons=MagicMock(return_value={"message_id": 7}),
            answer_callback_query=MagicMock(return_value=True),
            edit_message_reply_markup=MagicMock(return_value=True),
        )

    def test_request_approval_creates_pending_row_and_audit(self):
        Approval = self.env["rteam.tg.approval.request"]
        with self._patched():
            req = Approval.request_approval(
                source_record=self.source,
                approver_user=self.approver,
                summary="Pls approve",
                requester_user=self.requester,
            )
        self.assertEqual(req.state, "pending")
        self.assertEqual(req.tg_chat_id, "999999")
        self.assertEqual(req.tg_message_id, "7")
        self.assertEqual(req.requester_user_id, self.requester)
        self.assertEqual(req.approver_user_id, self.approver)
        audit = self.env["rteam.tg.audit"].search(
            [("event", "=", "approval_requested"), ("user_id", "=", self.approver.id)],
            order="create_date desc",
            limit=1,
        )
        self.assertTrue(audit)

    def test_request_approval_refuses_when_no_active_binding(self):
        no_bind_user = self.env["res.users"].create({"name": "No Bind", "login": "no_bind_t2"})
        with self.assertRaises(UserError):
            self.env["rteam.tg.approval.request"].request_approval(
                source_record=self.source,
                approver_user=no_bind_user,
                summary="x",
            )

    def test_resolve_approve_flips_state_and_calls_source_hook(self):
        Approval = self.env["rteam.tg.approval.request"]
        with self._patched():
            req = Approval.request_approval(
                source_record=self.source,
                approver_user=self.approver,
                summary="x",
                requester_user=self.requester,
            )
        # Stub the source-model hook on res.partner.
        called = {}

        def hook(self_, request, new_state):
            called["request_id"] = request.id
            called["new_state"] = new_state

        with patch.object(type(self.source), "on_rteam_tg_approval_resolved", hook, create=True):
            with self._patched():
                ok = req._resolve("y", callback_query_id="cbq1", actor_chat_id="999999")
        self.assertTrue(ok)
        self.assertEqual(req.state, "approved")
        self.assertEqual(called.get("new_state"), "approved")

    def test_resolve_rejects_wrong_chat_id(self):
        Approval = self.env["rteam.tg.approval.request"]
        with self._patched():
            req = Approval.request_approval(
                source_record=self.source,
                approver_user=self.approver,
                summary="x",
                requester_user=self.requester,
            )
        with self._patched():
            ok = req._resolve("y", callback_query_id="cbq2", actor_chat_id="000000")
        self.assertFalse(ok)
        self.assertEqual(req.state, "pending", "wrong chat must not flip state")

    def test_resolve_rejects_already_consumed(self):
        Approval = self.env["rteam.tg.approval.request"]
        with self._patched():
            req = Approval.request_approval(
                source_record=self.source,
                approver_user=self.approver,
                summary="x",
                requester_user=self.requester,
            )
            req._resolve("y", callback_query_id="cbq3", actor_chat_id="999999")
            # Second tap on the same request should be a no-op.
            ok = req._resolve("y", callback_query_id="cbq4", actor_chat_id="999999")
        self.assertFalse(ok)
        self.assertEqual(req.state, "approved")

    def test_resolve_rejects_expired(self):
        Approval = self.env["rteam.tg.approval.request"]
        with self._patched():
            req = Approval.request_approval(
                source_record=self.source,
                approver_user=self.approver,
                summary="x",
                requester_user=self.requester,
            )
        req.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        with self._patched():
            ok = req._resolve("y", callback_query_id="cbq5", actor_chat_id="999999")
        self.assertFalse(ok)
        self.assertEqual(req.state, "expired")

    def test_cron_expire_stale_only_touches_pending_overdue(self):
        Approval = self.env["rteam.tg.approval.request"]
        with self._patched():
            stale = Approval.request_approval(
                source_record=self.source,
                approver_user=self.approver,
                summary="stale",
                requester_user=self.requester,
            )
            fresh = Approval.request_approval(
                source_record=self.source,
                approver_user=self.approver,
                summary="fresh",
                requester_user=self.requester,
            )
        stale.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        with self._patched():
            count = Approval._cron_expire_stale()
        self.assertGreaterEqual(count, 1)
        stale.refresh()
        fresh.refresh()
        self.assertEqual(stale.state, "expired")
        self.assertEqual(fresh.state, "pending")
