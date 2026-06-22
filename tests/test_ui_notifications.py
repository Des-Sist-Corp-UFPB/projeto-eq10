import unittest
import inspect

from src.ui.notifications import (
    PENDING_TOAST_KEY,
    PENDING_TOAST_KIND_KEY,
    SUCCESS_FEEDBACK_CSS,
    build_success_feedback_html,
    queue_toast,
    render_pending_toast,
    show_success_feedback,
)


class TestUiNotifications(unittest.TestCase):
    def test_queue_toast_armazena_mensagem_para_proxima_renderizacao(self):
        session_state = {}

        queue_toast(session_state, "Login realizado com sucesso.")

        self.assertEqual(session_state[PENDING_TOAST_KEY], "Login realizado com sucesso.")
        self.assertEqual(session_state[PENDING_TOAST_KIND_KEY], "success")

    def test_feedback_nao_usa_toast_nativo_escuro_nem_markdown(self):
        source = inspect.getsource(render_pending_toast)
        show_source = inspect.getsource(show_success_feedback)

        self.assertNotIn("app-toast", source)
        self.assertNotIn("st.toast", source + show_source)
        self.assertNotIn('getattr(st, "toast"', source + show_source)
        self.assertNotIn("markdown", source + show_source)
        self.assertIn("html", show_source)
        self.assertIn("st.success", source)

    def test_success_feedback_html_e_leve_e_nao_indenta_como_codigo(self):
        html = build_success_feedback_html("Login realizado com sucesso.")

        self.assertTrue(html.startswith("<style>"))
        self.assertIn("success-feedback-stack", html)
        self.assertIn("success-feedback-card", html)
        self.assertIn("success-feedback-icon", html)
        self.assertIn("&#10003;", html)
        self.assertNotIn("âœ", html)
        self.assertIn("#f0fdf4", SUCCESS_FEEDBACK_CSS)
        self.assertIn("#bbf7d0", SUCCESS_FEEDBACK_CSS)
        self.assertIn("#166534", SUCCESS_FEEDBACK_CSS)
        self.assertIn("#22c55e", SUCCESS_FEEDBACK_CSS)
        self.assertIn("z-index:2147483000", SUCCESS_FEEDBACK_CSS)
        self.assertNotIn("app-toast", html)


if __name__ == "__main__":
    unittest.main()
