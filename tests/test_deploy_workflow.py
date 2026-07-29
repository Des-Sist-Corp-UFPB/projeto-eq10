from pathlib import Path
import re
import unittest


WORKFLOW_PATH = Path(".github/workflows/deploy.yml")
PROD_COMPOSE_PATH = Path("docker-compose.prod.yml")
HEALTH_SCRIPT_PATH = Path("scripts/verify_deploy_health.py")


class TestDeployWorkflow(unittest.TestCase):
    def read_workflow(self) -> str:
        return WORKFLOW_PATH.read_text(encoding="utf-8")

    def read_prod_compose(self) -> str:
        return PROD_COMPOSE_PATH.read_text(encoding="utf-8")

    def test_workflow_existe(self):
        self.assertTrue(WORKFLOW_PATH.exists())
        self.assertTrue(PROD_COMPOSE_PATH.exists())
        self.assertTrue(HEALTH_SCRIPT_PATH.exists())

    def test_workflow_runner_esta_explicito(self):
        source = self.read_workflow()

        allowed_runners = {
            "runs-on: [self-hosted, dsc-selfhosted]",
            "runs-on: ubuntu-latest",
        }
        self.assertTrue(any(runner in source for runner in allowed_runners), source)

    def test_build_publica_imagem_do_dockerfile_chat(self):
        source = self.read_workflow()

        self.assertIn("IMAGE=ghcr.io/", source)
        self.assertIn("${{ github.repository }}", source)
        self.assertIn("uses: docker/build-push-action@v5", source)
        self.assertIn("context: .", source)
        self.assertIn("file: Dockerfile.chat", source)
        self.assertIn("push: true", source)
        self.assertIn("tags: ${{ env.IMAGE }}", source)

    def test_deploy_remoto_usa_ssh_sem_imprimir_variaveis(self):
        source = self.read_workflow()

        self.assertIn("secrets.SSH_DEPLOY_KEY", source)
        self.assertIn("secrets.SSH_USERNAME", source)
        self.assertIn("${{ github.actor }}:${{ secrets.GITHUB_TOKEN }}", source)
        self.assertIn("StrictHostKeyChecking=no", source)
        self.assertNotIn("printenv", source)
        self.assertNotIn("cat .env", source)
        self.assertNotIn("docker compose logs", source)

    def test_workflow_verifica_saude_depois_do_deploy(self):
        source = self.read_workflow()

        self.assertIn("Verifica saude publica da aplicacao", source)
        self.assertIn("APP_HEALTH_URL: ${{ vars.APP_HEALTH_URL }}", source)
        self.assertIn('DEPLOY_HEALTH_TIMEOUT_SECONDS: "120"', source)
        self.assertIn('DEPLOY_HEALTH_INTERVAL_SECONDS: "5"', source)
        self.assertIn("python scripts/verify_deploy_health.py", source)

    def test_workflow_solicita_diagnosticos_seguros_apos_falha(self):
        source = self.read_workflow()

        self.assertIn("Solicita diagnosticos seguros no servidor", source)
        self.assertIn("if: failure()", source)
        self.assertIn("diagnostics", source)
        self.assertIn("compose ps", source)
        self.assertIn("app logs tail", source)
        self.assertIn("app state", source)
        self.assertIn("app cmd", source)
        self.assertIn("app entrypoint", source)
        self.assertNotIn("printenv", source)
        self.assertNotIn("cat .env", source)
        self.assertNotIn("docker inspect", source)

    def test_prod_compose_app_usa_imagem_publicada_sem_command_override(self):
        source = self.read_prod_compose()
        app_block = source.split("  etl:", 1)[0]

        self.assertIn("  app:", app_block)
        self.assertIn("image: ${IMAGE:-ghcr.io/des-sist-corp-ufpb/projeto-eq10:latest}", app_block)
        self.assertIn('"127.0.0.1:8110:8080"', app_block)
        self.assertIn(".env.prod", app_block)
        self.assertIn("ENVIRONMENT=production", app_block)
        self.assertNotIn("command:", app_block)
        self.assertNotIn("entrypoint:", app_block)
        self.assertNotIn("main.py", app_block)

    def test_prod_compose_nao_declara_credenciais_reais_no_yaml(self):
        source = self.read_prod_compose()

        self.assertIn(".env.prod", source)
        self.assertNotRegex(source, re.compile(r"^\s*-\s*(user|password|host|database)=", re.MULTILINE))
        self.assertNotRegex(source, re.compile(r"^\s*-\s*AI_DB_(USER|PASSWORD|HOST|NAME|PORT)=", re.MULTILINE))

    def test_prod_compose_carrega_segredos_otel_do_env_file(self):
        source = self.read_prod_compose()
        app_block = source.split("  etl:", 1)[0]

        self.assertIn("env_file:", app_block)
        self.assertIn("- .env.prod", app_block)
        self.assertIn("- OTEL_ENABLED=true", app_block)
        self.assertIn("- OTEL_SERVICE_NAME=dsc-eq10", app_block)
        self.assertIn("- OTEL_TRACES_EXPORTER=otlp", app_block)
        self.assertIn("- OTEL_METRICS_EXPORTER=otlp", app_block)
        self.assertIn("- OTEL_LOGS_EXPORTER=otlp", app_block)
        self.assertIn("- OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf", app_block)
        self.assertIn("- OTEL_EXPORTER_OTLP_TIMEOUT=10000", app_block)
        self.assertNotIn("OTEL_EXPORTER_OTLP_ENDPOINT=", app_block)
        self.assertNotIn("OTEL_EXPORTER_OTLP_HEADERS=", app_block)

    def test_workflow_nao_transporta_segredos_otel(self):
        source = self.read_workflow()

        self.assertNotIn("OTEL_EXPORTER_OTLP_ENDPOINT", source)
        self.assertNotIn("OTEL_EXPORTER_OTLP_HEADERS", source)
        self.assertNotIn("secrets.OTEL_", source)


if __name__ == "__main__":
    unittest.main()
