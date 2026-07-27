"""Compatibilidade publica para a politica central de prompts."""

from __future__ import annotations

from src.ai.prompt_policy import BLOCK_MESSAGE, classify_prompt

MENSAGEM_BLOQUEIO = BLOCK_MESSAGE


def validar_prompt(prompt: str) -> tuple[bool, str]:
    """Mantem a API antiga, delegando toda decisao para a politica unica."""
    decision = classify_prompt(prompt)
    return (True, "") if decision.allowed else (False, MENSAGEM_BLOQUEIO)
