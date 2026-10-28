"""Keep one active binding per Telegram chat before its unique index is added.

Up to 19.0.2.1.3 only the /start handler checked that a chat was not bound to
another user, and two handlers running at once both passed the check. The
index cannot be created over such rows: Odoo logs a warning and goes on
without it.

Per chat the binding bound first stays active (bound_at, then id). The others
are revoked, keeping their chat_id, with an ``admin_reset`` audit row each.
Their users log in without Telegram 2FA until they bind another chat, so the
warning names them.

Pre-migration runs before the module's Python is imported, so this file
stays self-contained. tests/test_migration.py runs it against duplicates.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        WITH ranked AS (
            SELECT id,
                   first_value(user_id) OVER per_chat AS kept_user_id,
                   row_number() OVER per_chat AS n
              FROM rteam_tg_binding
             WHERE state = 'active' AND chat_id IS NOT NULL
            WINDOW per_chat AS (PARTITION BY chat_id ORDER BY bound_at NULLS LAST, id)
        )
        UPDATE rteam_tg_binding b
           SET state = 'revoked', write_date = now() AT TIME ZONE 'UTC'
          FROM ranked
         WHERE b.id = ranked.id
           AND ranked.n > 1
        RETURNING b.id, b.user_id, b.chat_id, ranked.kept_user_id
        """
    )
    revoked = cr.fetchall()
    if not revoked:
        return
    cr.execute(
        """
        INSERT INTO rteam_tg_audit (binding_id, user_id, event, note, create_date, write_date)
        SELECT binding_id, user_id, 'admin_reset',
               'Revoked by the 19.0.2.1.4 upgrade: chat ' || chat_id
                   || ' stays bound to user ' || kept_user_id,
               now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC'
          FROM unnest(%s::int[], %s::int[], %s::varchar[], %s::int[])
               AS r(binding_id, user_id, chat_id, kept_user_id)
        """,
        [list(column) for column in zip(*revoked, strict=True)],
    )
    _logger.warning(
        "rteam_tg_auth: revoked %d Telegram binding(s) that shared a chat with another "
        "user's active binding; these users log in without Telegram 2FA until they bind "
        "another chat: %s",
        len(revoked),
        ", ".join(f"user {user_id} (chat {chat_id})" for _id, user_id, chat_id, _kept in revoked),
    )
