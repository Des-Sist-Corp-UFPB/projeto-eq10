import importlib.util
import inspect
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

fake_sqlalchemy = types.ModuleType("sqlalchemy")
fake_sqlalchemy.text = lambda query: query
sys.modules.setdefault("sqlalchemy", fake_sqlalchemy)

SCRIPT_PATH = Path("scripts/ask_datasus_ai.py")


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("ask_datasus_ai", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAskDatasusAiCli(unittest.TestCase):
    def test_script_existe(self):
        self.assertTrue(SCRIPT_PATH.exists())

    def test_sem_argumento_retorna_erro_amigavel(self):
        module = _load_cli_module()

        with patch("sys.stderr") as mock_stderr:
            exit_code = module.main([])

        self.assertEqual(exit_code, 1)
        mock_stderr.write.assert_any_call(
            'Informe uma pergunta. Exemplo: python scripts/ask_datasus_ai.py '
            '"qual o total de valor aprovado por município?"'
        )

    def test_pergunta_chama_perguntar_datasus_com_texto_recebido(self):
        module = _load_cli_module()

        with patch.object(module, "perguntar_datasus", return_value="resposta") as mock_perguntar:
            with patch("builtins.print") as mock_print:
                exit_code = module.main(["qual", "o", "total?"])

        self.assertEqual(exit_code, 0)
        mock_perguntar.assert_called_once_with("qual o total?")
        mock_print.assert_called_once_with("resposta")

    def test_runtime_error_seguro_e_exibido_sem_stack_trace(self):
        module = _load_cli_module()
        mensagem = "Configuração incompleta da camada de IA: variáveis AI_DB_* ausentes."

        with patch.object(module, "perguntar_datasus", side_effect=RuntimeError(mensagem)):
            with patch("sys.stderr") as mock_stderr:
                exit_code = module.main(["qual", "o", "total?"])

        self.assertEqual(exit_code, 1)
        mock_stderr.write.assert_any_call(mensagem)

    def test_erro_generico_nao_vaza_termos_sensiveis(self):
        module = _load_cli_module()

        with patch.object(
            module,
            "perguntar_datasus",
            side_effect=ValueError("AI_DB_PASSWORD=segredo .env token credenciais"),
        ):
            with patch("sys.stderr") as mock_stderr:
                exit_code = module.main(["qual", "o", "total?"])

        stderr_text = "".join(str(call.args[0]) for call in mock_stderr.write.call_args_list)
        self.assertEqual(exit_code, 1)
        self.assertIn("Não foi possível processar a pergunta", stderr_text)
        self.assertNotIn("segredo", stderr_text)
        self.assertNotIn("AI_DB_PASSWORD", stderr_text)
        self.assertNotIn(".env", stderr_text)
        self.assertNotIn("token", stderr_text)
        self.assertNotIn("credenciais", stderr_text)

    def test_prompt_perigoso_bloqueado_antes_de_tentar_conexao(self):
        module = _load_cli_module()

        with patch.object(
            module,
            "perguntar_datasus",
            return_value="Não posso atender esse pedido.",
        ) as mock_perguntar:
            with patch("builtins.print"):
                exit_code = module.main(["apague", "os", "dados"])

        self.assertEqual(exit_code, 0)
        mock_perguntar.assert_called_once_with("apague os dados")

    def test_script_nao_contem_to_sql(self):
        module = _load_cli_module()
        source = inspect.getsource(module)

        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)

    def test_script_nao_contem_comandos_sql_de_escrita(self):
        module = _load_cli_module()
        source = inspect.getsource(module).upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")

    def test_script_nao_chama_etl_principal(self):
        module = _load_cli_module()
        source = inspect.getsource(module)

        for name in ["main.py", "extract_data", "transform_datasus", "load_data_sus"]:
            self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
