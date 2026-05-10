"""Modal that shows the deep-link the user clicks to complete a Telegram bind."""

from odoo import api, fields, models


class RteamTgBindWizard(models.TransientModel):
    _name = "rteam.tg.bind.wizard"
    _description = "Bind Telegram Wizard"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    binding_id = fields.Many2one(
        "rteam.tg.binding",
        required=True,
        readonly=True,
    )
    bot_username = fields.Char(
        compute="_compute_bot_username",
        string="Bot",
    )
    bind_token = fields.Char(
        related="binding_id.bind_token",
        readonly=True,
    )
    expires_at = fields.Datetime(
        related="binding_id.bind_token_expires_at",
        readonly=True,
    )
    deep_link = fields.Char(
        compute="_compute_deep_link",
        readonly=True,
    )

    @api.depends("bind_token")
    def _compute_bot_username(self):
        username = (
            self.env["ir.config_parameter"].sudo().get_param("rteam_tg_auth.bot_username") or ""
        )
        for wiz in self:
            wiz.bot_username = username

    @api.depends("bot_username", "bind_token")
    def _compute_deep_link(self):
        for wiz in self:
            if wiz.bot_username and wiz.bind_token:
                wiz.deep_link = f"https://t.me/{wiz.bot_username}?start={wiz.bind_token}"
            else:
                wiz.deep_link = False

    def action_open_telegram(self):
        """Return a URL action so the deep-link opens in the user's browser/Telegram."""
        self.ensure_one()
        if not self.deep_link:
            return False
        return {
            "type": "ir.actions.act_url",
            "url": self.deep_link,
            "target": "new",
        }

    def action_check_status(self):
        """Reload the wizard so the user sees whether the binding flipped to active."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context),
        }
