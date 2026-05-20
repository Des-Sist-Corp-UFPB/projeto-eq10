"""Logging seguro para interacoes com a camada de IA."""

import logging

logger = logging.getLogger(__name__)


def log_ai_question(prompt: str, status: str, detail: str | None = None) -> None:
    """Registra metadados basicos da pergunta sem salvar credenciais ou .env."""
    prompt_size = len(prompt or "")
    if detail:
        logger.info(
            "Pergunta IA | status=%s | tamanho_prompt=%s | detalhe=%s",
            status,
            prompt_size,
            detail,
        )
        return

    logger.info("Pergunta IA | status=%s | tamanho_prompt=%s", status, prompt_size)
