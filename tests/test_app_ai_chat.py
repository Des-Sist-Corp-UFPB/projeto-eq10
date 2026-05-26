from pathlib import Path
import unittest

APP_PATH = Path("app_ai_chat.py")


class TestAppAiChat(unittest.TestCase):
    def test_app_existe(self):
        self.assertTrue(APP_PATH.exists())

    def test_app_importa_perguntar_datasus(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.ai.datasus_ai import perguntar_datasus", source)
        self.assertIn("perguntar_datasus(prompt)", source)

    def test_app_contem_referencias_visuais_esperadas(self):
        source = APP_PATH.read_text(encoding="utf-8")

        expected_texts = [
            "Assistente Estatístico SIA/DATASUS",
            "Chat",
            "Estatísticas",
            "Digite uma pergunta estatística",
        ]

        for text in expected_texts:
            self.assertIn(text, source)

    def test_app_nao_chama_etl_principal(self):
        source = APP_PATH.read_text(encoding="utf-8")

        for name in ["extract_data", "transform_datasus", "load_data_sus", "main.py"]:
            self.assertNotIn(name, source)

    def test_app_nao_importa_pandasai_ou_banco_diretamente(self):
        source = APP_PATH.read_text(encoding="utf-8")

        forbidden_fragments = [
            "pandasai",
            "psycopg2",
            "sqlalchemy",
            "read_only_datasus",
            "data_provider",
        ]

        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)

    def test_app_nao_contem_comandos_sql_de_escrita(self):
        source = APP_PATH.read_text(encoding="utf-8").upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")

    def test_app_nao_contem_to_sql(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertNotIn("DataFrame.to_sql", source)
        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)


if __name__ == "__main__":
    unittest.main()
