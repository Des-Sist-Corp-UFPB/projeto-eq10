import inspect
import os
import sys
import types
import unittest
from datetime import date
from unittest.mock import Mock, patch

import pandas as pd

from src.ai.pandasai_runner import (
    INVALID_OPENROUTER_MODEL_MESSAGE,
    LLM_RATE_LIMIT_ERROR_MESSAGE,
    MISSING_LLM_KEY_MESSAGE,
    PANDASAI_LITELLM_ERROR_MESSAGE,
    PANDASAI_NO_RESULT_ERROR_MESSAGE,
    UNSUPPORTED_LLM_PROVIDER_MESSAGE,
    _sanitize_log_text,
    executar_pergunta_com_pandasai,
    is_llm_enabled,
)


class TestPandasAiRunner(unittest.TestCase):
    def setUp(self):
        self._load_env_patcher = patch("src.ai.pandasai_runner._load_env_files")
        self._load_env_patcher.start()
        self.addCleanup(self._load_env_patcher.stop)

    def _install_fake_pandasai(self, fake_df_class, fake_litellm_class):
        fake_pai = types.ModuleType("pandasai")
        fake_litellm_module = types.ModuleType("pandasai_litellm.litellm")
        fake_package = types.ModuleType("pandasai_litellm")

        fake_pai.DataFrame = fake_df_class
        fake_pai.config = Mock()
        fake_litellm_module.LiteLLM = fake_litellm_class

        modules = {
            "pandasai": fake_pai,
            "pandasai_litellm": fake_package,
            "pandasai_litellm.litellm": fake_litellm_module,
        }

        return patch.dict(sys.modules, modules), fake_pai

    def test_falha_com_runtime_error_seguro_sem_chave_modelo(self):
        with patch.dict(os.environ, {"AI_LLM_MODEL": "gpt-4.1-mini"}, clear=True):
            with self.assertRaises(RuntimeError) as context:
                executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(str(context.exception), MISSING_LLM_KEY_MESSAGE)

    def test_ai_use_llm_false_desativa_llm(self):
        with patch.dict(os.environ, {"AI_USE_LLM": "false"}, clear=True):
            self.assertFalse(is_llm_enabled())

    def test_ai_use_llm_padrao_ativo(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(is_llm_enabled())

    def test_sanitizacao_de_unicode_problematico(self):
        texto = "2026\u201101\u201131\u202f\u201cvalor\u201d\u2014teste"

        self.assertEqual(_sanitize_log_text(texto), '2026-01-31 "valor"-teste')

    def test_pandasai_recebe_apenas_dataframe_controlado(self):
        original_df = pd.DataFrame([{"valor_aprovado": 10}])
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                captured["df"] = df

            def chat(self, prompt):
                captured["prompt"] = prompt
                return "resposta"

            def clear_memory(self):
                captured["cleared"] = True

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["model"] = model
                captured["api_key"] = api_key

        modules_patcher, fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {"AI_LLM_API_KEY": "fake-key", "AI_LLM_MODEL": "gpt-4.1-mini"},
                clear=True,
            ):
                resposta = executar_pergunta_com_pandasai(
                    original_df,
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, "resposta")
        self.assertIsInstance(captured["df"], pd.DataFrame)
        self.assertIsNot(captured["df"], original_df)
        self.assertIn("Use apenas o DataFrame fornecido", captured["prompt"])
        self.assertIn("2026-01-01 até antes de 2026-04-01", captured["prompt"])
        self.assertIn(
            "Sempre atribua a resposta final a uma variavel chamada result",
            captured["prompt"],
        )
        self.assertIn("Use apenas caracteres ASCII simples", captured["prompt"])
        self.assertIn("Nao use caracteres Unicode especiais", captured["prompt"])
        self.assertIn('Use hifen normal "-"', captured["prompt"])
        self.assertIn('result = {"type": "string", "value": "..."}', captured["prompt"])
        self.assertIn('result = {"type": "number", "value": 123}', captured["prompt"])
        self.assertIn(
            'result = {"type": "dataframe", "value": dataframe_resultante}',
            captured["prompt"],
        )
        self.assertIn("Nunca use apenas print(output)", captured["prompt"])
        self.assertIn("Nunca use uma variavel chamada output", captured["prompt"])
        self.assertIn("result = output", captured["prompt"])
        self.assertIn("A ultima resposta deve estar em result", captured["prompt"])
        self.assertEqual(captured["model"], "gpt-4.1-mini")
        self.assertEqual(captured["api_key"], "fake-key")
        self.assertTrue(captured["cleared"])
        fake_pai.config.set.assert_called_once()

    def test_pandasai_dict_number_retorna_string_formatada(self):
        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return {"type": "number", "value": 1234.5}

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual a media?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, "1.234,50")

    def test_pandasai_dict_dataframe_retorna_tabela_simples(self):
        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return {
                    "type": "dataframe",
                    "value": pd.DataFrame(
                        [
                            {
                                "municipio": "251250",
                                "total_valor_aprovado": 15681.57,
                            },
                            {
                                "municipio": "250890",
                                "total_valor_aprovado": 12187.25,
                            },
                            {
                                "municipio": "250150",
                                "total_valor_aprovado": 10854.31,
                            },
                        ]
                    ),
                }

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "ranking por municipio",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(
            resposta,
            "\n".join(
                [
                    "Total de valor aprovado por município:",
                    "1. 251250: R$ 15.681,57",
                    "2. 250890: R$ 12.187,25",
                    "3. 250150: R$ 10.854,31",
                ]
            ),
        )

    def test_pandasai_dataframe_direto_retorna_lista_amigavel(self):
        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return pd.DataFrame(
                    [
                        {"municipio": "251250", "total_valor_aprovado": 15681.57},
                        {"municipio": "250890", "total_valor_aprovado": 12187.25},
                    ]
                )

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "total por municipio",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertIn("Total de valor aprovado por município:", resposta)
        self.assertIn("1. 251250: R$ 15.681,57", resposta)
        self.assertIn("2. 250890: R$ 12.187,25", resposta)

    def test_pandasai_string_tem_unicode_problematico_sanitizado(self):
        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "Total\u202f:\u00a0R$ 15\u2011681,57 \u201cok\u201d"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, 'Total : R$ 15-681,57 "ok"')
        self.assertNotIn("\u202f", resposta)
        self.assertNotIn("\u2011", resposta)
        self.assertNotIn("\u201c", resposta)

    def test_fallback_openai_api_key(self):
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["api_key"] = api_key

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-fallback"}, clear=True):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["api_key"], "openai-fallback")

    def test_ai_llm_api_key_define_openai_api_key_quando_fallback_ausente(self):
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["api_key"] = api_key

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {"AI_LLM_API_KEY": "fake-key", "AI_LLM_MODEL": "gpt-4.1-mini"},
                clear=True,
            ):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )
                openai_key = os.environ.get("OPENAI_API_KEY")

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["api_key"], "fake-key")
        self.assertEqual(openai_key, "fake-key")

    def test_gemini_usa_gemini_api_key_e_prefixa_modelo(self):
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["model"] = model
                captured["api_key"] = api_key

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {
                    "AI_LLM_PROVIDER": "gemini",
                    "AI_LLM_MODEL": "gemini-2.0-flash",
                    "GEMINI_API_KEY": "gemini-fallback",
                },
                clear=True,
            ):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["model"], "gemini/gemini-2.0-flash")
        self.assertEqual(captured["api_key"], "gemini-fallback")

    def test_gemini_usa_ai_llm_api_key_e_define_gemini_api_key(self):
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["model"] = model
                captured["api_key"] = api_key

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {
                    "AI_LLM_PROVIDER": "gemini",
                    "AI_LLM_MODEL": "gemini/gemini-2.0-flash",
                    "AI_LLM_API_KEY": "gemini-ai-key",
                },
                clear=True,
            ):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )
                gemini_key = os.environ.get("GEMINI_API_KEY")

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["model"], "gemini/gemini-2.0-flash")
        self.assertEqual(captured["api_key"], "gemini-ai-key")
        self.assertEqual(gemini_key, "gemini-ai-key")

    def test_openrouter_usa_openrouter_api_key(self):
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["model"] = model
                captured["api_key"] = api_key

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {
                    "AI_LLM_PROVIDER": "openrouter",
                    "AI_LLM_MODEL": "openrouter/openrouter/free",
                    "OPENROUTER_API_KEY": "openrouter-fallback",
                },
                clear=True,
            ):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["model"], "openrouter/openrouter/free")
        self.assertEqual(captured["api_key"], "openrouter-fallback")

    def test_openrouter_usa_ai_llm_api_key_e_define_openrouter_api_key(self):
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["model"] = model
                captured["api_key"] = api_key

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {
                    "AI_LLM_PROVIDER": "openrouter",
                    "AI_LLM_MODEL": "openrouter/openrouter/free",
                    "AI_LLM_API_KEY": "openrouter-ai-key",
                },
                clear=True,
            ):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )
                openrouter_key = os.environ.get("OPENROUTER_API_KEY")

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["model"], "openrouter/openrouter/free")
        self.assertEqual(captured["api_key"], "openrouter-ai-key")
        self.assertEqual(openrouter_key, "openrouter-ai-key")

    def test_openrouter_usa_modelo_padrao_quando_modelo_nao_informado(self):
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["model"] = model
                captured["api_key"] = api_key

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {
                    "AI_LLM_PROVIDER": "openrouter",
                    "AI_LLM_API_KEY": "openrouter-ai-key",
                },
                clear=True,
            ):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["model"], "openrouter/openrouter/free")
        self.assertEqual(captured["api_key"], "openrouter-ai-key")

    def test_openrouter_exige_prefixo_openrouter(self):
        with patch.dict(
            os.environ,
                {
                    "AI_LLM_PROVIDER": "openrouter",
                    "AI_LLM_MODEL": "openrouter-free",
                    "AI_LLM_API_KEY": "openrouter-ai-key",
                },
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as context:
                executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        mensagem = str(context.exception)
        self.assertEqual(mensagem, INVALID_OPENROUTER_MODEL_MESSAGE)
        self.assertNotIn("openrouter-ai-key", mensagem)

    def test_provider_desconhecido_retorna_erro_seguro(self):
        with patch.dict(
            os.environ,
            {
                "AI_LLM_PROVIDER": "desconhecido",
                "AI_LLM_API_KEY": "fake-key",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as context:
                executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        mensagem = str(context.exception)
        self.assertEqual(mensagem, UNSUPPORTED_LLM_PROVIDER_MESSAGE)
        self.assertNotIn("fake-key", mensagem)

    def test_erro_pandasai_litellm_retorna_runtime_error_seguro(self):
        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                raise ValueError("fake-secret-key db-password detalhes internos")

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                with self.assertRaises(RuntimeError) as context:
                    executar_pergunta_com_pandasai(
                        pd.DataFrame([{"valor_aprovado": 10}]),
                        "qual o total?",
                        date(2026, 1, 1),
                        date(2026, 4, 1),
                    )

        mensagem = str(context.exception)
        self.assertEqual(mensagem, PANDASAI_LITELLM_ERROR_MESSAGE)
        self.assertNotIn("fake-secret-key", mensagem)
        self.assertNotIn("db-password", mensagem)

    def test_log_seguro_nao_expoe_senha_token_ou_chave(self):
        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                raise ValueError("senha fake-password token fake-token chave fake-key")

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                with self.assertLogs("src.ai.pandasai_runner", level="WARNING") as logs:
                    with self.assertRaises(RuntimeError):
                        executar_pergunta_com_pandasai(
                            pd.DataFrame([{"valor_aprovado": 10}]),
                            "qual o total?",
                            date(2026, 1, 1),
                            date(2026, 4, 1),
                        )

        log_output = "\n".join(logs.output)
        self.assertIn("tipo=ValueError", log_output)
        self.assertNotIn("fake-password", log_output)
        self.assertNotIn("fake-token", log_output)
        self.assertNotIn("fake-key", log_output)

    def test_debug_seguro_inclui_tipo_sem_expor_mensagem_original(self):
        class FakeBadRequestError(Exception):
            pass

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                raise FakeBadRequestError("fake-secret-key db-password")

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {"AI_LLM_API_KEY": "fake-key", "AI_DEBUG_SAFE": "true"},
                clear=True,
            ):
                with self.assertRaises(RuntimeError) as context:
                    executar_pergunta_com_pandasai(
                        pd.DataFrame([{"valor_aprovado": 10}]),
                        "qual o total?",
                        date(2026, 1, 1),
                        date(2026, 4, 1),
                    )

        mensagem = str(context.exception)
        self.assertEqual(
            mensagem,
            f"{PANDASAI_LITELLM_ERROR_MESSAGE} Tipo: FakeBadRequestError",
        )
        self.assertNotIn("fake-secret-key", mensagem)
        self.assertNotIn("db-password", mensagem)

    def test_no_result_found_error_retorna_mensagem_segura(self):
        class NoResultFoundError(Exception):
            pass

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                raise NoResultFoundError("fake-secret-key db-password")

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                with self.assertRaises(RuntimeError) as context:
                    executar_pergunta_com_pandasai(
                        pd.DataFrame([{"valor_aprovado": 10}]),
                        "qual a media de idade?",
                        date(2026, 1, 1),
                        date(2026, 4, 1),
                    )

        mensagem = str(context.exception)
        self.assertEqual(mensagem, PANDASAI_NO_RESULT_ERROR_MESSAGE)
        self.assertNotIn("fake-secret-key", mensagem)
        self.assertNotIn("db-password", mensagem)

    def test_no_result_found_error_debug_inclui_tipo_sem_credenciais(self):
        class NoResultFoundError(Exception):
            pass

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                raise NoResultFoundError("fake-token fake-password")

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(
                os.environ,
                {"AI_LLM_API_KEY": "fake-key", "AI_DEBUG_SAFE": "true"},
                clear=True,
            ):
                with self.assertRaises(RuntimeError) as context:
                    executar_pergunta_com_pandasai(
                        pd.DataFrame([{"valor_aprovado": 10}]),
                        "qual a media de idade?",
                        date(2026, 1, 1),
                        date(2026, 4, 1),
                    )

        mensagem = str(context.exception)
        self.assertEqual(
            mensagem,
            f"{PANDASAI_NO_RESULT_ERROR_MESSAGE} Tipo: NoResultFoundError",
        )
        self.assertNotIn("fake-token", mensagem)
        self.assertNotIn("fake-password", mensagem)

    def test_rate_limit_error_retorna_mensagem_segura(self):
        class RateLimitError(Exception):
            pass

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                raise RateLimitError("sem credito para fake-secret-key")

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                with self.assertRaises(RuntimeError) as context:
                    executar_pergunta_com_pandasai(
                        pd.DataFrame([{"valor_aprovado": 10}]),
                        "qual o total?",
                        date(2026, 1, 1),
                        date(2026, 4, 1),
                    )

        mensagem = str(context.exception)
        self.assertEqual(mensagem, LLM_RATE_LIMIT_ERROR_MESSAGE)
        self.assertIn("AI_USE_LLM=false", mensagem)
        self.assertNotIn("fake-secret-key", mensagem)

    def test_quota_exceeded_retorna_mensagem_segura_recuperavel(self):
        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                raise RuntimeError("quota exceeded for fake-secret-key")

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                pass

        modules_patcher, _fake_pai = self._install_fake_pandasai(
            FakePandasAiDataFrame,
            FakeLiteLLM,
        )

        with modules_patcher:
            with patch.dict(os.environ, {"AI_LLM_API_KEY": "fake-key"}, clear=True):
                with self.assertRaises(RuntimeError) as context:
                    executar_pergunta_com_pandasai(
                        pd.DataFrame([{"valor_aprovado": 10}]),
                        "qual o total?",
                        date(2026, 1, 1),
                        date(2026, 4, 1),
                    )

        mensagem = str(context.exception)
        self.assertEqual(mensagem, LLM_RATE_LIMIT_ERROR_MESSAGE)
        self.assertNotIn("fake-secret-key", mensagem)

    def test_runner_nao_contem_to_sql(self):
        import src.ai.pandasai_runner as pandasai_runner

        source = inspect.getsource(pandasai_runner)

        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)

    def test_runner_nao_contem_comandos_sql_de_escrita(self):
        import src.ai.pandasai_runner as pandasai_runner

        source = inspect.getsource(pandasai_runner).upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")

    def test_runner_nao_chama_etl_principal(self):
        import src.ai.pandasai_runner as pandasai_runner

        source = inspect.getsource(pandasai_runner)

        for name in ["main.py", "extract_data", "transform_datasus", "load_data_sus"]:
            self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
