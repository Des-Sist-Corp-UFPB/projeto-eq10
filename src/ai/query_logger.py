"""Logging seguro para interacoes com a camada de IA."""

import logging
import re

logger = logging.getLogger(__name__)


def safe_prompt_for_log(prompt: str) -> str:
    value = " ".join((prompt or "").split())[:300]
    value = re.sub(
        r"(?i)\b(?:postgresql(?:\+\w+)?|mysql|mariadb|sqlite)://\S+",
        "[DATABASE_URL_REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)\b(senhas?|tokens?|secrets?|chaves?|api[_ ]?keys?)\b\s*[:=]?\s*\S*",
        r"\1=[REDACTED]",
        value,
    )
    return re.sub(r"(?i)\btraceback\b.*", "[TRACEBACK_REDACTED]", value)


def log_ai_pipeline(
    prompt: str,
    *,
    detected_intent: str,
    guard_decision: str,
    validation_decision: str,
    query_generated: str,
    final_decision: str,
) -> None:
    """Registra o pipeline interno sem enviar diagnosticos para a interface."""
    logger.info(
        "Pipeline IA | prompt=%r | intent=%s | guard=%s | validation=%s | "
        "query=%s | final=%s",
        safe_prompt_for_log(prompt),
        detected_intent,
        guard_decision,
        validation_decision,
        query_generated,
        final_decision,
    )


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
