"""Provedores controlados de dados para a camada de IA."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import text

from src.ai.config import AI_ALLOWED_COLUMNS, AI_ALLOWED_TABLES, AI_MAX_MONTHS, AI_MAX_ROWS
from src.ai.read_only_datasus import get_last_available_date, get_readonly_engine

DATA_SUS_TABLE = "data_sus"


def _first_day_of_month(reference_date: date) -> date:
    return date(reference_date.year, reference_date.month, 1)


def _first_day_months_before(reference_date: date, months: int) -> date:
    month_index = reference_date.year * 12 + (reference_date.month - 1) - months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _first_day_next_month(reference_date: date) -> date:
    month_index = reference_date.year * 12 + reference_date.month
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def load_controlled_datasus_dataframe():
    """Carrega um DataFrame controlado da tabela data_sus.

    A consulta carrega apenas dados ja existentes no banco, limitada aos ultimos
    3 meses disponiveis, respeitando allowlist de colunas e limite maximo de
    linhas configurados para a camada de IA.
    """
    if DATA_SUS_TABLE not in AI_ALLOWED_TABLES:
        raise RuntimeError("Tabela data_sus nao esta liberada para a camada de IA.")

    engine = get_readonly_engine()
    ultima_data = get_last_available_date(engine)

    if ultima_data is None:
        return pd.DataFrame(columns=AI_ALLOWED_COLUMNS), None, None

    primeiro_dia_mes_final = _first_day_of_month(ultima_data)
    data_inicio = _first_day_months_before(primeiro_dia_mes_final, AI_MAX_MONTHS - 1)
    data_fim_exclusiva = _first_day_next_month(primeiro_dia_mes_final)
    selected_columns = ", ".join(AI_ALLOWED_COLUMNS)

    query = text(f"""
        SELECT {selected_columns}
        FROM {DATA_SUS_TABLE}
        WHERE data >= :data_inicio
          AND data < :data_fim_exclusiva
        ORDER BY data DESC
        LIMIT :limit
    """)

    df = pd.read_sql_query(
        query,
        con=engine,
        params={
            "data_inicio": data_inicio,
            "data_fim_exclusiva": data_fim_exclusiva,
            "limit": AI_MAX_ROWS,
        },
    )

    return df.loc[:, AI_ALLOWED_COLUMNS], data_inicio, data_fim_exclusiva
