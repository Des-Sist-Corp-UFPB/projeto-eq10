from pathlib import Path
import unittest


DOCKERFILE_PATH = Path("Dockerfile.chat")
COMPOSE_PATH = Path("docker-compose.chat.yml")


class TestDockerChatConfig(unittest.TestCase):
    def test_arquivos_existem(self):
        self.assertTrue(DOCKERFILE_PATH.exists())
        self.assertTrue(COMPOSE_PATH.exists())

    def test_dockerfile_usa_python_311(self):
        source = DOCKERFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("FROM python:3.11-slim", source)

    def test_dockerfile_nao_contem_segredos(self):
        source = DOCKERFILE_PATH.read_text(encoding="utf-8").lower()

        forbidden_fragments = [
            "ai_llm_api_key",
            "ai_db_password",
            "password=",
            "token=",
            "secret=",
            "api_key=",
        ]

        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)

    def test_compose_usa_env_file_env(self):
        source = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("env_file:", source)
        self.assertIn("- ./.env", source)

    def test_compose_expoe_porta_8501(self):
        source = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn('"8501:8501"', source)

    def test_compose_nao_executa_main_py(self):
        source = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertNotIn("main.py", source)

    def test_chat_chama_apenas_app_ou_cli(self):
        dockerfile_source = DOCKERFILE_PATH.read_text(encoding="utf-8")
        compose_source = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("app_ai_chat.py", dockerfile_source)
        self.assertIn("app_ai_chat.py", compose_source)
        self.assertIn("scripts", dockerfile_source)


if __name__ == "__main__":
    unittest.main()
