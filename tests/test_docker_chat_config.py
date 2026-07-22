from pathlib import Path
import unittest
import re


DOCKERFILE_PATH = Path("Dockerfile.chat")
COMPOSE_PATH = Path("docker-compose.chat.yml")
PROD_COMPOSE_PATH = Path("docker-compose.prod.yml")
START_SCRIPT_PATH = Path("start.sh")
NGINX_PATH = Path("nginx.conf")


class TestDockerChatConfig(unittest.TestCase):
    def test_arquivos_existem(self):
        self.assertTrue(DOCKERFILE_PATH.exists())
        self.assertTrue(COMPOSE_PATH.exists())
        self.assertTrue(PROD_COMPOSE_PATH.exists())
        self.assertTrue(START_SCRIPT_PATH.exists())
        self.assertTrue(NGINX_PATH.exists())

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

    def test_compose_expoe_porta_8080(self):
        source = COMPOSE_PATH.read_text(encoding="utf-8")
        self.assertIn('"8080:8080"', source)

    def test_compose_nao_executa_main_py(self):
        source = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertNotIn("main.py", source)
        self.assertNotIn("streamlit", source.lower())

    def test_chat_chama_apenas_app_ou_cli(self):
        dockerfile_source = DOCKERFILE_PATH.read_text(encoding="utf-8")
        compose_source = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("app_ai_chat.py", dockerfile_source)
        self.assertNotIn("app_ai_chat.py", compose_source)
        self.assertIn("scripts", dockerfile_source)

    def test_startup_usa_nginx_para_streamlit_8501(self):
        dockerfile_source = DOCKERFILE_PATH.read_text(encoding="utf-8")
        start_source = START_SCRIPT_PATH.read_text(encoding="utf-8")
        nginx_source = NGINX_PATH.read_text(encoding="utf-8")

        self.assertIn('CMD ["./start.sh"]', dockerfile_source)
        self.assertIn("HEALTHCHECK", dockerfile_source)
        self.assertIn("0.0.0.0", start_source)
        self.assertIn("--server.port=\"${STREAMLIT_PORT}\"", start_source)
        self.assertIn("--server.headless=true", start_source)
        self.assertIn('STREAMLIT_PORT="8501"', start_source)
        self.assertIn("wait -n", start_source)
        self.assertIn("proxy_pass http://127.0.0.1:8501", nginx_source)
        self.assertIn("http://127.0.0.1:8501/_stcore/health", dockerfile_source)

    def test_ping_prova_saude_do_streamlit(self):
        nginx_source = NGINX_PATH.read_text(encoding="utf-8")

        self.assertIn("location = /ping", nginx_source)
        self.assertIn("proxy_pass http://127.0.0.1:8501/_stcore/health", nginx_source)
        self.assertNotIn("return 200", nginx_source)
        self.assertNotIn('"status": "ok"', nginx_source)

    def test_prod_compose_nao_carrega_credenciais_de_banco_no_yaml(self):
        source = PROD_COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("ENVIRONMENT=production", source)
        self.assertIn(".env.prod", source)
        self.assertNotRegex(source, re.compile(r"^\s*-\s*(user|password|host|database)=", re.MULTILINE))
        self.assertNotRegex(source, re.compile(r"^\s*-\s*AI_DB_(USER|PASSWORD|HOST|NAME|PORT)=", re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
