import unittest
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from src.auth.email_change_service import (
    EMAIL_CHANGE_CODE_SENT_MESSAGE,
    EMAIL_CHANGE_DUPLICATE_MESSAGE,
    EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE,
    EMAIL_CHANGE_EXPIRED_CODE_MESSAGE,
    EMAIL_CHANGE_INVALID_CODE_MESSAGE,
    EMAIL_CHANGE_SUCCESS_MESSAGE,
    EMAIL_CHANGE_TOO_MANY_ATTEMPTS_MESSAGE,
    EMAIL_CHANGE_USED_CODE_MESSAGE,
    EmailChangeService,
    hash_email_change_code,
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
        self.code = ""
        self.recipient = ""
        self.expires_in_minutes = 0

    def send_email_change_code_email(
        self,
        to: str,
        code: str,
        *,
        expires_in_minutes: int = 15,
    ) -> EmailSendResult:
        self.recipient = to
        self.code = code
        self.expires_in_minutes = expires_in_minutes
        return EmailSendResult(
            success=self.success_result,
            sent=self.sent_result,
            provider=self.config.provider,
            mode="smtp",
            message="ok" if self.success_result else "falha segura",
            error_code=None if self.success_result else "smtp_send_failed",
            message_type="email_change_code",
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
        )
        self.user = self.user_service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

    def _change_row(self, user_id=None):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM pending_email_changes
                    WHERE user_id = :user_id
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"user_id": user_id or self.user.id},
            ).mappings().first()

    def _change_count(self):
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT COUNT(*) AS total FROM pending_email_changes")).mappings().first()
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

    def test_schema_de_alteracao_pendente_e_criado(self):
        with self.engine.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(pending_email_changes)")).mappings()
            }

        self.assertIn("user_id", columns)
        self.assertIn("novo_email", columns)
        self.assertIn("codigo_hash", columns)
        self.assertIn("criado_em", columns)
        self.assertIn("expira_em", columns)
        self.assertIn("usado_em", columns)
        self.assertIn("tentativas", columns)

    def test_solicitar_alteracao_nao_atualiza_email_imediatamente(self):
        result = self.change_service.request_email_change(
            self.user.id,
            "ana.nova@example.com",
            "senha-forte",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "code_sent")
        self.assertEqual(result.message, EMAIL_CHANGE_CODE_SENT_MESSAGE)
        self.assertIsNotNone(result.pending_change_id)
        self.assertEqual(self._user_row()["email"], "ana@example.com")
        self.assertEqual(self.email_service.recipient, "ana.nova@example.com")
        self.assertEqual(len(self.email_service.code), 6)
        self.assertTrue(self.email_service.code.isdigit())
        self.assertNotIn(self.email_service.code, result.message)
        self.assertNotIn(self.email_service.code, str(result.send_result.as_dict()))

    def test_alteracao_pendente_armazena_hash_e_nao_codigo_cru(self):
        pending = self.change_service.create_pending_email_change(self.user.id, "ana.nova@example.com")
        row = self._change_row()

        self.assertNotEqual(row["codigo_hash"], pending.raw_code)
        self.assertEqual(row["codigo_hash"], hash_email_change_code(pending.raw_code))
        self.assertEqual(len(row["codigo_hash"]), 64)

    def test_codigo_valido_atualiza_email_e_verificacao(self):
        pending = self.change_service.create_pending_email_change(self.user.id, "ana.nova@example.com")

        result = self.change_service.confirm_email_change_code(pending.id, self.user.id, pending.raw_code)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "changed")
        self.assertEqual(result.message, EMAIL_CHANGE_SUCCESS_MESSAGE)
        self.assertEqual(result.user.email, "ana.nova@example.com")
        row = self._user_row()
        self.assertEqual(row["email"], "ana.nova@example.com")
        self.assertTrue(row["email_verificado"])
        self.assertIsNotNone(row["email_verificado_em"])
        self.assertIsNotNone(self._change_row()["usado_em"])

    def test_codigo_expirado_falha_sem_alterar_email(self):
        pending = self.change_service.create_pending_email_change(self.user.id, "ana.nova@example.com")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE pending_email_changes
                    SET expira_em = :expira_em
                    WHERE id = :id
                    """
                ),
                {"expira_em": _now() - timedelta(minutes=1), "id": pending.id},
            )

        result = self.change_service.confirm_email_change_code(pending.id, self.user.id, pending.raw_code)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "expired")
        self.assertEqual(result.message, EMAIL_CHANGE_EXPIRED_CODE_MESSAGE)
        self.assertEqual(self._user_row()["email"], "ana@example.com")

    def test_codigo_usado_nao_pode_ser_reutilizado(self):
        pending = self.change_service.create_pending_email_change(self.user.id, "ana.nova@example.com")
        self.change_service.confirm_email_change_code(pending.id, self.user.id, pending.raw_code)

        result = self.change_service.confirm_email_change_code(pending.id, self.user.id, pending.raw_code)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "used")
        self.assertEqual(result.message, EMAIL_CHANGE_USED_CODE_MESSAGE)

    def test_codigo_errado_incrementa_tentativas(self):
        pending = self.change_service.create_pending_email_change(self.user.id, "ana.nova@example.com")

        result = self.change_service.confirm_email_change_code(pending.id, self.user.id, "000000")

        self.assertFalse(result.success)
        self.assertEqual(result.status, "invalid_code")
        self.assertEqual(result.message, EMAIL_CHANGE_INVALID_CODE_MESSAGE)
        self.assertEqual(int(self._change_row()["tentativas"]), 1)
        self.assertEqual(self._user_row()["email"], "ana@example.com")

    def test_tentativas_invalidas_demais_bloqueiam_codigo(self):
        pending = self.change_service.create_pending_email_change(self.user.id, "ana.nova@example.com")

        result = None
        for _ in range(self.change_service.max_attempts):
            result = self.change_service.confirm_email_change_code(pending.id, self.user.id, "000000")

        self.assertFalse(result.success)
        self.assertEqual(result.status, "too_many_attempts")
        self.assertEqual(result.message, EMAIL_CHANGE_TOO_MANY_ATTEMPTS_MESSAGE)
        valid_after_block = self.change_service.confirm_email_change_code(pending.id, self.user.id, pending.raw_code)
        self.assertFalse(valid_after_block.success)
        self.assertEqual(valid_after_block.status, "too_many_attempts")
        self.assertEqual(self._user_row()["email"], "ana@example.com")

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
        self.assertEqual(self._change_count(), 0)

    def test_usuario_deletado_nao_solicita_alteracao(self):
        self.user_service.soft_delete_user(self.user.id)

        with self.assertRaises(AuthValidationError):
            self.change_service.request_email_change(self.user.id, "ana.nova@example.com", "senha-forte")

        self.assertEqual(self._change_count(), 0)

    def test_senha_atual_invalida_falha_sem_pendente(self):
        with self.assertRaises(AuthValidationError) as context:
            self.change_service.request_email_change(self.user.id, "ana.nova@example.com", "errada")

        self.assertEqual(context.exception.public_message, "Senha atual invalida.")
        self.assertEqual(self._change_count(), 0)

    def test_modo_fake_nao_promete_envio_real_nem_cria_pendente(self):
        service = EmailChangeService(
            self.engine,
            email_service=EmailService(EmailConfig(enabled=False, provider="fake")),
        )

        result = service.request_email_change(self.user.id, "ana.nova@example.com", "senha-forte")

        self.assertFalse(result.success)
        self.assertEqual(result.status, "email_disabled")
        self.assertEqual(result.message, EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE)
        self.assertEqual(self._change_count(), 0)

    def test_codigo_cru_nao_aparece_em_logs(self):
        with self.assertLogs("src.auth.email_change_service", level="INFO") as context:
            pending = self.change_service.create_pending_email_change(self.user.id, "ana.nova@example.com")

        logs = "\n".join(context.output)
        self.assertNotIn(pending.raw_code, logs)
        self.assertIn("Alteracao de e-mail pendente criada", logs)

    def test_alteracao_nao_toca_tabelas_datasus(self):
        source = Path("src/auth/email_change_service.py").read_text(encoding="utf-8").upper()

        for fragment in ["DATA_SUS", "VW_DATA_SUS_IA", "DIM_"]:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
