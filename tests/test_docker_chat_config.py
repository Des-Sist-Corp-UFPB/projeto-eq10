from pathlib import Path
import unittest
import re


DOCKERFILE_PATH = Path("Dockerfile.chat")
COMPOSE_PATH = Path("docker-compose.chat.yml")
PROD_COMPOSE_PATH = Path("docker-compose.prod.yml")
START_SCRIPT_PATH = Path("start.sh")
NGINX_PATH = Path("nginx.conf")
STREAMLIT_CONFIG_PATH = Path(".streamlit/config.toml")
DOCKERIGNORE_PATH = Path(".dockerignore")


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

    def test_dockerfile_instala_dependencias_na_venv_com_uv(self):
        source = DOCKERFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("COPY --from=ghcr.io/astral-sh/uv:0.5.31", source)
        self.assertIn("UV_PROJECT_ENVIRONMENT=/app/.venv", source)
        self.assertIn('PATH="/app/.venv/bin:$PATH"', source)
        self.assertIn("uv venv", source)
        self.assertIn("uv pip install", source)
        self.assertIn("requirements.txt", source)
        self.assertIn("/app/.venv/bin/python", source)
        self.assertNotIn("pip install --no-cache-dir -r requirements.txt", source)
        self.assertNotIn("|| true", source)

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
        self.assertIn("/app/.venv/bin/python", dockerfile_source)
        self.assertIn("0.0.0.0", start_source)
        self.assertIn('STREAMLIT_PYTHON="/app/.venv/bin/python"', start_source)
        self.assertIn('STREAMLIT_APP="app_ai_chat.py"', start_source)
        self.assertIn('"$STREAMLIT_PYTHON" -m streamlit run "$STREAMLIT_APP"', start_source)
        self.assertIn('STREAMLIT_PID=$!', start_source)
        self.assertIn('status=listening', start_source)
        self.assertLess(
            start_source.index("component=readiness | status=listening"),
            start_source.index('nginx -g "daemon off;"'),
        )
        self.assertIn("--server.port=\"${STREAMLIT_PORT}\"", start_source)
        self.assertIn("--server.headless=true", start_source)
        self.assertIn('STREAMLIT_PORT="8501"', start_source)
        self.assertNotIn("python -m streamlit", start_source)
        self.assertNotIn("wait -n", start_source)
        self.assertNotIn("main.py", start_source)
        self.assertIn("proxy_pass http://127.0.0.1:8501", nginx_source)
        self.assertIn("http://127.0.0.1:8080/ping", dockerfile_source)

    def test_readiness_server_is_internal_and_supervised(self):
        start_source = START_SCRIPT_PATH.read_text(encoding="utf-8")
        nginx_source = NGINX_PATH.read_text(encoding="utf-8")
        dockerfile_source = DOCKERFILE_PATH.read_text(encoding="utf-8")
        compose_sources = (
            COMPOSE_PATH.read_text(encoding="utf-8")
            + PROD_COMPOSE_PATH.read_text(encoding="utf-8")
        )

        self.assertIn("-m src.diagnostics.readiness_server", start_source)
        self.assertIn('READINESS_PORT="8502"', start_source)
        self.assertIn('READINESS_PID=$!', start_source)
        self.assertIn('"$READINESS_PID" "$STREAMLIT_PID" "$NGINX_PID"', start_source)
        self.assertIn("location = /health", nginx_source)
        self.assertIn("proxy_pass http://127.0.0.1:8502/health", nginx_source)
        self.assertIn("proxy_connect_timeout 5s", nginx_source)
        self.assertNotIn("8502:", compose_sources)
        self.assertNotIn("EXPOSE 8502", dockerfile_source)

    def test_ping_prova_saude_do_streamlit(self):
        nginx_source = NGINX_PATH.read_text(encoding="utf-8")

        self.assertIn("location = /ping", nginx_source)
        self.assertIn("proxy_pass http://127.0.0.1:8501/_stcore/health", nginx_source)
        self.assertNotIn("return 200", nginx_source)
        self.assertNotIn('"status": "ok"', nginx_source)

    def test_dockerfile_copia_streamlit_config_para_tema_claro_em_producao(self):
        """Sem essa copia, o Streamlit em producao nao recebe base="light" e
        renderiza selects/inputs/tabelas/dialogos com tema escuro por padrao."""
        source = DOCKERFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("COPY .streamlit ./.streamlit", source)
        self.assertTrue(STREAMLIT_CONFIG_PATH.exists())

    def test_dockerignore_nao_exclui_streamlit_config(self):
        source = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
        lines = [line.strip() for line in source.splitlines()]

        self.assertNotIn(".streamlit", lines)

    def test_prod_compose_nao_carrega_credenciais_de_banco_no_yaml(self):
        source = PROD_COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("ENVIRONMENT=production", source)
        self.assertIn(".env.prod", source)
        self.assertNotRegex(source, re.compile(r"^\s*-\s*(user|password|host|database)=", re.MULTILINE))
        self.assertNotRegex(source, re.compile(r"^\s*-\s*AI_DB_(USER|PASSWORD|HOST|NAME|PORT)=", re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
