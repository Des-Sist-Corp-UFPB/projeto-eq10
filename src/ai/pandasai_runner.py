"""Execucao experimental e controlada do PandasAI sobre DataFrame ja validado."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

DEFAULT_LLM_MODEL = "gpt-4.1-mini"
MISSING_LLM_KEY_MESSAGE = "Configuração incompleta da IA: chave do modelo ausente."
PANDASAI_IMPORT_ERROR_MESSAGE = (
    "Dependências da IA não instaladas. Instale pandasai e pandasai-litellm."
)
PANDASAI_LITELLM_ERROR_MESSAGE = (
    "Erro ao executar PandasAI/LiteLLM. Verifique chave, modelo e dependências da IA."
)

BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return

    load_dotenv(BASE_DIR / ".env")
    load_dotenv(BASE_DIR / "config" / ".env")


def _is_safe_debug_enabled() -> bool:
    return (os.getenv("AI_DEBUG_SAFE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_llm_config() -> tuple[str, str]:
    _load_env_files()

    model = os.getenv("AI_LLM_MODEL") or DEFAULT_LLM_MODEL
    ai_api_key = os.getenv("AI_LLM_API_KEY")

    if ai_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = ai_api_key

    api_key = ai_api_key or os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(MISSING_LLM_KEY_MESSAGE)

    return model, api_key


def _build_pandasai_litellm_error_message(error: Exception) -> str:
    if _is_safe_debug_enabled():
        return f"{PANDASAI_LITELLM_ERROR_MESSAGE} Tipo: {type(error).__name__}"

    return PANDASAI_LITELLM_ERROR_MESSAGE


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
        return str(resposta)
    except Exception as exc:
        logger.warning("Erro seguro PandasAI/LiteLLM | tipo=%s", type(exc).__name__)
        raise RuntimeError(_build_pandasai_litellm_error_message(exc)) from exc
    finally:
        _clear_pandasai_context(pai, pandasai_df)
