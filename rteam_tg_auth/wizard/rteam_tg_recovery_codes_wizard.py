"""One-shot modal that displays recovery codes once.

Plain-text codes never get persisted -- they are returned by
``rteam.tg.binding.generate_recovery_codes`` as a list, then carried
into a ``codes_text`` field on this transient wizard so the form view
can render them. Closing the wizard is the user's commitment that they
saved the codes.
"""

from odoo import _, api, fields, models


class RteamTgRecoveryCodesWizard(models.TransientModel):
    _name = "rteam.tg.recovery.codes.wizard"
    _description = "Telegram 2FA Recovery Codes"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    binding_id = fields.Many2one("rteam.tg.binding", required=True, readonly=True)
    codes_text = fields.Text(string="Recovery codes", readonly=True)
    saved_confirm = fields.Boolean(
        string="I have saved these codes in a safe place.",
        default=False,
    )

    @api.model
    def render_for_binding(self, binding):
        plain = binding.generate_recovery_codes()
        wizard = self.create(
            {
                "user_id": binding.user_id.id,
                "binding_id": binding.id,
                "codes_text": "\n".join(plain),
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Telegram 2FA Recovery Codes"),
            "res_model": self._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context),
        }

    def action_close(self):
        # No-op except for closing the dialog -- the codes were already
        # generated and persisted (hashed) in render_for_binding.
        return {"type": "ir.actions.act_window_close"}
