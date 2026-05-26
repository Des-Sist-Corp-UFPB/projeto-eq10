import inspect
import os
import sys
import types
import unittest
from datetime import date
from unittest.mock import Mock, patch

import pandas as pd

from src.ai.pandasai_runner import (
    MISSING_LLM_KEY_MESSAGE,
    PANDASAI_LITELLM_ERROR_MESSAGE,
    executar_pergunta_com_pandasai,
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
        self.assertEqual(captured["model"], "gpt-4.1-mini")
        self.assertEqual(captured["api_key"], "fake-key")
        self.assertTrue(captured["cleared"])
        fake_pai.config.set.assert_called_once()

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
