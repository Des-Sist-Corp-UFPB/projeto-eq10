import os
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from src.ai.config import AI_ALLOWED_COLUMNS
from src.ai.data_provider import load_controlled_datasus_dataframe
from src.audit.audit_log_service import AuditLogService
from src.auth.account_reactivation_service import AccountReactivationService
from src.auth.email_change_service import EmailChangeService
from src.auth.email_verification_service import EmailVerificationService
from src.auth.password_reset_service import PasswordResetService
from src.auth.pending_registration_service import PendingRegistrationService
from src.auth.user_service import UserService, _get_auth_database_url
from src.chat.chat_history_service import ChatHistoryService


class TestDatabaseRouting(unittest.TestCase):
    def test_application_services_from_environment_use_application_engine(self):
        fake_engine = MagicMock(name="application_engine")
        fake_email_service = MagicMock(name="email_service")
        cases = [
            (UserService, "src.auth.user_service.get_auth_engine", None),
            (AuditLogService, "src.auth.user_service.get_auth_engine", None),
            (ChatHistoryService, "src.chat.chat_history_service.get_auth_engine", None),
            (
                PendingRegistrationService,
                "src.auth.pending_registration_service.get_auth_engine",
                "src.auth.pending_registration_service.EmailService.from_environment",
            ),
            (
                PasswordResetService,
                "src.auth.password_reset_service.get_auth_engine",
                "src.auth.password_reset_service.EmailService.from_environment",
            ),
            (
                EmailVerificationService,
                "src.auth.email_verification_service.get_auth_engine",
                "src.auth.email_verification_service.EmailService.from_environment",
            ),
            (
                EmailChangeService,
                "src.auth.email_change_service.get_auth_engine",
                "src.auth.email_change_service.EmailService.from_environment",
            ),
            (
                AccountReactivationService,
                "src.auth.account_reactivation_service.get_auth_engine",
                "src.auth.account_reactivation_service.EmailService.from_environment",
            ),
        ]

        for service_class, engine_path, email_path in cases:
            with self.subTest(service=service_class.__name__):
                patches = [
                    patch(engine_path, return_value=fake_engine),
                    patch.object(service_class, "__init__", return_value=None),
                ]
                if email_path:
                    patches.append(patch(email_path, return_value=fake_email_service))

                with patches[0] as engine_factory, patches[1] as initializer:
                    if len(patches) == 3:
                        with patches[2]:
                            service_class.from_environment()
                    else:
                        service_class.from_environment()

                engine_factory.assert_called_once_with()
                self.assertIn(fake_engine, initializer.call_args.args)

    @patch("src.ai.data_provider.get_readonly_engine")
    @patch("src.ai.data_provider.get_last_available_date", return_value=date(2026, 3, 1))
    @patch("src.ai.data_provider.pd.read_sql_query")
    def test_datasus_provider_uses_only_ai_readonly_engine(
        self,
        read_sql_query,
        _last_date,
        readonly_engine_factory,
    ):
        fake_engine = MagicMock(name="ai_readonly_engine")
        readonly_engine_factory.return_value = fake_engine
        read_sql_query.return_value = pd.DataFrame(
            [{column: None for column in AI_ALLOWED_COLUMNS}]
        )

        with patch("src.auth.user_service.get_auth_engine", side_effect=AssertionError("auth engine used")):
            load_controlled_datasus_dataframe()

        readonly_engine_factory.assert_called_once_with()
        self.assertIs(read_sql_query.call_args.kwargs["con"], fake_engine)

    def test_production_does_not_use_generic_or_legacy_auth_fallbacks(self):
        unsafe_envs = [
            {"ENVIRONMENT": "production", "DATABASE_URL": "postgresql://user:secret@example/db"},
            {
                "ENVIRONMENT": "production",
                "user": "legacy",
                "password": "secret",
                "host": "localhost",
                "database": "app",
            },
            {
                "ENVIRONMENT": "production",
                "AI_DB_USER": "ia",
                "AI_DB_PASSWORD": "secret",
                "AI_DB_HOST": "neon.example",
                "AI_DB_PORT": "5432",
                "AI_DB_NAME": "analytics",
            },
        ]

        for env in unsafe_envs:
            with self.subTest(env=sorted(env)):
                with patch.dict(os.environ, env, clear=True):
                    with self.assertRaises(RuntimeError):
                        _get_auth_database_url()

    def test_legacy_auth_fallback_logs_only_source_outside_production(self):
        env = {
            "ENVIRONMENT": "development",
            "DATABASE_URL": "postgresql://user:secret@example/db",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertLogs("src.auth.user_service", level="WARNING") as logs:
                _database_url, source = _get_auth_database_url()

        payload = "\n".join(logs.output)
        self.assertEqual(source, "DATABASE_URL")
        self.assertIn("DATABASE_URL", payload)
        self.assertNotIn("secret", payload)
        self.assertNotIn("postgresql://", payload)

    def test_incomplete_production_auth_config_fails_with_safe_log(self):
        env = {
            "ENVIRONMENT": "production",
            "AUTH_DB_HOST": "app-db.example",
            "AUTH_DB_USER": "auth_user",
        }

        with patch.dict(os.environ, env, clear=True):
            with self.assertLogs("src.auth.user_service", level="ERROR") as logs:
                with self.assertRaises(RuntimeError) as context:
                    _get_auth_database_url()

        payload = "\n".join(logs.output)
        self.assertIn("AUTH_DB_PORT", payload)
        self.assertIn("AUTH_DB_NAME", payload)
        self.assertIn("AUTH_DB_PASSWORD", payload)
        self.assertNotIn("app-db.example", payload)
        self.assertNotIn("auth_user", payload)
        self.assertIn("AUTH_DB_PASSWORD", str(context.exception))


if __name__ == "__main__":
    unittest.main()
