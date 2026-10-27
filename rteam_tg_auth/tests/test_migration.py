"""Tests for the 19.0.2.1.3 pre-migration that removes duplicate bindings."""

import importlib.util

from odoo.tests.common import TransactionCase
from odoo.tools.misc import file_path


def _run_pre_migrate(cr):
    path = file_path("rteam_tg_auth/migrations/19.0.2.1.3/pre-migrate.py")
    spec = importlib.util.spec_from_file_location("rteam_tg_auth_pre_migrate_19_0_2_1_3", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(cr, "19.0.2.1.2")


class TestDuplicateBindingMigration(TransactionCase):
    def _insert(self, user, state):
        self.env.cr.execute(
            "INSERT INTO rteam_tg_binding (user_id, state) VALUES (%s, %s) RETURNING id",
            [user.id, state],
        )
        return self.env.cr.fetchone()[0]

    def test_keeps_the_active_then_oldest_row_and_leaves_audit_rows(self):
        Users = self.env["res.users"]
        both = Users.create({"name": "Two Actives", "login": "mig_two_actives"})
        pending_only = Users.create({"name": "Pending Only", "login": "mig_pending_only"})
        single = Users.create({"name": "Single", "login": "mig_single"})

        # Databases at 19.0.2.1.2 never got the constraint; drop it so the
        # duplicates can exist (the test transaction restores it).
        self.env.cr.execute(
            "ALTER TABLE rteam_tg_binding DROP CONSTRAINT rteam_tg_binding_user_unique_active"
        )
        first_pending = self._insert(both, "pending")
        oldest_active = self._insert(both, "active")
        newer_active = self._insert(both, "active")
        revoked = self._insert(pending_only, "revoked")
        older_pending = self._insert(pending_only, "pending")
        newer_pending = self._insert(pending_only, "pending")
        only_row = self._insert(single, "active")
        audit = self.env["rteam.tg.audit"].create(
            {"user_id": both.id, "binding_id": newer_active, "event": "challenge_sent"}
        )
        self.env.invalidate_all()

        _run_pre_migrate(self.env.cr)
        self.env.invalidate_all()

        Binding = self.env["rteam.tg.binding"]
        self.assertEqual(Binding.search([("user_id", "=", both.id)]).ids, [oldest_active])
        self.assertEqual(Binding.search([("user_id", "=", pending_only.id)]).ids, [older_pending])
        self.assertEqual(Binding.search([("user_id", "=", single.id)]).ids, [only_row])
        self.assertFalse(
            Binding.browse([first_pending, newer_active, revoked, newer_pending]).exists()
        )
        # The audit row stays as written, only its link to the deleted row goes.
        self.assertEqual(audit.user_id, both)
        self.assertFalse(audit.binding_id)
        self.assertEqual(both.tg_2fa_state, "active")
