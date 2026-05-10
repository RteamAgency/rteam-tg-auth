"""Install / upgrade hooks for rteam_tg_auth.

Why a Python hook for something that "should" be in security.xml: in
practice, declaring ``implied_ids`` on the stock ``base.group_user`` and
``base.group_system`` records via XML is unreliable. Even outside a
``noupdate="1"`` block, observed loads on Odoo 19 apply the change to one
of the two and silently drop the other (suspected interaction with the
order in which modules touch those base groups). A direct
``res.groups.write`` after data load makes the assertion explicit and
idempotent: running it again is a no-op.
"""

import logging

_logger = logging.getLogger(__name__)

CROSS_GRANTS = (
    # (base group xmlid, our group xmlid, label)
    ("base.group_user", "rteam_tg_auth.group_rteam_tg_user", "Internal User -> Telegram 2FA User"),
    (
        "base.group_system",
        "rteam_tg_auth.group_rteam_tg_admin",
        "System Administrator -> Telegram 2FA Administrator",
    ),
)


def _apply_cross_grants(env):
    for base_xmlid, our_xmlid, label in CROSS_GRANTS:
        base_grp = env.ref(base_xmlid, raise_if_not_found=False)
        our_grp = env.ref(our_xmlid, raise_if_not_found=False)
        if not base_grp or not our_grp:
            _logger.warning(
                "rteam_tg_auth: cannot apply cross-grant '%s' (base=%s, ours=%s)",
                label,
                base_grp,
                our_grp,
            )
            continue
        if our_grp in base_grp.implied_ids:
            continue
        base_grp.write({"implied_ids": [(4, our_grp.id)]})
        _logger.info("rteam_tg_auth: applied cross-grant '%s'", label)
        # Promote existing members of base_grp so the role takes effect now,
        # not only for users created after this point.
        base_grp.users.write({"group_ids": [(4, our_grp.id)]})


def post_init(env):
    """Run after the module is installed for the first time."""
    _apply_cross_grants(env)


def post_load_upgrade(env):
    """Run after every module upgrade to re-assert the cross-grants."""
    _apply_cross_grants(env)
