"""Provedores controlados de dados para a camada de IA."""

from __future__ import annotations

from datetime import date
import time

import pandas as pd
from sqlalchemy import text

from src.ai.config import (
    AI_ALLOWED_COLUMNS,
    AI_ALLOWED_TABLES,
    AI_DATA_SOURCE,
    AI_MAX_MONTHS,
    AI_MAX_ROWS,
)
from src.ai.read_only_datasus import get_last_available_date, get_readonly_engine
from src.observability.telemetry import add_metric, record_duration, record_error, set_span_attributes, span

DATA_SUS_AI_VIEW = AI_DATA_SOURCE


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
    """Carrega um DataFrame controlado da fonte enriquecida da camada de IA.

    A consulta carrega apenas dados ja existentes no banco, limitada aos ultimos
    3 meses disponiveis, respeitando allowlist de colunas e limite maximo de
    linhas configurados para a camada de IA.
    """
    if DATA_SUS_AI_VIEW not in AI_ALLOWED_TABLES:
        raise RuntimeError("Fonte de dados da IA nao esta liberada.")

    with span("db.analytical.connect", {
        "db.system": "postgresql", "db.category": "analytical",
        "db.operation": "connect", "db.view": DATA_SUS_AI_VIEW,
    }):
        engine = get_readonly_engine()
    with span("db.analytical.maximum_date", {
        "db.system": "postgresql", "db.category": "analytical",
        "db.operation": "select", "db.view": DATA_SUS_AI_VIEW,
    }):
        ultima_data = get_last_available_date(engine)

    if ultima_data is None:
        return pd.DataFrame(columns=AI_ALLOWED_COLUMNS), None, None

    primeiro_dia_mes_final = _first_day_of_month(ultima_data)
    data_inicio = _first_day_months_before(primeiro_dia_mes_final, AI_MAX_MONTHS - 1)
    data_fim_exclusiva = _first_day_next_month(primeiro_dia_mes_final)
    selected_columns = ",\n            ".join(AI_ALLOWED_COLUMNS)

    query = text(f"""
        SELECT
            {selected_columns}
        FROM {DATA_SUS_AI_VIEW}
        WHERE data >= :data_inicio
          AND data < :data_fim_exclusiva
        ORDER BY data DESC
        LIMIT :limit
    """)

    started = time.perf_counter()
    attributes = {
        "db.system": "postgresql", "db.category": "analytical",
        "db.operation": "select", "db.view": DATA_SUS_AI_VIEW,
    }
    with span("db.analytical.query", attributes) as current:
        try:
            df = pd.read_sql_query(
                query,
                con=engine,
                params={
                    "data_inicio": data_inicio,
                    "data_fim_exclusiva": data_fim_exclusiva,
                    "limit": AI_MAX_ROWS,
                },
            )
            set_span_attributes(current, {"db.result_status": "success", "db.row_count": len(df)})
        except Exception as exc:
            category = type(exc).__name__
            record_error(current, category)
            add_metric("eq10_analytical_query_errors_total", attributes={"error.category": category})
            raise
        finally:
            record_duration(
                "eq10_analytical_query_duration_seconds",
                time.perf_counter() - started,
                {"db.operation": "select"},
            )

    return df.loc[:, AI_ALLOWED_COLUMNS], data_inicio, data_fim_exclusiva
