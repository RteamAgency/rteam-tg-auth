"""Tests for the pre-migrations that clear duplicates before a unique constraint:
19.0.2.1.3 (one binding per user) and 19.0.2.1.4 (one active binding per chat).
"""

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


def _run_pre_migrate_2_1_4(cr):
    path = file_path("rteam_tg_auth/migrations/19.0.2.1.4/pre-migrate.py")
    spec = importlib.util.spec_from_file_location("rteam_tg_auth_pre_migrate_19_0_2_1_4", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(cr, "19.0.2.1.3")


class TestSharedChatMigration(TransactionCase):
    def _insert(self, login, state, chat_id, bound_at):
        user = self.env["res.users"].create({"name": login, "login": login})
        self.env.cr.execute(
            """
            INSERT INTO rteam_tg_binding (user_id, state, chat_id, bound_at)
            VALUES (%s, %s, %s, %s) RETURNING id
            """,
            [user.id, state, chat_id, bound_at],
        )
        return user, self.env.cr.fetchone()[0]

    def test_unique_index_exists(self):
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            ["rteam_tg_binding_chat_unique_active"],
        )
        row = self.env.cr.fetchone()
        self.assertTrue(row)
        self.assertIn("UNIQUE", row[0])
        self.assertIn("WHERE", row[0])

    def test_keeps_the_first_bound_chat_and_revokes_the_others(self):
        # Databases at 19.0.2.1.3 have no index; drop it so the shared chat
        # can exist (the test transaction restores it).
        self.env.cr.execute("DROP INDEX rteam_tg_binding_chat_unique_active")
        first, first_id = self._insert("mig_chat_first", "active", "500", "2026-01-01 10:00:00")
        later, later_id = self._insert("mig_chat_later", "active", "500", "2026-02-01 10:00:00")
        undated, undated_id = self._insert("mig_chat_undated", "active", "500", None)
        _alone, alone_id = self._insert("mig_chat_alone", "active", "600", "2026-03-01 10:00:00")
        _old, old_id = self._insert("mig_chat_revoked", "revoked", "500", "2025-01-01 10:00:00")
        self.env.invalidate_all()

        _run_pre_migrate_2_1_4(self.env.cr)
        self.env.invalidate_all()

        Binding = self.env["rteam.tg.binding"]
        states = {b.id: b.state for b in Binding.browse([first_id, later_id, undated_id])}
        self.assertEqual(states, {first_id: "active", later_id: "revoked", undated_id: "revoked"})
        self.assertEqual(Binding.browse(alone_id).state, "active")
        self.assertEqual(Binding.browse(old_id).state, "revoked")
        self.assertEqual(Binding.browse(later_id).chat_id, "500")
        self.assertEqual(first.tg_2fa_state, "active")
        self.assertEqual(later.tg_2fa_state, "revoked")

        audits = self.env["rteam.tg.audit"].search([("event", "=", "admin_reset")])
        self.assertEqual(audits.user_id, later | undated)
        self.assertIn(f"stays bound to user {first.id}", audits[0].note)

        # With the duplicates gone the index goes back on.
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX rteam_tg_binding_chat_unique_active
                ON rteam_tg_binding (chat_id) WHERE state = 'active'
            """
        )
