import unittest
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from src.auth.email_service import EmailConfig, EmailService
from src.auth.password_reset_service import (
    PASSWORD_RESET_INVALID_MESSAGE,
    PASSWORD_RESET_NEUTRAL_MESSAGE,
    PASSWORD_RESET_USED_MESSAGE,
    PasswordResetService,
    hash_password_reset_token,
)
from src.auth.security import verify_password
from src.auth.user_service import AuthValidationError, UserService, _now


class TestPasswordResetService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.user_service = UserService(self.engine)
        self.email_service = EmailService(EmailConfig(enabled=False, provider="fake"))
        self.reset_service = PasswordResetService(self.engine, email_service=self.email_service)
        self.user = self.user_service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

    def _reset_row(self):
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    """
                    SELECT *
                    FROM password_reset_tokens
                    WHERE user_id = :user_id
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ),
                {"user_id": self.user.id},
            ).mappings().first()

    def _token_count(self):
        with self.engine.connect() as conn:
            row = conn.execute(text("SELECT COUNT(*) AS total FROM password_reset_tokens")).mappings().first()
        return int(row["total"])

    def _senha_hash(self):
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT senha_hash FROM usuarios WHERE id = :id"),
                {"id": self.user.id},
            ).mappings().first()
        return row["senha_hash"]

    def test_schema_de_tokens_e_criado(self):
        with self.engine.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(password_reset_tokens)")).mappings()
            }

        self.assertIn("user_id", columns)
        self.assertIn("token_hash", columns)
        self.assertIn("criado_em", columns)
        self.assertIn("expira_em", columns)
        self.assertIn("usado_em", columns)

    def test_token_armazena_hash_e_nao_token_cru(self):
        token = self.reset_service.create_password_reset_token(self.user.id)
        row = self._reset_row()

        self.assertNotEqual(row["token_hash"], token.raw_token)
        self.assertEqual(row["token_hash"], hash_password_reset_token(token.raw_token))
        self.assertEqual(len(row["token_hash"]), 64)

    def test_solicitacao_usuario_ativo_cria_token_em_modo_fake(self):
        result = self.reset_service.request_password_reset("ana@example.com")

        self.assertTrue(result.success)
        self.assertEqual(result.status, "fake")
        self.assertEqual(result.message, PASSWORD_RESET_NEUTRAL_MESSAGE)
        self.assertTrue(result.token_created)
        self.assertIsNotNone(result.send_result)
        self.assertFalse(result.send_result.sent)
        self.assertEqual(self._token_count(), 1)

    def test_email_desconhecido_retorna_mensagem_neutra_sem_token(self):
        result = self.reset_service.request_password_reset("ninguem@example.com")

        self.assertTrue(result.success)
        self.assertEqual(result.message, PASSWORD_RESET_NEUTRAL_MESSAGE)
        self.assertFalse(result.token_created)
        self.assertEqual(self._token_count(), 0)

    def test_usuario_desativado_nao_recebe_token_util(self):
        self.user_service.soft_delete_user(self.user.id)

        result = self.reset_service.request_password_reset("ana@example.com")

        self.assertTrue(result.success)
        self.assertEqual(result.message, PASSWORD_RESET_NEUTRAL_MESSAGE)
        self.assertFalse(result.token_created)
        self.assertEqual(self._token_count(), 0)

    def test_token_valido_redefine_senha_e_marca_usado(self):
        token = self.reset_service.create_password_reset_token(self.user.id)

        result = self.reset_service.reset_password_with_token(
            token.raw_token,
            "nova-senha",
            "nova-senha",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "reset")
        with self.assertRaises(AuthValidationError):
            self.user_service.authenticate("ana@example.com", "senha-forte")
        self.assertEqual(
            self.user_service.authenticate("ana@example.com", "nova-senha").id,
            self.user.id,
        )
        self.assertNotEqual(self._senha_hash(), "nova-senha")
        self.assertTrue(verify_password("nova-senha", self._senha_hash()))
        self.assertIsNotNone(self._reset_row()["usado_em"])

    def test_token_expirado_falha_sem_alterar_senha(self):
        token = self.reset_service.create_password_reset_token(self.user.id)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE password_reset_tokens
                    SET expira_em = :expira_em
                    WHERE user_id = :user_id
                    """
                ),
                {"expira_em": _now() - timedelta(minutes=1), "user_id": self.user.id},
            )

        result = self.reset_service.reset_password_with_token(
            token.raw_token,
            "nova-senha",
            "nova-senha",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "expired")
        self.assertEqual(result.message, PASSWORD_RESET_INVALID_MESSAGE)
        self.assertEqual(
            self.user_service.authenticate("ana@example.com", "senha-forte").id,
            self.user.id,
        )

    def test_token_usado_nao_pode_ser_reutilizado(self):
        token = self.reset_service.create_password_reset_token(self.user.id)
        self.reset_service.reset_password_with_token(token.raw_token, "nova-senha", "nova-senha")

        result = self.reset_service.reset_password_with_token(
            token.raw_token,
            "outra-senha",
            "outra-senha",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "used")
        self.assertEqual(result.message, PASSWORD_RESET_USED_MESSAGE)

    def test_token_invalido_falha_com_mensagem_segura(self):
        result = self.reset_service.validate_password_reset_token("token-inexistente")

        self.assertFalse(result.success)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.message, PASSWORD_RESET_INVALID_MESSAGE)

    def test_confirmacao_de_senha_invalida_falha_antes_de_alterar(self):
        token = self.reset_service.create_password_reset_token(self.user.id)

        with self.assertRaises(AuthValidationError) as context:
            self.reset_service.reset_password_with_token(token.raw_token, "nova-senha", "diferente")

        self.assertEqual(context.exception.public_message, "As senhas nao coincidem.")
        self.assertEqual(
            self.user_service.authenticate("ana@example.com", "senha-forte").id,
            self.user.id,
        )

    def test_token_cru_nao_aparece_em_logs(self):
        with self.assertLogs("src.auth.password_reset_service", level="INFO") as context:
            token = self.reset_service.create_password_reset_token(self.user.id)

        logs = "\n".join(context.output)
        self.assertNotIn(token.raw_token, logs)
        self.assertIn("Token de recuperacao criado", logs)

    def test_resultado_publico_nao_expoe_token_ou_link(self):
        result = self.reset_service.request_password_reset("ana@example.com")
        row = self._reset_row()

        self.assertNotIn(row["token_hash"], result.message)
        self.assertNotIn("reset_password_token", result.message)
        self.assertEqual(result.message, PASSWORD_RESET_NEUTRAL_MESSAGE)

    def test_recuperacao_nao_toca_tabelas_datasus(self):
        source = Path("src/auth/password_reset_service.py").read_text(encoding="utf-8").upper()

        for fragment in ["DATA_SUS", "VW_DATA_SUS_IA", "DIM_"]:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
