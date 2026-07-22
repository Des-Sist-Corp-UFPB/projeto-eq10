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
    get_readonly_engine,
    get_readonly_database_config_source,
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
            with patch("sqlalchemy.create_engine") as create_engine:
                source = get_readonly_database_config_source()
                get_readonly_engine()

        self.assertEqual(source, "AI_DATABASE_URL")
        self.assertEqual(create_engine.call_args.args[0], url)
        self.assertEqual(
            create_engine.call_args.kwargs["connect_args"],
            {"options": "-c default_transaction_read_only=on"},
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
