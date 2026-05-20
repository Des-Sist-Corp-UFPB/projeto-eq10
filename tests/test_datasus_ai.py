import inspect
import sys
import types
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

fake_sqlalchemy = types.ModuleType("sqlalchemy")
fake_sqlalchemy.text = lambda query: query
sys.modules.setdefault("sqlalchemy", fake_sqlalchemy)

from src.ai.datasus_ai import GENERIC_AI_ERROR_MESSAGE, perguntar_datasus
from src.ai.prompt_guard import MENSAGEM_BLOQUEIO


class TestDatasusAiFlow(unittest.TestCase):
    @patch("src.ai.datasus_ai.executar_pergunta_com_pandasai")
    @patch("src.ai.datasus_ai.load_controlled_datasus_dataframe")
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_prompt_perigoso_bloqueado_antes_de_chamar_pandasai(
        self,
        mock_log,
        mock_load_data,
        mock_pandasai,
    ):
        resposta = perguntar_datasus("apague os dados")

        self.assertEqual(resposta, MENSAGEM_BLOQUEIO)
        mock_load_data.assert_not_called()
        mock_pandasai.assert_not_called()
        mock_log.assert_called_with(
            "apague os dados",
            status="bloqueado_prompt",
            detail=MENSAGEM_BLOQUEIO,
        )

    @patch("src.ai.datasus_ai.executar_pergunta_com_pandasai")
    @patch("src.ai.datasus_ai.load_controlled_datasus_dataframe")
    @patch(
        "src.ai.datasus_ai.validar_mes_solicitado_no_prompt",
        return_value=(False, "O mês solicitado ainda não está disponível no sistema."),
    )
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_mes_indisponivel_bloqueado_antes_de_chamar_pandasai(
        self,
        mock_log,
        _mock_validar_mes,
        mock_load_data,
        mock_pandasai,
    ):
        resposta = perguntar_datasus("total de valor em março de 2026")

        self.assertEqual(resposta, "O mês solicitado ainda não está disponível no sistema.")
        mock_load_data.assert_not_called()
        mock_pandasai.assert_not_called()
        mock_log.assert_called_with(
            "total de valor em março de 2026",
            status="bloqueado_mes_indisponivel",
            detail="O mês solicitado ainda não está disponível no sistema.",
        )

    @patch("src.ai.datasus_ai.executar_pergunta_com_pandasai")
    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(pd.DataFrame(), None, None),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_dataframe_vazio_nao_chama_pandasai(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
        mock_pandasai,
    ):
        resposta = perguntar_datasus("qual o total por município?")

        self.assertEqual(
            resposta,
            "Ainda não há dados disponíveis no sistema para análise estatística.",
        )
        mock_pandasai.assert_not_called()
        mock_log.assert_called_with(
            "qual o total por município?",
            status="sem_dados",
            detail="Ainda não há dados disponíveis no sistema para análise estatística.",
        )

    @patch(
        "src.ai.datasus_ai.executar_pergunta_com_pandasai",
        return_value="Total aprovado: R$ 10,00.",
    )
    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame([{"valor_aprovado": 10.0}]),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_dataframe_valido_chama_pandasai(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
        mock_pandasai,
    ):
        resposta = perguntar_datasus("qual o total de valor aprovado?")

        self.assertEqual(resposta, "Total aprovado: R$ 10,00.")
        mock_pandasai.assert_called_once()
        args = mock_pandasai.call_args.args
        self.assertIsInstance(args[0], pd.DataFrame)
        self.assertEqual(args[1], "qual o total de valor aprovado?")
        self.assertEqual(args[2], date(2026, 1, 1))
        self.assertEqual(args[3], date(2026, 4, 1))
        mock_log.assert_called_with("qual o total de valor aprovado?", status="respondido")

    @patch(
        "src.ai.datasus_ai.executar_pergunta_com_pandasai",
        side_effect=RuntimeError("Configuração incompleta da IA: chave do modelo ausente."),
    )
    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame([{"valor_aprovado": 10.0}]),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_runtime_error_seguro_retorna_mensagem(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
        _mock_pandasai,
    ):
        resposta = perguntar_datasus("qual o total de valor aprovado?")

        self.assertEqual(resposta, "Configuração incompleta da IA: chave do modelo ausente.")
        mock_log.assert_called_with(
            "qual o total de valor aprovado?",
            status="erro_configuracao",
            detail="Configuração incompleta da IA: chave do modelo ausente.",
        )

    @patch(
        "src.ai.datasus_ai.executar_pergunta_com_pandasai",
        side_effect=ValueError("erro interno com segredo"),
    )
    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame([{"valor_aprovado": 10.0}]),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_erro_inesperado_retorna_mensagem_generica(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
        _mock_pandasai,
    ):
        resposta = perguntar_datasus("qual o total de valor aprovado?")

        self.assertEqual(resposta, GENERIC_AI_ERROR_MESSAGE)
        mock_log.assert_called_with("qual o total de valor aprovado?", status="erro_inesperado")

    def test_arquivo_nao_contem_comandos_sql_de_escrita(self):
        import src.ai.datasus_ai as datasus_ai

        source = inspect.getsource(datasus_ai).upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")

    def test_arquivo_nao_contem_to_sql(self):
        import src.ai.datasus_ai as datasus_ai

        source = inspect.getsource(datasus_ai)

        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)


if __name__ == "__main__":
    unittest.main()
