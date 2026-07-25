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
    municipio_column: str = "municipio_atendimento",
    municipio_display: str = "município de atendimento",
) -> str:
    if not _has_columns(df, [municipio_column, "valor_aprovado"]):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    working_df = df[[municipio_column, "valor_aprovado"]].copy()
    working_df["valor_aprovado"] = _numeric_series(working_df, "valor_aprovado")
    result = (
        working_df.groupby(municipio_column, dropna=False)["valor_aprovado"]
        .sum()
        .sort_values(ascending=False)
    )

    lines = [
        f"Total de valor aprovado por {municipio_display}:",
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
    if not _has_columns(df, ["unidade", "quantidade_apresentada"]):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    working_df = df[["unidade", "quantidade_apresentada"]].copy()
    working_df["quantidade_apresentada"] = _numeric_series(
        working_df,
        "quantidade_apresentada",
    )
    result = (
        working_df.groupby("unidade", dropna=False)["quantidade_apresentada"]
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


def _media_idade_por_dimensao(
    df: pd.DataFrame,
    dimension_column: str,
    dimension_display: str,
    data_inicio: Any,
    data_fim_exclusiva: Any,
    limit: int = 10,
) -> str:
    if not _has_columns(df, [dimension_column, "idade"]):
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    working_df = df[[dimension_column, "idade"]].copy()
    working_df["idade"] = pd.to_numeric(working_df["idade"], errors="coerce")
    working_df = working_df.dropna(subset=["idade"])
    if working_df.empty:
        return "Não há idades válidas para calcular a média."

    result = (
        working_df.groupby(dimension_column, dropna=False)["idade"]
        .mean()
        .sort_values(ascending=False)
        .head(limit)
    )

    lines = [
        f"Média de idade por {dimension_display}:",
        _period_text(data_inicio, data_fim_exclusiva),
    ]
    for group_value, media in result.items():
        lines.append(f"- {group_value}: {_format_number(float(media))} anos")

    return "\n".join(lines)


def _contagem_atendimentos_por_dimensao(
    df: pd.DataFrame,
    dimension_column: str,
    dimension_display: str,
    data_inicio: Any,
    data_fim_exclusiva: Any,
    limit: int = 10,
) -> str:
    if dimension_column not in df.columns:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    result = (
        df.groupby(dimension_column, dropna=False)
        .size()
        .sort_values(ascending=False)
        .head(limit)
    )

    lines = [
        f"Total de atendimentos por {dimension_display}:",
        _period_text(data_inicio, data_fim_exclusiva),
    ]
    for group_value, total in result.items():
        lines.append(f"- {group_value}: {_format_int(int(total))}")

    return "\n".join(lines)


def _total_numerico(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
    column: str,
    display_name: str,
    *,
    currency: bool = False,
) -> str:
    if column not in df.columns:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    total = float(_numeric_series(df, column).sum())
    formatted_total = f"R$ {_format_number(total)}" if currency else _format_int(int(total))
    return "\n".join(
        [
            f"Total geral de {display_name}: {formatted_total}.",
            _period_text(data_inicio, data_fim_exclusiva),
        ]
    )


def _total_geral_valor_aprovado(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    return _total_numerico(
        df,
        data_inicio,
        data_fim_exclusiva,
        "valor_aprovado",
        "valor aprovado",
        currency=True,
    )


def _contagem_procedimentos(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    if "procedimento" not in df.columns:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    procedimentos = df["procedimento"].dropna().astype(str).str.strip()
    procedimentos = procedimentos[procedimentos != ""]
    total_distintos = int(procedimentos.nunique())

    return "\n".join(
        [
            f"Contagem de procedimentos distintos: {_format_int(total_distintos)}.",
            _period_text(data_inicio, data_fim_exclusiva),
        ]
    )


def _ultima_data_disponivel(
    df: pd.DataFrame,
    data_inicio: Any,
    data_fim_exclusiva: Any,
) -> str:
    if "data" not in df.columns:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    datas = pd.to_datetime(df["data"], errors="coerce").dropna()
    if datas.empty:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

    ultima_data = datas.max()
    return "\n".join(
        [
            f"Data mais recente disponivel: {ultima_data.strftime('%d/%m/%Y')}.",
            f"Mes mais recente disponivel: {ultima_data.strftime('%m/%Y')}.",
            _period_text(data_inicio, data_fim_exclusiva),
        ]
    )


def _dimension_from_prompt(prompt: str) -> tuple[str | None, str | None]:
    if "municipio" in prompt and "residencia" in prompt:
        return "municipio_residencia", "município de residência"
    if "municipio" in prompt:
        return "municipio_atendimento", "município de atendimento"
    if "unidade" in prompt:
        return "unidade", "unidade de atendimento"
    if "procedimento" in prompt:
        return "procedimento", "procedimento"
    if "raca cor" in prompt or "raca" in prompt:
        return "raca_cor", "raça/cor"
    if "ocupacao" in prompt:
        return "ocupacao", "ocupação"
    if "sexo" in prompt:
        return "sexo", "sexo"

    return None, None


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

    dimension_column, dimension_display = _dimension_from_prompt(prompt)
    metric_label = next(
        (label for label in metrics if label in prompt),
        "valor aprovado",
    )

    if dimension_column is None or dimension_display is None:
        return SIMPLE_STATS_UNAVAILABLE_MESSAGE

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
            f"Ranking por {dimension_display} "
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
    dimension_column, dimension_display = _dimension_from_prompt(prompt)

    if "ranking" in prompt or "rankings" in prompt or "top" in prompt:
        return _ranking_basico(df, prompt, data_inicio, data_fim_exclusiva)

    if "valor aprovado" in prompt and "municipio" in prompt:
        municipio_column, municipio_display = _dimension_from_prompt(prompt)
        return _total_valor_aprovado_por_municipio(
            df,
            data_inicio,
            data_fim_exclusiva,
            municipio_column or "municipio_atendimento",
            municipio_display or "município de atendimento",
        )

    if "valor aprovado" in prompt and dimension_column is not None:
        return _ranking_basico(df, prompt, data_inicio, data_fim_exclusiva)

    if "frequencia" in prompt and "sexo" in prompt:
        return _frequencia_por_sexo(df, data_inicio, data_fim_exclusiva)

    if "unidade" in prompt and (
        "quantidade apresentada" in prompt
        or "maior" in prompt
        or "ranking" in prompt
    ):
        return _ranking_unidades_por_quantidade(df, data_inicio, data_fim_exclusiva)

    if "media" in prompt and "idade" in prompt:
        if dimension_column is not None:
            return _media_idade_por_dimensao(
                df,
                dimension_column,
                dimension_display or dimension_column,
                data_inicio,
                data_fim_exclusiva,
            )
        return _media_idade(df, data_inicio, data_fim_exclusiva)

    if (
        "ultima data" in prompt
        or "data mais recente" in prompt
        or "ultimo mes" in prompt
        or "mes mais recente" in prompt
    ):
        return _ultima_data_disponivel(df, data_inicio, data_fim_exclusiva)

    if "procedimento" in prompt and (
        "contagem" in prompt
        or "quantos" in prompt
        or "quantidade de procedimentos" in prompt
        or "numero de procedimentos" in prompt
        or "total de procedimentos" in prompt
    ):
        return _contagem_procedimentos(df, data_inicio, data_fim_exclusiva)

    if (
        dimension_column is not None
        and (
            "frequencia" in prompt
            or "quantidade apresentada" in prompt
            or "valor apresentado" in prompt
        )
    ):
        return _ranking_basico(df, prompt, data_inicio, data_fim_exclusiva)

    if (
        dimension_column is not None
        and ("atendimento" in prompt or "atendimentos" in prompt)
        and ("total" in prompt or "quantidade" in prompt or "contagem" in prompt)
    ):
        return _contagem_atendimentos_por_dimensao(
            df,
            dimension_column,
            dimension_display or dimension_column,
            data_inicio,
            data_fim_exclusiva,
        )

    if "valor aprovado" in prompt and ("total" in prompt or "soma" in prompt):
        return _total_geral_valor_aprovado(df, data_inicio, data_fim_exclusiva)

    if "valor apresentado" in prompt and ("total" in prompt or "soma" in prompt):
        return _total_numerico(
            df,
            data_inicio,
            data_fim_exclusiva,
            "valor_apresentado",
            "valor apresentado",
            currency=True,
        )

    if "quantidade apresentada" in prompt and ("total" in prompt or "soma" in prompt):
        return _total_numerico(
            df,
            data_inicio,
            data_fim_exclusiva,
            "quantidade_apresentada",
            "quantidade apresentada",
        )

    if "frequencia" in prompt and ("total" in prompt or "soma" in prompt):
        return _total_numerico(
            df,
            data_inicio,
            data_fim_exclusiva,
            "frequencia",
            "frequencia",
        )

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
