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
    executar_pergunta_com_pandasai,
)


class TestPandasAiRunner(unittest.TestCase):
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
        fake_pai = types.ModuleType("pandasai")
        fake_litellm_module = types.ModuleType("pandasai_litellm.litellm")
        fake_package = types.ModuleType("pandasai_litellm")

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

        fake_pai.DataFrame = FakePandasAiDataFrame
        fake_pai.config = Mock()
        fake_litellm_module.LiteLLM = FakeLiteLLM

        modules = {
            "pandasai": fake_pai,
            "pandasai_litellm": fake_package,
            "pandasai_litellm.litellm": fake_litellm_module,
        }

        with patch.dict(sys.modules, modules):
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
        fake_pai = types.ModuleType("pandasai")
        fake_litellm_module = types.ModuleType("pandasai_litellm.litellm")
        fake_package = types.ModuleType("pandasai_litellm")
        captured = {}

        class FakePandasAiDataFrame:
            def __init__(self, df):
                pass

            def chat(self, prompt):
                return "ok"

        class FakeLiteLLM:
            def __init__(self, model, api_key):
                captured["api_key"] = api_key

        fake_pai.DataFrame = FakePandasAiDataFrame
        fake_pai.config = Mock()
        fake_litellm_module.LiteLLM = FakeLiteLLM

        with patch.dict(
            sys.modules,
            {
                "pandasai": fake_pai,
                "pandasai_litellm": fake_package,
                "pandasai_litellm.litellm": fake_litellm_module,
            },
        ):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-fallback"}, clear=True):
                resposta = executar_pergunta_com_pandasai(
                    pd.DataFrame([{"valor_aprovado": 10}]),
                    "qual o total?",
                    date(2026, 1, 1),
                    date(2026, 4, 1),
                )

        self.assertEqual(resposta, "ok")
        self.assertEqual(captured["api_key"], "openai-fallback")

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
