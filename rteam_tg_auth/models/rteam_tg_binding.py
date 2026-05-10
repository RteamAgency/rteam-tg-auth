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

# Alphabet for recovery codes: skip ambiguous I/O/0/1 so codes are
# legible across fonts and easy to dictate over a phone call.
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_GROUP_LEN = 4
RECOVERY_GROUPS = 3  # XXXX-XXXX-XXXX
RECOVERY_CODE_COUNT = 10


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

    @staticmethod
    def _normalize_recovery_code(value):
        """Strip whitespace + dashes + lowercase noise so users can type
        ``abcd efgh ijkl`` or ``ABCDEFGHIJKL`` and we still recognize it
        against ``ABCD-EFGH-IJKL`` storage."""
        if not value:
            return ""
        return "".join(c for c in value.upper() if c in RECOVERY_ALPHABET)

    @staticmethod
    def _format_recovery_code(raw):
        """Insert dashes every RECOVERY_GROUP_LEN characters."""
        return "-".join(
            raw[i : i + RECOVERY_GROUP_LEN] for i in range(0, len(raw), RECOVERY_GROUP_LEN)
        )

    # ---------------------------------------------------------------- recovery

    def generate_recovery_codes(self):
        """Generate ``RECOVERY_CODE_COUNT`` fresh codes, replace any prior set.

        Returns the list of plain-text codes -- the caller MUST show these
        to the user once; only the SHA-256 hashes survive on the binding.
        """
        self.ensure_one()
        if self.state != "active":
            raise UserError(
                _("Bind Telegram first; recovery codes only make sense for an active binding.")
            )
        plain_codes = []
        hashes = []
        for _i in range(RECOVERY_CODE_COUNT):
            raw = "".join(
                secrets.choice(RECOVERY_ALPHABET)
                for _j in range(RECOVERY_GROUP_LEN * RECOVERY_GROUPS)
            )
            plain_codes.append(self._format_recovery_code(raw))
            hashes.append(self._hash_code(raw))
        self.sudo().write({"recovery_codes": "\n".join(hashes)})
        return plain_codes

    def _verify_recovery_code(self, submitted):
        """Try the submitted value as a recovery code; consume on match."""
        self.ensure_one()
        normalized = self._normalize_recovery_code(submitted)
        if not normalized or not self.recovery_codes:
            return False
        target = self._hash_code(normalized)
        kept = []
        matched = False
        for stored in (self.recovery_codes or "").splitlines():
            stored = stored.strip()
            if not stored:
                continue
            if not matched and stored == target:
                matched = True  # consume one code
                continue
            kept.append(stored)
        if not matched:
            return False
        self.sudo().write({"recovery_codes": "\n".join(kept)})
        return True

    def recovery_codes_remaining(self):
        self.ensure_one()
        return sum(1 for line in (self.recovery_codes or "").splitlines() if line.strip())

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
        """Return True if ``submitted_code`` matches the live pending code,
        OR a stored recovery code (consumed on match).

        Pending-code path: on success clears the pending code; on failure
        increments attempts and invalidates the code after the attempt
        limit. Recovery path: tries when no live pending code OR when the
        pending check fails. Recovery codes are single-use and cleared
        from the stored set on consume.
        """
        self.ensure_one()
        if not submitted_code:
            return False
        normalized = submitted_code.strip()

        # Recovery code is dash-grouped, longer than 6 digits, and not
        # purely numeric. Try the recovery path first when the input
        # shape clearly is not a 6-digit code.
        looks_like_recovery = len(normalized) > 6 or any(
            not c.isdigit() and c not in "- " for c in normalized
        )
        if looks_like_recovery and self._verify_recovery_code(normalized):
            self.sudo().write({"last_used_at": fields.Datetime.now()})
            self.env["rteam.tg.audit"].sudo().create(
                {
                    "user_id": self.user_id.id,
                    "binding_id": self.id,
                    "event": "recovery_used",
                    "ip": ip,
                    "user_agent": user_agent,
                    "note": f"Recovery codes remaining: {self.recovery_codes_remaining()}",
                }
            )
            return True

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
