from pathlib import Path
from types import SimpleNamespace
import unittest

from src.auth.roles import can_view_audit_log
from src.ui.sidebar import ADMIN_PAGE, DEFAULT_PAGE, _sidebar_nav_markup


SIDEBAR_PATH = Path("src/ui/sidebar.py")
APP_PATH = Path("app_ai_chat.py")


class TestSidebarAdminAccess(unittest.TestCase):
    def test_logged_out_user_does_not_see_audit_navigation(self):
        markup = _sidebar_nav_markup(DEFAULT_PAGE, show_admin=can_view_audit_log(None))

        self.assertNotIn(ADMIN_PAGE, markup)
        self.assertNotIn("</nav>", markup)

    def test_normal_user_without_permission_does_not_see_audit_navigation(self):
        user = {"role": "user", "can_view_audit": False}
        markup = _sidebar_nav_markup(DEFAULT_PAGE, show_admin=can_view_audit_log(user))

        self.assertNotIn(ADMIN_PAGE, markup)

    def test_user_with_can_view_audit_sees_audit_navigation(self):
        user = {"role": "user", "can_view_audit": True}
        markup = _sidebar_nav_markup(DEFAULT_PAGE, show_admin=can_view_audit_log(user))

        self.assertIn(ADMIN_PAGE, markup)
        self.assertIn("nav-icon audit", markup)
        self.assertIn("nav-icon stats", markup)
        self.assertIn("nav-icon chat", markup)

    def test_audit_sidebar_icon_has_stronger_visual_weight(self):
        app_source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn(".nav-icon.audit", app_source)
        self.assertIn("width: 1.35rem", app_source)
        self.assertIn("border: 2.5px solid currentColor", app_source)

    def test_admin_role_sees_audit_navigation(self):
        user = {"role": "admin", "can_view_audit": False}
        markup = _sidebar_nav_markup(DEFAULT_PAGE, show_admin=can_view_audit_log(user))

        self.assertIn(ADMIN_PAGE, markup)

    def test_super_admin_role_sees_audit_navigation(self):
        user = SimpleNamespace(role="super_admin", can_view_audit=False)
        markup = _sidebar_nav_markup(DEFAULT_PAGE, show_admin=can_view_audit_log(user))

        self.assertIn(ADMIN_PAGE, markup)

    def test_sidebar_source_does_not_render_literal_nav_close(self):
        sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")

        self.assertNotIn("<nav", sidebar_source)
        self.assertNotIn("</nav>", sidebar_source)


if __name__ == "__main__":
    unittest.main()
