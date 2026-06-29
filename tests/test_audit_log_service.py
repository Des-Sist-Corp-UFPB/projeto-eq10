import unittest

from sqlalchemy import create_engine, text

from src.audit.audit_log_service import AuditLogService, EVENT_CHAT_PROMPT, EVENT_LOGIN


class TestAuditLogService(unittest.TestCase):
    def test_falha_de_auditoria_nao_propaga_e_loga_resumo_seguro(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        service = AuditLogService(engine, initialize_schema=False)

        with self.assertLogs("src.audit.audit_log_service", level="WARNING") as logs:
            service.log_event(EVENT_LOGIN, user_id=1, user_email="ana@example.com")

        output = "\n".join(logs.output)
        self.assertIn("falha ao registrar evento", output)
        self.assertIn("audit log table does not exist", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("ana@example.com", output)

    def test_busca_de_auditoria_falha_com_lista_vazia_segura(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        service = AuditLogService(engine, initialize_schema=False)

        with self.assertLogs("src.audit.audit_log_service", level="WARNING") as logs:
            entries = service.get_recent_logs()

        self.assertEqual(entries, [])
        self.assertNotIn("Traceback", "\n".join(logs.output))

    def test_evento_persistido_tem_status_origem_acao(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        service = AuditLogService(engine)

        service.log_event(
            EVENT_LOGIN,
            user_id=1,
            user_email="ana@example.com",
            detalhe="provider=password",
            status="success",
            source="auth",
            action="login",
        )

        entry = service.get_recent_logs(limit=1)[0]

        self.assertEqual(entry.evento, EVENT_LOGIN)
        self.assertEqual(entry.status, "success")
        self.assertEqual(entry.source, "auth")
        self.assertEqual(entry.action, "login")

    def test_sanitiza_prompt_e_detalhe_sensiveis_antes_de_persistir(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        service = AuditLogService(engine)
        prompt = "senha=segredo " + ("x" * 300)
        detail = "OperationalError postgresql://user:password@host/db reset_password_token=abc123"

        service.log_event(
            EVENT_CHAT_PROMPT,
            user_id=1,
            user_email="ana@example.com",
            prompt_text=prompt,
            detalhe=detail,
        )

        entry = service.get_recent_logs(limit=1)[0]

        self.assertLessEqual(len(entry.prompt_text), 160)
        self.assertNotIn("segredo", entry.prompt_text)
        self.assertNotIn("password@host", entry.detalhe)
        self.assertNotIn("abc123", entry.detalhe)
        self.assertIn("[db-url-oculta]", entry.detalhe)

    def test_schema_antigo_sem_status_continua_recebendo_evento(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        evento TEXT NOT NULL,
                        user_id INTEGER NULL,
                        user_email TEXT NULL,
                        prompt_text TEXT NULL,
                        detalhe TEXT NULL,
                        criado_em TIMESTAMP NOT NULL
                    )
                    """
                )
            )
        service = AuditLogService(engine, initialize_schema=False)

        service.log_event(EVENT_LOGIN, user_id=1, user_email="ana@example.com")

        entries = service.get_recent_logs(limit=1)
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].status)


if __name__ == "__main__":
    unittest.main()
