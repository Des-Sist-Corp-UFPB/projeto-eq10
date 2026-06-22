import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from src.auth.user_service import UserService
from src.chat.chat_history_service import ChatHistoryService, redact_sensitive_content


class TestChatHistoryService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.user_service = UserService(self.engine)
        self.service = ChatHistoryService(self.engine)
        self.user = self.user_service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )
        self.other_user = self.user_service.create_user(
            "Bia Souza",
            "bia@example.com",
            "senha-forte",
            "senha-forte",
        )

    def test_schema_cria_tabelas_de_historico(self):
        with self.engine.connect() as conn:
            session_columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(chat_sessions)")).mappings()
            }
            message_columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(chat_messages)")).mappings()
            }

        for column in ["id", "user_id", "titulo", "criado_em", "atualizado_em", "deletado", "deletado_em"]:
            self.assertIn(column, session_columns)
        for column in [
            "id",
            "chat_session_id",
            "user_id",
            "role",
            "conteudo",
            "status",
            "criado_em",
            "deletado",
            "deletado_em",
        ]:
            self.assertIn(column, message_columns)

    def test_cria_sessao_para_usuario(self):
        session = self.service.create_chat_session(self.user.id, "Primeira conversa")

        self.assertGreater(session.id, 0)
        self.assertEqual(session.user_id, self.user.id)
        self.assertEqual(session.titulo, "Primeira conversa")

    def test_get_or_create_reaproveita_sessao_ativa(self):
        first = self.service.get_or_create_active_chat_session(self.user.id, "Pergunta inicial")
        second = self.service.get_or_create_active_chat_session(self.user.id, "Outra pergunta")

        self.assertEqual(first.id, second.id)

    def test_adiciona_mensagens_de_usuario_e_assistente(self):
        session = self.service.create_chat_session(self.user.id, "Valores")

        user_message = self.service.add_chat_message(session.id, self.user.id, "user", "Total aprovado?")
        assistant_message = self.service.add_chat_message(
            session.id,
            self.user.id,
            "assistant",
            "O total aprovado e 10.",
            status="ok",
        )

        messages = self.service.list_chat_messages(session.id, self.user.id)
        self.assertEqual([message.id for message in messages], [user_message.id, assistant_message.id])
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[1].role, "assistant")
        self.assertEqual(messages[1].status, "ok")

    def test_lista_apenas_sessoes_nao_deletadas_do_usuario(self):
        visible = self.service.create_chat_session(self.user.id, "Visivel")
        hidden = self.service.create_chat_session(self.user.id, "Oculta")
        self.service.create_chat_session(self.other_user.id, "Outra pessoa")

        self.service.soft_delete_chat_session(hidden.id, self.user.id)

        sessions = self.service.list_user_chat_sessions(self.user.id)
        self.assertEqual([session.id for session in sessions], [visible.id])

    def test_lista_apenas_mensagens_do_usuario_autenticado(self):
        own_session = self.service.create_chat_session(self.user.id, "Ana")
        other_session = self.service.create_chat_session(self.other_user.id, "Bia")
        own_message = self.service.add_chat_message(own_session.id, self.user.id, "user", "Minha pergunta")
        self.service.add_chat_message(other_session.id, self.other_user.id, "user", "Outra pergunta")

        self.assertEqual(
            [message.id for message in self.service.list_chat_messages(own_session.id, self.user.id)],
            [own_message.id],
        )
        self.assertEqual(self.service.list_chat_messages(other_session.id, self.user.id), [])

    def test_soft_delete_de_sessao_oculta_historico(self):
        session = self.service.create_chat_session(self.user.id, "Remover")
        self.service.add_chat_message(session.id, self.user.id, "user", "Pergunta")

        self.service.soft_delete_chat_session(session.id, self.user.id)

        self.assertEqual(self.service.list_user_chat_sessions(self.user.id), [])
        self.assertEqual(self.service.list_chat_messages(session.id, self.user.id), [])
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT deletado, deletado_em FROM chat_sessions WHERE id = :id"),
                {"id": session.id},
            ).mappings().first()
        self.assertTrue(row["deletado"])
        self.assertIsNotNone(row["deletado_em"])

    def test_soft_delete_de_mensagem_oculta_mensagem(self):
        session = self.service.create_chat_session(self.user.id, "Mensagens")
        message = self.service.add_chat_message(session.id, self.user.id, "user", "Pergunta")

        self.service.soft_delete_chat_message(message.id, self.user.id)

        self.assertEqual(self.service.list_chat_messages(session.id, self.user.id), [])
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT deletado, deletado_em FROM chat_messages WHERE id = :id"),
                {"id": message.id},
            ).mappings().first()
        self.assertTrue(row["deletado"])
        self.assertIsNotNone(row["deletado_em"])

    def test_conteudo_sensivel_e_redigido_antes_de_persistir(self):
        session = self.service.create_chat_session(self.user.id, "Seguranca")
        content = (
            "reset_password_token=ABC123 "
            "verify_email_token=DEF456 "
            "api_key=SECRET "
            "senha=oculta "
            "abcdef1234567890abcdef1234567890abcdef1234567890"
        )

        message = self.service.add_chat_message(session.id, self.user.id, "user", content)

        self.assertNotIn("ABC123", message.conteudo)
        self.assertNotIn("DEF456", message.conteudo)
        self.assertNotIn("SECRET", message.conteudo)
        self.assertNotIn("oculta", message.conteudo)
        self.assertIn("reset_password_token=[REDACTED]", message.conteudo)
        self.assertIn("[REDACTED_HASH]", message.conteudo)

    def test_redacao_funciona_sem_banco(self):
        redacted = redact_sensitive_content("password=abc token=xyz")

        self.assertEqual(redacted, "password=[REDACTED] token=[REDACTED]")

    def test_status_invalido_vira_ok(self):
        session = self.service.create_chat_session(self.user.id, "Status")

        message = self.service.add_chat_message(session.id, self.user.id, "assistant", "Resposta", status="estranho")

        self.assertEqual(message.status, "ok")

    def test_nao_usa_delete_fisico_nem_tabelas_datasus(self):
        source = Path("src/chat/chat_history_service.py").read_text(encoding="utf-8").upper()

        self.assertNotIn("DELETE FROM", source)
        for fragment in ["DATA_SUS", "VW_DATA_SUS_IA", "DIM_"]:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
