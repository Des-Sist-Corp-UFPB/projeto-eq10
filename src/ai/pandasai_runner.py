"""Execucao experimental e controlada do PandasAI sobre DataFrame ja validado."""

from __future__ import annotations

import logging
import os
import sys
from numbers import Number
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_LLM_MODEL = "gpt-4.1-mini"
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_GEMINI_MODEL = "gemini/gemini-2.0-flash"
DEFAULT_OPENROUTER_MODEL = "openrouter/openrouter/free"
MISSING_LLM_KEY_MESSAGE = "Configuração incompleta da IA: chave do modelo ausente."
UNSUPPORTED_LLM_PROVIDER_MESSAGE = (
    "Provedor de IA não suportado. Use openai, gemini ou openrouter."
)
INVALID_OPENROUTER_MODEL_MESSAGE = (
    "Configuração inválida da IA: modelo OpenRouter deve começar com openrouter/."
)
PANDASAI_IMPORT_ERROR_MESSAGE = (
    "Dependências da IA não instaladas. Instale pandasai e pandasai-litellm."
)
PANDASAI_LITELLM_ERROR_MESSAGE = (
    "Erro ao executar PandasAI/LiteLLM. Verifique chave, modelo e dependências da IA."
)
PANDASAI_NO_RESULT_ERROR_MESSAGE = (
    "A IA calculou a consulta, mas não retornou o resultado no formato esperado. "
    "Tente novamente ou use uma pergunta estatística mais direta."
)
LLM_RECOVERABLE_ERROR_MESSAGE = (
    "A chamada ao provedor de IA não pôde ser concluída por limite ou crédito da API. "
    "Defina AI_USE_LLM=false para usar o modo estatístico simples local."
)
LLM_RATE_LIMIT_ERROR_MESSAGE = LLM_RECOVERABLE_ERROR_MESSAGE

BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
_ORIGINAL_LOG_RECORD_FACTORY = logging.getLogRecordFactory()
_SAFE_LOG_RECORD_FACTORY_READY = False
_SPECIAL_CHAR_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u200b": "",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2022": "-",
        "\u2026": "...",
        "\u202f": " ",
        "\u2212": "-",
        "\ufeff": "",
    }
)


class _SafeLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize_log_text(record.msg)

        if isinstance(record.args, tuple):
            record.args = tuple(_sanitize_log_text(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: _sanitize_log_text(value) for key, value in record.args.items()
            }

        return True


class LLMRecoverableError(RuntimeError):
    """Erro seguro para limite, credito, billing ou indisponibilidade de API."""


class LLMRateLimitError(LLMRecoverableError):
    """Alias compativel para erros de limite da API de IA."""


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return

    load_dotenv(BASE_DIR / ".env")
    load_dotenv(BASE_DIR / "config" / ".env")


def _is_env_flag_enabled(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().strip("\"'").lower() in {"1", "true", "yes", "on"}


def _is_safe_debug_enabled() -> bool:
    return _is_env_flag_enabled("AI_DEBUG_SAFE", default=False)


def _sanitize_log_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    return value.translate(_SPECIAL_CHAR_TRANSLATION)


def _sanitize_log_args(args: Any) -> Any:
    if isinstance(args, tuple):
        return tuple(_sanitize_log_text(arg) for arg in args)

    if isinstance(args, dict):
        return {key: _sanitize_log_text(value) for key, value in args.items()}

    return _sanitize_log_text(args)


def _install_safe_log_record_factory() -> None:
    global _SAFE_LOG_RECORD_FACTORY_READY

    if _SAFE_LOG_RECORD_FACTORY_READY:
        return

    def safe_record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = _ORIGINAL_LOG_RECORD_FACTORY(*args, **kwargs)
        record.msg = _sanitize_log_text(record.msg)
        record.args = _sanitize_log_args(record.args)
        return record

    logging.setLogRecordFactory(safe_record_factory)
    _SAFE_LOG_RECORD_FACTORY_READY = True


def _configure_safe_pandasai_logging() -> None:
    _install_safe_log_record_factory()

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    safe_filter = _SafeLogFilter()
    internal_logger_names = (
        "pandasai",
        "pandasai.helpers",
        "pandasai.helpers.logger",
        "pandasai_litellm",
        "litellm",
        "LiteLLM",
    )
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, _SafeLogFilter) for item in handler.filters):
            handler.addFilter(safe_filter)

    for logger_name in (__name__, *internal_logger_names):
        target_logger = logging.getLogger(logger_name)
        if not any(isinstance(item, _SafeLogFilter) for item in target_logger.filters):
            target_logger.addFilter(safe_filter)

        if logger_name != __name__:
            target_logger.setLevel(logging.CRITICAL)
            target_logger.propagate = False
            if not any(isinstance(item, logging.NullHandler) for item in target_logger.handlers):
                target_logger.addHandler(logging.NullHandler())


def is_llm_enabled() -> bool:
    _load_env_files()
    return _is_env_flag_enabled("AI_USE_LLM", default=True)


def is_simple_fallback_enabled() -> bool:
    _load_env_files()
    return _is_env_flag_enabled("AI_FALLBACK_TO_SIMPLE", default=True)


def _provider_name() -> str:
    return (os.getenv("AI_LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()


def _normalize_gemini_model(model: str | None) -> str:
    selected_model = (model or DEFAULT_GEMINI_MODEL).strip()
    if not selected_model:
        selected_model = DEFAULT_GEMINI_MODEL

    if selected_model.startswith("gemini/"):
        return selected_model

    return f"gemini/{selected_model}"


def _normalize_openrouter_model(model: str | None) -> str:
    selected_model = (model or DEFAULT_OPENROUTER_MODEL).strip()
    if not selected_model:
        selected_model = DEFAULT_OPENROUTER_MODEL

    if not selected_model.startswith("openrouter/"):
        raise RuntimeError(INVALID_OPENROUTER_MODEL_MESSAGE)

    return selected_model


def _get_llm_config() -> tuple[str, str]:
    _load_env_files()

    provider = _provider_name()

    if provider == "gemini":
        model = _normalize_gemini_model(os.getenv("AI_LLM_MODEL"))
        ai_api_key = os.getenv("AI_LLM_API_KEY")
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        api_key = ai_api_key or gemini_api_key

        if ai_api_key and not gemini_api_key:
            os.environ["GEMINI_API_KEY"] = ai_api_key
    elif provider == "openrouter":
        model = _normalize_openrouter_model(os.getenv("AI_LLM_MODEL"))
        ai_api_key = os.getenv("AI_LLM_API_KEY")
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        api_key = ai_api_key or openrouter_api_key

        if ai_api_key and not openrouter_api_key:
            os.environ["OPENROUTER_API_KEY"] = ai_api_key
    elif provider == "openai":
        model = os.getenv("AI_LLM_MODEL") or DEFAULT_LLM_MODEL
        ai_api_key = os.getenv("AI_LLM_API_KEY")
        openai_api_key = os.getenv("OPENAI_API_KEY")
        api_key = ai_api_key or openai_api_key

        if ai_api_key and not openai_api_key:
            os.environ["OPENAI_API_KEY"] = ai_api_key
    else:
        raise RuntimeError(UNSUPPORTED_LLM_PROVIDER_MESSAGE)

    if not api_key:
        raise RuntimeError(MISSING_LLM_KEY_MESSAGE)

    return model, api_key


def _build_pandasai_litellm_error_message(error: Exception) -> str:
    if _is_safe_debug_enabled():
        return f"{PANDASAI_LITELLM_ERROR_MESSAGE} Tipo: {type(error).__name__}"

    return PANDASAI_LITELLM_ERROR_MESSAGE


def _build_no_result_error_message(error: Exception) -> str:
    no_result_error = _find_chained_error(error, "NoResultFoundError") or error
    if _is_safe_debug_enabled():
        return f"{PANDASAI_NO_RESULT_ERROR_MESSAGE} Tipo: {type(no_result_error).__name__}"

    return PANDASAI_NO_RESULT_ERROR_MESSAGE


def _error_chain(error: BaseException):
    current: BaseException | None = error
    while current is not None:
        yield current
        current = current.__cause__ or current.__context__


def _find_chained_error(error: BaseException, class_name: str) -> BaseException | None:
    for chained_error in _error_chain(error):
        if type(chained_error).__name__ == class_name:
            return chained_error

    return None


def _is_no_result_error(error: Exception) -> bool:
    return _find_chained_error(error, "NoResultFoundError") is not None


def _is_recoverable_llm_error(error: Exception) -> bool:
    indicators = (
        "ratelimit",
        "rate_limit",
        "rate limit",
        "quota",
        "exceeded",
        "credit",
        "crédito",
        "credito",
        "billing",
        "insufficient",
        "unavailable",
        "temporarily",
        "temporary",
        "timeout",
        "serviceunavailable",
        "service unavailable",
    )

    for chained_error in _error_chain(error):
        class_name = type(chained_error).__name__.replace("_", "").lower()
        message = str(chained_error).lower()
        haystack = f"{class_name} {message}"
        if any(indicator in haystack for indicator in indicators):
            return True

    return False


def _build_recoverable_error_message(error: Exception) -> str:
    if _is_safe_debug_enabled():
        return f"{LLM_RECOVERABLE_ERROR_MESSAGE} Tipo: {type(error).__name__}"

    return LLM_RECOVERABLE_ERROR_MESSAGE


def _format_portuguese_number(value: int | float) -> str:
    formatted = f"{float(value):,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_currency(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _clean_output_text(value)

    if pd.isna(number):
        return "0,00"

    return _format_portuguese_number(number)


def _clean_output_text(value: Any) -> str:
    text = _sanitize_log_text(str(value)).strip()
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _find_dataframe_column(value: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    normalized_columns = {str(column).lower(): column for column in value.columns}
    for candidate in candidates:
        if candidate in normalized_columns:
            return normalized_columns[candidate]

    return None


def _format_valor_aprovado_por_municipio(value: pd.DataFrame) -> str | None:
    municipio_column = _find_dataframe_column(
        value,
        ("municipio", "cod_municipio_atendido"),
    )
    total_column = _find_dataframe_column(
        value,
        ("total_valor_aprovado", "valor_aprovado"),
    )

    if municipio_column is None or total_column is None:
        return None

    lines = ["Total de valor aprovado por município:"]
    for position, row in enumerate(value.itertuples(index=False), start=1):
        row_data = dict(zip(value.columns, row, strict=False))
        municipio = _clean_output_text(row_data[municipio_column])
        total = _format_currency(row_data[total_column])
        lines.append(f"{position}. {municipio}: R$ {total}")

    return "\n".join(lines)


def _format_dataframe_response(value: pd.DataFrame) -> str:
    if value.empty:
        return "Sem resultados para exibir."

    formatted_by_metric = _format_valor_aprovado_por_municipio(value)
    if formatted_by_metric:
        return formatted_by_metric

    return _sanitize_log_text(value.to_string(index=False))


def _format_series_response(value: pd.Series) -> str:
    if value.empty:
        return "Sem resultados para exibir."

    return _sanitize_log_text(value.to_string())


def _format_response_value(value: Any) -> str:
    if isinstance(value, pd.DataFrame):
        return _format_dataframe_response(value)

    if isinstance(value, pd.Series):
        return _format_series_response(value)

    if isinstance(value, Number) and not isinstance(value, bool):
        return _format_portuguese_number(value)

    return _clean_output_text(value)


def _postprocess_pandasai_response(response: Any) -> str:
    if isinstance(response, dict):
        if "value" in response:
            return _format_response_value(response["value"])

        return "\n".join(
            f"{key}: {_format_response_value(value)}"
            for key, value in response.items()
        )

    return _format_response_value(response)


def _build_prompt(prompt_usuario: str, data_inicio: Any, data_fim_exclusiva: Any) -> str:
    return f"""
Você é uma IA de análise estatística dos dados SIA/DATASUS.
Use apenas o DataFrame fornecido.
Responda apenas perguntas estatísticas.
Nunca invente dados.
Nunca diga que consultou fontes externas.
Nunca gere instruções para escrita em banco.
Nunca modifique banco, código, arquivos ou estrutura do sistema.
Nunca tente acessar .env, senhas, tokens ou credenciais.
Nunca responda fora do período disponível.
Se os dados não forem suficientes, informe isso claramente.
Responda em português brasileiro.
Sempre informe o período analisado: {data_inicio} até antes de {data_fim_exclusiva}.

Regras obrigatorias para retorno do codigo PandasAI:
- Use apenas caracteres ASCII simples em comentarios e strings auxiliares do codigo.
- Nao use caracteres Unicode especiais, hifen especial, aspas curvas ou espaco estreito.
- Use hifen normal "-", aspas retas e espaco normal.
- Sempre atribua a resposta final a uma variavel chamada result.
- result deve ser um dicionario no formato:
  result = {{"type": "string", "value": "..."}}
  result = {{"type": "number", "value": 123}}
  result = {{"type": "dataframe", "value": dataframe_resultante}}
- Nunca use apenas print(output).
- Nunca use uma variavel chamada output como resposta final.
- Se criar uma variavel auxiliar chamada output, no final obrigatoriamente faca:
  result = output
- Nao deixe a resposta apenas impressa no console.
- A ultima resposta deve estar em result.

Pergunta do usuário:
{prompt_usuario}
""".strip()


def _clear_pandasai_context(pai: Any, pandasai_df: Any) -> None:
    for target in (pandasai_df, getattr(pandasai_df, "agent", None), pai):
        if target is None:
            continue

        for method_name in ("clear_memory", "reset_memory", "clear_cache"):
            method = getattr(target, method_name, None)
            if callable(method):
                method()
                return


def executar_pergunta_com_pandasai(
    df,
    prompt_usuario: str,
    data_inicio,
    data_fim_exclusiva,
) -> str:
    """Executa PandasAI apenas sobre o DataFrame controlado recebido."""
    _configure_safe_pandasai_logging()
    model, api_key = _get_llm_config()

    try:
        import pandasai as pai
        from pandasai_litellm.litellm import LiteLLM
    except ModuleNotFoundError as exc:
        raise RuntimeError(PANDASAI_IMPORT_ERROR_MESSAGE) from exc

    pandasai_df = None

    try:
        llm = LiteLLM(model=model, api_key=api_key)
        pai.config.set({"llm": llm})

        # PandasAI v3 recomenda pai.DataFrame e pai.config.set({"llm": llm}).
        # O DataFrame recebido aqui ja foi limitado e filtrado por data_provider.py.
        pandasai_df = pai.DataFrame(df.copy())
        prompt_com_regras = _build_prompt(prompt_usuario, data_inicio, data_fim_exclusiva)
        resposta = pandasai_df.chat(prompt_com_regras)
        return _postprocess_pandasai_response(resposta)
    except Exception as exc:
        logger.warning("Erro seguro PandasAI/LiteLLM | tipo=%s", type(exc).__name__)
        if _is_no_result_error(exc):
            raise RuntimeError(_build_no_result_error_message(exc)) from exc
        if _is_recoverable_llm_error(exc):
            raise LLMRateLimitError(_build_recoverable_error_message(exc)) from exc
        raise RuntimeError(_build_pandasai_litellm_error_message(exc)) from exc
    finally:
        _clear_pandasai_context(pai, pandasai_df)
