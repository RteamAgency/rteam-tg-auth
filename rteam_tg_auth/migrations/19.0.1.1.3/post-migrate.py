"""Re-apply Telegram 2FA cross-grants on every upgrade.

The post_init_hook in the manifest only runs on a fresh install. For
upgrades, this script is the one that hardens the implication chain
(needed because the XML <data> block alone has been observed to apply
to base.group_system but not base.group_user, leaving Telegram 2FA
unreachable for normal employees).
"""

from odoo import SUPERUSER_ID, api
from odoo.addons.rteam_tg_auth.hooks import post_load_upgrade


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    post_load_upgrade(env)
