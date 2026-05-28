from pathlib import Path
import re
import unittest


WORKFLOW_PATH = Path(".github/workflows/deploy.yml")
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

    def test_workflow_existe(self):
        self.assertTrue(WORKFLOW_PATH.exists())

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

        self.assertIn(f"docker pull {GHCR_IMAGE}", source)
        self.assertRegex(source, rf"(?m)^\s+{re.escape(GHCR_IMAGE)}$")
        self.assertNotIn("DEPLOY_IMAGE", source)
        self.assertNotIn("env.IMAGE", source)
        self.assertNotIn('"$IMAGE"', source)
        self.assertNotIn("GITHUB_ENV", source)
        self.assertNotIn("GITHUB_OUTPUT", source)

    def test_deploy_nao_contem_placeholders_ou_echo_stub(self):
        source = self.read_workflow()

        self.assertNotIn("CONFIG" + "URAR", source)
        self.assertNotIn("*" * 3, source)
        self.assertNotIn('script: echo "deploy"', source)
        self.assertNotIn("script: echo 'deploy'", source)

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

    def test_deploy_sobe_container_streamlit_na_porta_8110_para_8501(self):
        source = self.read_workflow()

        self.assertIn("docker stop eq10-chat || true", source)
        self.assertIn("docker rm eq10-chat || true", source)
        self.assertIn("docker run -d", source)
        self.assertIn("--name eq10-chat", source)
        self.assertIn("--restart unless-stopped", source)
        self.assertIn("-p 127.0.0.1:8110:8501", source)
        self.assertNotIn("-p 8501:8501", source)

        for env_name in AI_ENV_NAMES:
            self.assertIn(f'-e {env_name}="${env_name}"'.replace('"AI_', '"$AI_'), source)

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
