import os
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text

from src.auth.email_service import EmailConfig, EmailService
from src.auth.email_verification_service import (
    EMAIL_VERIFICATION_FAKE_MESSAGE,
    EMAIL_VERIFICATION_INVALID_MESSAGE,
    EMAIL_VERIFICATION_REQUIRED_ENV,
    EMAIL_VERIFICATION_USED_MESSAGE,
    EmailVerificationService,
    hash_email_verification_token,
    is_email_verification_required,
)
from src.auth.user_service import UserService, _now


class TestEmailVerificationService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.user_service = UserService(self.engine)
        self.email_service = EmailService(EmailConfig(enabled=False, provider="fake"))
        self.verification_service = EmailVerificationService(
            self.engine,
            email_service=self.email_service,
        )
        self.user = self.user_service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

    def _verification_row(self):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM email_verification_tokens
                    WHERE user_id = :user_id
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"user_id": self.user.id},
            ).mappings().first()

    def test_schema_adiciona_campos_de_verificacao(self):
        with self.engine.connect() as conn:
            user_columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(usuarios)")).mappings()
            }
            token_columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(email_verification_tokens)")).mappings()
            }

        self.assertIn("email_verificado", user_columns)
        self.assertIn("email_verificado_em", user_columns)
        self.assertIn("user_id", token_columns)
        self.assertIn("token_hash", token_columns)
        self.assertIn("expira_em", token_columns)
        self.assertIn("usado_em", token_columns)

    def test_novo_usuario_inicia_com_email_nao_verificado(self):
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT email_verificado, email_verificado_em
                    FROM usuarios
                    WHERE id = :id
                    """
                ),
                {"id": self.user.id},
            ).mappings().first()

        self.assertFalse(row["email_verificado"])
        self.assertIsNone(row["email_verificado_em"])
        self.assertFalse(self.verification_service.is_email_verified(self.user.id))

    def test_token_armazena_hash_e_nao_token_cru(self):
        token = self.verification_service.create_email_verification_token(self.user.id)
        row = self._verification_row()

        self.assertNotEqual(row["token_hash"], token.raw_token)
        self.assertEqual(row["token_hash"], hash_email_verification_token(token.raw_token))
        self.assertEqual(len(row["token_hash"]), 64)

    def test_token_valido_marca_usuario_como_verificado(self):
        token = self.verification_service.create_email_verification_token(self.user.id)

        result = self.verification_service.verify_email_token(token.raw_token)

        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertTrue(self.verification_service.is_email_verified(self.user.id))
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT email_verificado, email_verificado_em
                    FROM usuarios
                    WHERE id = :id
                    """
                ),
                {"id": self.user.id},
            ).mappings().first()
        self.assertTrue(row["email_verificado"])
        self.assertIsNotNone(row["email_verificado_em"])

    def test_token_invalido_falha_com_mensagem_segura(self):
        result = self.verification_service.verify_email_token("token-inexistente")

        self.assertFalse(result.success)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.message, EMAIL_VERIFICATION_INVALID_MESSAGE)

    def test_token_expirado_falha_sem_verificar_usuario(self):
        token = self.verification_service.create_email_verification_token(self.user.id)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE email_verification_tokens
                    SET expira_em = :expira_em
                    WHERE user_id = :user_id
                    """
                ),
                {"expira_em": _now() - timedelta(minutes=1), "user_id": self.user.id},
            )

        result = self.verification_service.verify_email_token(token.raw_token)

        self.assertFalse(result.success)
        self.assertEqual(result.status, "expired")
        self.assertFalse(self.verification_service.is_email_verified(self.user.id))

    def test_token_usado_nao_pode_ser_reutilizado(self):
        token = self.verification_service.create_email_verification_token(self.user.id)

        first_result = self.verification_service.verify_email_token(token.raw_token)
        second_result = self.verification_service.verify_email_token(token.raw_token)

        self.assertTrue(first_result.success)
        self.assertFalse(second_result.success)
        self.assertEqual(second_result.status, "used")
        self.assertEqual(second_result.message, EMAIL_VERIFICATION_USED_MESSAGE)

    def test_envio_fake_cria_token_sem_prometer_envio_real(self):
        result = self.verification_service.send_verification_email(self.user.id)
        row = self._verification_row()

        self.assertTrue(result.success)
        self.assertEqual(result.status, "fake")
        self.assertEqual(result.message, EMAIL_VERIFICATION_FAKE_MESSAGE)
        self.assertIsNotNone(result.send_result)
        self.assertFalse(result.send_result.sent)
        self.assertEqual(result.send_result.mode, "fake")
        self.assertIsNotNone(row)

    def test_reenvio_cria_novo_token(self):
        first = self.verification_service.create_email_verification_token(self.user.id)

        result = self.verification_service.resend_verification_email(self.user.id)

        self.assertEqual(result.status, "fake")
        with self.engine.connect() as conn:
            rows = list(
                conn.execute(
                    text(
                        """
                        SELECT token_hash
                        FROM email_verification_tokens
                        WHERE user_id = :user_id
                        ORDER BY id
                        """
                    ),
                    {"user_id": self.user.id},
                ).mappings()
            )
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[-1]["token_hash"], hash_email_verification_token(first.raw_token))

    def test_token_cru_nao_aparece_em_logs(self):
        with self.assertLogs("src.auth.email_verification_service", level="INFO") as context:
            token = self.verification_service.create_email_verification_token(self.user.id)

        logs = "\n".join(context.output)
        self.assertNotIn(token.raw_token, logs)
        self.assertIn("Token de verificacao criado", logs)

    def test_configuracao_required_default_false(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_email_verification_required())

        with patch.dict(os.environ, {EMAIL_VERIFICATION_REQUIRED_ENV: "true"}, clear=True):
            self.assertTrue(is_email_verification_required())

    def test_usuario_nao_verificado_consegue_login_quando_required_false(self):
        with patch.dict(os.environ, {EMAIL_VERIFICATION_REQUIRED_ENV: "false"}, clear=True):
            authenticated_user = self.user_service.authenticate("ana@example.com", "senha-forte")

        self.assertEqual(authenticated_user.id, self.user.id)
        self.assertFalse(self.verification_service.is_email_verified(self.user.id))

    def test_verificacao_nao_toca_tabelas_datasus(self):
        source = Path("src/auth/email_verification_service.py").read_text(encoding="utf-8").upper()

        for fragment in ["DATA_SUS", "VW_DATA_SUS_IA", "DIM_"]:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
