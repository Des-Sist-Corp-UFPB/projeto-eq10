import unittest
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from src.auth.email_change_service import (
    EMAIL_CHANGE_DUPLICATE_MESSAGE,
    EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE,
    EMAIL_CHANGE_INVALID_MESSAGE,
    EMAIL_CHANGE_SENT_MESSAGE,
    EMAIL_CHANGE_SUCCESS_MESSAGE,
    EMAIL_CHANGE_USED_MESSAGE,
    EmailChangeService,
    hash_email_change_token,
)
from src.auth.email_service import EmailConfig, EmailSendResult, EmailService, mask_email
from src.auth.user_service import AuthValidationError, UserService, _now


class RecordingEmailService(EmailService):
    def __init__(self, *, success=True, sent=True):
        super().__init__(
            EmailConfig(
                enabled=True,
                provider="smtp",
                from_email="noreply@example.com",
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="noreply@example.com",
                smtp_password="smtp-secret",
            )
        )
        self.success_result = success
        self.sent_result = sent
        self.change_target = ""
        self.recipient = ""

    def send_email_change_confirmation_email(self, to: str, confirmation_url: str) -> EmailSendResult:
        self.recipient = to
        self.change_target = confirmation_url
        return EmailSendResult(
            success=self.success_result,
            sent=self.sent_result,
            provider=self.config.provider,
            mode="smtp",
            message="ok" if self.success_result else "falha segura",
            error_code=None if self.success_result else "smtp_send_failed",
            message_type="email_change",
            recipient=mask_email(to),
        )


class TestEmailChangeService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.user_service = UserService(self.engine)
        self.email_service = RecordingEmailService()
        self.change_service = EmailChangeService(
            self.engine,
            email_service=self.email_service,
            app_public_url="https://app.example.com",
        )
        self.user = self.user_service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

    def _change_row(self):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM email_change_tokens
                    WHERE user_id = :user_id
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"user_id": self.user.id},
            ).mappings().first()

    def _token_count(self):
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT COUNT(*) AS total FROM email_change_tokens")).mappings().first()
        return int(row["total"])

    def _user_row(self, user_id=None):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM usuarios
                    WHERE id = :id
                    """
                ),
                {"id": user_id or self.user.id},
            ).mappings().first()

    def test_schema_de_tokens_e_criado(self):
        with self.engine.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(email_change_tokens)")).mappings()
            }

        self.assertIn("user_id", columns)
        self.assertIn("novo_email", columns)
        self.assertIn("token_hash", columns)
        self.assertIn("criado_em", columns)
        self.assertIn("expira_em", columns)
        self.assertIn("usado_em", columns)

    def test_solicitar_alteracao_nao_atualiza_email_imediatamente(self):
        result = self.change_service.request_email_change(
            self.user.id,
            "ana.nova@example.com",
            "senha-forte",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "sent")
        self.assertEqual(result.message, EMAIL_CHANGE_SENT_MESSAGE)
        self.assertTrue(result.token_created)
        self.assertEqual(self._user_row()["email"], "ana@example.com")
        self.assertEqual(self.email_service.recipient, "ana.nova@example.com")
        self.assertIn("https://app.example.com?confirm_email_change_token=", self.email_service.change_target)
        self.assertNotIn(self.email_service.change_target, result.message)
        self.assertNotIn(self.email_service.change_target, str(result.send_result.as_dict()))

    def test_token_armazena_hash_e_nao_token_cru(self):
        token = self.change_service.create_email_change_token(self.user.id, "ana.nova@example.com")
        row = self._change_row()

        self.assertNotEqual(row["token_hash"], token.raw_token)
        self.assertEqual(row["token_hash"], hash_email_change_token(token.raw_token))
        self.assertEqual(len(row["token_hash"]), 64)

    def test_token_valido_atualiza_email_e_verificacao(self):
        token = self.change_service.create_email_change_token(self.user.id, "ana.nova@example.com")

        result = self.change_service.confirm_email_change_token(token.raw_token)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "changed")
        self.assertEqual(result.message, EMAIL_CHANGE_SUCCESS_MESSAGE)
        self.assertEqual(result.user.email, "ana.nova@example.com")
        row = self._user_row()
        self.assertEqual(row["email"], "ana.nova@example.com")
        self.assertTrue(row["email_verificado"])
        self.assertIsNotNone(row["email_verificado_em"])
        self.assertIsNotNone(self._change_row()["usado_em"])

    def test_token_expirado_falha_sem_alterar_email(self):
        token = self.change_service.create_email_change_token(self.user.id, "ana.nova@example.com")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE email_change_tokens
                    SET expira_em = :expira_em
                    WHERE user_id = :user_id
                    """
                ),
                {"expira_em": _now() - timedelta(minutes=1), "user_id": self.user.id},
            )

        result = self.change_service.confirm_email_change_token(token.raw_token)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "expired")
        self.assertEqual(result.message, EMAIL_CHANGE_INVALID_MESSAGE)
        self.assertEqual(self._user_row()["email"], "ana@example.com")

    def test_token_usado_nao_pode_ser_reutilizado(self):
        token = self.change_service.create_email_change_token(self.user.id, "ana.nova@example.com")
        self.change_service.confirm_email_change_token(token.raw_token)

        result = self.change_service.confirm_email_change_token(token.raw_token)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "used")
        self.assertEqual(result.message, EMAIL_CHANGE_USED_MESSAGE)

    def test_email_ativo_duplicado_e_bloqueado_com_mensagem_segura(self):
        self.user_service.create_user(
            "Bia Souza",
            "bia@example.com",
            "senha-forte",
            "senha-forte",
        )

        result = self.change_service.request_email_change(self.user.id, "bia@example.com", "senha-forte")

        self.assertFalse(result.success)
        self.assertEqual(result.status, "duplicate_email")
        self.assertEqual(result.message, EMAIL_CHANGE_DUPLICATE_MESSAGE)
        self.assertEqual(self._token_count(), 0)

    def test_usuario_deletado_nao_solicita_alteracao(self):
        self.user_service.soft_delete_user(self.user.id)

        with self.assertRaises(AuthValidationError):
            self.change_service.request_email_change(self.user.id, "ana.nova@example.com", "senha-forte")

        self.assertEqual(self._token_count(), 0)

    def test_senha_atual_invalida_falha_sem_token(self):
        with self.assertRaises(AuthValidationError) as context:
            self.change_service.request_email_change(self.user.id, "ana.nova@example.com", "errada")

        self.assertEqual(context.exception.public_message, "Senha atual invalida.")
        self.assertEqual(self._token_count(), 0)

    def test_modo_fake_nao_promete_envio_real_nem_cria_token(self):
        service = EmailChangeService(
            self.engine,
            email_service=EmailService(EmailConfig(enabled=False, provider="fake")),
        )

        result = service.request_email_change(self.user.id, "ana.nova@example.com", "senha-forte")

        self.assertFalse(result.success)
        self.assertEqual(result.status, "email_disabled")
        self.assertEqual(result.message, EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE)
        self.assertEqual(self._token_count(), 0)

    def test_token_cru_nao_aparece_em_logs(self):
        with self.assertLogs("src.auth.email_change_service", level="INFO") as context:
            token = self.change_service.create_email_change_token(self.user.id, "ana.nova@example.com")

        logs = "\n".join(context.output)
        self.assertNotIn(token.raw_token, logs)
        self.assertIn("Token de alteracao de e-mail criado", logs)

    def test_alteracao_nao_toca_tabelas_datasus(self):
        source = Path("src/auth/email_change_service.py").read_text(encoding="utf-8").upper()

        for fragment in ["DATA_SUS", "VW_DATA_SUS_IA", "DIM_"]:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
