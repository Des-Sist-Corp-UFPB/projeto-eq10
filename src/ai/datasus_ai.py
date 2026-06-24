"""Entrada publica da camada isolada de IA para SIA/DATASUS."""

from __future__ import annotations

import os
from pathlib import Path

from src.ai.data_provider import load_controlled_datasus_dataframe
from src.ai.month_checker import validar_mes_solicitado_no_prompt
from src.ai.prompt_guard import validar_prompt
from src.ai.query_logger import log_ai_question
from src.ai.simple_stats_runner import (
    SIMPLE_STATS_UNAVAILABLE_MESSAGE,
    executar_pergunta_simples,
)

GENERIC_AI_ERROR_MESSAGE = (
    "Não foi possível processar a pergunta. Verifique a configuração da camada de IA."
)
LLM_SIMPLE_FALLBACK_NOTICE = (
    "O modelo de IA não pôde ser usado por limite ou crédito da API. "
    "Respondi usando o modo estatístico simples."
)

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_env_files() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() == "test":
        return

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


def is_llm_enabled() -> bool:
    _load_env_files()
    return _is_env_flag_enabled("AI_USE_LLM", default=True)


def is_simple_fallback_enabled() -> bool:
    _load_env_files()
    return _is_env_flag_enabled("AI_FALLBACK_TO_SIMPLE", default=True)


def _responder_modo_simples(df, prompt_usuario, data_inicio, data_fim_exclusiva) -> str:
    return executar_pergunta_simples(
        df,
        prompt_usuario,
        data_inicio,
        data_fim_exclusiva,
    )


def _try_responder_modo_simples(
    df,
    prompt_usuario,
    data_inicio,
    data_fim_exclusiva,
) -> str | None:
    resposta = _responder_modo_simples(
        df,
        prompt_usuario,
        data_inicio,
        data_fim_exclusiva,
    )
    if resposta == SIMPLE_STATS_UNAVAILABLE_MESSAGE:
        return None

    return resposta


def perguntar_datasus(prompt_usuario: str, user_context: dict | None = None) -> str:
    """Recebe uma pergunta sobre dados SIA/DATASUS sem acionar a ETL principal.

    Args:
        prompt_usuario: O texto da pergunta do usuario.
        user_context: Dicionario com id, nome, email e role do usuario autenticado
                      (de get_authenticated_user()). Usado para auditoria.
    """
    user_id = int(user_context["id"]) if user_context and user_context.get("id") else None
    user_email = user_context.get("email") if user_context else None

    valido, mensagem = validar_prompt(prompt_usuario)

    if not valido:
        log_ai_question(prompt_usuario, status="bloqueado_prompt", detail=mensagem)
        # Auditoria: prompt bloqueado pelo prompt_guard
        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_PROMPT_GUARD_BLOCK
            AuditLogService.from_environment().log_event(
                EVENT_PROMPT_GUARD_BLOCK,
                user_id=user_id,
                user_email=user_email,
                prompt_text=prompt_usuario,
                detalhe=mensagem,
            )
        except Exception:
            pass
        return mensagem

    mes_valido, mensagem_mes = validar_mes_solicitado_no_prompt(prompt_usuario)

    if not mes_valido:
        log_ai_question(
            prompt_usuario,
            status="bloqueado_mes_indisponivel",
            detail=mensagem_mes,
        )
        return mensagem_mes

    try:
        df, data_inicio, data_fim_exclusiva = load_controlled_datasus_dataframe()
    except Exception as exc:
        log_ai_question(prompt_usuario, status="erro_banco", detail=type(exc).__name__)
        return GENERIC_AI_ERROR_MESSAGE

    if df.empty:
        mensagem_sem_dados = (
            "Ainda não há dados disponíveis no sistema para análise estatística."
        )
        log_ai_question(prompt_usuario, status="sem_dados", detail=mensagem_sem_dados)
        return mensagem_sem_dados

    try:
        resposta_simples = _try_responder_modo_simples(
            df,
            prompt_usuario,
            data_inicio,
            data_fim_exclusiva,
        )
    except Exception as exc:
        log_ai_question(
            prompt_usuario,
            status="erro_modo_simples",
            detail=type(exc).__name__,
        )
        resposta_simples = None

    if resposta_simples is not None:
        log_ai_question(prompt_usuario, status="respondido_modo_simples")
        # Auditoria: prompt respondido
        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_CHAT_PROMPT
            AuditLogService.from_environment().log_event(
                EVENT_CHAT_PROMPT,
                user_id=user_id,
                user_email=user_email,
                prompt_text=prompt_usuario,
                detalhe="modo_simples",
            )
        except Exception:
            pass
        return resposta_simples

    if not is_llm_enabled():
        try:
            resposta = _responder_modo_simples(
                df,
                prompt_usuario,
                data_inicio,
                data_fim_exclusiva,
            )
        except Exception as exc:
            log_ai_question(
                prompt_usuario,
                status="erro_modo_simples",
                detail=type(exc).__name__,
            )
            return GENERIC_AI_ERROR_MESSAGE

        status = (
            "pergunta_fora_escopo_modo_simples"
            if resposta == SIMPLE_STATS_UNAVAILABLE_MESSAGE
            else "respondido_modo_simples"
        )
        log_ai_question(prompt_usuario, status=status)
        return resposta

    try:
        from src.ai.pandasai_runner import LLMRateLimitError, executar_pergunta_com_pandasai

        resposta = executar_pergunta_com_pandasai(
            df,
            prompt_usuario,
            data_inicio,
            data_fim_exclusiva,
        )
    except LLMRateLimitError as exc:
        mensagem_erro = str(exc)
        if not is_simple_fallback_enabled():
            log_ai_question(
                prompt_usuario,
                status="erro_limite_llm",
                detail=mensagem_erro,
            )
            return mensagem_erro

        try:
            resposta_simples = _responder_modo_simples(
                df,
                prompt_usuario,
                data_inicio,
                data_fim_exclusiva,
            )
        except Exception:
            log_ai_question(
                prompt_usuario,
                status="erro_configuracao",
                detail=mensagem_erro,
            )
            return mensagem_erro

        resposta = (
            f"{LLM_SIMPLE_FALLBACK_NOTICE}\n\n"
            "Resposta em modo estatístico simples:\n"
            f"{resposta_simples}"
        )
        log_ai_question(
            prompt_usuario,
            status="respondido_modo_simples_rate_limit",
            detail=mensagem_erro,
        )
        return resposta
    except RuntimeError as exc:
        mensagem_erro = str(exc)
        log_ai_question(prompt_usuario, status="erro_configuracao", detail=mensagem_erro)
        return mensagem_erro
    except Exception as exc:
        log_ai_question(prompt_usuario, status="erro_llm", detail=type(exc).__name__)
        return GENERIC_AI_ERROR_MESSAGE

    log_ai_question(prompt_usuario, status="respondido")
    # Auditoria: prompt respondido pelo LLM
    try:
        from src.audit.audit_log_service import AuditLogService, EVENT_CHAT_PROMPT
        AuditLogService.from_environment().log_event(
            EVENT_CHAT_PROMPT,
            user_id=user_id,
            user_email=user_email,
            prompt_text=prompt_usuario,
            detalhe="llm",
        )
    except Exception:
        pass
    return resposta
