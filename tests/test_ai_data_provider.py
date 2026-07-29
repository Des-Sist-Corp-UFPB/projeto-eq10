import inspect
import os
import unittest
from datetime import date
from unittest.mock import Mock, patch

import pandas as pd

from src.ai.config import AI_ALLOWED_COLUMNS, AI_DATA_SOURCE
from src.ai.data_provider import load_controlled_datasus_dataframe
from src.ai.read_only_datasus import (
    AI_CONFIG_ERROR_MESSAGE,
    _get_readonly_database_url,
    classify_analytical_database_failure,
    get_analytical_database_diagnostic,
    get_readonly_engine,
    get_readonly_database_config_source,
    _set_session_read_only,
)


class TestAiReadOnlyDataLayer(unittest.TestCase):
    def test_colunas_permitidas_usam_nomes_legiveis_da_view(self):
        self.assertEqual(
            AI_ALLOWED_COLUMNS,
            [
                "data",
                "idade",
                "sexo",
                "municipio_atendimento",
                "municipio_residencia",
                "raca_cor",
                "unidade",
                "ocupacao",
                "procedimento",
                "frequencia",
                "quantidade_apresentada",
                "valor_apresentado",
                "valor_aprovado",
            ],
        )
        self.assertNotIn("cod_municipio_atendido", AI_ALLOWED_COLUMNS)
        self.assertNotIn("cod_municipio_residencia", AI_ALLOWED_COLUMNS)

    def test_get_readonly_engine_falha_se_faltar_variavel_de_ambiente(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "test"}, clear=True):
            with self.assertRaises(RuntimeError) as context:
                get_readonly_engine()

        mensagem = str(context.exception)
        self.assertEqual(mensagem, AI_CONFIG_ERROR_MESSAGE)
        self.assertNotIn("AI_DB_PASSWORD=", mensagem)

    def test_get_readonly_engine_aceita_ai_database_url_sem_expor_segredo(self):
        url = "postgresql://ia_user:secret@example.invalid:5432/analytics"
        with patch.dict(os.environ, {"ENVIRONMENT": "test", "AI_DATABASE_URL": url}, clear=True):
            with patch("sqlalchemy.create_engine") as create_engine, patch(
                "sqlalchemy.event.listen"
            ) as listen:
                source = get_readonly_database_config_source()
                get_readonly_engine()

        self.assertEqual(source, "AI_DATABASE_URL")
        effective_url = create_engine.call_args.args[0]
        self.assertIn("sslmode=require", effective_url)
        self.assertNotEqual(effective_url, url)
        self.assertNotIn("connect_args", create_engine.call_args.kwargs)
        listen.assert_called_once()

    def test_ai_db_fields_build_neon_readonly_url_with_required_ssl(self):
        env = {
            "ENVIRONMENT": "test",
            "AI_DB_HOST": "ep-example.neon.tech",
            "AI_DB_PORT": "5432",
            "AI_DB_NAME": "analytics",
            "AI_DB_USER": "ia_readonly",
            "AI_DB_PASSWORD": "secret",
            "AI_DB_SSLMODE": "require",
        }
        with patch.dict(os.environ, env, clear=True):
            url, source = _get_readonly_database_url()

        self.assertEqual(source, "AI_DB_*")
        self.assertIn("@ep-example.neon.tech:5432/analytics", url)
        self.assertIn("sslmode=require", url)
        self.assertIn("channel_binding=require", url)

    def test_cloud_host_never_disables_ssl_but_local_host_can(self):
        cloud_env = {
            "ENVIRONMENT": "test",
            "AI_DB_HOST": "ep-example.neon.tech",
            "AI_DB_PORT": "5432",
            "AI_DB_NAME": "analytics",
            "AI_DB_USER": "ia_readonly",
            "AI_DB_PASSWORD": "secret",
            "AI_DB_SSLMODE": "disable",
        }
        with patch.dict(os.environ, cloud_env, clear=True):
            cloud_url, _ = _get_readonly_database_url()
        self.assertIn("sslmode=require", cloud_url)
        self.assertNotIn("sslmode=disable", cloud_url)

        local_env = {**cloud_env, "AI_DB_HOST": "postgres"}
        with patch.dict(os.environ, local_env, clear=True):
            local_url, _ = _get_readonly_database_url()
        self.assertIn("sslmode=disable", local_url)

    def test_readonly_is_applied_after_handshake_for_neon_pooler(self):
        dbapi_connection = Mock()
        cursor = dbapi_connection.cursor.return_value

        _set_session_read_only(dbapi_connection, Mock())

        cursor.execute.assert_called_once_with("SET default_transaction_read_only = on")
        cursor.close.assert_called_once_with()

    def test_safe_diagnostic_reports_success_without_credentials(self):
        engine = Mock()
        connection = Mock()
        engine.connect.return_value.__enter__ = Mock(return_value=connection)
        engine.connect.return_value.__exit__ = Mock(return_value=False)
        connection.execute.side_effect = [
            Mock(),
            Mock(scalar=Mock(return_value="on")),
            Mock(),
            Mock(scalar=Mock(return_value=date(2026, 7, 1))),
        ]
        env = {
            "ENVIRONMENT": "test",
            "AI_DATABASE_URL": (
                "postgresql+psycopg2://ia_readonly:secret@ep-example.neon.tech:5432/"
                "analytics?sslmode=require"
            ),
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("sqlalchemy.create_engine", return_value=engine), patch(
                "sqlalchemy.event.listen"
            ):
                diagnostic = get_analytical_database_diagnostic()

        self.assertEqual(diagnostic["selected_configuration_source"], "AI_DATABASE_URL")
        self.assertEqual(diagnostic["database_category"], "analytical")
        self.assertEqual(diagnostic["host_type"], "cloud")
        self.assertEqual(diagnostic["ssl_mode"], "require")
        self.assertEqual(diagnostic["connection_category"], "connection_success")
        self.assertTrue(diagnostic["view_available"])
        self.assertTrue(diagnostic["select_permission"])
        self.assertTrue(diagnostic["session_readonly"])
        self.assertTrue(diagnostic["view_query_success"])
        self.assertTrue(diagnostic["maximum_date_query_success"])
        self.assertTrue(diagnostic["essential_checks_passed"])
        self.assertEqual(diagnostic["underlying_metadata_check"], "not_required")
        self.assertEqual(diagnostic["maximum_available_data_date"], "2026-07-01")
        self.assertNotIn("secret", str(diagnostic))
        self.assertNotIn("ep-example", str(diagnostic))

        executed_sql = " ".join(str(call.args[0]) for call in connection.execute.call_args_list)
        self.assertNotIn("to_regclass", executed_sql)
        self.assertNotIn("has_table_privilege", executed_sql)

    def test_empty_view_with_null_maximum_date_is_healthy(self):
        engine = Mock()
        connection = Mock()
        engine.connect.return_value.__enter__ = Mock(return_value=connection)
        engine.connect.return_value.__exit__ = Mock(return_value=False)
        connection.execute.side_effect = [
            Mock(),
            Mock(scalar=Mock(return_value="on")),
            Mock(),
            Mock(scalar=Mock(return_value=None)),
        ]
        env = {
            "ENVIRONMENT": "test",
            "AI_DATABASE_URL": (
                "postgresql+psycopg2://ia_readonly:secret@ep-example.neon.tech:5432/"
                "analytics?sslmode=require"
            ),
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "sqlalchemy.create_engine", return_value=engine
        ), patch("sqlalchemy.event.listen"):
            diagnostic = get_analytical_database_diagnostic()

        self.assertTrue(diagnostic["essential_checks_passed"])
        self.assertTrue(diagnostic["maximum_date_query_success"])
        self.assertIsNone(diagnostic["maximum_available_data_date"])

    def test_view_missing_and_select_denied_fail_essential_checks_safely(self):
        cases = {
            'relation "vw_data_sus_ia" does not exist': "view_missing",
            "permission denied for relation vw_data_sus_ia": "permission_denied",
        }
        env = {
            "ENVIRONMENT": "test",
            "AI_DATABASE_URL": (
                "postgresql+psycopg2://ia_readonly:secret@ep-example.neon.tech:5432/"
                "analytics?sslmode=require"
            ),
        }
        for message, expected_category in cases.items():
            engine = Mock()
            connection = Mock()
            engine.connect.return_value.__enter__ = Mock(return_value=connection)
            engine.connect.return_value.__exit__ = Mock(return_value=False)
            connection.execute.side_effect = [
                Mock(),
                Mock(scalar=Mock(return_value="on")),
                RuntimeError(message),
            ]
            with self.subTest(category=expected_category), patch.dict(
                os.environ, env, clear=True
            ), patch("sqlalchemy.create_engine", return_value=engine), patch(
                "sqlalchemy.event.listen"
            ):
                diagnostic = get_analytical_database_diagnostic()

            self.assertEqual(diagnostic["connection_category"], expected_category)
            self.assertFalse(diagnostic["essential_checks_passed"])
            self.assertFalse(diagnostic["view_query_success"])
            self.assertNotIn("secret", str(diagnostic))

    def test_safe_diagnostic_reports_missing_configuration(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "test"}, clear=True):
            diagnostic = get_analytical_database_diagnostic()

        self.assertEqual(diagnostic["connection_category"], "configuration_missing")
        self.assertEqual(diagnostic["database_category"], "analytical")

    def test_database_failure_categories(self):
        cases = {
            "could not translate host name": "dns_failure",
            "SSL certificate verify failed": "ssl_failure",
            "password authentication failed": "authentication_failure",
            "permission denied for relation": "permission_denied",
            'relation "vw_data_sus_ia" does not exist': "view_missing",
            "connection refused": "connection_failure",
            "connection to server failed: Permission denied (10013)": "connection_failure",
            "unexpected select error": "query_failure",
        }
        for message, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(
                    classify_analytical_database_failure(RuntimeError(message)),
                    expected,
                )

    @patch("src.ai.data_provider.get_readonly_engine")
    @patch("src.ai.data_provider.get_last_available_date", return_value=None)
    def test_load_controlled_datasus_dataframe_retorna_vazio_sem_ultima_data(
        self,
        _mock_last_date,
        mock_engine,
    ):
        mock_engine.return_value = Mock()

        df, data_inicio, data_fim_exclusiva = load_controlled_datasus_dataframe()

        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), AI_ALLOWED_COLUMNS)
        self.assertIsNone(data_inicio)
        self.assertIsNone(data_fim_exclusiva)

    @patch("src.ai.data_provider.get_readonly_engine")
    @patch("src.ai.data_provider.get_last_available_date", return_value=date(2026, 3, 15))
    @patch("src.ai.data_provider.text", side_effect=lambda query: query)
    @patch("src.ai.data_provider.pd.read_sql_query")
    def test_query_usa_somente_colunas_permitidas(
        self,
        mock_read_sql_query,
        _mock_text,
        _mock_last_date,
        mock_engine,
    ):
        mock_engine.return_value = Mock()
        mock_read_sql_query.return_value = pd.DataFrame(
            [{column: None for column in AI_ALLOWED_COLUMNS}]
        )

        df, data_inicio, data_fim_exclusiva = load_controlled_datasus_dataframe()

        query = str(mock_read_sql_query.call_args.args[0])
        select_clause = query.split("FROM")[0]
        params = mock_read_sql_query.call_args.kwargs["params"]

        for column in AI_ALLOWED_COLUMNS:
            self.assertIn(column, select_clause)

        self.assertNotIn("*", select_clause)
        self.assertIn(f"FROM {AI_DATA_SOURCE}", query)
        self.assertNotRegex(query, r"FROM\s+data_sus\b")
        self.assertTrue(query.strip().upper().startswith("SELECT"))
        self.assertIn("data >= :data_inicio", query)
        self.assertIn("data < :data_fim_exclusiva", query)
        self.assertNotIn("data <= :data_fim", query)
        self.assertEqual(list(df.columns), AI_ALLOWED_COLUMNS)
        self.assertEqual(data_inicio, date(2026, 1, 1))
        self.assertEqual(data_fim_exclusiva, date(2026, 4, 1))
        self.assertEqual(params["data_inicio"], date(2026, 1, 1))
        self.assertEqual(params["data_fim_exclusiva"], date(2026, 4, 1))

    @patch("src.ai.data_provider.get_readonly_engine")
    @patch("src.ai.data_provider.get_last_available_date", return_value=date(2026, 1, 10))
    @patch("src.ai.data_provider.text", side_effect=lambda query: query)
    @patch("src.ai.data_provider.pd.read_sql_query")
    def test_calculo_periodo_em_virada_de_ano(
        self,
        mock_read_sql_query,
        _mock_text,
        _mock_last_date,
        mock_engine,
    ):
        mock_engine.return_value = Mock()
        mock_read_sql_query.return_value = pd.DataFrame(
            [{column: None for column in AI_ALLOWED_COLUMNS}]
        )

        _df, data_inicio, data_fim_exclusiva = load_controlled_datasus_dataframe()
        params = mock_read_sql_query.call_args.kwargs["params"]

        self.assertEqual(data_inicio, date(2025, 11, 1))
        self.assertEqual(data_fim_exclusiva, date(2026, 2, 1))
        self.assertEqual(params["data_inicio"], date(2025, 11, 1))
        self.assertEqual(params["data_fim_exclusiva"], date(2026, 2, 1))

    def test_funcoes_nao_chamam_to_sql(self):
        import src.ai.data_provider as data_provider
        import src.ai.read_only_datasus as read_only_datasus

        source = inspect.getsource(data_provider) + inspect.getsource(read_only_datasus)

        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)

    def test_funcoes_nao_usam_comandos_de_escrita(self):
        import src.ai.data_provider as data_provider
        import src.ai.read_only_datasus as read_only_datasus

        source = (inspect.getsource(data_provider) + inspect.getsource(read_only_datasus)).upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")


if __name__ == "__main__":
    unittest.main()
