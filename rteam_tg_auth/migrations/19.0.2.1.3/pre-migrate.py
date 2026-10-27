"""Keep one Telegram binding per user before UNIQUE(user_id) is added.

Up to 19.0.2.1.2 the constraint was declared through _sql_constraints,
which Odoo 19 ignores, so a database may hold several rows for one user.
The module upgrade cannot add the constraint over duplicates.

The row kept is the one the login check should see: an active one first,
then pending, then revoked, and on a tie the oldest, which is the row the
code has been reading (``tg_binding_id[:1]``, ``search(limit=1)``) and the
one holding the user's recovery codes. Audit rows are left as written:
they keep their user_id, and ON DELETE SET NULL clears the binding_id of
the rows that pointed at a deleted duplicate. A bind link still open for a
deleted pending row stops working; the user clicks Bind again.

Pre-migration runs before the module's Python is imported, so this file
stays self-contained. tests/test_binding.py runs it against duplicates.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM rteam_tg_binding b
         USING (
            SELECT id,
                   first_value(id) OVER (
                       PARTITION BY user_id
                       ORDER BY CASE state WHEN 'active' THEN 0
                                           WHEN 'pending' THEN 1
                                           ELSE 2 END,
                                id
                   ) AS keep_id
              FROM rteam_tg_binding
         ) ranked
         WHERE b.id = ranked.id
           AND ranked.id != ranked.keep_id
        """
    )
    if cr.rowcount:
        _logger.warning(
            "rteam_tg_auth: removed %d duplicate Telegram binding(s) before adding UNIQUE(user_id)",
            cr.rowcount,
        )
