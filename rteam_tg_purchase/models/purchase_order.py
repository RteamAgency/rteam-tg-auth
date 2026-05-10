"""Hook button_confirm to gate large POs through Telegram approval."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    rteam_tg_pending_request_id = fields.Many2one(
        "rteam.tg.approval.request",
        compute="_compute_pending_request",
        store=False,
    )
    rteam_tg_has_pending = fields.Boolean(
        compute="_compute_pending_request",
        store=False,
    )

    @api.depends("amount_total", "state")
    def _compute_pending_request(self):
        Approval = self.env["rteam.tg.approval.request"].sudo()
        for order in self:
            req = Approval.search(
                [
                    ("source_model", "=", "purchase.order"),
                    ("source_id", "=", order.id),
                    ("state", "=", "pending"),
                ],
                order="create_date desc",
                limit=1,
            )
            order.rteam_tg_pending_request_id = req.id or False
            order.rteam_tg_has_pending = bool(req)

    # ---------------------------------------------------------------- helpers

    @api.model
    def _rteam_tg_purchase_settings(self):
        params = self.env["ir.config_parameter"].sudo()
        try:
            threshold = float(params.get_param("rteam_tg_purchase.threshold", "0") or "0")
        except (TypeError, ValueError):
            threshold = 0.0
        approver_id = params.get_param("rteam_tg_purchase.approver_user_id")
        try:
            approver_id = int(approver_id) if approver_id else 0
        except (TypeError, ValueError):
            approver_id = 0
        approver = self.env["res.users"].sudo().browse(approver_id) if approver_id else None
        return threshold, approver

    def _rteam_tg_should_gate(self):
        """Return the approver if this PO must be gated; falsy otherwise."""
        self.ensure_one()
        threshold, approver = self._rteam_tg_purchase_settings()
        if not approver or not approver.exists():
            return False
        if approver.id == self.env.user.id:
            # Don't ask people to approve their own POs.
            return False
        if self.amount_total < threshold:
            return False
        return approver

    # ---------------------------------------------------------------- override

    def button_confirm(self):
        """Intercept confirm: if the amount crosses the threshold and an
        approver is configured, fire a Telegram approval and stop here.

        The original confirm runs from ``on_rteam_tg_approval_resolved``
        once the approver taps Approve in Telegram.
        """
        gated_orders = self.env["purchase.order"]
        passthrough_orders = self.env["purchase.order"]
        for order in self:
            approver = order._rteam_tg_should_gate()
            if approver:
                gated_orders |= order
            else:
                passthrough_orders |= order

        result = (
            super(PurchaseOrder, passthrough_orders).button_confirm()
            if passthrough_orders
            else True
        )

        for order in gated_orders:
            existing = order.rteam_tg_pending_request_id
            if existing:
                raise UserError(
                    _(
                        "%(po)s already has a pending approval request in Telegram. "
                        "Wait for it to be answered, or cancel it from the Telegram "
                        "Approvals menu."
                    )
                    % {"po": order.display_name}
                )
            approver = order._rteam_tg_should_gate()
            summary = order._rteam_tg_summary()
            self.env["rteam.tg.approval.request"].sudo().request_approval(
                source_record=order,
                approver_user=approver,
                summary=summary,
                requester_user=self.env.user,
            )
            order.message_post(
                body=_(
                    "Telegram approval request sent to %(approver)s. "
                    "The order will be confirmed when they tap Approve."
                )
                % {"approver": approver.display_name},
                subtype_xmlid="mail.mt_note",
            )

        if gated_orders and not passthrough_orders:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "info",
                    "sticky": False,
                    "title": _("Awaiting Telegram approval"),
                    "message": _(
                        "Approval request delivered. The order stays in its current state until the approver taps in Telegram."
                    ),
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return result

    def _rteam_tg_summary(self):
        self.ensure_one()
        currency = self.currency_id.name or ""
        partner = self.partner_id.display_name or "-"
        line_count = len(self.order_line)
        return (
            f"Vendor: {partner}\n"
            f"Total: {self.amount_total:,.2f} {currency}\n"
            f"Lines: {line_count}\n"
            f"Reference: {self.partner_ref or '-'}"
        )

    # ---------------------------------------------------------------- callback

    def on_rteam_tg_approval_resolved(self, request, new_state):
        """Source-model hook called by ``rteam.tg.approval.request._resolve``.

        ``new_state`` is one of approved / rejected / expired / cancelled.
        """
        self.ensure_one()
        if new_state == "approved":
            try:
                # Bypass the gate to avoid a recursive approval loop.
                super(PurchaseOrder, self.with_context(rteam_tg_skip_gate=True)).button_confirm()
            except Exception as e:  # noqa: BLE001
                _logger.exception("rteam_tg_purchase: button_confirm after approve failed")
                self.message_post(
                    body=_("Telegram approval came back APPROVED but auto-confirm failed: %s") % e,
                    subtype_xmlid="mail.mt_note",
                )
                return
            self.message_post(
                body=_("Approved via Telegram by %(approver)s. Purchase order confirmed.")
                % {"approver": request.approver_user_id.display_name},
                subtype_xmlid="mail.mt_note",
            )
        elif new_state == "rejected":
            self.message_post(
                body=_("Rejected via Telegram by %(approver)s. Purchase order stays in %(state)s.")
                % {
                    "approver": request.approver_user_id.display_name,
                    "state": self.state,
                },
                subtype_xmlid="mail.mt_note",
            )
        elif new_state == "expired":
            self.message_post(
                body=_(
                    "Telegram approval request expired without an answer. "
                    "Re-confirm the order to send a new request."
                ),
                subtype_xmlid="mail.mt_note",
            )

    # ---------------------------------------------------------------- view actions

    def rteam_tg_open_pending_request(self):
        self.ensure_one()
        if not self.rteam_tg_pending_request_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "rteam.tg.approval.request",
            "res_id": self.rteam_tg_pending_request_id.id,
            "view_mode": "form",
            "target": "current",
        }
