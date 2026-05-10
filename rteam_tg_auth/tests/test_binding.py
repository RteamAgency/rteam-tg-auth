"""Tests for rteam.tg.binding challenge issue / verify and rate limit."""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestBindingChallenge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env["ir.config_parameter"].sudo()
        cls.params.set_param("rteam_tg_auth.bot_token", "TEST_TOKEN")
        cls.params.set_param("rteam_tg_auth.bot_username", "test_bot")
        cls.user = cls.env["res.users"].create({"name": "Bound User", "login": "bound_user_t1"})
        cls.binding = cls.env["rteam.tg.binding"].create(
            {
                "user_id": cls.user.id,
                "state": "active",
                "chat_id": "123456",
                "tg_username": "tg_user",
                "bound_at": fields.Datetime.now(),
            }
        )

    def _patched_send(self, return_value=None):
        return patch(
            "odoo.addons.rteam_tg_auth.models.rteam_tg_binding.send_message",
            return_value=return_value or {"message_id": 42},
        )

    # ---------------------------------------------------------------- issue

    def test_issue_challenge_sends_and_persists_hash(self):
        with self._patched_send() as mocked:
            sent = self.binding.issue_challenge(ip="1.2.3.4", user_agent="UA")
        self.assertTrue(sent)
        self.assertTrue(self.binding.pending_code_hash)
        self.assertGreater(self.binding.pending_code_expires_at, fields.Datetime.now())
        self.assertEqual(self.binding.pending_code_attempts, 0)
        mocked.assert_called_once()
        # Audit row written.
        audit = self.env["rteam.tg.audit"].search(
            [("user_id", "=", self.user.id), ("event", "=", "challenge_sent")],
            order="create_date desc",
            limit=1,
        )
        self.assertTrue(audit)
        self.assertEqual(audit.tg_message_id, "42")

    def test_issue_challenge_idempotent_within_ttl(self):
        with self._patched_send() as mocked:
            first = self.binding.issue_challenge()
            second = self.binding.issue_challenge()
        self.assertTrue(first)
        self.assertFalse(second, "second call should be a no-op while code is fresh")
        self.assertEqual(mocked.call_count, 1)

    def test_issue_challenge_refuses_when_not_active(self):
        self.binding.state = "pending"
        with self._patched_send():
            with self.assertRaises(UserError):
                self.binding.issue_challenge()

    def test_issue_challenge_propagates_rate_limit(self):
        # Prime the limit by writing 5 challenge_sent audit rows in window.
        for _ in range(5):
            self.env["rteam.tg.audit"].create(
                {
                    "user_id": self.user.id,
                    "binding_id": self.binding.id,
                    "event": "challenge_sent",
                }
            )
        with self._patched_send():
            with self.assertRaises(UserError):
                self.binding.issue_challenge()
        # rate_limited audit row written.
        rate = self.env["rteam.tg.audit"].search(
            [("user_id", "=", self.user.id), ("event", "=", "rate_limited")]
        )
        self.assertTrue(rate)

    def test_issue_challenge_surfaces_telegram_error(self):
        from odoo.addons.rteam_tg_auth.models.telegram_api import TelegramApiError

        with patch(
            "odoo.addons.rteam_tg_auth.models.rteam_tg_binding.send_message",
            side_effect=TelegramApiError("HTTP 401 Unauthorized"),
        ):
            with self.assertRaises(UserError) as cm:
                self.binding.issue_challenge()
        self.assertIn("Unauthorized", str(cm.exception))

    # --------------------------------------------------------------- verify

    def test_verify_challenge_accepts_correct_code(self):
        with self._patched_send():
            self.binding.issue_challenge()
        # We don't know the code; reach into the hash via a known one.
        self.binding.pending_code_hash = self.binding._hash_code("000111")
        self.assertTrue(self.binding.verify_challenge("000111"))
        self.assertFalse(self.binding.pending_code_hash)
        self.assertTrue(self.binding.last_used_at)

    def test_verify_challenge_rejects_wrong_code(self):
        self.binding.write(
            {
                "pending_code_hash": self.binding._hash_code("123456"),
                "pending_code_expires_at": fields.Datetime.now() + timedelta(seconds=60),
                "pending_code_attempts": 0,
            }
        )
        self.assertFalse(self.binding.verify_challenge("999999"))
        self.assertEqual(self.binding.pending_code_attempts, 1)
        self.assertTrue(self.binding.pending_code_hash, "hash kept after one wrong try")

    def test_verify_challenge_invalidates_after_attempt_limit(self):
        self.binding.write(
            {
                "pending_code_hash": self.binding._hash_code("123456"),
                "pending_code_expires_at": fields.Datetime.now() + timedelta(seconds=60),
                "pending_code_attempts": 4,  # one more wrong try should clear it
            }
        )
        self.assertFalse(self.binding.verify_challenge("999999"))
        self.assertFalse(self.binding.pending_code_hash)
        self.assertEqual(self.binding.pending_code_attempts, 0)

    def test_verify_challenge_rejects_expired_code(self):
        self.binding.write(
            {
                "pending_code_hash": self.binding._hash_code("123456"),
                "pending_code_expires_at": fields.Datetime.now() - timedelta(seconds=1),
            }
        )
        self.assertFalse(self.binding.verify_challenge("123456"))

    def test_verify_challenge_rejects_when_no_pending_code(self):
        self.binding.pending_code_hash = False
        self.binding.pending_code_expires_at = False
        self.assertFalse(self.binding.verify_challenge("123456"))


class TestRecoveryCodes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env["ir.config_parameter"].sudo()
        cls.params.set_param("rteam_tg_auth.bot_token", "TEST_TOKEN")
        cls.user = cls.env["res.users"].create({"name": "Recovery U", "login": "recovery_user_t1b"})
        cls.binding = cls.env["rteam.tg.binding"].create(
            {
                "user_id": cls.user.id,
                "state": "active",
                "chat_id": "777777",
                "bound_at": fields.Datetime.now(),
            }
        )

    def test_generate_returns_ten_unique_codes_and_stores_hashes(self):
        codes = self.binding.generate_recovery_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10, "codes must be unique")
        self.assertEqual(self.binding.recovery_codes_remaining(), 10)
        # Plain codes never persisted -- only hashes.
        for plain in codes:
            self.assertNotIn(plain, self.binding.recovery_codes or "")

    def test_generate_refuses_when_not_active(self):
        self.binding.state = "pending"
        with self.assertRaises(UserError):
            self.binding.generate_recovery_codes()

    def test_recovery_code_consumed_on_first_use(self):
        codes = self.binding.generate_recovery_codes()
        ok = self.binding.verify_challenge(codes[0])
        self.assertTrue(ok)
        self.assertEqual(self.binding.recovery_codes_remaining(), 9)
        # Same code rejected the second time.
        self.assertFalse(self.binding.verify_challenge(codes[0]))

    def test_recovery_code_normalization(self):
        codes = self.binding.generate_recovery_codes()
        c = codes[0]
        # Strip dashes, lowercase, surround with whitespace -- still works.
        smudged = " " + c.replace("-", "").lower() + " "
        self.assertTrue(self.binding.verify_challenge(smudged))

    def test_unknown_recovery_code_is_rejected(self):
        self.binding.generate_recovery_codes()
        # 12 chars from valid alphabet but not a generated code.
        from odoo.addons.rteam_tg_auth.models.rteam_tg_binding import RECOVERY_ALPHABET

        unknown = (
            (RECOVERY_ALPHABET[0] * 4)
            + "-"
            + (RECOVERY_ALPHABET[1] * 4)
            + "-"
            + (RECOVERY_ALPHABET[2] * 4)
        )
        self.assertFalse(self.binding.verify_challenge(unknown))
        self.assertEqual(self.binding.recovery_codes_remaining(), 10)

    def test_six_digit_pending_code_still_takes_priority(self):
        # Recovery codes exist AND there's a fresh 6-digit code: the
        # 6-digit code path must still work and not be misrouted.
        self.binding.generate_recovery_codes()
        self.binding.write(
            {
                "pending_code_hash": self.binding._hash_code("424242"),
                "pending_code_expires_at": fields.Datetime.now() + timedelta(seconds=60),
            }
        )
        self.assertTrue(self.binding.verify_challenge("424242"))
        # Code consumed, no recovery code used.
        self.assertFalse(self.binding.pending_code_hash)
        self.assertEqual(self.binding.recovery_codes_remaining(), 10)
