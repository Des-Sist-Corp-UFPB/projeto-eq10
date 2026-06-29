from types import SimpleNamespace
import unittest
from unittest.mock import patch

import app_ai_chat
from src.ui.sidebar import ADMIN_PAGE, DEFAULT_PAGE


class _FakeStreamlit:
    def __init__(self):
        self.session_state = _FakeSessionState()


class _FakeSessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class TestAdminRouteAccess(unittest.TestCase):
    def test_direct_admin_access_is_blocked_when_logged_out(self):
        fake_st = _FakeStreamlit()

        with (
            patch.object(app_ai_chat, "st", fake_st),
            patch.object(app_ai_chat, "get_authenticated_user", return_value=None),
            patch.object(app_ai_chat, "set_current_page") as set_current_page,
        ):
            page = app_ai_chat._resolve_authorized_page(ADMIN_PAGE)

        self.assertEqual(page, DEFAULT_PAGE)
        set_current_page.assert_called_once_with(DEFAULT_PAGE)
        self.assertNotIn("admin_access_feedback", fake_st.session_state)

    def test_direct_admin_access_is_blocked_for_user_without_permission(self):
        fake_st = _FakeStreamlit()
        user = {"id": 1, "role": "user", "can_view_audit": False}

        with (
            patch.object(app_ai_chat, "st", fake_st),
            patch.object(app_ai_chat, "get_authenticated_user", return_value=user),
            patch.object(app_ai_chat, "set_current_page") as set_current_page,
        ):
            page = app_ai_chat._resolve_authorized_page(ADMIN_PAGE)

        self.assertEqual(page, DEFAULT_PAGE)
        set_current_page.assert_called_once_with(DEFAULT_PAGE)
        self.assertEqual(
            fake_st.session_state.get("admin_access_feedback"),
            app_ai_chat.ADMIN_ACCESS_DENIED_MESSAGE,
        )

    def test_direct_admin_access_is_allowed_for_audit_user(self):
        fake_st = _FakeStreamlit()
        user = SimpleNamespace(id=1, role="user", can_view_audit=True)

        with (
            patch.object(app_ai_chat, "st", fake_st),
            patch.object(app_ai_chat, "get_authenticated_user", return_value=user),
            patch.object(app_ai_chat, "set_current_page") as set_current_page,
        ):
            page = app_ai_chat._resolve_authorized_page(ADMIN_PAGE)

        self.assertEqual(page, ADMIN_PAGE)
        set_current_page.assert_not_called()
        self.assertNotIn("admin_access_feedback", fake_st.session_state)


if __name__ == "__main__":
    unittest.main()
