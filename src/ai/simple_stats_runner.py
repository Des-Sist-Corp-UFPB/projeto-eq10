"""Runner local para estatisticas simples sem chamada externa de LLM."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

SIMPLE_STATS_UNAVAILABLE_MESSAGE = (
    "Esta pergunta ainda não está disponível no modo estatístico simples. "
    "Tente perguntar sobre totais, médias, contagens ou rankings básicos."
)


def _normalize_prompt(prompt: str) -> str:
    text = unicodedata.normalize("NFKD", prompt or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    return re.sub(r"[^a-z0-9_]+", " ", text).strip()


def _format_number(value: float, decimals: int = 2) -> str:
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _period_text(data_inicio: Any, data_fim_exclusiva: Any) -> str:
    return f"Período analisado: {data_inicio} até antes de {data_fim_exclusiva}."


def _has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return all(column in df.columns for column in columns)


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce").fillna(0)


def _total_valor_aprovado_por_municipio(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    if not _has_columns(df, ["cod_municipio_atendido", "valor_aprovado"]):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    working_df = df[["cod_municipio_atendido", "valor_aprovado"]].copy()
    working_df["valor_aprovado"] = _numeric_series(working_df, "valor_aprovado")
    result = (
        working_df.groupby("cod_municipio_atendido", dropna=False)["valor_aprovado"]
        .sum()
        .sort_values(ascending=False)
    )

    lines = [
        "Total de valor aprovado por município de atendimento:",
        _period_text(data_inicio, data_fim_exclusiva),
    ]
    for municipio, total in result.items():
        lines.append(f"- {municipio}: R$ {_format_number(float(total))}")

    return "\n".join(lines)


def _frequencia_por_sexo(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    if not _has_columns(df, ["sexo", "frequencia"]):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    working_df = df[["sexo", "frequencia"]].copy()
    working_df["frequencia"] = _numeric_series(working_df, "frequencia")
    result = (
        working_df.groupby("sexo", dropna=False)["frequencia"]
        .sum()
        .sort_values(ascending=False)
    )

    lines = [
        "Frequência total por sexo:",
        _period_text(data_inicio, data_fim_exclusiva),
    ]
    for sexo, total in result.items():
        lines.append(f"- {sexo}: {_format_int(int(total))}")

    return "\n".join(lines)


def _ranking_unidades_por_quantidade(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
    limit: int = 10,
) -> str:
    if not _has_columns(df, ["cod_unidade", "quantidade_apresentada"]):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    working_df = df[["cod_unidade", "quantidade_apresentada"]].copy()
    working_df["quantidade_apresentada"] = _numeric_series(
        working_df,
        "quantidade_apresentada",
    )
    result = (
        working_df.groupby("cod_unidade", dropna=False)["quantidade_apresentada"]
        .sum()
        .sort_values(ascending=False)
        .head(limit)
    )

    lines = [
        "Unidades com maior quantidade apresentada:",
        _period_text(data_inicio, data_fim_exclusiva),
    ]
    for position, (unidade, total) in enumerate(result.items(), start=1):
        lines.append(f"{position}. {unidade}: {_format_int(int(total))}")

    return "\n".join(lines)


def _media_idade(df: pd.DataFrame, data_inicio: Any, data_fim_exclusiva: Any) -> str:
    if "idade" not in df.columns:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    idade = pd.to_numeric(df["idade"], errors="coerce").dropna()
    if idade.empty:
        return "Não há idades válidas para calcular a média."

    return "\n".join(
        [
            f"Média de idade dos atendimentos: {_format_number(float(idade.mean()))} anos.",
            _period_text(data_inicio, data_fim_exclusiva),
        ]
    )


def _total_geral_valor_aprovado(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    if "valor_aprovado" not in df.columns:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    total = float(_numeric_series(df, "valor_aprovado").sum())
    return "\n".join(
        [
            f"Total geral de valor aprovado: R$ {_format_number(total)}.",
            _period_text(data_inicio, data_fim_exclusiva),
        ]
    )


def _contagem_registros(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    return "\n".join(
        [
            f"Contagem de registros: {_format_int(len(df))}.",
            _period_text(data_inicio, data_fim_exclusiva),
        ]
    )


def _ranking_basico(
    df: pd.DataFrame,
    prompt: str,
    data_inicio: Any,
    data_fim_exclusiva: Any,
    limit: int = 10,
) -> str:
    dimensions = {
        "municipio": "cod_municipio_atendido",
        "unidade": "cod_unidade",
        "sexo": "sexo",
    }
    dimension_display = {
        "municipio": "município",
        "unidade": "unidade",
        "sexo": "sexo",
    }
    metrics = {
        "valor aprovado": "valor_aprovado",
        "frequencia": "frequencia",
        "quantidade apresentada": "quantidade_apresentada",
        "valor apresentado": "valor_apresentado",
    }
    metric_display = {
        "valor aprovado": "valor aprovado",
        "frequencia": "frequência",
        "quantidade apresentada": "quantidade apresentada",
        "valor apresentado": "valor apresentado",
    }

    dimension_label = next(
        (label for label in dimensions if label in prompt),
        None,
    )
    metric_label = next(
        (label for label in metrics if label in prompt),
        "valor aprovado",
    )

    if dimension_label is None:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    dimension_column = dimensions[dimension_label]
    metric_column = metrics[metric_label]
    if not _has_columns(df, [dimension_column, metric_column]):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    working_df = df[[dimension_column, metric_column]].copy()
    working_df[metric_column] = _numeric_series(working_df, metric_column)
    result = (
        working_df.groupby(dimension_column, dropna=False)[metric_column]
        .sum()
        .sort_values(ascending=False)
        .head(limit)
    )

    lines = [
        (
            f"Ranking por {dimension_display[dimension_label]} "
            f"usando {metric_display[metric_label]}:"
        ),
        _period_text(data_inicio, data_fim_exclusiva),
    ]
    for position, (group_value, total) in enumerate(result.items(), start=1):
        if metric_column.startswith("valor"):
            formatted_total = f"R$ {_format_number(float(total))}"
        else:
            formatted_total = _format_int(int(total))
        lines.append(f"{position}. {group_value}: {formatted_total}")

    return "\n".join(lines)


def executar_pergunta_estatistica_simples(
    df: pd.DataFrame,
    prompt_usuario: str,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    """Responde perguntas estatisticas conhecidas usando apenas pandas local."""
    prompt = _normalize_prompt(prompt_usuario)

    if "ranking" in prompt or "rankings" in prompt or "top" in prompt:
        return _ranking_basico(df, prompt, data_inicio, data_fim_exclusiva)

    if "valor aprovado" in prompt and "municipio" in prompt:
        return _total_valor_aprovado_por_municipio(df, data_inicio, data_fim_exclusiva)

    if "frequencia" in prompt and "sexo" in prompt:
        return _frequencia_por_sexo(df, data_inicio, data_fim_exclusiva)

    if "unidade" in prompt and (
        "quantidade apresentada" in prompt
        or "maior" in prompt
        or "ranking" in prompt
    ):
        return _ranking_unidades_por_quantidade(df, data_inicio, data_fim_exclusiva)

    if "media" in prompt and "idade" in prompt:
        return _media_idade(df, data_inicio, data_fim_exclusiva)

    if "valor aprovado" in prompt and ("total" in prompt or "soma" in prompt):
        return _total_geral_valor_aprovado(df, data_inicio, data_fim_exclusiva)

    if (
        "contagem" in prompt
        or "quantidade de registros" in prompt
        or "total de registros" in prompt
        or "numero de registros" in prompt
    ):
        return _contagem_registros(df, data_inicio, data_fim_exclusiva)

    if "maiores" in prompt or "maior" in prompt:
        return _ranking_basico(df, prompt, data_inicio, data_fim_exclusiva)

    return SIMPLE_STATS_UNAVAILABLE_MESSAGE


def executar_pergunta_simples(
    df: pd.DataFrame,
    prompt_usuario: str,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    """Alias publico para o modo estatistico simples sem LLM."""
    return executar_pergunta_estatistica_simples(
        df,
        prompt_usuario,
        data_inicio,
        data_fim_exclusiva,
    )
