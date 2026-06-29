import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text

from src.auth.account_reactivation_service import (
    ACCOUNT_REACTIVATION_EMAIL_DISABLED_MESSAGE,
    ACCOUNT_REACTIVATION_EXPIRED_CODE_MESSAGE,
    ACCOUNT_REACTIVATION_SUCCESS_MESSAGE,
    ACCOUNT_REACTIVATION_TOO_MANY_ATTEMPTS_MESSAGE,
    ACCOUNT_REACTIVATION_USED_CODE_MESSAGE,
    ACCOUNT_REACTIVATION_WINDOW_EXPIRED_MESSAGE,
    MAX_ACCOUNT_REACTIVATION_ATTEMPTS,
    AccountReactivationService,
    hash_reactivation_code,
)
from src.auth.email_service import EmailConfig, EmailSendResult, EmailService, mask_email
from src.auth.user_service import AuthValidationError, UserService, _now


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


class TestAccountReactivationService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.user_service = UserService(self.engine)
        self.email_service = SentEmailService()
        self.service = AccountReactivationService(
            self.engine,
            email_service=self.email_service,
            window_days=90,
        )

    def _create_deleted_user(self, email="ana@example.com"):
        user = self.user_service.create_user("Ana Silva", email, "senha-forte", "senha-forte")
        self.user_service.soft_delete_user(user.id)
        return user

    def _token_row(self, user_id: int):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM account_reactivation_tokens
                    WHERE user_id = :user_id
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"user_id": user_id},
            ).mappings().first()

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

    def test_schema_de_tokens_de_reativacao_e_criado(self):
        with self.engine.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(account_reactivation_tokens)")).mappings()
            }

        self.assertIn("user_id", columns)
        self.assertIn("codigo_hash", columns)
        self.assertIn("expira_em", columns)
        self.assertIn("usado_em", columns)
        self.assertIn("tentativas", columns)

    def test_email_ativo_nao_dispara_reativacao(self):
        self.user_service.create_user("Ana Silva", "ana@example.com", "senha-forte", "senha-forte")

        result = self.service.request_reactivation("ana@example.com")

        self.assertTrue(result.success)
        self.assertEqual(result.status, "not_applicable")
        self.assertIsNone(result.reactivation_token_id)
        self.assertEqual(len(self.email_service.messages), 0)

    def test_email_desativado_dispara_codigo_sem_criar_usuario_novo(self):
        user = self._create_deleted_user()

        with patch("src.auth.account_reactivation_service.generate_reactivation_code", return_value="123456"):
            result = self.service.request_reactivation("ana@example.com")

        row = self._token_row(user.id)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "code_sent")
        self.assertEqual(self._user_count(), 1)
        self.assertEqual(row["codigo_hash"], hash_reactivation_code("123456"))
        self.assertNotEqual(row["codigo_hash"], "123456")
        self.assertEqual(self.email_service.messages[-1]["message_type"], "account_reactivation_code")
        self.assertIn("123456", self.email_service.messages[-1]["body_text"])
        self.assertNotIn("123456", str(result))

    def test_codigo_valido_reativa_conta(self):
        from src.audit.audit_log_service import AuditLogService

        AuditLogService(self.engine)
        self._create_deleted_user()
        with patch("src.auth.account_reactivation_service.generate_reactivation_code", return_value="123456"):
            result = self.service.request_reactivation("ana@example.com")

        confirm_result = self.service.confirm_reactivation_code(
            result.reactivation_token_id,
            "ana@example.com",
            "123456",
        )
        user_row = self._user_row()

        self.assertTrue(confirm_result.success)
        self.assertEqual(confirm_result.message, ACCOUNT_REACTIVATION_SUCCESS_MESSAGE)
        self.assertFalse(user_row["deletado"])
        self.assertIsNone(user_row["deletado_em"])
        self.assertIsNone(user_row["deleted_at"])
        self.assertTrue(user_row["email_verificado"])
        self.assertIsNotNone(user_row["email_verificado_em"])
        authenticated = self.user_service.authenticate("ana@example.com", "senha-forte")
        self.assertEqual(authenticated.email, "ana@example.com")
        with self.engine.connect() as conn:
            audit_row = conn.execute(
                text(
                    """
                    SELECT evento, status, user_email, detalhe
                    FROM audit_log
                    WHERE evento = 'account_reactivated'
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row["status"], "success")
        self.assertEqual(audit_row["user_email"], "ana@example.com")
        self.assertNotIn("123456", str(audit_row["detalhe"]))

    def test_codigo_invalido_incrementa_tentativas_e_bloqueia(self):
        self._create_deleted_user()
        with patch("src.auth.account_reactivation_service.generate_reactivation_code", return_value="123456"):
            result = self.service.request_reactivation("ana@example.com")

        last_result = None
        for _ in range(MAX_ACCOUNT_REACTIVATION_ATTEMPTS):
            last_result = self.service.confirm_reactivation_code(
                result.reactivation_token_id,
                "ana@example.com",
                "000000",
            )

        self.assertIsNotNone(last_result)
        self.assertFalse(last_result.success)
        self.assertEqual(last_result.message, ACCOUNT_REACTIVATION_TOO_MANY_ATTEMPTS_MESSAGE)
        self.assertTrue(self._user_row()["deletado"])

    def test_codigo_expirado_falha(self):
        user = self._create_deleted_user()
        with patch("src.auth.account_reactivation_service.generate_reactivation_code", return_value="123456"):
            result = self.service.request_reactivation("ana@example.com")
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE account_reactivation_tokens SET expira_em = :expira_em WHERE user_id = :user_id"),
                {"user_id": user.id, "expira_em": _now() - timedelta(minutes=1)},
            )

        confirm_result = self.service.confirm_reactivation_code(
            result.reactivation_token_id,
            "ana@example.com",
            "123456",
        )

        self.assertFalse(confirm_result.success)
        self.assertEqual(confirm_result.message, ACCOUNT_REACTIVATION_EXPIRED_CODE_MESSAGE)
        self.assertTrue(self._user_row()["deletado"])

    def test_codigo_usado_nao_pode_ser_reutilizado(self):
        self._create_deleted_user()
        with patch("src.auth.account_reactivation_service.generate_reactivation_code", return_value="123456"):
            result = self.service.request_reactivation("ana@example.com")

        first = self.service.confirm_reactivation_code(result.reactivation_token_id, "ana@example.com", "123456")
        second = self.service.confirm_reactivation_code(result.reactivation_token_id, "ana@example.com", "123456")

        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertEqual(second.message, ACCOUNT_REACTIVATION_USED_CODE_MESSAGE)
        self.assertEqual(self._user_count(), 1)

    def test_conta_fora_da_janela_nao_reativa_automaticamente(self):
        user = self._create_deleted_user()
        with self.engine.begin() as conn:
            old_date = _now() - timedelta(days=91)
            conn.execute(
                text(
                    """
                    UPDATE usuarios
                    SET deletado_em = :old_date,
                        deleted_at = :old_date
                    WHERE id = :id
                    """
                ),
                {"id": user.id, "old_date": old_date},
            )

        result = self.service.request_reactivation("ana@example.com")

        self.assertFalse(result.success)
        self.assertEqual(result.message, ACCOUNT_REACTIVATION_WINDOW_EXPIRED_MESSAGE)
        self.assertIsNone(result.reactivation_token_id)
        self.assertEqual(len(self.email_service.messages), 0)

    def test_deletado_sem_timestamp_e_tratado_sem_crash(self):
        user = self._create_deleted_user()
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE usuarios SET deletado_em = NULL, deleted_at = NULL WHERE id = :id"),
                {"id": user.id},
            )

        with patch("src.auth.account_reactivation_service.generate_reactivation_code", return_value="123456"):
            result = self.service.request_reactivation("ana@example.com")

        self.assertTrue(result.success)
        self.assertEqual(result.status, "code_sent")

    def test_email_enabled_false_nao_finge_envio(self):
        self._create_deleted_user()
        fake_service = AccountReactivationService(
            self.engine,
            email_service=EmailService(EmailConfig(enabled=False, provider="fake")),
            window_days=90,
        )

        with patch("src.auth.account_reactivation_service.generate_reactivation_code", return_value="123456"):
            result = fake_service.request_reactivation("ana@example.com")

        self.assertFalse(result.success)
        self.assertEqual(result.message, ACCOUNT_REACTIVATION_EMAIL_DISABLED_MESSAGE)
        row = self._user_row()
        self.assertTrue(row["deletado"])

    def test_confirmacao_nao_toca_tabelas_datasus(self):
        source = Path("src/auth/account_reactivation_service.py").read_text(encoding="utf-8").lower()

        self.assertNotIn("data_sus", source)
        self.assertNotIn("vw_data_sus_ia", source)
        self.assertNotIn("dim_", source)


if __name__ == "__main__":
    unittest.main()
