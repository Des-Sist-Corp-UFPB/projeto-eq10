import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from src.auth.security import verify_password
from src.auth.user_service import (
    AuthValidationError,
    UserService,
    get_auth_engine,
    safe_auth_exception_summary,
)


class TestAuthUserService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        self.service = UserService(self.engine)

    def _senha_hash(self, email="ana@example.com"):
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT senha_hash FROM usuarios WHERE email = :email"),
                {"email": email},
            ).mappings().first()

        return row["senha_hash"]

    def test_schema_de_usuarios_e_inicializado(self):
        with self.engine.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute(text("PRAGMA table_info(usuarios)")).mappings()
            }
            indexes = {
                row["name"]
                for row in conn.execute(text("PRAGMA index_list(usuarios)")).mappings()
            }

        self.assertIn("id", columns)
        self.assertIn("nome", columns)
        self.assertIn("email", columns)
        self.assertIn("senha_hash", columns)
        self.assertIn("role", columns)
        self.assertIn("criado_em", columns)
        self.assertIn("atualizado_em", columns)
        self.assertIn("ultimo_login_em", columns)
        self.assertIn("email_verificado", columns)
        self.assertIn("email_verificado_em", columns)
        self.assertIn("deleted_at", columns)
        self.assertIn("deletado", columns)
        self.assertIn("deletado_em", columns)
        self.assertIn("ux_usuarios_email_ativo", indexes)

    def test_get_auth_engine_nao_usa_ai_db_readonly_como_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = os.path.join(tmpdir, "auth.sqlite3")
            env = {
                "ENVIRONMENT": "test",
                "AUTH_SQLITE_PATH": sqlite_path,
                "AI_DB_USER": "ia_readonly",
                "AI_DB_PASSWORD": "fake-password",
                "AI_DB_HOST": "fake-host",
                "AI_DB_NAME": "fake-db",
            }
            with patch.dict(os.environ, env, clear=True):
                engine = get_auth_engine()
                try:
                    service = UserService(engine)
                    created_user = service.create_user(
                        "Ana Silva",
                        "ana@example.com",
                        "senha-forte",
                        "senha-forte",
                    )
                    authenticated_user = service.authenticate("ana@example.com", "senha-forte")

                    self.assertEqual(engine.dialect.name, "sqlite")
                    self.assertIn("auth.sqlite3", str(engine.url))
                    self.assertTrue(os.path.exists(sqlite_path))
                    self.assertEqual(created_user.email, "ana@example.com")
                    self.assertEqual(authenticated_user.id, created_user.id)
                finally:
                    engine.dispose()

    def test_resumo_seguro_identifica_tabela_usuarios_ausente(self):
        exc = OperationalError(
            "SELECT * FROM usuarios",
            {},
            Exception('relation "usuarios" does not exist'),
        )

        self.assertEqual(safe_auth_exception_summary(exc), "users table does not exist")

    def test_resumo_seguro_identifica_dependencia_ausente(self):
        exc = ModuleNotFoundError("No module named 'psycopg2'")

        self.assertEqual(safe_auth_exception_summary(exc), "auth dependency missing")

    def test_cadastro_de_usuario(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        self.assertGreater(user.id, 0)
        self.assertEqual(user.nome, "Ana Silva")
        self.assertEqual(user.email, "ana@example.com")
        self.assertEqual(user.role, "user")

    def test_cadastro_cria_usuario_ativo_por_padrao(self):
        self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT deletado, deletado_em FROM usuarios WHERE email = :email"),
                {"email": "ana@example.com"},
            ).mappings().first()

        self.assertFalse(row["deletado"])
        self.assertIsNone(row["deletado_em"])

    def test_cadastro_cria_email_nao_verificado_por_padrao(self):
        self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT email_verificado, email_verificado_em
                    FROM usuarios
                    WHERE email = :email
                    """
                ),
                {"email": "ana@example.com"},
            ).mappings().first()

        self.assertFalse(row["email_verificado"])
        self.assertIsNone(row["email_verificado_em"])

    def test_senha_nao_e_salva_em_texto_puro(self):
        self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        senha_hash = self._senha_hash()

        self.assertNotEqual(senha_hash, "senha-forte")
        self.assertTrue(senha_hash.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password("senha-forte", senha_hash))

    def test_nao_permite_email_ativo_duplicado(self):
        self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.assertRaises(AuthValidationError) as context:
            self.service.create_user(
                "Outra Ana",
                "ANA@example.com",
                "senha-forte",
                "senha-forte",
            )

        self.assertEqual(
            context.exception.public_message,
            "Já existe uma conta ativa com este e-mail.",
        )

    def test_login_com_senha_correta(self):
        self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        user = self.service.authenticate("ana@example.com", "senha-forte")

        self.assertEqual(user.email, "ana@example.com")
        self.assertIsNotNone(user.ultimo_login_em)

    def test_falha_login_com_senha_incorreta(self):
        self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.assertRaises(AuthValidationError) as context:
            self.service.authenticate("ana@example.com", "senha-errada")

        self.assertEqual(context.exception.public_message, "E-mail ou senha inválidos.")

    def test_falha_login_usuario_com_deleted_at(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )
        self.service.soft_delete_user(user.id)

        with self.assertRaises(AuthValidationError) as context:
            self.service.authenticate("ana@example.com", "senha-forte")

        self.assertEqual(context.exception.public_message, "E-mail ou senha inválidos.")

    def test_login_bloqueia_usuario_com_deletado_boolean(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE usuarios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT NOT NULL,
                        email TEXT NOT NULL,
                        senha_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'user',
                        criado_em TIMESTAMP NOT NULL,
                        atualizado_em TIMESTAMP NOT NULL,
                        ultimo_login_em TIMESTAMP NULL,
                        deletado BOOLEAN DEFAULT false
                    )
                    """
                )
            )
        service = UserService(engine)
        user = service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        service.soft_delete_user(user.id)

        with self.assertRaises(AuthValidationError) as context:
            service.authenticate("ana@example.com", "senha-forte")

        self.assertEqual(context.exception.public_message, "E-mail ou senha inválidos.")
        self.assertFalse(service.active_email_exists("ana@example.com"))

    def test_soft_delete_remove_usuario_dos_ativos(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        self.service.soft_delete_user(user.id)

        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT deletado, deletado_em FROM usuarios WHERE id = :id"),
                {"id": user.id},
            ).mappings().first()

        self.assertTrue(row["deletado"])
        self.assertIsNotNone(row["deletado_em"])
        self.assertIsNone(self.service.get_user_by_id(user.id))
        self.assertFalse(self.service.active_email_exists("ana@example.com"))

    def test_desativacao_nao_usa_delete_fisico_nem_tabelas_datasus(self):
        source = Path("src/auth/user_service.py").read_text(encoding="utf-8").upper()

        self.assertNotIn("DELETE FROM USUARIOS", source)
        self.assertIn("UPDATE USUARIOS", source)
        for fragment in ["DATA_SUS", "VW_DATA_SUS_IA", "DIM_"]:
            self.assertNotIn(fragment, source)

    def test_alterar_nome(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        updated_user = self.service.update_name(user.id, "Ana Maria")

        self.assertEqual(updated_user.nome, "Ana Maria")

    def test_alterar_nome_rejeita_vazio(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.assertRaises(AuthValidationError) as context:
            self.service.update_name(user.id, "   ")

        self.assertEqual(context.exception.public_message, "Informe seu nome.")

    def test_alterar_email_atualiza_usuario(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        updated_user = self.service.update_email(user.id, "ana.nova@example.com")

        self.assertEqual(updated_user.email, "ana.nova@example.com")
        self.assertEqual(
            self.service.authenticate("ana.nova@example.com", "senha-forte").id,
            user.id,
        )

    def test_alterar_email_redefine_verificacao(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE usuarios
                    SET email_verificado = true,
                        email_verificado_em = atualizado_em
                    WHERE id = :id
                    """
                ),
                {"id": user.id},
            )

        self.service.update_email(user.id, "ana.nova@example.com")

        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT email_verificado, email_verificado_em
                    FROM usuarios
                    WHERE id = :id
                    """
                ),
                {"id": user.id},
            ).mappings().first()

        self.assertFalse(row["email_verificado"])
        self.assertIsNone(row["email_verificado_em"])

    def test_alterar_email_valida_formato(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.assertRaises(AuthValidationError) as context:
            self.service.update_email(user.id, "email-invalido")

        self.assertEqual(context.exception.public_message, "Informe um e-mail válido.")

    def test_alterar_email_bloqueia_email_ativo_duplicado(self):
        self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )
        user = self.service.create_user(
            "Bia Souza",
            "bia@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.assertRaises(AuthValidationError) as context:
            self.service.update_email(user.id, "ANA@example.com")

        self.assertEqual(
            context.exception.public_message,
            "JÃ¡ existe uma conta ativa com este e-mail.",
        )

    def test_alterar_senha_exige_senha_atual(self):
        user = self.service.create_user(
            "Ana Silva",
            "ana@example.com",
            "senha-forte",
            "senha-forte",
        )

        with self.assertRaises(AuthValidationError) as context:
            self.service.change_password(
                user.id,
                "senha-errada",
                "nova-senha",
                "nova-senha",
            )

        self.assertEqual(context.exception.public_message, "Senha atual invalida.")

        self.service.change_password(
            user.id,
            "senha-forte",
            "nova-senha",
            "nova-senha",
        )
        senha_hash = self._senha_hash()

        self.assertNotEqual(senha_hash, "nova-senha")
        self.assertTrue(verify_password("nova-senha", senha_hash))
        self.assertEqual(
            self.service.authenticate("ana@example.com", "nova-senha").id,
            user.id,
        )


if __name__ == "__main__":
    unittest.main()
