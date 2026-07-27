import inspect
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from src.ai.datasus_ai import (
    DATABASE_UNAVAILABLE_MESSAGE,
    ENGINE_UNAVAILABLE_MESSAGE,
    GENERIC_AI_ERROR_MESSAGE,
    LLM_SIMPLE_FALLBACK_NOTICE,
    perguntar_datasus,
)
from src.ai.prompt_guard import MENSAGEM_BLOQUEIO
from src.ai.simple_stats_runner import SIMPLE_STATS_UNAVAILABLE_MESSAGE

AI_ENV_KEYS = (
    "AI_USE_LLM",
    "AI_LLM_PROVIDER",
    "AI_LLM_MODEL",
    "AI_LLM_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "AI_DEBUG_SAFE",
    "AI_FALLBACK_TO_SIMPLE",
)


class TestDatasusAiFlow(unittest.TestCase):
    def setUp(self):
        self._load_env_patcher = patch("src.ai.datasus_ai._load_env_files")
        self._load_env_patcher.start()
        self.addCleanup(self._load_env_patcher.stop)
        sys.modules.pop("src.ai.pandasai_runner", None)
        sys.modules.pop("pandasai_litellm", None)
        sys.modules.pop("pandasai_litellm.litellm", None)
        sys.modules.pop("pandasai", None)

    def _ai_env(self, **overrides):
        env = {"ENVIRONMENT": "test"}
        for key in AI_ENV_KEYS:
            if key in overrides and overrides[key] is not None:
                env[key] = overrides[key]

        return env

    def _patch_ai_env(self, **overrides):
        return patch.dict(os.environ, self._ai_env(**overrides), clear=True)

    @patch("src.ai.datasus_ai.load_controlled_datasus_dataframe")
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_prompt_perigoso_bloqueado_antes_de_chamar_pandasai(
        self,
        mock_log,
        mock_load_data,
    ):
        resposta = perguntar_datasus("apague os dados")

        self.assertEqual(resposta, MENSAGEM_BLOQUEIO)
        mock_load_data.assert_not_called()
        self.assertNotIn("src.ai.pandasai_runner", sys.modules)
        mock_log.assert_called_with(
            "apague os dados",
            status="bloqueado_prompt",
            detail="unsafe_request",
        )

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
    ):
        resposta = perguntar_datasus("total de valor em março de 2026")

        self.assertEqual(resposta, "O mês solicitado ainda não está disponível no sistema.")
        mock_load_data.assert_not_called()
        self.assertNotIn("src.ai.pandasai_runner", sys.modules)
        mock_log.assert_called_with(
            "total de valor em março de 2026",
            status="bloqueado_mes_indisponivel",
            detail="O mês solicitado ainda não está disponível no sistema.",
        )

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
    ):
        resposta = perguntar_datasus("qual o total por município?")

        self.assertEqual(
            resposta,
            "Ainda não há dados disponíveis no sistema para análise estatística.",
        )
        self.assertNotIn("src.ai.pandasai_runner", sys.modules)
        mock_log.assert_called_with(
            "qual o total por município?",
            status="sem_dados",
            detail="Ainda não há dados disponíveis no sistema para análise estatística.",
        )

    @patch(
        "src.ai.pandasai_runner.executar_pergunta_com_pandasai",
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
    def test_ai_use_llm_true_chama_llm(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
        mock_pandasai,
    ):
        with self._patch_ai_env(AI_USE_LLM="true"):
            resposta = perguntar_datasus("compare a variação de idade por período")

        self.assertEqual(resposta, "Total aprovado: R$ 10,00.")
        mock_pandasai.assert_called_once()
        args = mock_pandasai.call_args.args
        self.assertIsInstance(args[0], pd.DataFrame)
        self.assertEqual(args[1], "compare a variação de idade por período")
        self.assertEqual(args[2], date(2026, 1, 1))
        self.assertEqual(args[3], date(2026, 4, 1))
        mock_log.assert_called_with("compare a variação de idade por período", status="respondido")

    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame(
                [
                    {
                        "data": date(2026, 1, 10),
                        "municipio_atendimento": "Cajazeiras",
                        "valor_aprovado": 10.0,
                        "valor_apresentado": 11.0,
                        "frequencia": 2,
                        "sexo": "M",
                        "unidade": "Hospital Regional",
                        "procedimento": "Consulta medica",
                        "raca_cor": "Parda",
                        "quantidade_apresentada": 5,
                        "idade": 30,
                    },
                    {
                        "data": date(2026, 3, 15),
                        "municipio_atendimento": "Sousa",
                        "valor_aprovado": 20.0,
                        "valor_apresentado": 21.0,
                        "frequencia": 3,
                        "sexo": "F",
                        "unidade": "UPA Central",
                        "procedimento": "Exame laboratorial",
                        "raca_cor": "Branca",
                        "quantidade_apresentada": 8,
                        "idade": 40,
                    },
                ]
            ),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_sugestoes_principais_usam_modo_simples_antes_do_llm(
        self,
        _mock_log,
        _mock_validar_mes,
        _mock_load_data,
    ):
        prompts = {
            "Média de idade dos atendimentos": "Média de idade dos atendimentos",
            "Frequência total por sexo": "Frequência total por sexo",
            "Unidades com maior quantidade apresentada": "Unidades com maior quantidade apresentada",
            "Procedimentos com maior valor aprovado": "Ranking por procedimento usando valor aprovado",
            "Valor aprovado por município de atendimento": "Total de valor aprovado por município de atendimento",
            "Valor aprovado por raça/cor": "Ranking por raça/cor usando valor aprovado",
            "Total geral de valor apresentado": "Total geral de valor apresentado",
            "Total de quantidade apresentada": "Total geral de quantidade apresentada",
            "Contagem de procedimentos": "Contagem de procedimentos distintos",
            "Data mais recente dos atendimentos": "Data mais recente disponivel",
            "Qual a média de idade dos atendimentos?": "Média de idade dos atendimentos",
            "Total de valor aprovado por município": "Total de valor aprovado por município de atendimento",
            "Quantidade de atendimentos por procedimento": "Total de atendimentos por procedimento",
            "Frequência por unidade": "Ranking por unidade de atendimento usando frequência",
            "Ranking de municípios por valor aprovado": "Ranking por município de atendimento usando valor aprovado",
            "Quais procedimentos tiveram maior valor aprovado?": "Ranking por procedimento usando valor aprovado",
            "Total de atendimentos por sexo": "Total de atendimentos por sexo",
            "Valor apresentado por unidade": "Ranking por unidade de atendimento usando valor apresentado",
            "Média de idade por município": "Média de idade por município de atendimento",
        }

        with self._patch_ai_env(AI_USE_LLM="true"):
            for prompt, expected in prompts.items():
                with self.subTest(prompt=prompt):
                    resposta = perguntar_datasus(prompt)
                    self.assertIn(expected, resposta)
                    self.assertNotEqual(resposta, GENERIC_AI_ERROR_MESSAGE)
                    self.assertNotEqual(resposta, SIMPLE_STATS_UNAVAILABLE_MESSAGE)

        self.assertNotIn("src.ai.pandasai_runner", sys.modules)

    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame(
                [
                    {
                        "municipio_atendimento": "Cajazeiras",
                        "valor_aprovado": 10.0,
                    },
                    {
                        "municipio_atendimento": "Cajazeiras",
                        "valor_aprovado": 5.5,
                    },
                ]
            ),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_ai_use_llm_false_chama_modo_simples_sem_importar_pandasai_runner(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
    ):
        with self._patch_ai_env(AI_USE_LLM="false"):
            resposta = perguntar_datasus("total de valor aprovado por município")

        self.assertIn("Cajazeiras: R$ 15,50", resposta)
        self.assertNotIn("src.ai.pandasai_runner", sys.modules)
        self.assertNotIn("pandasai_litellm.litellm", sys.modules)
        mock_log.assert_called_with(
            "total de valor aprovado por município",
            status="respondido_modo_simples",
        )

    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame(
                [
                    {
                        "municipio_atendimento": "Cajazeiras",
                        "valor_aprovado": 10.0,
                    },
                ]
            ),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_ai_use_llm_false_nao_exige_chave_llm(
        self,
        _mock_log,
        _mock_validar_mes,
        _mock_load_data,
    ):
        with self._patch_ai_env(AI_USE_LLM="false"):
            resposta = perguntar_datasus("total geral de valor aprovado")

        self.assertIn("Total geral de valor aprovado: R$ 10,00", resposta)
        self.assertNotIn("chave do modelo ausente", resposta)
        self.assertNotIn("src.ai.pandasai_runner", sys.modules)

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
    def test_ai_use_llm_false_pergunta_nao_reconhecida(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
    ):
        with self._patch_ai_env(AI_USE_LLM="false"):
            resposta = perguntar_datasus("qual procedimento cresceu mais?")

        self.assertEqual(resposta, SIMPLE_STATS_UNAVAILABLE_MESSAGE)
        self.assertNotIn("src.ai.pandasai_runner", sys.modules)
        mock_log.assert_called_with(
            "qual procedimento cresceu mais?",
            status="pergunta_fora_escopo_modo_simples",
        )

    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame(
                [
                    {
                        "municipio_atendimento": "Cajazeiras",
                        "valor_aprovado": 10.0,
                    },
                    {
                        "municipio_atendimento": "Cajazeiras",
                        "valor_aprovado": 5.5,
                    },
                ]
            ),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_rate_limit_retorna_mensagem_segura_e_fallback_simples(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
    ):
        from src.ai.pandasai_runner import LLM_RATE_LIMIT_ERROR_MESSAGE, LLMRateLimitError

        with patch(
            "src.ai.pandasai_runner.executar_pergunta_com_pandasai",
            side_effect=LLMRateLimitError(LLM_RATE_LIMIT_ERROR_MESSAGE),
        ):
            with self._patch_ai_env(
                AI_USE_LLM="true",
                AI_FALLBACK_TO_SIMPLE="true",
            ):
                resposta = perguntar_datasus("compare a variação de valor aprovado por período")

        self.assertEqual(resposta, ENGINE_UNAVAILABLE_MESSAGE)
        self.assertNotIn("fake-secret-key", resposta)
        mock_log.assert_called_with(
            "compare a variação de valor aprovado por período",
            status="erro_motor_sem_fallback",
        )

    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        return_value=(
            pd.DataFrame(
                [
                    {
                        "municipio_atendimento": "Cajazeiras",
                        "valor_aprovado": 10.0,
                    },
                ]
            ),
            date(2026, 1, 1),
            date(2026, 4, 1),
        ),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_rate_limit_sem_fallback_retorna_erro_seguro(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
    ):
        from src.ai.pandasai_runner import LLM_RATE_LIMIT_ERROR_MESSAGE, LLMRateLimitError

        with patch(
            "src.ai.pandasai_runner.executar_pergunta_com_pandasai",
            side_effect=LLMRateLimitError(LLM_RATE_LIMIT_ERROR_MESSAGE),
        ):
            with self._patch_ai_env(
                AI_USE_LLM="true",
                AI_FALLBACK_TO_SIMPLE="false",
            ):
                resposta = perguntar_datasus("compare a variação de valor aprovado por período")

        self.assertEqual(resposta, ENGINE_UNAVAILABLE_MESSAGE)
        self.assertNotIn("fake-secret-key", resposta)
        mock_log.assert_called_with(
            "compare a variação de valor aprovado por período",
            status="erro_limite_llm",
            detail="llm_unavailable",
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
    ):
        with patch(
            "src.ai.pandasai_runner.executar_pergunta_com_pandasai",
            side_effect=RuntimeError("Configuração incompleta da IA: chave do modelo ausente."),
        ):
            with self._patch_ai_env(AI_USE_LLM="true"):
                resposta = perguntar_datasus("compare a variação de idade por período")

        self.assertEqual(resposta, ENGINE_UNAVAILABLE_MESSAGE)
        mock_log.assert_called_with(
            "compare a variação de idade por período",
            status="erro_motor",
            detail="RuntimeError",
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
    ):
        with patch(
            "src.ai.pandasai_runner.executar_pergunta_com_pandasai",
            side_effect=ValueError("erro interno com segredo"),
        ):
            with self._patch_ai_env(AI_USE_LLM="true"):
                resposta = perguntar_datasus("compare a variação de idade por período")

        self.assertEqual(resposta, GENERIC_AI_ERROR_MESSAGE)
        mock_log.assert_called_with(
            "compare a variação de idade por período",
            status="erro_llm",
            detail="ValueError",
        )

    @patch(
        "src.ai.datasus_ai.load_controlled_datasus_dataframe",
        side_effect=RuntimeError("erro de provider com possível segredo"),
    )
    @patch("src.ai.datasus_ai.validar_mes_solicitado_no_prompt", return_value=(True, ""))
    @patch("src.ai.datasus_ai.log_ai_question")
    def test_erro_no_carregamento_dos_dados_retorna_mensagem_generica(
        self,
        mock_log,
        _mock_validar_mes,
        _mock_load_data,
    ):
        resposta = perguntar_datasus("qual o total de valor aprovado?")

        self.assertEqual(resposta, DATABASE_UNAVAILABLE_MESSAGE)
        mock_log.assert_called_with(
            "qual o total de valor aprovado?",
            status="erro_banco",
            detail="query_failure",
        )

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
