import unittest
from unittest.mock import patch

from src.ui import auth_modal


class _FakeSessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class TestAuthModalProcessing(unittest.TestCase):
    def test_clear_auth_processing_state_removes_all_known_flags(self):
        session_state = _FakeSessionState(
            {
                "auth_modal_processing_message": "Entrando...",
                "auth_processing": True,
                "login_processing": True,
                "register_processing": True,
                "forgot_password_processing": True,
                "reset_password_processing": True,
                "email_code_processing": True,
                "google_processing": True,
                "profile_processing": True,
                "email_processing": True,
                "reactivation_processing": True,
                "auth_modal_feedback_message": "erro anterior",
            }
        )

        auth_modal.clear_auth_processing_state(session_state)

        for key in auth_modal.AUTH_MODAL_PROCESSING_STATE_KEYS:
            self.assertNotIn(key, session_state)
        self.assertEqual(session_state["auth_modal_feedback_message"], "erro anterior")

    def test_start_modal_processing_clears_stale_flags_first(self):
        session_state = _FakeSessionState(
            {
                "login_processing": True,
                "google_processing": True,
            }
        )

        with patch.object(auth_modal.st, "session_state", session_state):
            auth_modal._start_modal_processing("Entrando...")

        self.assertEqual(session_state[auth_modal.AUTH_MODAL_PROCESSING_KEY], "Entrando...")
        self.assertNotIn("login_processing", session_state)
        self.assertNotIn("google_processing", session_state)

    def test_finish_modal_action_feedback_clears_processing_before_rerun(self):
        session_state = _FakeSessionState(
            {
                auth_modal.AUTH_MODAL_PROCESSING_KEY: "Entrando...",
                "login_processing": True,
            }
        )

        with (
            patch.object(auth_modal.st, "session_state", session_state),
            patch.object(auth_modal.st, "rerun", side_effect=RuntimeError("rerun")) as rerun,
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._finish_modal_action_feedback("Erro de login.", "error")

        rerun.assert_called_once()
        self.assertNotIn(auth_modal.AUTH_MODAL_PROCESSING_KEY, session_state)
        self.assertNotIn("login_processing", session_state)
        self.assertEqual(session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Erro de login.")
        self.assertEqual(session_state[auth_modal.AUTH_MODAL_FEEDBACK_KIND_KEY], "error")


if __name__ == "__main__":
    unittest.main()
