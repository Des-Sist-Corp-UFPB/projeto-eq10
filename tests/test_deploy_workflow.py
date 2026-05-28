from pathlib import Path
import re
import unittest


WORKFLOW_PATH = Path(".github/workflows/deploy.yml")
PROD_COMPOSE_PATH = Path("docker-compose.prod.yml")
DEPLOY_FILE_PATHS = [WORKFLOW_PATH, PROD_COMPOSE_PATH]
GHCR_IMAGE = "ghcr.io/des-sist-corp-ufpb/projeto-eq10:latest"

AI_ENV_NAMES = [
    "AI_DB_USER",
    "AI_DB_PASSWORD",
    "AI_DB_HOST",
    "AI_DB_NAME",
    "AI_USE_LLM",
    "AI_FALLBACK_TO_SIMPLE",
    "AI_LLM_PROVIDER",
    "AI_LLM_MODEL",
    "AI_LLM_API_KEY",
    "AI_DEBUG_SAFE",
]

AI_VARIABLE_NAMES = [
    "AI_DB_USER",
    "AI_DB_HOST",
    "AI_DB_NAME",
    "AI_USE_LLM",
    "AI_FALLBACK_TO_SIMPLE",
    "AI_LLM_PROVIDER",
    "AI_LLM_MODEL",
    "AI_DEBUG_SAFE",
]


class TestDeployWorkflow(unittest.TestCase):
    def read_workflow(self):
        return WORKFLOW_PATH.read_text(encoding="utf-8")

    def read_deploy_files(self):
        return {
            path: path.read_text(encoding="utf-8")
            for path in DEPLOY_FILE_PATHS
        }

    def test_workflow_existe(self):
        self.assertTrue(WORKFLOW_PATH.exists())
        self.assertTrue(PROD_COMPOSE_PATH.exists())

    def test_build_usa_dockerfile_chat_e_imagem_fixa(self):
        source = self.read_workflow()

        self.assertIn(GHCR_IMAGE, source)
        self.assertIn("uses: docker/build-push-action@v5", source)
        self.assertIn("context: .", source)
        self.assertIn("file: Dockerfile.chat", source)
        self.assertIn("push: true", source)
        self.assertIn(f"tags: {GHCR_IMAGE}", source)
        self.assertNotIn("Prepara nome da imagem", source)
        self.assertNotIn("Mostra imagem de deploy", source)
        self.assertNotIn("steps.image.outputs.deploy_image", source)

    def test_deploy_usa_imagem_fixa_sem_variavel_de_imagem(self):
        source = self.read_workflow()

        self.assertIn(GHCR_IMAGE, source)
        self.assertNotIn("DEPLOY_IMAGE", source)
        self.assertNotIn("env.IMAGE", source)
        self.assertNotIn('"$IMAGE"', source)
        self.assertNotIn("GITHUB_ENV", source)
        self.assertNotIn("GITHUB_OUTPUT", source)
        self.assertNotIn("docker pull", source)
        self.assertNotIn("docker run", source)
        self.assertNotIn("docker stop", source)
        self.assertNotIn("docker rm", source)

    def test_deploy_nao_contem_placeholders_ou_echo_stub(self):
        source = self.read_workflow()

        self.assertNotIn("ghcr.io/CONFIG" + "URAR", source)
        self.assertNotIn("*" * 3, source)
        self.assertNotIn('script: echo "deploy"', source)
        self.assertNotIn("script: echo 'deploy'", source)

    def test_deploy_tem_apenas_diagnostico_seguro_no_script(self):
        source = self.read_workflow()

        self.assertIn('echo "=== DIAGNOSTICO DEPLOY EQ10 ==="', source)
        self.assertIn('echo "Imagem fixa esperada:"', source)
        self.assertIn(f'echo "{GHCR_IMAGE}"', source)
        self.assertIn('echo "Variavel IMAGE no servidor:"', source)
        self.assertIn("printenv IMAGE || true", source)
        self.assertIn('echo "Variaveis relacionadas a imagem no servidor:"', source)
        self.assertIn("env | grep -i image || true", source)
        self.assertIn('echo "Containers existentes com eq10/chat/CONFIGURAR:"', source)
        self.assertIn(
            'docker ps -a --format "table {{.Names}}\\t{{.Image}}\\t{{.Status}}" | grep -E "eq10|chat|CONFIGURAR" || true',
            source,
        )
        self.assertIn('echo "Imagens locais relacionadas:"', source)
        self.assertIn(
            'docker images --format "table {{.Repository}}\\t{{.Tag}}\\t{{.ID}}" | grep -E "eq10|CONFIGURAR|des-sist" || true',
            source,
        )
        self.assertIn('echo "Docker version:"', source)
        self.assertIn("docker --version || true", source)
        self.assertIn('echo "=== FIM DIAGNOSTICO DEPLOY EQ10 ==="', source)

    def test_arquivos_de_deploy_nao_usam_image_ou_placeholders(self):
        forbidden_fragments = [
            "${" + "IMAGE",
            "ghcr.io/CONFIG" + "URAR",
            "*" * 3,
            "DEPLOY_IMAGE",
            "env.IMAGE",
            '"$IMAGE"',
            "steps.image.outputs.deploy_image",
        ]

        for path, source in self.read_deploy_files().items():
            with self.subTest(path=str(path)):
                self.assertIn(GHCR_IMAGE, source)

                for fragment in forbidden_fragments:
                    self.assertNotIn(fragment, source)

        compose_source = PROD_COMPOSE_PATH.read_text(encoding="utf-8")
        self.assertIn(f"image: {GHCR_IMAGE}", compose_source)
        self.assertIn(
            "AI_DB_PASSWORD=${AI_DB_PASSWORD:?AI_DB_PASSWORD obrigatoria}",
            compose_source,
        )

    def test_deploy_declara_secrets_variables_e_envs_necessarios(self):
        source = self.read_workflow()

        self.assertIn("username: ${{ secrets.SSH_USERNAME }}", source)
        self.assertIn("key: ${{ secrets.SSH_DEPLOY_KEY }}", source)
        self.assertIn("AI_DB_PASSWORD: ${{ secrets.AI_DB_PASSWORD }}", source)
        self.assertIn("AI_LLM_API_KEY: ${{ secrets.GEMINI_API_KEY }}", source)

        for variable_name in AI_VARIABLE_NAMES:
            self.assertIn(f"{variable_name}: ${{{{ vars.{variable_name} }}}}", source)

        self.assertNotIn("secrets.AI_DB_USER", source)
        self.assertNotIn("secrets.AI_DB_HOST", source)
        self.assertNotIn("secrets.AI_DB_NAME", source)
        self.assertNotIn("secrets.AI_LLM_API_KEY", source)

        expected_envs = "envs: " + ",".join(AI_ENV_NAMES)
        self.assertIn(expected_envs, source)

    def test_modo_diagnostico_nao_executa_container_ou_pull(self):
        source = self.read_workflow()

        self.assertNotIn("docker pull", source)
        self.assertNotIn("docker stop", source)
        self.assertNotIn("docker rm", source)
        self.assertNotIn("docker run", source)
        self.assertNotIn("--name eq10-chat", source)
        self.assertNotIn("--restart unless-stopped", source)
        self.assertNotIn("-p 127.0.0.1:8110:8501", source)
        self.assertNotIn("-p 8501:8501", source)

        self.assertNotIn("main.py", source)
        self.assertNotIn("env_file", source)
        self.assertNotIn(".env", source.lower())

    def test_deploy_nao_contem_credenciais_reais_em_campos_sensiveis(self):
        source = self.read_workflow()
        sensitive_assignment = re.compile(
            r"^(username|password|key|AI_DB_PASSWORD|AI_LLM_API_KEY):\s*(.+)$"
        )

        for line in source.splitlines():
            match = sensitive_assignment.match(line.strip())
            if not match:
                continue

            value = match.group(2)
            uses_secret = value.startswith("${{ secrets.")
            uses_github_actor = value == "${{ github.actor }}"
            self.assertTrue(uses_secret or uses_github_actor, line)


if __name__ == "__main__":
    unittest.main()
