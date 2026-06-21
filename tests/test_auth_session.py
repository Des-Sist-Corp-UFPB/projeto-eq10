import unittest

from src.auth.session import (
    AUTH_SESSION_KEY,
    can_access_chat,
    get_authenticated_user,
    login_session,
    logout_session,
)


class TestAuthSession(unittest.TestCase):
    def test_logout_limpa_sessao(self):
        session_state = {
            AUTH_SESSION_KEY: {
                "id": 1,
                "nome": "Ana",
                "email": "ana@example.com",
                "role": "user",
            },
            "pending_prompt": "Média de idade",
            "messages": [{"role": "user", "content": "oi"}],
            "current_page": "Chat IA",
        }

        logout_session(session_state)

        self.assertNotIn(AUTH_SESSION_KEY, session_state)
        self.assertNotIn("auth_user_id", session_state)
        self.assertNotIn("auth_user_name", session_state)
        self.assertNotIn("auth_user_email", session_state)
        self.assertFalse(session_state["is_authenticated"])
        self.assertNotIn("pending_prompt", session_state)
        self.assertEqual(session_state["messages"], [])
        self.assertEqual(session_state["current_page"], "Chat IA")

    def test_chat_bloqueia_usuario_deslogado(self):
        self.assertFalse(can_access_chat({}))
        self.assertIsNone(get_authenticated_user({}))

    def test_usuario_logado_consegue_acessar_fluxo_do_chat(self):
        session_state = {}

        login_session(
            session_state,
            {
                "id": 1,
                "nome": "Ana",
                "email": "ana@example.com",
                "role": "user",
            },
        )

        self.assertTrue(can_access_chat(session_state))
        self.assertEqual(get_authenticated_user(session_state)["email"], "ana@example.com")
        self.assertEqual(session_state["auth_user_id"], 1)
        self.assertEqual(session_state["auth_user_name"], "Ana")
        self.assertEqual(session_state["auth_user_email"], "ana@example.com")
        self.assertTrue(session_state["is_authenticated"])

    def test_login_persiste_quando_pagina_muda(self):
        session_state = {"current_page": "Estatísticas"}

        login_session(
            session_state,
            {
                "id": 1,
                "nome": "Ana",
                "email": "ana@example.com",
                "role": "user",
            },
        )
        session_state["current_page"] = "Chat IA"

        self.assertTrue(can_access_chat(session_state))
        self.assertEqual(get_authenticated_user(session_state)["email"], "ana@example.com")


if __name__ == "__main__":
    unittest.main()
