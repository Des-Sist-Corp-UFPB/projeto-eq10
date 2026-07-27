"""Entrada publica da camada isolada de IA para SIA/DATASUS."""

from __future__ import annotations

import os
from pathlib import Path

from src.ai.data_provider import load_controlled_datasus_dataframe
from src.ai.month_checker import validar_mes_solicitado_no_prompt
from src.ai.read_only_datasus import (
    classify_analytical_database_failure,
    get_analytical_database_diagnostic,
)
from src.ai.prompt_policy import BLOCK_MESSAGE, PromptDecision, classify_prompt
from src.ai.query_logger import log_ai_pipeline, log_ai_question, safe_prompt_for_log
from src.ai.simple_stats_runner import (
    SIMPLE_STATS_UNAVAILABLE_MESSAGE,
    executar_pergunta_simples,
)

GENERIC_AI_ERROR_MESSAGE = (
    "Ocorreu um erro operacional ao processar a consulta. Tente novamente."
)
DATABASE_UNAVAILABLE_MESSAGE = (
    "Não foi possível acessar a base analítica no momento. Tente novamente mais tarde."
)
ENGINE_UNAVAILABLE_MESSAGE = (
    "O motor de análise não está disponível no momento e esta consulta não possui "
    "fallback estatístico local."
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


def _responder_modo_simples(
    df,
    prompt_usuario,
    data_inicio,
    data_fim_exclusiva,
    decision: PromptDecision | None = None,
) -> str:
    return executar_pergunta_simples(
        df,
        prompt_usuario,
        data_inicio,
        data_fim_exclusiva,
        decision,
    )


def _try_responder_modo_simples(
    df,
    prompt_usuario,
    data_inicio,
    data_fim_exclusiva,
    decision: PromptDecision | None = None,
) -> str | None:
    resposta = _responder_modo_simples(
        df,
        prompt_usuario,
        data_inicio,
        data_fim_exclusiva,
        decision,
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

    decision = classify_prompt(prompt_usuario)

    def log_pipeline(final_decision: str, validation: str | None = None) -> None:
        log_ai_pipeline(
            prompt_usuario,
            detected_intent=decision.intent,
            guard_decision="allowed" if decision.allowed else "blocked",
            validation_decision=validation or decision.reason,
            query_generated=decision.query_plan,
            final_decision=final_decision,
        )

    if not decision.allowed:
        log_ai_question(prompt_usuario, status="bloqueado_prompt", detail=decision.reason)
        log_pipeline("blocked")
        # Auditoria: prompt bloqueado pelo prompt_guard
        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_PROMPT_GUARD_BLOCK
            AuditLogService.from_environment().log_event(
                EVENT_PROMPT_GUARD_BLOCK,
                user_id=user_id,
                user_email=user_email,
                prompt_text=safe_prompt_for_log(prompt_usuario),
                detalhe=decision.reason,
            )
        except Exception:
            pass
        return BLOCK_MESSAGE

    mes_valido, mensagem_mes = validar_mes_solicitado_no_prompt(prompt_usuario)

    if not mes_valido:
        log_ai_question(
            prompt_usuario,
            status="bloqueado_mes_indisponivel",
            detail=mensagem_mes,
        )
        log_pipeline("blocked_month", "month_outside_available_window")
        return mensagem_mes

    try:
        df, data_inicio, data_fim_exclusiva = load_controlled_datasus_dataframe()
    except Exception as exc:
        failure_category = classify_analytical_database_failure(exc)
        get_analytical_database_diagnostic(connection_error=exc)
        log_ai_question(prompt_usuario, status="erro_banco", detail=failure_category)
        log_pipeline("data_access_error", failure_category)
        return DATABASE_UNAVAILABLE_MESSAGE

    if df.empty:
        mensagem_sem_dados = (
            "Ainda não há dados disponíveis no sistema para análise estatística."
        )
        log_ai_question(prompt_usuario, status="sem_dados", detail=mensagem_sem_dados)
        log_pipeline("empty_dataframe", "no_available_data")
        return mensagem_sem_dados

    try:
        resposta_simples = _try_responder_modo_simples(
            df,
            prompt_usuario,
            data_inicio,
            data_fim_exclusiva,
            decision,
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
        log_pipeline("answered_simple")
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
                decision,
            )
        except Exception as exc:
            log_ai_question(
                prompt_usuario,
                status="erro_modo_simples",
                detail=type(exc).__name__,
            )
            log_pipeline("simple_execution_error", "simple_runner_failed")
            return GENERIC_AI_ERROR_MESSAGE

        status = (
            "pergunta_fora_escopo_modo_simples"
            if resposta == SIMPLE_STATS_UNAVAILABLE_MESSAGE
            else "respondido_modo_simples"
        )
        log_ai_question(prompt_usuario, status=status)
        log_pipeline(status)
        return resposta

    try:
        from src.ai.pandasai_runner import LLMRateLimitError, executar_pergunta_com_pandasai

        resposta = executar_pergunta_com_pandasai(
            df,
            prompt_usuario,
            data_inicio,
            data_fim_exclusiva,
            decision,
        )
    except LLMRateLimitError as exc:
        mensagem_erro = str(exc)
        if not is_simple_fallback_enabled():
            log_ai_question(
                prompt_usuario,
                status="erro_limite_llm",
                detail="llm_unavailable",
            )
            log_pipeline("engine_unavailable", "llm_unavailable")
            return ENGINE_UNAVAILABLE_MESSAGE

        try:
            resposta_simples = _responder_modo_simples(
                df,
                prompt_usuario,
            data_inicio,
            data_fim_exclusiva,
            decision,
            )
        except Exception:
            log_ai_question(
                prompt_usuario,
                status="erro_configuracao",
                detail=mensagem_erro,
            )
            log_pipeline("engine_unavailable", "simple_fallback_failed")
            return ENGINE_UNAVAILABLE_MESSAGE

        if resposta_simples == SIMPLE_STATS_UNAVAILABLE_MESSAGE:
            log_ai_question(prompt_usuario, status="erro_motor_sem_fallback")
            log_pipeline("engine_unavailable", "no_supported_fallback")
            return ENGINE_UNAVAILABLE_MESSAGE

        resposta = (
            f"{LLM_SIMPLE_FALLBACK_NOTICE}\n\n"
            "Resposta em modo estatístico simples:\n"
            f"{resposta_simples}"
        )
        log_ai_question(
            prompt_usuario,
            status="respondido_modo_simples_rate_limit",
            detail="llm_unavailable",
        )
        log_pipeline("answered_simple_fallback", "llm_unavailable")
        return resposta
    except RuntimeError as exc:
        log_ai_question(prompt_usuario, status="erro_motor", detail=type(exc).__name__)
        log_pipeline("engine_unavailable", "llm_runtime_error")
        return ENGINE_UNAVAILABLE_MESSAGE
    except Exception as exc:
        log_ai_question(prompt_usuario, status="erro_llm", detail=type(exc).__name__)
        log_pipeline("unexpected_operational_error", "unexpected_llm_error")
        return GENERIC_AI_ERROR_MESSAGE

    log_ai_question(prompt_usuario, status="respondido")
    log_pipeline("answered_llm")
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
