"""Executor local de planos estatisticos produzidos pela politica central."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.ai.prompt_policy import (
    PromptDecision,
    classify_prompt,
    dimension_display,
    metric_display,
)

SIMPLE_STATS_UNAVAILABLE_MESSAGE = (
    "Esta pergunta estatística é segura, mas ainda não está disponível no modo "
    "estatístico simples."
)


def _format_number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _period_text(start: Any, end: Any) -> str:
    return f"Período analisado: {start} até antes de {end}."


def _format_metric(value: float, metric: str, operation: str) -> str:
    if metric.startswith("valor"):
        return f"R$ {_format_number(value)}"
    if operation == "mean":
        suffix = " anos" if metric == "idade" else ""
        return f"{_format_number(value)}{suffix}"
    return _format_int(int(value))


def _execute_plan(
    df: pd.DataFrame,
    decision: PromptDecision,
    start: Any,
    end: Any,
) -> str:
    operation = decision.operation or "unsupported"
    metric = decision.metric or "rows"
    dimension = decision.dimension

    if operation == "unsupported":
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE
    if operation == "latest":
        if "data" not in df.columns:
            return SIMPLE_STATS_UNAVAILABLE_MESSAGE
        dates = pd.to_datetime(df["data"], errors="coerce").dropna()
        if dates.empty:
            return SIMPLE_STATS_UNAVAILABLE_MESSAGE
        latest = dates.max()
        return "\n".join(
            [
                f"Data mais recente disponivel: {latest.strftime('%d/%m/%Y')}.",
                f"Mes mais recente disponivel: {latest.strftime('%m/%Y')}.",
                _period_text(start, end),
            ]
        )
    if operation == "count_distinct":
        if metric not in df.columns:
            return SIMPLE_STATS_UNAVAILABLE_MESSAGE
        values = df[metric].dropna().astype(str).str.strip()
        total = values[values != ""].nunique()
        return "\n".join(
            [f"Contagem de procedimentos distintos: {_format_int(int(total))}.", _period_text(start, end)]
        )

    row_metrics = {"rows", "records"}
    required = [column for column in (dimension, None if metric in row_metrics else metric) if column]
    if any(column not in df.columns for column in required):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    if metric in row_metrics:
        if dimension is None:
            title = "Contagem de registros" if metric == "records" else "Total de atendimentos"
            return "\n".join(
                [f"{title}: {_format_int(len(df))}.", _period_text(start, end)]
            )
        result = df.groupby(dimension, dropna=False).size()
    else:
        columns = [column for column in (dimension, metric) if column]
        working = df[columns].copy()
        working[metric] = pd.to_numeric(working[metric], errors="coerce")
        if dimension is None:
            series = working[metric].dropna()
            if series.empty:
                return SIMPLE_STATS_UNAVAILABLE_MESSAGE
            value = series.mean() if operation == "mean" else series.sum()
            label = "Média" if operation == "mean" else "Total geral"
            display = "frequencia" if metric == "frequencia" else metric_display(metric)
            title = f"{label} de {display}"
            if operation == "mean" and metric == "idade":
                title = "Média de idade dos atendimentos"
            return "\n".join(
                [f"{title}: {_format_metric(float(value), metric, operation)}.", _period_text(start, end)]
            )
        grouped = working.groupby(dimension, dropna=False)[metric]
        result = grouped.mean() if operation == "mean" else grouped.sum(min_count=1)

    result = result.dropna().sort_values(ascending=False)
    if operation == "ranking":
        result = result.head(decision.limit)

    dim_label = dimension_display(dimension)
    metric_label = metric_display(metric)
    if metric in row_metrics:
        title = f"Total de atendimentos por {dim_label}:"
    elif metric == "frequencia" and dimension == "sexo" and operation == "sum":
        title = "Frequência total por sexo:"
    elif metric == "quantidade_apresentada" and dimension == "unidade":
        title = "Unidades com maior quantidade apresentada:"
    elif operation == "mean":
        title = f"Média de {metric_label} por {dim_label}:"
    elif metric == "valor_aprovado" and dimension.startswith("municipio") and operation == "sum":
        title = f"Total de valor aprovado por {dim_label}:"
    else:
        title = f"Ranking por {dim_label} usando {metric_label}:"

    lines = [title, _period_text(start, end)]
    for position, (label, value) in enumerate(result.items(), start=1):
        prefix = f"{position}. " if operation == "ranking" or metric != "rows" else "- "
        lines.append(f"{prefix}{label}: {_format_metric(float(value), metric, operation)}")
    return "\n".join(lines)


def executar_pergunta_estatistica_simples(
    df: pd.DataFrame,
    prompt_usuario: str,
    data_inicio: Any,
    data_fim_exclusiva: Any,
    decision: PromptDecision | None = None,
) -> str:
    """Executa somente a decisao tipada; nao interpreta palavras do prompt."""
    decision = decision or classify_prompt(prompt_usuario)
    if not decision.allowed:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE
    return _execute_plan(df, decision, data_inicio, data_fim_exclusiva)


def executar_pergunta_simples(
    df: pd.DataFrame,
    prompt_usuario: str,
    data_inicio: Any,
    data_fim_exclusiva: Any,
    decision: PromptDecision | None = None,
) -> str:
    return executar_pergunta_estatistica_simples(
        df, prompt_usuario, data_inicio, data_fim_exclusiva, decision
    )
