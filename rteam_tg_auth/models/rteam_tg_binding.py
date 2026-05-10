"""User-to-Telegram binding.

One active binding per Odoo user. Holds the chat_id that outbound 2FA codes
are delivered to, plus the short-lived ``bind_token`` consumed during the
handshake and the recovery codes generated at enrollment.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError

from .telegram_api import TelegramApiError, send_message

_logger = logging.getLogger(__name__)

DEFAULT_CODE_TTL = 300  # seconds
DEFAULT_CODE_ATTEMPT_LIMIT = 5
DEFAULT_RATE_LIMIT_WINDOW = 900  # seconds
DEFAULT_RATE_LIMIT_MAX = 5


class RteamTgBinding(models.Model):
    _name = "rteam.tg.binding"
    _description = "Rteam Telegram 2FA Binding"
    _rec_name = "user_id"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="user_id.company_id",
        store=True,
        index=True,
    )

    state = fields.Selection(
        [
            ("pending", "Awaiting bind"),
            ("active", "Active"),
            ("revoked", "Revoked"),
        ],
        default="pending",
        required=True,
        index=True,
    )

    chat_id = fields.Char(
        string="Telegram Chat ID",
        help="Numeric Telegram chat identifier where 2FA codes are delivered.",
    )
    tg_username = fields.Char(string="Telegram Username")

    bind_token = fields.Char(
        string="Bind Token",
        help="Short-lived token the user sends to the bot to complete the handshake.",
    )
    bind_token_expires_at = fields.Datetime()

    bound_at = fields.Datetime()
    last_used_at = fields.Datetime()

    recovery_codes = fields.Text(
        string="Recovery Codes",
        help="Newline-separated single-use codes. Stored hashed on enrollment.",
    )

    pending_code_hash = fields.Char(string="Pending Code Hash")
    pending_code_expires_at = fields.Datetime()
    pending_code_attempts = fields.Integer(default=0)

    _sql_constraints = [
        (
            "user_unique_active",
            "unique(user_id)",
            "A user can only have one Telegram binding.",
        ),
    ]

    # ---------------------------------------------------------------- helpers

    def _params(self):
        return self.env["ir.config_parameter"].sudo()

    def _code_ttl_seconds(self):
        try:
            return int(self._params().get_param("rteam_tg_auth.code_ttl_seconds", DEFAULT_CODE_TTL))
        except (TypeError, ValueError):
            return DEFAULT_CODE_TTL

    def _code_attempt_limit(self):
        try:
            return int(
                self._params().get_param(
                    "rteam_tg_auth.code_attempt_limit", DEFAULT_CODE_ATTEMPT_LIMIT
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_CODE_ATTEMPT_LIMIT

    def _rate_limit_window(self):
        try:
            return int(
                self._params().get_param(
                    "rteam_tg_auth.rate_limit_window_seconds", DEFAULT_RATE_LIMIT_WINDOW
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_RATE_LIMIT_WINDOW

    def _rate_limit_max(self):
        try:
            return int(
                self._params().get_param("rteam_tg_auth.rate_limit_max", DEFAULT_RATE_LIMIT_MAX)
            )
        except (TypeError, ValueError):
            return DEFAULT_RATE_LIMIT_MAX

    @staticmethod
    def _hash_code(code):
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------- challenge

    def _is_pending_code_fresh(self):
        self.ensure_one()
        if not self.pending_code_hash or not self.pending_code_expires_at:
            return False
        return self.pending_code_expires_at > fields.Datetime.now()

    def _check_rate_limit(self):
        """Raise UserError if the user has burned the per-window send quota."""
        self.ensure_one()
        window_start = fields.Datetime.now() - timedelta(seconds=self._rate_limit_window())
        sent_recently = (
            self.env["rteam.tg.audit"]
            .sudo()
            .search_count(
                [
                    ("user_id", "=", self.user_id.id),
                    ("event", "=", "challenge_sent"),
                    ("create_date", ">=", window_start),
                ]
            )
        )
        if sent_recently >= self._rate_limit_max():
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": self.user_id.id,
                    "binding_id": self.id,
                    "event": "rate_limited",
                    "note": f"Sent {sent_recently} codes in last {self._rate_limit_window()}s",
                }
            )
            raise UserError(
                _(
                    "Too many code requests. Wait a few minutes before trying again, "
                    "or use a recovery code if you have one."
                )
            )

    def issue_challenge(self, ip=None, user_agent=None):
        """Generate a fresh 6-digit code, store its hash, deliver to Telegram.

        Idempotent within the TTL window: if a fresh pending code already
        exists this is a no-op (returns False) so refreshing the form does
        not spam the user with codes. Returns True if a new code was sent.
        """
        self.ensure_one()
        if self.state != "active" or not self.chat_id:
            raise UserError(_("This user is not bound to Telegram."))
        if self._is_pending_code_fresh():
            return False
        self._check_rate_limit()

        code = f"{secrets.randbelow(1_000_000):06d}"
        token = self.env["ir.config_parameter"].sudo().get_param("rteam_tg_auth.bot_token")
        if not token:
            raise UserError(_("The Telegram bot is not configured. Contact your administrator."))

        try:
            msg = send_message(
                token,
                self.chat_id,
                _(
                    "Your Odoo login code is:\n\n%(code)s\n\n"
                    "It expires in %(minutes)s minutes. If you did not request this, "
                    "tell your administrator immediately."
                )
                % {"code": code, "minutes": max(1, self._code_ttl_seconds() // 60)},
            )
        except TelegramApiError as e:
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": self.user_id.id,
                    "binding_id": self.id,
                    "event": "challenge_sent",
                    "ip": ip,
                    "user_agent": user_agent,
                    "note": f"DELIVERY FAILED: {e}",
                }
            )
            raise UserError(
                _(
                    "Could not deliver the code to Telegram:\n\n%(err)s\n\n"
                    "Use a recovery code if you have one, or ask an administrator "
                    "to reset your binding."
                )
                % {"err": str(e)}
            ) from e

        expires_at = fields.Datetime.now() + timedelta(seconds=self._code_ttl_seconds())
        self.write(
            {
                "pending_code_hash": self._hash_code(code),
                "pending_code_expires_at": expires_at,
                "pending_code_attempts": 0,
            }
        )
        self.env["rteam.tg.audit"].sudo().create(
            {
                "user_id": self.user_id.id,
                "binding_id": self.id,
                "event": "challenge_sent",
                "ip": ip,
                "user_agent": user_agent,
                "tg_message_id": str(msg.get("message_id") or ""),
                "note": f"Code TTL {self._code_ttl_seconds()}s",
            }
        )
        return True

    def verify_challenge(self, submitted_code, ip=None, user_agent=None):
        """Return True if ``submitted_code`` matches the live pending code.

        On success, clears the pending code so it cannot be reused.
        On failure, increments attempts and clears the pending code once the
        attempt limit is hit so the next try forces a fresh code.
        """
        self.ensure_one()
        if not submitted_code:
            return False
        normalized = submitted_code.strip()
        if not self._is_pending_code_fresh():
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": self.user_id.id,
                    "binding_id": self.id,
                    "event": "challenge_rejected",
                    "ip": ip,
                    "user_agent": user_agent,
                    "note": "No live code (expired or never issued)",
                }
            )
            return False
        if self._hash_code(normalized) == self.pending_code_hash:
            self.write(
                {
                    "pending_code_hash": False,
                    "pending_code_expires_at": False,
                    "pending_code_attempts": 0,
                    "last_used_at": fields.Datetime.now(),
                }
            )
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": self.user_id.id,
                    "binding_id": self.id,
                    "event": "challenge_accepted",
                    "ip": ip,
                    "user_agent": user_agent,
                }
            )
            return True

        self.pending_code_attempts += 1
        attempts_left = self._code_attempt_limit() - self.pending_code_attempts
        if attempts_left <= 0:
            self.write(
                {
                    "pending_code_hash": False,
                    "pending_code_expires_at": False,
                    "pending_code_attempts": 0,
                }
            )
        self.env["rteam.tg.audit"].sudo().create(
            {
                "user_id": self.user_id.id,
                "binding_id": self.id,
                "event": "challenge_rejected",
                "ip": ip,
                "user_agent": user_agent,
                "note": f"Wrong code, {max(attempts_left, 0)} attempts left",
            }
        )
        return False
