"""Tests for the MFA hooks: _mfa_type / _mfa_url / _check_credentials."""

from odoo.exceptions import AccessDenied
from odoo.tests.common import TransactionCase


class TestMfaHooks(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env["ir.config_parameter"].sudo()
        cls.params.set_param("rteam_tg_auth.bot_token", "TEST_TOKEN")
        cls.user_internal = cls.env["res.users"].create(
            {"name": "Internal U", "login": "internal_mfa_t3"}
        )
        cls.user_public = cls.env.ref("base.public_user")

    def test_mfa_type_none_when_unbound(self):
        self.params.set_param("rteam_tg_auth.enforce_2fa", "True")
        self.assertIsNone(self.user_internal._mfa_type())
        self.assertIsNone(self.user_internal._mfa_url())

    def test_mfa_type_none_when_enforce_off(self):
        self.params.set_param("rteam_tg_auth.enforce_2fa", "False")
        self._make_active_binding(self.user_internal)
        self.assertIsNone(self.user_internal._mfa_type())

    def test_mfa_type_set_when_enforced_and_bound(self):
        self.params.set_param("rteam_tg_auth.enforce_2fa", "True")
        self._make_active_binding(self.user_internal)
        self.assertEqual(self.user_internal._mfa_type(), "rteam_tg")
        self.assertEqual(self.user_internal._mfa_url(), "/web/login/rteam_tg")

    def test_mfa_type_short_circuits_for_public_user(self):
        # Even with enforce on, public user must never trigger TG 2FA --
        # they have no binding ACL and their session evaluation must not
        # 500 the /web/login page (regression guard for v0.1.2.2).
        self.params.set_param("rteam_tg_auth.enforce_2fa", "True")
        self.assertIsNone(self.user_public._mfa_type())
        self.assertIsNone(self.user_public._mfa_url())

    def test_check_credentials_rejects_when_no_binding(self):
        with self.assertRaises(AccessDenied):
            self.user_internal._check_credentials(
                {"type": "rteam_tg", "token": "123456"}, {"interactive": True}
            )

    def test_check_credentials_rejects_wrong_code(self):
        binding = self._make_active_binding(self.user_internal)
        # No pending code at all.
        binding.pending_code_hash = False
        with self.assertRaises(AccessDenied):
            self.user_internal._check_credentials(
                {"type": "rteam_tg", "token": "999999"}, {"interactive": True}
            )

    def test_check_credentials_accepts_correct_code(self):
        from datetime import timedelta

        from odoo import fields

        binding = self._make_active_binding(self.user_internal)
        binding.write(
            {
                "pending_code_hash": binding._hash_code("424242"),
                "pending_code_expires_at": fields.Datetime.now() + timedelta(seconds=60),
            }
        )
        info = self.user_internal._check_credentials(
            {"type": "rteam_tg", "token": "424242"}, {"interactive": True}
        )
        self.assertEqual(info.get("auth_method"), "rteam_tg")
        # Pending code consumed.
        self.assertFalse(binding.pending_code_hash)

    # ---------------------------------------------------------------- helpers

    def _make_active_binding(self, user):
        from odoo import fields

        return self.env["rteam.tg.binding"].create(
            {
                "user_id": user.id,
                "state": "active",
                "chat_id": "111222",
                "bound_at": fields.Datetime.now(),
            }
        )
