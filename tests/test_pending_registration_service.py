import unittest
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, text

from src.auth.email_service import EmailConfig, EmailSendResult, EmailService, mask_email
from src.auth.pending_registration_service import (
    MAX_REGISTRATION_CODE_ATTEMPTS,
    REGISTRATION_ACTIVE_EMAIL_MESSAGE,
    REGISTRATION_DELETED_EMAIL_MESSAGE,
    REGISTRATION_EMAIL_DISABLED_MESSAGE,
    REGISTRATION_EXPIRED_CODE_MESSAGE,
    REGISTRATION_SUCCESS_MESSAGE,
    REGISTRATION_TOO_MANY_ATTEMPTS_MESSAGE,
    PendingRegistrationService,
    hash_registration_code,
)
from src.auth.security import verify_password
from src.auth.user_service import UserService, _now


class SentEmailService(EmailService):
    def __init__(self):
        super().__init__(EmailConfig(enabled=True, provider="smtp"))
        self.messages = []

    def send_email(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        *,
        message_type: str = "generic",
    ) -> EmailSendResult:
        self.messages.append(
            {
                "to": to,
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
                "message_type": message_type,
            }
        )
        return EmailSendResult(
            success=True,
            sent=True,
            provider="smtp",
            mode="smtp",
            message="sent",
            message_type=message_type,
            recipient=mask_email(to),
        )


class TestPendingRegistrationService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.user_service = UserService(self.engine)
        self.email_service = SentEmailService()
        self.service = PendingRegistrationService(self.engine, email_service=self.email_service)

    def _pending_row(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM pending_registrations
                    WHERE lower(email) = :email
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"email": email},
            ).mappings().first()

    def _active_pending_count(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS total
                    FROM pending_registrations
                    WHERE lower(email) = :email
                      AND usado_em IS NULL
                    """
                ),
                {"email": email},
            ).mappings().first()
        return int(row["total"])

    def _user_row(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM usuarios
                    WHERE lower(email) = :email
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"email": email},
            ).mappings().first()

    def _user_count(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT COUNT(*) AS total FROM usuarios WHERE lower(email) = :email"),
                {"email": email},
            ).mappings().first()
        return int(row["total"])

    def test_schema_de_cadastro_pendente_e_criado(self):
        with self.engine.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(pending_registrations)")).mappings()
            }

        self.assertIn("nome", columns)
        self.assertIn("email", columns)
        self.assertIn("senha_hash", columns)
        self.assertIn("codigo_hash", columns)
        self.assertIn("expira_em", columns)
        self.assertIn("usado_em", columns)
        self.assertIn("tentativas", columns)
        self.assertIn("consumed_user_id", columns)

    def test_cadastro_pendente_nao_cria_usuario_imediatamente(self):
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="123456"):
            result = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        self.assertTrue(result.success)
        self.assertEqual(self._user_count(), 0)
        self.assertEqual(self._active_pending_count(), 1)
        self.assertEqual(self.email_service.messages[-1]["message_type"], "registration_verification_code")
        self.assertIn("123456", self.email_service.messages[-1]["body_text"])
        self.assertNotIn("123456", str(result))

    def test_cadastro_pendente_armazena_hashes_e_nao_valores_crus(self):
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="123456"):
            self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        row = self._pending_row()

        self.assertNotEqual(row["senha_hash"], "senha-forte")
        self.assertTrue(verify_password("senha-forte", row["senha_hash"]))
        self.assertNotEqual(row["codigo_hash"], "123456")
        self.assertEqual(row["codigo_hash"], hash_registration_code("123456"))

    def test_codigo_valido_cria_usuario_verificado(self):
        from src.audit.audit_log_service import AuditLogService

        AuditLogService(self.engine)
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="123456"):
            result = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        confirm_result = self.service.confirm_registration_code(
            result.pending_registration_id,
            "ana@example.com",
            "123456",
        )
        user_row = self._user_row()
        pending_row = self._pending_row()

        self.assertTrue(confirm_result.success)
        self.assertEqual(confirm_result.message, REGISTRATION_SUCCESS_MESSAGE)
        self.assertEqual(user_row["email"], "ana@example.com")
        self.assertTrue(user_row["email_verificado"])
        self.assertIsNotNone(user_row["email_verificado_em"])
        self.assertFalse(user_row["deletado"])
        self.assertIsNone(user_row["deletado_em"])
        self.assertIsNotNone(pending_row["usado_em"])
        self.assertEqual(pending_row["consumed_user_id"], user_row["id"])
        authenticated = self.user_service.authenticate("ana@example.com", "senha-forte")
        self.assertEqual(authenticated.email, "ana@example.com")
        with self.engine.connect() as conn:
            audit_row = conn.execute(
                text(
                    """
                    SELECT evento, status, user_email, detalhe
                    FROM audit_log
                    WHERE evento = 'account_created'
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["status"], "success")
        self.assertEqual(audit_row["user_email"], "ana@example.com")
        self.assertIn("pending_registration", audit_row["detalhe"])

    def test_codigo_nao_pode_ser_reutilizado(self):
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="123456"):
            result = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        first = self.service.confirm_registration_code(result.pending_registration_id, "ana@example.com", "123456")
        second = self.service.confirm_registration_code(result.pending_registration_id, "ana@example.com", "123456")

        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertEqual(self._user_count(), 1)

    def test_codigo_expirado_nao_cria_usuario(self):
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="123456"):
            result = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE pending_registrations SET expira_em = :expira_em WHERE id = :id"),
                {"id": result.pending_registration_id, "expira_em": _now() - timedelta(minutes=1)},
            )

        confirm_result = self.service.confirm_registration_code(
            result.pending_registration_id,
            "ana@example.com",
            "123456",
        )

        self.assertFalse(confirm_result.success)
        self.assertEqual(confirm_result.message, REGISTRATION_EXPIRED_CODE_MESSAGE)
        self.assertEqual(self._user_count(), 0)

    def test_tentativas_invalidas_demais_bloqueiam_codigo(self):
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="123456"):
            result = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        last_result = None
        for _ in range(MAX_REGISTRATION_CODE_ATTEMPTS):
            last_result = self.service.confirm_registration_code(
                result.pending_registration_id,
                "ana@example.com",
                "000000",
            )

        self.assertIsNotNone(last_result)
        self.assertFalse(last_result.success)
        self.assertEqual(last_result.message, REGISTRATION_TOO_MANY_ATTEMPTS_MESSAGE)
        self.assertEqual(self._user_count(), 0)

    def test_email_enabled_false_nao_finge_envio_e_nao_cria_usuario(self):
        fake_service = PendingRegistrationService(
            self.engine,
            email_service=EmailService(EmailConfig(enabled=False, provider="fake")),
        )

        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="123456"):
            result = fake_service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        self.assertFalse(result.success)
        self.assertEqual(result.message, REGISTRATION_EMAIL_DISABLED_MESSAGE)
        self.assertEqual(self._user_count(), 0)
        self.assertEqual(self._active_pending_count(), 0)

    def test_email_ativo_duplicado_e_bloqueado(self):
        self.user_service.create_user("Ana Silva", "ana@example.com", "senha-forte", "senha-forte")

        result = self.service.start_registration(
            "Ana Silva",
            "ana@example.com",
            "outra-senha",
            "outra-senha",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "active_email_exists")
        self.assertEqual(result.message, REGISTRATION_ACTIVE_EMAIL_MESSAGE)
        self.assertEqual(self._user_count(), 1)

    def test_usuario_deletado_nao_e_recriado_silenciosamente(self):
        user = self.user_service.create_user("Ana Silva", "ana@example.com", "senha-forte", "senha-forte")
        self.user_service.soft_delete_user(user.id)

        result = self.service.start_registration(
            "Ana Silva",
            "ana@example.com",
            "outra-senha",
            "outra-senha",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "deactivated_user_found")
        self.assertEqual(result.message, REGISTRATION_DELETED_EMAIL_MESSAGE)
        self.assertEqual(self._user_count(), 1)

    def test_novo_codigo_substitui_pendente_anterior_sem_duplicar_ativos(self):
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="111111"):
            first = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="222222"):
            second = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        self.assertNotEqual(first.pending_registration_id, second.pending_registration_id)
        self.assertEqual(self._active_pending_count(), 1)
        first_confirm = self.service.confirm_registration_code(first.pending_registration_id, "ana@example.com", "111111")
        second_confirm = self.service.confirm_registration_code(second.pending_registration_id, "ana@example.com", "222222")
        self.assertFalse(first_confirm.success)
        self.assertTrue(second_confirm.success)
        self.assertEqual(self._user_count(), 1)

    def test_pendente_expirado_nao_bloqueia_novo_cadastro(self):
        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="111111"):
            first = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE pending_registrations SET expira_em = :expira_em WHERE id = :id"),
                {"id": first.pending_registration_id, "expira_em": _now() - timedelta(minutes=1)},
            )

        with patch("src.auth.pending_registration_service.generate_registration_code", return_value="222222"):
            second = self.service.start_registration(
                "Ana Silva",
                "ana@example.com",
                "senha-forte",
                "senha-forte",
            )

        self.assertTrue(second.success)
        self.assertEqual(self._active_pending_count(), 1)
        stale_confirm = self.service.confirm_registration_code(first.pending_registration_id, "ana@example.com", "111111")
        fresh_confirm = self.service.confirm_registration_code(second.pending_registration_id, "ana@example.com", "222222")

        self.assertFalse(stale_confirm.success)
        self.assertTrue(fresh_confirm.success)
        self.assertEqual(self._user_count(), 1)


if __name__ == "__main__":
    unittest.main()
