import os
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError, SQLAlchemyError

from src.ai import read_only_datasus
from src.audit import audit_log_service
from src.auth import security, user_service
from src.auth.roles import ROLE_ADMIN, ROLE_USER
from src.auth.user_service import AuthValidationError, UserService
from src import utils


class TestServiceHelperCoverage(unittest.TestCase):
    def test_auth_env_builders_prefer_explicit_safe_sources(self):
        fake_dotenv = types.SimpleNamespace(load_dotenv=MagicMock())
        with patch.dict(sys.modules, {"dotenv": fake_dotenv}):
            with patch.dict(os.environ, {"ENVIRONMENT": "dev"}, clear=True):
                user_service._load_env_files()

        self.assertEqual(fake_dotenv.load_dotenv.call_count, 2)

        env = {
            "AUTH_DB_USER": "user",
            "AUTH_DB_PASSWORD": "p@ ss",
            "AUTH_DB_HOST": "neon.example.com",
            "AUTH_DB_NAME": "neondb",
            "AUTH_DB_PORT": "5432",
        }
        with patch.dict(os.environ, env, clear=True):
            url = user_service._build_database_url("AUTH_DB")
        self.assertIn("p%40+ss", url)
        self.assertIn("sslmode=require", url)
        self.assertIn("channel_binding=require", url)

        lower_env = {
            "user": "legacy",
            "password": "secret",
            "host": "localhost",
            "database": "db",
        }
        with patch.dict(os.environ, lower_env, clear=True):
            legacy_url = user_service._build_lowercase_database_url()
        self.assertIn("legacy", legacy_url)
        self.assertIn("sslmode=disable", legacy_url)

        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = str(Path(tmpdir) / "auth.sqlite3")
            with patch.dict(os.environ, {"ENVIRONMENT": "test", "AUTH_SQLITE_PATH": sqlite_path}, clear=True):
                database_url, source = user_service._get_auth_database_url()
        self.assertEqual(source, "local SQLite")
        self.assertIn("sqlite+pysqlite:///", database_url)

        with patch.dict(os.environ, {"AUTH_DATABASE_URL": "sqlite+pysqlite:///:memory:"}, clear=True):
            self.assertEqual(user_service._get_auth_database_url(), ("sqlite+pysqlite:///:memory:", "AUTH_DATABASE_URL"))

        with patch.dict(os.environ, {"DATABASE_URL": "sqlite+pysqlite:///:memory:"}, clear=True):
            self.assertEqual(user_service._get_auth_database_url(), ("sqlite+pysqlite:///:memory:", "DATABASE_URL"))

        with patch.dict(os.environ, {"AUTH_DATABASE_URL": "sqlite+pysqlite:///:memory:", "ENVIRONMENT": "test"}, clear=True):
            with patch("sqlalchemy.create_engine", return_value="engine") as create_engine:
                self.assertEqual(user_service.get_auth_engine(), "engine")
        create_engine.assert_called_once()

    def test_user_service_helpers_and_schema_migration_paths(self):
        for password, confirmation, message in [
            ("", None, "Informe uma senha."),
            ("curta", None, "pelo menos"),
            ("SenhaSegura123", "", "Confirme sua senha."),
            ("SenhaSegura123", "OutraSenha123", "coincidem"),
        ]:
            with self.subTest(message=message):
                with self.assertRaises(AuthValidationError) as context:
                    user_service._validate_new_password(password, confirmation)
                self.assertIn(message, context.exception.public_message)

        self.assertEqual(user_service._active_user_condition(set()), "1 = 1")
        self.assertEqual(user_service._soft_delete_select_columns(set()), "NULL AS deleted_at, FALSE AS deletado, NULL AS deletado_em")
        self.assertFalse(user_service._is_soft_deleted({"deleted_at": None, "deletado": False, "deletado_em": None}))
        self.assertTrue(user_service._is_soft_deleted({"deleted_at": None, "deletado": True, "deletado_em": None}))

        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE usuarios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT NOT NULL,
                        email TEXT NOT NULL,
                        senha_hash TEXT NOT NULL
                    )
                    """
                )
            )
        UserService(engine)
        with engine.connect() as conn:
            senha_hash_info = conn.execute(text("PRAGMA table_info(usuarios)")).mappings().all()
        senha_hash_column = next(row for row in senha_hash_info if row["name"] == "senha_hash")
        self.assertFalse(bool(senha_hash_column["notnull"]))

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE dup_test (value TEXT)"))
            conn.execute(text("INSERT INTO dup_test (value) VALUES ('a'), ('a')"))
            with self.assertLogs("src.auth.user_service", level="WARNING") as logs:
                user_service._create_unique_index_safely(
                    conn,
                    "CREATE UNIQUE INDEX ux_dup_test_value ON dup_test (value)",
                    "ux_dup_test_value",
                )
        self.assertIn("ensure_schema_index", "\n".join(logs.output))

    def test_safe_database_error_summaries_cover_expected_categories(self):
        errors = [
            IntegrityError("stmt", {}, Exception("duplicate key")),
            OperationalError("stmt", {}, Exception("could not connect")),
            ProgrammingError("stmt", {}, Exception("bad sql")),
        ]
        summaries = [user_service.safe_auth_exception_summary(exc) for exc in errors]

        self.assertIn("duplicate or constraint violation", summaries)
        self.assertIn("database connection failed", summaries)
        self.assertIn("database schema or SQL error", summaries)
        self.assertEqual(user_service.safe_auth_exception_summary(ModuleNotFoundError("sqlalchemy")), "auth dependency missing")
        self.assertEqual(user_service.safe_auth_exception_summary(RuntimeError("boom")), "RuntimeError")

    def test_user_admin_operations_and_audit_failures_do_not_break_flow(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        service = UserService(engine)

        admin = service.create_user("Admin", "admin@example.com", "SenhaSegura123", "SenhaSegura123", role=ROLE_ADMIN)
        user = service.create_user("Ana", "ana@example.com", "SenhaSegura123", "SenhaSegura123")

        all_users = service.get_all_users()
        self.assertEqual({profile.email for profile in all_users}, {"admin@example.com", "ana@example.com"})

        updated = service.set_role(user.id, ROLE_ADMIN, acting_admin_id=admin.id, acting_admin_email=admin.email)
        self.assertEqual(updated.role, ROLE_ADMIN)

        with self.assertRaises(AuthValidationError):
            service.set_role(user.id, "root")

        service.set_audit_access(user.id, True, acting_admin_id=admin.id, acting_admin_email=admin.email)
        self.assertTrue(service.get_user_by_id(user.id).can_view_audit)
        service.set_audit_access(user.id, False, acting_admin_id=admin.id, acting_admin_email=admin.email)
        self.assertFalse(service.get_user_by_id(user.id).can_view_audit)

        service.soft_delete_user(user.id)
        self.assertIsNone(service.get_user_by_id(user.id))
        active_user = service.get_active_user_by_email("admin@example.com")
        self.assertEqual(active_user.id, admin.id)

    def test_security_fallbacks_and_legacy_hashes(self):
        with self.assertRaises(ValueError):
            security.hash_password("")

        with patch.object(security, "_get_argon2_hasher", return_value=None):
            legacy_hash = security.hash_password("SenhaSegura123")
        self.assertTrue(legacy_hash.startswith("pbkdf2_sha256$"))
        self.assertTrue(security.verify_password("SenhaSegura123", legacy_hash))
        self.assertFalse(security.verify_password("SenhaErrada", legacy_hash))
        self.assertFalse(security.verify_password("SenhaSegura123", "unknown$1$salt$digest"))

        bad_hasher = types.SimpleNamespace(verify=MagicMock(side_effect=RuntimeError("invalid")))
        with patch.object(security, "_get_argon2_hasher", return_value=bad_hasher):
            self.assertFalse(security.verify_password("SenhaSegura123", "$argon2id$broken"))

        with patch.object(security, "_get_argon2_hasher", return_value=None):
            self.assertFalse(security.verify_password("SenhaSegura123", "$argon2id$broken"))

    def test_audit_helpers_and_non_blocking_failure_paths(self):
        self.assertIsNone(audit_log_service._sanitize_text(None))
        self.assertIsNone(audit_log_service._sanitize_text("   "))
        sanitized = audit_log_service._sanitize_text(
            "Bearer abc.def token=raw postgresql://u:p@host/db reset_password_token=abc"
        )
        self.assertNotIn("abc.def", sanitized)
        self.assertNotIn("raw", sanitized)
        self.assertNotIn("postgresql://", sanitized)
        self.assertNotIn("reset_password_token=abc", sanitized)

        self.assertEqual(audit_log_service._infer_status("login"), "success")
        self.assertEqual(audit_log_service._infer_status("login_failure"), "failure")
        self.assertEqual(audit_log_service._infer_status("prompt_guard_block"), "blocked")
        self.assertEqual(audit_log_service._infer_status("logout"), "info")
        self.assertEqual(audit_log_service._infer_status("custom"), "info")

        class BrokenConn:
            def execute(self, query):
                raise SQLAlchemyError("boom")

        self.assertEqual(audit_log_service._get_audit_columns(BrokenConn(), "sqlite"), set())

        engine = create_engine("sqlite+pysqlite:///:memory:")
        service = audit_log_service.AuditLogService(engine)
        service.log_event(
            audit_log_service.EVENT_EMAIL_SENDING_FAILURE,
            user_id=1,
            user_email="ana@example.com",
            detalhe="smtp_password=secret",
            status="unexpected",
        )
        service.log_event("unknown_event", user_id=1)
        entries = service.get_logs_by_user(1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].status, "failure")
        self.assertNotIn("secret", entries[0].detalhe)

        class BrokenEngine:
            dialect = types.SimpleNamespace(name="sqlite")

            def begin(self):
                raise RuntimeError("db down")

        with self.assertLogs("src.audit.audit_log_service", level="WARNING") as logs:
            audit_log_service.AuditLogService(BrokenEngine(), initialize_schema=False).log_event(
                audit_log_service.EVENT_LOGIN,
                user_id=1,
            )
        self.assertIn("falha inesperada", "\n".join(logs.output))

    def test_readonly_and_query_utility_helpers(self):
        class FakeDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 1, 15)

        with patch.object(utils, "datetime", FakeDateTime):
            self.assertEqual(utils.get_target_period(), (2025, 11))

        class FakeDateTimeJune:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 29)

        with patch.object(utils, "datetime", FakeDateTimeJune):
            self.assertEqual(utils.get_target_period(), (2026, 4))

        fake_result = types.SimpleNamespace(mappings=lambda: types.SimpleNamespace(first=lambda: None))
        fake_conn = types.SimpleNamespace(execute=MagicMock(return_value=fake_result))

        class FakeEngine:
            def connect(self):
                return self

            def __enter__(self):
                return fake_conn

            def __exit__(self, exc_type, exc, tb):
                return False

        self.assertIsNone(read_only_datasus.get_last_available_date(FakeEngine()))


if __name__ == "__main__":
    unittest.main()
