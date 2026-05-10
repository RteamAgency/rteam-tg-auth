"""Smoke test: module installs, models exist, default groups present."""

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger
from psycopg2 import IntegrityError


class TestSmoke(TransactionCase):
    def test_models_exist(self):
        self.assertIn("rteam.tg.binding", self.env)
        self.assertIn("rteam.tg.audit", self.env)

    def test_groups_present(self):
        user_group = self.env.ref("rteam_tg_auth.group_rteam_tg_user")
        admin_group = self.env.ref("rteam_tg_auth.group_rteam_tg_admin")
        self.assertTrue(user_group)
        self.assertTrue(admin_group)
        # Admin implies user.
        self.assertIn(user_group, admin_group.implied_ids)

    def test_binding_unique_per_user(self):
        Binding = self.env["rteam.tg.binding"]
        user = self.env.ref("base.user_admin")
        Binding.create({"user_id": user.id})
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            Binding.create({"user_id": user.id})
            self.env.flush_all()
