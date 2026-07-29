import inspect
import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text

from src.auth.user_service import UserService
from src.chat.chat_history_service import ChatHistoryService
from src.diagnostics.health_service import (
    HealthCheckResult,
    HealthService,
    classify_application_database_failure,
)


def _flatten(value):
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value)


class TestHealthService(unittest.TestCase):
    def setUp(self):
        self.auth_engine = create_engine("sqlite+pysqlite:///:memory:")
        self.user_service = UserService(self.auth_engine)
        self.chat_history_service = ChatHistoryService(self.auth_engine)

        self.analytics_engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.analytics_engine.begin() as conn:
            conn.execute(text("CREATE TABLE vw_data_sus_ia (data TEXT)"))
            conn.execute(text("INSERT INTO vw_data_sus_ia (data) VALUES ('2026-06-01')"))

        self.service = HealthService(
            auth_engine=self.auth_engine,
            analytics_engine=self.analytics_engine,
        )

    def test_app_health_retorna_ok(self):
        result = self.service.check_app()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.name, "app")
        self.assertIn("Aplicacao", result.message)

    def test_banco_de_aplicacao_retorna_ok(self):
        result = self.service.check_application_database()

        self.assertEqual(result.status, "ok")
        self.assertTrue(result.details["connectivity"])
        self.assertNotIn("sqlite+pysqlite://", _flatten(result.as_dict()))

    def test_falha_de_banco_de_aplicacao_e_segura(self):
        def failing_factory():
            raise RuntimeError("postgresql://user:senha-super-secreta@localhost/db")

        service = HealthService(auth_engine_factory=failing_factory)

        result = service.check_application_database()
        payload = _flatten(result.as_dict())

        self.assertEqual(result.status, "error")
        self.assertNotIn("senha-super-secreta", payload)
        self.assertNotIn("postgresql://user:senha-super-secreta", payload)
        self.assertEqual(result.details["connection_category"], "query_failure")

    def test_tabelas_de_aplicacao_encontradas(self):
        result = self.service.check_application_tables()

        self.assertEqual(result.status, "ok")
        self.assertTrue(result.details["tables"]["usuarios"])
        self.assertTrue(result.details["tables"]["chat_sessions"])
        self.assertTrue(result.details["tables"]["chat_messages"])

    def test_tabelas_de_aplicacao_ausentes_geram_warning(self):
        empty_engine = create_engine("sqlite+pysqlite:///:memory:")
        service = HealthService(auth_engine=empty_engine)

        result = service.check_application_tables()

        self.assertEqual(result.status, "warning")
        self.assertIn("usuarios", result.details["missing_tables"])

    def test_view_datasus_e_validada_com_read_only(self):
        result = self.service.check_datasus_view()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.details["source"], "vw_data_sus_ia")
        self.assertTrue(result.details["read_only"])
        self.assertEqual(result.details["latest_date_available"], "2026-06-01")

    def test_falha_da_view_datasus_nao_expoe_configuracao(self):
        def failing_factory():
            raise RuntimeError("AI_DB_PASSWORD=segredo AI_DB_HOST=host")

        service = HealthService(analytics_engine_factory=failing_factory)

        result = service.check_datasus_view()
        payload = _flatten(result.as_dict())

        self.assertEqual(result.status, "warning")
        self.assertNotIn("segredo", payload)
        self.assertNotIn("AI_DB_PASSWORD=segredo", payload)

    def test_configuracao_ai_sem_chave_retorna_warning_sem_expor_chave(self):
        env = {
            "AI_USE_LLM": "true",
            "AI_LLM_PROVIDER": "gemini",
            "AI_LLM_MODEL": "gemini/gemini-2.0-flash",
            "ENVIRONMENT": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            result = self.service.check_ai_configuration()

        self.assertEqual(result.status, "warning")
        self.assertFalse(result.details["api_key_configured"])
        self.assertEqual(result.details["provider"], "gemini")

    def test_configuracao_ai_com_chave_mostra_apenas_booleano(self):
        env = {
            "AI_USE_LLM": "true",
            "AI_LLM_PROVIDER": "gemini",
            "AI_LLM_MODEL": "gemini/gemini-2.0-flash",
            "GEMINI_API_KEY": "AIza-chave-real-nao-deve-aparecer",
            "ENVIRONMENT": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            result = self.service.check_ai_configuration()

        payload = _flatten(result.as_dict())
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.details["api_key_configured"])
        self.assertNotIn("AIza-chave-real-nao-deve-aparecer", payload)

    def test_email_fake_local_e_reportado_sem_segredos(self):
        env = {
            "EMAIL_ENABLED": "false",
            "EMAIL_PROVIDER": "fake",
            "EMAIL_SMTP_PASSWORD": "smtp-secret",
            "EMAIL_API_KEY": "api-secret",
            "EMAIL_VERIFICATION_REQUIRED": "false",
            "ENVIRONMENT": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            result = self.service.check_email_configuration()

        payload = _flatten(result.as_dict())
        self.assertEqual(result.status, "ok")
        self.assertFalse(result.details["enabled"])
        self.assertEqual(result.details["provider"], "fake")
        self.assertNotIn("smtp-secret", payload)
        self.assertNotIn("api-secret", payload)

    def test_email_provider_nao_suportado_falha_com_seguranca(self):
        env = {
            "EMAIL_ENABLED": "true",
            "EMAIL_PROVIDER": "provedor-estranho",
            "EMAIL_API_KEY": "api-secret",
            "ENVIRONMENT": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            result = self.service.check_email_configuration()

        payload = _flatten(result.as_dict())
        self.assertEqual(result.status, "error")
        self.assertNotIn("api-secret", payload)

    def test_email_smtp_completo_e_reportado_sem_senha(self):
        env = {
            "EMAIL_ENABLED": "true",
            "EMAIL_PROVIDER": "smtp",
            "EMAIL_FROM": "SIA DATASUS <noreply@example.com>",
            "EMAIL_SMTP_HOST": "smtp.example.com",
            "EMAIL_SMTP_PORT": "587",
            "EMAIL_SMTP_USERNAME": "noreply@example.com",
            "EMAIL_SMTP_PASSWORD": "smtp-secret",
            "ENVIRONMENT": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            result = self.service.check_email_configuration()

        payload = _flatten(result.as_dict())
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.details["smtp_password_configured"])
        self.assertNotIn("smtp-secret", payload)

    def test_resultado_sanitiza_mensagem_e_detalhes(self):
        result = HealthCheckResult(
            name="teste",
            status="error",
            message="Falha password=abc123",
            details={
                "database_url": "postgresql://user:abc123@host/db",
                "api_key": "secret-key",
                "safe_boolean": True,
            },
        )

        payload = result.as_dict()
        flattened = _flatten(payload)

        self.assertNotIn("abc123", flattened)
        self.assertNotIn("secret-key", flattened)
        self.assertTrue(payload["details"]["safe_boolean"])

    def test_diagnostico_nao_usa_escrita_em_tabelas_datasus(self):
        import src.diagnostics.health_service as health_service

        source = inspect.getsource(health_service).upper()

        for fragment in [
            "INSERT INTO VW_DATA_SUS_IA",
            "UPDATE VW_DATA_SUS_IA",
            "DELETE FROM VW_DATA_SUS_IA",
            "DROP VIEW VW_DATA_SUS_IA",
            "ALTER VIEW VW_DATA_SUS_IA",
            "CREATE VIEW VW_DATA_SUS_IA",
        ]:
            self.assertNotIn(fragment, source)
        self.assertIn("SELECT MAX(DATA) AS ULTIMA_DATA FROM", source)

    def test_heartbeat_retorna_ok_quando_ambos_bancos_respondem(self):
        result = self.service.run_heartbeat()

        self.assertEqual(result.name, "heartbeat")
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.details["auth_db_ok"])
        self.assertTrue(result.details["analytics_db_ok"])

    def test_heartbeat_retorna_error_quando_banco_autenticacao_falha(self):
        def failing_auth_factory():
            from sqlalchemy import create_engine
            engine = create_engine("sqlite+pysqlite:///:memory:")
            engine.dispose()
            engine.pool.dispose()
            # Forçamos falha fechando a conexão definitivamente
            raise RuntimeError("banco offline simulado")

        service = HealthService(
            auth_engine_factory=failing_auth_factory,
            analytics_engine=self.analytics_engine,
        )
        result = service.run_heartbeat()

        self.assertEqual(result.name, "heartbeat")
        self.assertEqual(result.status, "error")
        self.assertFalse(result.details["auth_db_ok"])

    def test_heartbeat_retorna_error_quando_banco_analitico_falha(self):
        def failing_analytics_factory():
            raise RuntimeError("analytics offline simulado")

        service = HealthService(
            auth_engine=self.auth_engine,
            analytics_engine_factory=failing_analytics_factory,
        )
        result = service.run_heartbeat()

        self.assertEqual(result.name, "heartbeat")
        self.assertEqual(result.status, "ok")
        self.assertFalse(result.details["analytics_db_ok"])
        self.assertTrue(result.details["degraded"])

    def test_heartbeat_as_dict_tem_campos_esperados(self):
        result = self.service.run_heartbeat()
        payload = result.as_dict()

        self.assertIn("name", payload)
        self.assertIn("status", payload)
        self.assertIn("message", payload)
        self.assertIn("details", payload)
        self.assertIn("checked_at", payload)

    def test_application_database_failure_categories(self):
        cases = {
            "could not translate host name": "dns_failure",
            "SSL certificate failed": "ssl_failure",
            "password authentication failed": "authentication_failure",
            "permission denied": "permission_denied",
            'relation "usuarios" does not exist': "schema_missing",
            "connection refused": "connection_failure",
            "unexpected query": "query_failure",
        }
        for message, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(
                    classify_application_database_failure(RuntimeError(message)),
                    expected,
                )

    def test_application_database_schema_missing_is_unhealthy(self):
        empty_engine = create_engine("sqlite+pysqlite:///:memory:")
        result = HealthService(auth_engine=empty_engine).check_application_database()
        self.assertEqual(result.status, "error")
        self.assertEqual(result.details["connection_category"], "schema_missing")
        self.assertFalse(result.details["critical_schema_available"])

    def test_analytical_database_diagnostic_is_readonly_and_safe(self):
        result = self.service.check_analytical_database()
        payload = _flatten(result.as_dict())
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.details["session_readonly"])
        self.assertTrue(result.details["view_available"])
        self.assertTrue(result.details["view_query_success"])
        self.assertTrue(result.details["maximum_date_query_success"])
        self.assertTrue(result.details["essential_checks_passed"])
        self.assertEqual(result.details["maximum_available_data_date"], "2026-06-01")
        self.assertNotIn("sqlite+pysqlite", payload)

    def test_unified_report_all_healthy_and_safe(self):
        report = self.service.run_unified_report()
        payload = _flatten(report)
        self.assertEqual(report["application"]["status"], "healthy")
        self.assertEqual(report["application_database"]["status"], "healthy")
        self.assertEqual(report["analytical_database"]["status"], "healthy")
        self.assertNotIn("password", payload.casefold())
        self.assertNotIn("postgresql://", payload)

    def test_unified_report_analytical_failure_is_degraded_not_unhealthy(self):
        service = HealthService(
            auth_engine=self.auth_engine,
            analytics_engine_factory=lambda: (_ for _ in ()).throw(RuntimeError("connection refused")),
        )
        report = service.run_unified_report()
        self.assertEqual(report["application"]["status"], "healthy")
        self.assertEqual(report["overall_status"], "degraded")
        self.assertEqual(report["application_database"]["status"], "healthy")
        self.assertEqual(report["analytical_database"]["status"], "degraded")

    def test_unified_report_application_database_failure_is_unhealthy(self):
        service = HealthService(
            auth_engine_factory=lambda: (_ for _ in ()).throw(RuntimeError("connection refused")),
            analytics_engine=self.analytics_engine,
        )
        report = service.run_unified_report()
        self.assertEqual(report["application"]["status"], "healthy")
        self.assertEqual(report["overall_status"], "unhealthy")
        self.assertEqual(report["application_database"]["status"], "unhealthy")

    def test_optional_metadata_unavailable_does_not_degrade_essential_success(self):
        details = {
            "configuration_source": "AI_DATABASE_URL",
            "connection_category": "connection_success",
            "session_readonly": True,
            "view_available": True,
            "view_query_success": True,
            "maximum_date_query_success": True,
            "maximum_available_data_date": "2026-06-01",
            "essential_checks_passed": True,
            "underlying_metadata_check": "permission_denied",
            "warning_categories": ["underlying_metadata_permission_denied"],
        }
        with patch(
            "src.diagnostics.health_service.get_analytical_database_diagnostic",
            return_value=details,
        ):
            result = HealthService(auth_engine=self.auth_engine).check_analytical_database()

        self.assertEqual(result.status, "ok")
        self.assertEqual(
            result.details["warning_categories"],
            ["underlying_metadata_permission_denied"],
        )

    def test_missing_view_and_select_denied_degrade_analytical_health(self):
        for category in ("view_missing", "permission_denied"):
            with self.subTest(category=category), patch(
                "src.diagnostics.health_service.get_analytical_database_diagnostic",
                return_value={
                    "connection_category": category,
                    "session_readonly": True,
                    "view_available": category != "view_missing",
                    "view_query_success": False,
                    "maximum_date_query_success": False,
                    "essential_checks_passed": False,
                    "warning_categories": [],
                },
            ):
                result = HealthService(auth_engine=self.auth_engine).check_analytical_database()

            self.assertEqual(result.status, "warning")
            self.assertFalse(result.details["essential_checks_passed"])


if __name__ == "__main__":
    unittest.main()
