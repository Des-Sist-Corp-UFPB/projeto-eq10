"""Validacao de meses solicitados em prompts da camada de IA."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from sqlalchemy import text

from src.ai.read_only_datasus import get_readonly_engine

MENSAGEM_MES_INDISPONIVEL = "O mês solicitado ainda não está disponível no sistema."

MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _normalizar_texto(texto: str) -> str:
    texto_normalizado = unicodedata.normalize("NFKD", texto.casefold())
    texto_sem_acentos = "".join(
        caractere
        for caractere in texto_normalizado
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"\s+", " ", texto_sem_acentos).strip()


def _primeiro_dia_mes_seguinte(ano: int, mes: int) -> date:
    if mes == 12:
        return date(ano + 1, 1, 1)

    return date(ano, mes + 1, 1)


def extrair_mes_ano_do_prompt(prompt: str) -> tuple[int | None, int | None]:
    """Extrai mes em portugues e ano com 4 digitos de um prompt."""
    if not prompt:
        return None, None

    prompt_normalizado = _normalizar_texto(prompt)
    year_match = re.search(r"\b(19|20)\d{2}\b", prompt_normalizado)

    if not year_match:
        return None, None

    for month_name, month_number in MONTHS_PT.items():
        if re.search(rf"\b{month_name}\b", prompt_normalizado):
            return month_number, int(year_match.group(0))

    return None, None


def mes_existe_no_banco(ano: int, mes: int) -> bool:
    """Verifica se existe ao menos um registro no mes informado."""
    data_inicio = date(ano, mes, 1)
    data_fim_exclusiva = _primeiro_dia_mes_seguinte(ano, mes)
    query = text("""
        SELECT 1
        FROM data_sus
        WHERE data >= :data_inicio
          AND data < :data_fim_exclusiva
        LIMIT 1
    """)

    engine = get_readonly_engine()

    with engine.connect() as conn:
        result = conn.execute(
            query,
            {
                "data_inicio": data_inicio,
                "data_fim_exclusiva": data_fim_exclusiva,
            },
        ).fetchone()

    return result is not None


def validar_mes_solicitado_no_prompt(prompt: str) -> tuple[bool, str]:
    """Valida disponibilidade de um mes citado explicitamente no prompt."""
    mes, ano = extrair_mes_ano_do_prompt(prompt)

    if mes is None or ano is None:
        return True, ""

    if mes_existe_no_banco(ano, mes):
        return True, ""

    return False, MENSAGEM_MES_INDISPONIVEL
