import inspect
import sys
import types
import unittest
from datetime import date
from unittest.mock import MagicMock, Mock, patch

fake_sqlalchemy = types.ModuleType("sqlalchemy")
fake_sqlalchemy.text = lambda query: query
sys.modules.setdefault("sqlalchemy", fake_sqlalchemy)

from src.ai.month_checker import (
    MENSAGEM_MES_INDISPONIVEL,
    _primeiro_dia_mes_seguinte,
    extrair_mes_ano_do_prompt,
    mes_existe_no_banco,
    validar_mes_solicitado_no_prompt,
)


class TestAiMonthChecker(unittest.TestCase):
    def test_reconhece_marco_com_acento(self):
        self.assertEqual(
            extrair_mes_ano_do_prompt("total de valor aprovado em março de 2026"),
            (3, 2026),
        )

    def test_reconhece_marco_sem_acento(self):
        self.assertEqual(
            extrair_mes_ano_do_prompt("frequência em marco de 2026"),
            (3, 2026),
        )

    def test_reconhece_janeiro_case_insensitive(self):
        self.assertEqual(
            extrair_mes_ano_do_prompt("dados de Janeiro 2025"),
            (1, 2025),
        )

    def test_retorna_none_quando_nao_ha_mes_ano(self):
        self.assertEqual(
            extrair_mes_ano_do_prompt("qual o total por município?"),
            (None, None),
        )

    @patch("src.ai.month_checker.get_readonly_engine")
    def test_mes_existe_no_banco_retorna_true_quando_query_encontra_registro(
        self,
        mock_get_engine,
    ):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = (1,)
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection
        mock_get_engine.return_value = engine

        self.assertTrue(mes_existe_no_banco(2026, 3))

    @patch("src.ai.month_checker.get_readonly_engine")
    def test_mes_existe_no_banco_retorna_false_quando_query_nao_encontra_registro(
        self,
        mock_get_engine,
    ):
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = None
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection
        mock_get_engine.return_value = engine

        self.assertFalse(mes_existe_no_banco(2026, 3))

    def test_validar_mes_solicitado_retorna_true_quando_nao_ha_mes_especifico(self):
        self.assertEqual(
            validar_mes_solicitado_no_prompt("qual o total por município?"),
            (True, ""),
        )

    @patch("src.ai.month_checker.mes_existe_no_banco", return_value=False)
    def test_validar_mes_solicitado_retorna_false_quando_mes_nao_existe(
        self,
        _mock_mes_existe,
    ):
        self.assertEqual(
            validar_mes_solicitado_no_prompt("total em março de 2026"),
            (False, MENSAGEM_MES_INDISPONIVEL),
        )

    def test_primeiro_dia_mes_seguinte_em_virada_de_ano(self):
        self.assertEqual(_primeiro_dia_mes_seguinte(2025, 12), date(2026, 1, 1))

    def test_arquivo_nao_contem_to_sql(self):
        import src.ai.month_checker as month_checker

        source = inspect.getsource(month_checker)

        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)

    def test_arquivo_nao_contem_comandos_sql_de_escrita(self):
        import src.ai.month_checker as month_checker

        source = inspect.getsource(month_checker).upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")


if __name__ == "__main__":
    unittest.main()
