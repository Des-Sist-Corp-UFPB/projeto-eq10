"""Interface Streamlit para testar a camada de IA do SIA/DATASUS."""

from __future__ import annotations

import ast
import html
import json
import logging
import os
import re
from typing import Any

import streamlit as st

from src.analytics.umami import configure_umami, track_event, track_event_once, track_page_view
from src.observability.telemetry import configure_telemetry

configure_telemetry()

from src.auth.email_verification_service import EmailVerificationService, is_email_verification_required
from src.auth.google_oauth_service import (
    GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE,
    GOOGLE_OAUTH_INVALID_STATE_MESSAGE,
    GOOGLE_OAUTH_TARGET_PAGE_KEY,
    GoogleOAuthError,
    GoogleOAuthService,
    clear_oauth_state,
    validate_oauth_state,
)
from src.auth.roles import can_view_audit_log
from src.auth.session import can_access_chat, get_authenticated_user, login_session
from src.auth.user_service import AuthValidationError, UserService, safe_auth_exception_summary
from src.chat.chat_history_service import ChatHistoryService
from src.ui.auth_modal import close_auth_modal, open_auth_modal, render_auth_panel, set_auth_panel
from src.ui.header import render_auth_header
from src.ui.notifications import queue_toast, render_pending_toast
from src.ui.protected_chat import render_chat_auth_gate, render_chat_email_verification_gate
from src.ui.sidebar import ADMIN_PAGE, CHAT_PAGE, DEFAULT_PAGE, get_current_page, render_sidebar, set_current_page
from src.ui.styles import apply_global_light_styles
from src.ui.statistics_page import render_statistics_page
from src.ui.admin_page import render_admin_page
from src.diagnostics.health_service import HealthService, get_database_config_sources
from src.ai.prompt_policy import BLOCK_MESSAGE

APP_TITLE = "Assistente Estatístico SIA/DATASUS"
APP_SUBTITLE = "Converse com os dados disponíveis do SIA/DATASUS"
PROMPT_PLACEHOLDER = "Digite uma pergunta estatística..."
GENERIC_ERROR_MESSAGE = (
    "O motor estatístico não conseguiu concluir esta consulta agora. "
    "A pergunta foi aceita pela validação; tente novamente em alguns instantes."
)
DATA_ACCESS_ERROR_MESSAGE = (
    "Não consegui acessar os dados no momento. "
    "Tente novamente em alguns instantes."
)
EMAIL_VERIFICATION_QUERY_ERROR_MESSAGE = (
    "Nao foi possivel validar o link de verificacao agora. "
    "Tente novamente em alguns instantes."
)
GOOGLE_OAUTH_QUERY_ERROR_MESSAGE = GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE
ADMIN_ACCESS_DENIED_MESSAGE = "Voce nao tem permissao para acessar esta pagina."
UNEXPECTED_FORMAT_ERROR_MESSAGE = (
    "A camada de IA respondeu com um formato inesperado. "
    "Tente uma pergunta mais específica."
)

EXAMPLE_PROMPTS = (
    "Valor aprovado por município de atendimento",
    "Frequência total por sexo",
    "Procedimentos com maior valor aprovado",
    "Média de idade dos atendimentos",
    "Unidades com maior quantidade apresentada",
    "Valor aprovado por raça/cor",
)

logger = logging.getLogger(__name__)


@st.cache_resource(show_spinner=False)
def _log_startup_diagnostics_once() -> bool:
    """Logs safe startup routing details without exposing connection strings."""
    sources = get_database_config_sources()

    logger.info(
        "Startup diagnostics | application_db_source=%s | ai_db_source=%s | streamlit_port=%s | nginx_port=%s",
        sources["application_database"],
        sources["ai_database"],
        os.getenv("STREAMLIT_PORT") or os.getenv("STREAMLIT_SERVER_PORT") or "8501",
        os.getenv("NGINX_PORT") or "8080",
    )
    return True


@st.cache_resource(show_spinner=False)
def _get_health_service() -> HealthService:
    """Instancia o HealthService com as factories padrao."""
    return HealthService()


def _handle_healthcheck_query_param() -> None:
    """Intercepta requisicoes de heartbeat do Uptime Kuma.

    Quando a URL contem '?healthcheck=1', executa um ping SELECT 1 em ambas
    as bases de dados (autenticacao + analitico SIA) e exibe o resultado como
    JSON puro, sem renderizar o restante da interface Streamlit.

    Uptime Kuma deve ser configurado com:
      - Monitor type: HTTP(s) - Keyword
      - URL: https://seu-app.example.com/?healthcheck=1
      - Keyword esperada: '"status": "ok"'
      - Codigo de resposta esperado: 200

    Se qualquer banco de dados estiver offline, o campo 'status' sera 'error'
    e o Uptime Kuma marcara o servico como DOWN.
    """
    params = st.query_params
    if params.get("healthcheck") != "1":
        return

    import json as _json

    try:
        result = _get_health_service().run_heartbeat()
        payload = result.as_dict()
    except Exception as exc:
        payload = {
            "name": "heartbeat",
            "status": "error",
            "message": f"Heartbeat abortou com excecao inesperada: {type(exc).__name__}",
            "details": {},
        }

    st.json(payload)
    st.stop()


@st.cache_resource(show_spinner=False)
def _get_pandas_module() -> Any:
    import pandas

    return pandas


@st.cache_resource(show_spinner=False)
def _get_datasus_question_runner() -> Any:
    from src.ai.datasus_ai import perguntar_datasus

    return perguntar_datasus


@st.cache_resource(show_spinner=False)
def _get_email_verification_service() -> EmailVerificationService:
    return EmailVerificationService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_auth_user_service() -> UserService:
    return UserService.from_environment()


def _log_audit_event(evento: str, **kwargs: Any) -> None:
    try:
        from src.audit.audit_log_service import log_audit_event_safely

        log_audit_event_safely(_get_auth_user_service().engine, evento, **kwargs)
    except Exception as exc:
        logger.warning(
            "Erro seguro audit_log_app | evento=%s | causa=%s | tipo=%s",
            evento,
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )


@st.cache_resource(show_spinner=False)
def _get_google_oauth_service() -> GoogleOAuthService:
    return GoogleOAuthService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_chat_history_service() -> ChatHistoryService:
    return ChatHistoryService.from_environment()


def _can_use_chat_with_email_verification() -> bool:
    if not is_email_verification_required():
        return True

    user = get_authenticated_user(st.session_state)
    if not user:
        return False

    try:
        return _get_email_verification_service().is_email_verified(int(user["id"]))
    except Exception as exc:
        logger.warning(
            "Erro seguro verificacao_email_chat | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return False


def _chat_history_title_from_prompt(prompt: str) -> str:
    clean_prompt = _sanitize_text(prompt)
    return clean_prompt[:90] if clean_prompt else "Conversa do Chat IA"


def _get_or_create_chat_history_session_id(user_id: int, prompt: str) -> int | None:
    try:
        service = _get_chat_history_service()
        current_session_id = st.session_state.get("chat_history_session_id")
        if current_session_id:
            session = service.get_chat_session(int(current_session_id), user_id)
            if session is not None:
                return session.id

        session = service.get_or_create_active_chat_session(
            user_id,
            title=_chat_history_title_from_prompt(prompt),
        )
        st.session_state.chat_history_session_id = session.id
        return session.id
    except Exception as exc:
        logger.warning(
            "Erro seguro historico_chat | acao=obter_sessao | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return None


def _persist_chat_history_message(
    *,
    user_id: int,
    role: str,
    content: str,
    status: str = "ok",
    prompt_for_title: str = "",
) -> None:
    try:
        session_id = _get_or_create_chat_history_session_id(user_id, prompt_for_title or content)
        if not session_id:
            return
        _get_chat_history_service().add_chat_message(
            session_id,
            user_id,
            role,
            content,
            status=status,
        )
    except Exception as exc:
        logger.warning(
            "Erro seguro historico_chat | acao=salvar_mensagem | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )


def _handle_password_reset_query_param() -> None:
    raw_token = st.query_params.get("reset_password_token")
    if isinstance(raw_token, list):
        raw_token = raw_token[0] if raw_token else None
    clean_token = str(raw_token or "").strip()
    if not clean_token:
        return

    st.session_state.password_reset_token = clean_token
    set_auth_panel("reset_password", redirect_on_close=DEFAULT_PAGE)
    try:
        del st.query_params["reset_password_token"]
    except Exception as exc:
        logger.warning(
            "Erro seguro limpar_reset_password_token_query | tipo=%s",
            type(exc).__name__,
        )

def _handle_email_verification_query_param() -> None:
    raw_token = st.query_params.get("verify_email_token")
    if isinstance(raw_token, list):
        raw_token = raw_token[0] if raw_token else None
    clean_token = str(raw_token or "").strip()
    if not clean_token:
        return

    try:
        result = _get_email_verification_service().verify_email_token(clean_token)
        st.session_state.email_verification_feedback = {
            "message": result.message,
            "success": result.success,
        }
    except Exception as exc:
        logger.warning(
            "Erro seguro validar_verify_email_token | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        st.session_state.email_verification_feedback = {
            "message": EMAIL_VERIFICATION_QUERY_ERROR_MESSAGE,
            "success": False,
        }

    try:
        del st.query_params["verify_email_token"]
    except Exception as exc:
        logger.warning(
            "Erro seguro limpar_verify_email_token_query | tipo=%s",
            type(exc).__name__,
        )


def _get_query_param_value(name: str) -> str:
    raw_value = st.query_params.get(name)
    if isinstance(raw_value, list):
        raw_value = raw_value[0] if raw_value else None
    return str(raw_value or "").strip()


def _clear_google_oauth_query_params() -> None:
    for key in ("code", "state", "scope", "authuser", "prompt", "hd"):
        try:
            if key in st.query_params:
                del st.query_params[key]
        except Exception as exc:
            logger.warning(
                "Erro seguro limpar_google_oauth_query | chave=%s | tipo=%s",
                key,
                type(exc).__name__,
            )


def _handle_google_oauth_query_param() -> None:
    code = _get_query_param_value("code")
    state = _get_query_param_value("state")
    if not code and not state:
        return

    try:
        if not code or not validate_oauth_state(st.session_state, state):
            st.session_state.google_oauth_feedback = {
                "message": GOOGLE_OAUTH_INVALID_STATE_MESSAGE,
                "success": False,
            }
            return

        identity = _get_google_oauth_service().exchange_code_for_identity(code)
        user = _get_auth_user_service().authenticate_google_identity(
            google_sub=identity.sub,
            email=identity.email,
            email_verified=identity.email_verified,
            name=identity.name,
            picture=identity.picture,
        )
        login_session(st.session_state, user)
        target_page = st.session_state.pop(GOOGLE_OAUTH_TARGET_PAGE_KEY, None)
        close_auth_modal(redirect=False)
        if target_page:
            set_current_page(str(target_page))
        queue_toast(st.session_state, "Login realizado com sucesso.")
        st.session_state.google_oauth_feedback = {
            "message": "Login com Google realizado com sucesso.",
            "success": True,
        }
    except GoogleOAuthError as exc:
        logger.warning("Erro seguro google_oauth_callback | code=%s", exc.error_code)
        st.session_state.google_oauth_feedback = {
            "message": exc.public_message,
            "success": False,
        }
    except AuthValidationError as exc:
        st.session_state.google_oauth_feedback = {
            "message": exc.public_message,
            "success": False,
        }
    except Exception as exc:
        logger.warning(
            "Erro seguro google_oauth_callback | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        st.session_state.google_oauth_feedback = {
            "message": GOOGLE_OAUTH_QUERY_ERROR_MESSAGE,
            "success": False,
        }
    finally:
        clear_oauth_state(st.session_state)
        _clear_google_oauth_query_params()


def _render_email_verification_feedback() -> None:
    feedback = st.session_state.pop("email_verification_feedback", None)
    if not isinstance(feedback, dict):
        return

    message = str(feedback.get("message") or "").strip()
    if not message:
        return

    if bool(feedback.get("success")):
        st.success(message)
    else:
        st.error(message)


def _render_google_oauth_feedback() -> None:
    feedback = st.session_state.pop("google_oauth_feedback", None)
    if not isinstance(feedback, dict):
        return

    message = str(feedback.get("message") or "").strip()
    if not message:
        return

    if bool(feedback.get("success")):
        st.success(message)
    else:
        st.error(message)


def _resolve_authorized_page(current_page: str) -> str:
    if current_page != ADMIN_PAGE:
        return current_page

    user = get_authenticated_user(st.session_state)
    if can_view_audit_log(user):
        return current_page

    _log_audit_event(
        "admin_access_denied",
        user_id=int(user["id"]) if user and user.get("id") else None,
        user_email=user.get("email") if user else None,
        detalhe="page=auditoria",
        status="blocked",
        source="admin_page",
        action="access_denied",
    )
    if user:
        st.session_state.admin_access_feedback = ADMIN_ACCESS_DENIED_MESSAGE
    set_current_page(DEFAULT_PAGE)
    return DEFAULT_PAGE


def _render_admin_access_feedback() -> None:
    message = st.session_state.pop("admin_access_feedback", None)
    if message:
        st.warning(str(message))


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
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u2026": "...",
        "\u202f": " ",
        "\u2212": "-",
        "\ufeff": "",
    }
)
_NUMBER_RE = re.compile(r"^\s*(?:R\$\s*)?-?\d{1,3}(?:\.\d{3})*(?:,\d+)?\s*$|^\s*-?\d+(?:[.,]\d+)?\s*$")
_PAIR_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*(.+?):\s*(.+?)\s*$")
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$")
_UNSAFE_RESPONSE_PATTERNS = (
    "traceback",
    "postgresql://",
    "postgresql+" + "psyco" + "pg2://",
    "sqlite://",
    "sql" + "alchemy",
    "psyco" + "pg2",
    "operationalerror",
    "programmingerror",
    "integrityerror",
    "connection string",
    "api key",
    "apikey",
    "token",
    "client_secret",
    "api_secret",
    "secret_key",
    ".env",
)


def _apply_style() -> None:
    apply_global_light_styles(st)
    st.markdown(
        """
        <style>
        :root {
            --color-purple: #7B2CBF;
            --color-purple-soft: rgba(255, 255, 255, 0.14);
            --color-purple-dark: #4C1D95;
            --color-violet: #5B2BD1;
            --color-blue: #2563EB;
            --color-cyan: #38BDF8;
            --color-bg: #F5F7FB;
            --color-card: #FFFFFF;
            --color-card-border: rgba(123, 44, 191, 0.12);
            --color-input: #F1F5F9;
            --color-text: #1E293B;
            --color-muted: #64748B;
            --color-success-bg: #ECFEFF;
            --sidebar-width: 260px;
            --content-width: 960px;
            --shadow-card: 0 16px 34px rgba(15, 23, 42, 0.10);
            --shadow-soft: 0 10px 24px rgba(76, 29, 149, 0.13);
        }

        html,
        body,
        .stApp {
            min-height: 100%;
            background: var(--color-bg);
            color: var(--color-text);
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        #MainMenu,
        footer {
            visibility: hidden;
            height: 0;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        .block-container {
            width: min(var(--content-width), calc(100vw - var(--sidebar-width) - 112px));
            max-width: var(--content-width);
            margin-left: calc(var(--sidebar-width) + max(42px, (100vw - var(--sidebar-width) - var(--content-width)) / 2));
            margin-right: auto;
            padding: 1.15rem 0 3.8rem;
        }

        .app-sidebar {
            position: fixed;
            inset: 0 auto 0 0;
            z-index: 1000;
            width: var(--sidebar-width);
            min-height: 100vh;
            padding: 1.1rem 1rem 1rem;
            background: linear-gradient(180deg, var(--color-purple) 0%, var(--color-purple-dark) 100%);
            color: #FFFFFF;
            box-shadow: 14px 0 34px rgba(76, 29, 149, 0.18);
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.95rem;
            min-height: 5.2rem;
            margin: 0 -1rem 2.2rem;
            padding: 0 1.15rem 1.35rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.28);
        }

        .brand-mark {
            display: grid;
            place-items: center;
            width: 4.2rem;
            height: 4.2rem;
            flex: 0 0 4.2rem;
            overflow: hidden;
            border-radius: 999px;
            background: #FFFFFF;
            box-shadow:
                inset 0 0 0 2px rgba(255, 255, 255, 0.88),
                0 0 0 4px rgba(56, 189, 248, 0.26),
                0 12px 24px rgba(15, 23, 42, 0.18);
        }

        .brand-logo {
            width: 100%;
            height: 100%;
            display: block;
            object-fit: cover;
        }

        .brand-logo-fallback {
            color: var(--color-purple-dark);
            font-size: 0.95rem;
            font-weight: 850;
        }

        .brand-logo-fallback[hidden] {
            display: none;
        }

        .brand-title {
            margin: 0;
            color: #FFFFFF;
            font-size: 1.05rem;
            line-height: 1.1;
            font-weight: 800;
            letter-spacing: 0;
        }

        .brand-subtitle {
            margin: 0.28rem 0 0;
            color: rgba(255, 255, 255, 0.82);
            font-size: 0.86rem;
            line-height: 1.1;
        }

        .sidebar-nav {
            display: grid;
            gap: 1rem;
        }

        .sidebar-nav-item {
            position: relative;
        }

        .st-key-sidebar-nav-estatisticas,
        .st-key-sidebar-nav-chat-ia,
        .st-key-sidebar-nav-auditoria {
            position: fixed;
            left: 1rem;
            z-index: 1002;
            width: calc(var(--sidebar-width) - 2rem);
            height: 3.35rem;
            margin: 0 !important;
            padding: 0 !important;
        }

        .st-key-sidebar-nav-estatisticas {
            top: 8.65rem;
        }

        .st-key-sidebar-nav-chat-ia {
            top: 13rem;
        }

        .st-key-sidebar-nav-auditoria {
            top: 17.35rem;
        }

        .st-key-sidebar-nav-estatisticas [data-testid="stButton"],
        .st-key-sidebar-nav-chat-ia [data-testid="stButton"],
        .st-key-sidebar-nav-auditoria [data-testid="stButton"] {
            width: 100%;
            height: 100%;
        }

        .st-key-sidebar-nav-estatisticas [data-testid="stButton"] button,
        .st-key-sidebar-nav-chat-ia [data-testid="stButton"] button,
        .st-key-sidebar-nav-auditoria [data-testid="stButton"] button {
            width: 100%;
            height: 3.35rem;
            min-height: 3.35rem;
            padding: 0;
            border: 0 !important;
            border-color: transparent !important;
            border-radius: 0.9rem;
            background: transparent !important;
            color: transparent !important;
            box-shadow: none !important;
            text-shadow: none !important;
            font-size: 0 !important;
            line-height: 0 !important;
            opacity: 1;
        }

        .st-key-sidebar-nav-estatisticas [data-testid="stButton"] button *,
        .st-key-sidebar-nav-chat-ia [data-testid="stButton"] button *,
        .st-key-sidebar-nav-auditoria [data-testid="stButton"] button * {
            color: transparent !important;
            font-size: 0 !important;
            line-height: 0 !important;
            text-shadow: none !important;
        }

        .st-key-sidebar-nav-estatisticas [data-testid="stButton"] button:hover,
        .st-key-sidebar-nav-estatisticas [data-testid="stButton"] button:focus,
        .st-key-sidebar-nav-chat-ia [data-testid="stButton"] button:hover,
        .st-key-sidebar-nav-chat-ia [data-testid="stButton"] button:focus,
        .st-key-sidebar-nav-auditoria [data-testid="stButton"] button:hover,
        .st-key-sidebar-nav-auditoria [data-testid="stButton"] button:focus {
            border: 0 !important;
            background: transparent !important;
            color: transparent !important;
            box-shadow: none !important;
        }

        .sidebar-link {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-height: 3.35rem;
            padding: 0 1rem;
            border-radius: 0.9rem;
            color: rgba(255, 255, 255, 0.86);
            font-size: 1rem;
            font-weight: 760;
            text-decoration: none;
            transition: background 0.16s ease, color 0.16s ease, transform 0.16s ease;
        }

        .app-sidebar a,
        .app-sidebar a:visited,
        .app-sidebar a:hover,
        .app-sidebar a:focus,
        .sidebar-link,
        .sidebar-link:visited {
            color: inherit;
            text-decoration: none !important;
        }

        .sidebar-link:hover,
        .sidebar-link:focus {
            background: var(--color-purple-soft);
            color: #FFFFFF;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
        }

        .sidebar-link.active {
            background: #FFFFFF;
            color: var(--color-purple-dark) !important;
            box-shadow: 0 13px 22px rgba(15, 23, 42, 0.18);
        }

        .sidebar-link:hover,
        .sidebar-link:focus {
            transform: translateX(1px);
        }

        .sidebar-section-label {
            margin: 0.65rem 0 0.2rem;
            padding: 0 0.95rem;
            color: rgba(255, 255, 255, 0.62);
            font-size: 0.68rem;
            font-weight: 820;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .nav-icon {
            position: relative;
            display: inline-block;
            width: 1.2rem;
            height: 1.2rem;
            flex: 0 0 1.2rem;
            opacity: 1;
        }

        .nav-icon.chat::before {
            content: "";
            position: absolute;
            inset: 0.1rem 0.1rem 0.28rem;
            border: 2px solid currentColor;
            border-radius: 0.2rem;
        }

        .nav-icon.chat::after {
            content: "";
            position: absolute;
            left: 0.32rem;
            bottom: 0.02rem;
            width: 0.38rem;
            height: 0.38rem;
            border-left: 2px solid currentColor;
            border-bottom: 2px solid currentColor;
            transform: skewX(-18deg);
        }

        .nav-icon.stats {
            border-left: 2px solid currentColor;
            border-bottom: 2px solid currentColor;
            border-radius: 0 0 0 0.12rem;
        }

        .nav-icon.stats::before,
        .nav-icon.stats::after {
            content: "";
            position: absolute;
            bottom: 0.16rem;
            width: 0.16rem;
            border-radius: 999px;
            background: currentColor;
        }

        .nav-icon.stats::before {
            left: 0.36rem;
            height: 0.42rem;
        }

        .nav-icon.stats::after {
            left: 0.72rem;
            height: 0.74rem;
        }

        .nav-icon.audit {
            width: 1.35rem;
            height: 1.35rem;
            flex-basis: 1.35rem;
        }

        .nav-icon.audit::before {
            content: "";
            position: absolute;
            inset: 0.02rem 0.13rem 0.02rem;
            border: 2.5px solid currentColor;
            border-radius: 0.4rem 0.4rem 0.55rem 0.55rem;
            clip-path: polygon(50% 0, 100% 15%, 88% 70%, 50% 100%, 12% 70%, 0 15%);
            background: rgba(255, 255, 255, 0.08);
        }

        .nav-icon.audit::after {
            content: "";
            position: absolute;
            left: 0.45rem;
            top: 0.47rem;
            width: 0.4rem;
            height: 0.2rem;
            border-left: 2.5px solid currentColor;
            border-bottom: 2.5px solid currentColor;
            transform: rotate(-45deg);
        }

        .sidebar-link.active .nav-icon.audit::before {
            background: rgba(109, 40, 217, 0.10);
        }

        .app-hero {
            position: relative;
            overflow: hidden;
            min-height: 11.25rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1.5rem;
            background: linear-gradient(135deg, var(--color-purple) 0%, var(--color-violet) 46%, var(--color-blue) 100%);
            color: #FFFFFF;
            border-radius: 0.9rem;
            padding: 2rem 2rem 1.9rem;
            margin-bottom: 1.55rem;
            box-shadow: 0 17px 34px rgba(37, 99, 235, 0.22);
        }

        .app-hero::after {
            content: "";
            position: absolute;
            left: 0;
            right: 0;
            bottom: 0;
            height: 4px;
            background: var(--color-cyan);
        }

        .hero-content {
            position: relative;
            z-index: 1;
        }

        .hero-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            min-height: 1.62rem;
            padding: 0.2rem 0.75rem;
            margin-bottom: 1.1rem;
            border-radius: 999px;
            background: rgba(56, 189, 248, 0.20);
            border: 1px solid rgba(56, 189, 248, 0.38);
            color: #FFFFFF;
            font-size: 0.78rem;
            font-weight: 720;
        }

        .hero-badge::before {
            content: "";
            width: 0.38rem;
            height: 0.38rem;
            border-radius: 999px;
            background: var(--color-cyan);
            box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.18);
        }

        .app-hero h1 {
            margin: 0;
            color: #FFFFFF;
            font-size: 2.12rem;
            line-height: 1.14;
            letter-spacing: 0;
            font-weight: 820;
        }

        .app-subtitle {
            margin: 0.75rem 0 0;
            color: rgba(255, 255, 255, 0.90);
            font-size: 1.08rem;
            line-height: 1.5;
        }

        .intro-card {
            display: flex;
            gap: 1.05rem;
            background: var(--color-card);
            color: var(--color-text);
            border: 1px solid rgba(15, 23, 42, 0.05);
            border-radius: 1rem;
            padding: 1.55rem;
            margin: 0 0 1rem;
            box-shadow: var(--shadow-card);
        }

        .intro-icon {
            position: relative;
            display: grid;
            place-items: center;
            width: 3rem;
            height: 3rem;
            flex: 0 0 3rem;
            border-radius: 999px;
            background: linear-gradient(135deg, var(--color-purple) 0%, var(--color-blue) 100%);
            color: #FFFFFF;
            box-shadow: 0 14px 22px rgba(76, 29, 149, 0.18);
        }

        .intro-icon::before {
            content: "";
            position: absolute;
            inset: 0.88rem 0.76rem 1.04rem;
            border: 2px solid currentColor;
            border-radius: 0.18rem;
        }

        .intro-icon::after {
            content: "";
            position: absolute;
            left: 1.04rem;
            bottom: 0.78rem;
            width: 0.42rem;
            height: 0.42rem;
            border-left: 2px solid currentColor;
            border-bottom: 2px solid currentColor;
            transform: skewX(-18deg);
        }

        .intro-body {
            width: 100%;
        }

        .intro-card h2 {
            margin: 0 0 0.55rem;
            color: var(--color-text);
            font-size: 1.32rem;
            line-height: 1.25;
            letter-spacing: 0;
            font-weight: 760;
        }

        .intro-card p {
            margin: 0;
            color: var(--color-muted);
            line-height: 1.65;
            font-size: 1rem;
        }

        .usage-note {
            display: inline-flex;
            align-items: center;
            gap: 0.48rem;
            margin-top: 1rem;
            padding: 0.58rem 0.72rem;
            border-radius: 0.62rem;
            background: var(--color-success-bg);
            color: #155E75;
            font-size: 0.86rem;
            line-height: 1.35;
            font-weight: 650;
        }

        .usage-note::before {
            content: "";
            width: 0.42rem;
            height: 0.42rem;
            border-radius: 999px;
            background: var(--color-cyan);
            box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.18);
            flex: 0 0 auto;
        }

        .top-auth-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            margin-bottom: 0.9rem;
        }

        .top-auth-title {
            margin: 0;
            color: var(--color-muted);
            font-size: 0.84rem;
            font-weight: 760;
        }

        .top-auth-user {
            margin: 0.2rem 0 0;
            color: var(--color-text);
            font-size: 0.95rem;
            font-weight: 780;
        }

        [data-testid="stPopover"] > button {
            border: 1px solid rgba(123, 44, 191, 0.18);
            border-radius: 0.85rem;
            background: #FFFFFF;
            color: var(--color-purple-dark);
            box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
            font-weight: 780;
        }

        [data-testid="stPopoverBody"] {
            background: #FFFFFF !important;
            color: var(--color-text) !important;
            border: 1px solid rgba(15, 23, 42, 0.08) !important;
            border-radius: 0.9rem !important;
            box-shadow: 0 18px 38px rgba(15, 23, 42, 0.16) !important;
        }

        [data-testid="stPopoverBody"] *,
        .profile-menu,
        .profile-menu * {
            color: var(--color-text) !important;
        }

        .st-key-auth-menu-profile button {
            border: 1px solid rgba(123, 44, 191, 0.18) !important;
            border-radius: 0.72rem !important;
            background: #FFFFFF !important;
            color: var(--color-purple-dark) !important;
            font-weight: 760 !important;
        }

        .st-key-auth-menu-logout button {
            border: 1px solid #FECACA !important;
            border-radius: 0.72rem !important;
            background: #FEF2F2 !important;
            color: #B42318 !important;
            font-weight: 800 !important;
        }

        .auth-gate,
        .public-dashboard-card {
            background: var(--color-card);
            border: 1px solid rgba(15, 23, 42, 0.06);
            border-radius: 1rem;
            box-shadow: var(--shadow-card);
        }

        .auth-gate h2,
        .public-dashboard-card h2 {
            margin: 0 0 0.45rem;
            color: var(--color-text);
            font-size: 1.25rem;
            line-height: 1.25;
            font-weight: 780;
        }

        .auth-gate p,
        .public-dashboard-card p {
            margin: 0;
            color: var(--color-muted);
            line-height: 1.55;
        }

        .auth-gate {
            max-width: 36rem;
            margin: 1.5rem auto 0;
            padding: 1.55rem;
            text-align: center;
            border-left: 5px solid var(--color-purple);
        }

        .public-dashboard-card {
            overflow: hidden;
            margin-top: 1rem;
            border-left: 5px solid var(--color-blue);
        }

        .public-dashboard-copy {
            padding: 1.45rem;
        }

        .powerbi-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            align-items: center;
            margin-top: 1.2rem;
        }

        .powerbi-link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 2.9rem;
            padding: 0 1.15rem;
            border-radius: 0.82rem;
            background: linear-gradient(135deg, var(--color-purple) 0%, var(--color-blue) 100%);
            color: #FFFFFF !important;
            font-weight: 780;
            text-decoration: none !important;
            box-shadow: 0 14px 23px rgba(76, 29, 149, 0.22);
        }

        .powerbi-link:hover,
        .powerbi-link:focus {
            color: #FFFFFF !important;
            text-decoration: none !important;
            transform: translateY(-1px);
            box-shadow: 0 16px 28px rgba(37, 99, 235, 0.28);
        }

        .powerbi-note {
            color: var(--color-muted);
            font-size: 0.86rem;
        }

        .suggestion-heading {
            margin: 0.25rem 0 0.75rem;
            color: var(--color-muted);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .suggestion-grid {
            margin: 0 0 1.25rem;
        }

        .suggestion-grid [data-testid="stHorizontalBlock"] {
            gap: 0.72rem;
        }

        [data-testid="stButton"] button {
            min-height: 3.2rem;
            width: 100%;
            padding: 0.55rem 0.8rem;
            border-radius: 0.75rem;
            border: 1px solid rgba(123, 44, 191, 0.18);
            background: #FFFFFF;
            color: var(--color-purple-dark);
            box-shadow: 0 10px 20px rgba(15, 23, 42, 0.06);
            font-size: 0.88rem;
            font-weight: 720;
            line-height: 1.28;
            text-align: left;
            white-space: normal;
        }

        [data-testid="stButton"] button:hover,
        [data-testid="stButton"] button:focus {
            border-color: rgba(37, 99, 235, 0.32);
            color: var(--color-blue);
            background: #F8FAFC;
            box-shadow: 0 14px 24px rgba(37, 99, 235, 0.12);
            transform: translateY(-1px);
        }

        .example-list {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin-top: 1.55rem;
        }

        .example-chip {
            display: flex;
            align-items: center;
            min-height: 2.9rem;
            padding: 0.62rem 1rem;
            border-radius: 0.9rem;
            background: #FAF5FF;
            border: 1px solid rgba(123, 44, 191, 0.22);
            color: var(--color-purple-dark);
            font-weight: 720;
            font-size: 0.88rem;
            line-height: 1.25;
            cursor: default;
        }

        .chat-stack {
            display: flex;
            flex-direction: column;
            gap: 0.95rem;
            margin: 0 0 1.5rem;
        }

        .chat-row {
            display: flex;
            width: 100%;
        }

        .chat-row.user {
            justify-content: flex-end;
        }

        .chat-row.assistant {
            justify-content: flex-start;
        }

        .chat-bubble {
            max-width: 82%;
            max-height: 34rem;
            border-radius: 1rem;
            padding: 0.85rem 1rem 0.95rem;
            line-height: 1.62;
            font-size: 0.98rem;
            box-shadow: var(--shadow-soft);
            overflow-wrap: anywhere;
            overflow-y: auto;
            scrollbar-width: thin;
        }

        .chat-bubble.user {
            max-width: 74%;
            background: linear-gradient(135deg, var(--color-purple) 0%, var(--color-violet) 100%);
            color: #FFFFFF;
            border-bottom-right-radius: 0.35rem;
        }

        .chat-bubble.assistant {
            background: #FFFFFF;
            color: var(--color-text);
            border: 1px solid var(--color-card-border);
            border-bottom-left-radius: 0.35rem;
        }

        .chat-label {
            display: block;
            margin-bottom: 0.25rem;
            font-size: 0.72rem;
            line-height: 1;
            font-weight: 780;
            text-transform: uppercase;
            color: var(--color-muted);
        }

        .chat-bubble.user .chat-label {
            color: rgba(255, 255, 255, 0.78);
        }

        .chat-content {
            white-space: normal;
        }

        .chat-content p {
            margin: 0.35rem 0;
        }

        .chat-content p:first-child {
            margin-top: 0;
        }

        .chat-content p:last-child {
            margin-bottom: 0;
        }

        .assistant-result {
            display: inline-flex;
            align-items: baseline;
            gap: 0.55rem;
            padding: 0.72rem 0.85rem;
            border-radius: 0.72rem;
            background: #F8FAFC;
            border: 1px solid rgba(37, 99, 235, 0.14);
            color: var(--color-blue);
            font-size: 1.45rem;
            line-height: 1.1;
            font-weight: 820;
        }

        .assistant-result span {
            color: var(--color-muted);
            font-size: 0.8rem;
            font-weight: 760;
            text-transform: uppercase;
        }

        .assistant-table-wrap {
            max-width: 100%;
            margin-top: 0.5rem;
            overflow-x: auto;
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 0.72rem;
        }

        .assistant-table {
            width: 100%;
            min-width: 420px;
            border-collapse: collapse;
            background: #FFFFFF;
            font-size: 0.9rem;
            line-height: 1.35;
        }

        .assistant-table th,
        .assistant-table td {
            padding: 0.7rem 0.78rem;
            border-bottom: 1px solid rgba(15, 23, 42, 0.07);
            text-align: left;
            vertical-align: top;
        }

        .assistant-table th {
            background: #F8FAFC;
            color: var(--color-muted);
            font-size: 0.76rem;
            font-weight: 820;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .assistant-table tr:last-child td {
            border-bottom: 0;
        }

        .assistant-list {
            margin: 0.35rem 0 0;
            padding-left: 1.1rem;
        }

        .assistant-list li {
            margin: 0.34rem 0;
        }

        .assistant-muted {
            margin-top: 0.42rem;
            color: var(--color-muted);
            font-size: 0.84rem;
        }

        .processing-content {
            display: inline-flex;
            align-items: center;
            gap: 0.58rem;
            color: var(--color-purple-dark);
            font-weight: 720;
        }

        .processing-dots {
            display: inline-flex;
            gap: 0.2rem;
            align-items: center;
        }

        .processing-dots span {
            width: 0.34rem;
            height: 0.34rem;
            border-radius: 999px;
            background: var(--color-purple);
            opacity: 0.38;
            animation: processingPulse 1.15s infinite ease-in-out;
        }

        .processing-dots span:nth-child(2) {
            animation-delay: 0.16s;
        }

        .processing-dots span:nth-child(3) {
            animation-delay: 0.32s;
        }

        @keyframes processingPulse {
            0%,
            80%,
            100% {
                opacity: 0.28;
                transform: translateY(0);
            }

            40% {
                opacity: 1;
                transform: translateY(-2px);
            }
        }

        [data-testid="stForm"] {
            display: block;
            margin: 0;
            padding: 1rem;
            background: #FFFFFF;
            border: 0;
            border-radius: 1rem;
            box-shadow: var(--shadow-card);
        }

        [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
            gap: 0.75rem;
            align-items: center;
        }

        [data-testid="stTextInput"] {
            margin: 0;
        }

        [data-testid="stTextInput"] > div,
        [data-testid="stTextInput"] > div > div,
        [data-testid="stTextInput"] div:focus-within {
            background: transparent !important;
            border-radius: 0.875rem !important;
            box-shadow: none !important;
            outline: none !important;
        }

        [data-testid="stTextInput"] input,
        [data-testid="stForm"] input {
            min-height: 3rem;
            background: var(--color-input) !important;
            color: var(--color-text) !important;
            border: 1px solid rgba(100, 116, 139, 0.22) !important;
            border-radius: 0.875rem !important;
            outline: none !important;
            padding: 0 1rem !important;
            font-size: 0.98rem !important;
            box-shadow: none !important;
            background-clip: padding-box;
            transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
        }

        [data-testid="stTextInput"] input::placeholder,
        [data-testid="stForm"] input::placeholder {
            color: #94A3B8;
            opacity: 1;
        }

        [data-testid="stTextInput"] input:focus,
        [data-testid="stTextInput"] input:focus-visible,
        [data-testid="stForm"] input:focus,
        [data-testid="stForm"] input:focus-visible {
            border-color: rgba(37, 99, 235, 0.64) !important;
            box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.16) !important;
            outline: none !important;
        }

        [data-testid="stTextInput"]:has(input[type="password"]) button,
        [data-testid="stTextInput"]:has(input[type="password"]) [role="button"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
            width: 0 !important;
            min-width: 0 !important;
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        [data-testid="stTextInput"]:has(input[type="password"]) input {
            padding-right: 0.85rem !important;
        }

        [data-testid="stFormSubmitButton"] {
            display: flex;
            justify-content: flex-end;
            margin: 0;
        }

        [data-testid="stFormSubmitButton"] button {
            width: 3rem;
            height: 3rem;
            min-height: 3rem;
            padding: 0;
            border: 0;
            border-radius: 999px;
            background: linear-gradient(135deg, var(--color-purple) 0%, var(--color-blue) 100%);
            color: #FFFFFF;
            font-size: 1.18rem;
            line-height: 1;
            box-shadow: 0 14px 23px rgba(76, 29, 149, 0.24);
        }

        [data-testid="stFormSubmitButton"] button:hover,
        [data-testid="stFormSubmitButton"] button:focus {
            border: 0;
            color: #FFFFFF;
            transform: translateY(-1px);
            box-shadow: 0 16px 28px rgba(37, 99, 235, 0.28);
        }

        [data-testid="stForm"]:has(input[aria-label="E-mail"]),
        [data-testid="stForm"]:has(input[aria-label="Nome"]),
        [data-testid="stForm"]:has(input[aria-label="Senha atual"]) {
            max-width: 34rem;
            margin: 0 auto 0.85rem;
            padding: 0.35rem 1.4rem 1.35rem;
            border: 1px solid rgba(15, 23, 42, 0.06);
            border-top: 0;
            border-radius: 0 0 1rem 1rem;
            box-shadow: 0 12px 26px rgba(15, 23, 42, 0.08);
        }

        [data-testid="stForm"]:has(input[aria-label="E-mail"]) label,
        [data-testid="stForm"]:has(input[aria-label="Nome"]) label,
        [data-testid="stForm"]:has(input[aria-label="Senha atual"]) label {
            color: var(--color-text);
            font-size: 0.88rem;
            font-weight: 760;
        }

        [data-testid="stForm"]:has(input[aria-label="E-mail"]) input,
        [data-testid="stForm"]:has(input[aria-label="Nome"]) input,
        [data-testid="stForm"]:has(input[aria-label="Senha atual"]) input {
            min-height: 2.78rem;
            border-radius: 0.875rem !important;
            background: #F8FAFC !important;
            border-color: rgba(100, 116, 139, 0.22) !important;
        }

        [data-testid="stForm"]:has(input[aria-label="E-mail"]) [data-testid="stFormSubmitButton"],
        [data-testid="stForm"]:has(input[aria-label="Nome"]) [data-testid="stFormSubmitButton"],
        [data-testid="stForm"]:has(input[aria-label="Senha atual"]) [data-testid="stFormSubmitButton"] {
            justify-content: stretch;
            margin-top: 0.35rem;
        }

        [data-testid="stForm"]:has(input[aria-label="E-mail"]) [data-testid="stFormSubmitButton"] button,
        [data-testid="stForm"]:has(input[aria-label="Nome"]) [data-testid="stFormSubmitButton"] button,
        [data-testid="stForm"]:has(input[aria-label="Senha atual"]) [data-testid="stFormSubmitButton"] button {
            width: 100%;
            height: 2.8rem;
            min-height: 2.8rem;
            padding: 0 1rem;
            border-radius: 0.78rem;
            background: linear-gradient(135deg, var(--color-purple) 0%, var(--color-blue) 100%);
            font-size: 0.96rem;
            font-weight: 800;
            box-shadow: 0 12px 22px rgba(76, 29, 149, 0.20);
        }

        [data-testid="stSpinner"] {
            color: var(--color-purple-dark);
        }

        [data-testid="stSpinner"] > div {
            border-color: rgba(123, 44, 191, 0.18);
            border-top-color: var(--color-purple);
        }

        @media (max-width: 1120px) {
            .block-container {
                width: calc(100vw - var(--sidebar-width) - 72px);
                margin-left: calc(var(--sidebar-width) + 36px);
                margin-right: 36px;
            }
        }

        @media (max-width: 820px) {
            :root {
                --sidebar-width: 82px;
            }

            .app-sidebar {
                padding: 0.7rem 0.5rem;
            }

            .st-key-sidebar-nav-estatisticas,
            .st-key-sidebar-nav-chat-ia,
            .st-key-sidebar-nav-auditoria {
                left: 0.5rem;
                width: calc(var(--sidebar-width) - 1rem);
            }

            .st-key-sidebar-nav-estatisticas {
                top: 7.75rem;
            }

            .st-key-sidebar-nav-chat-ia {
                top: 12.1rem;
            }

            .st-key-sidebar-nav-auditoria {
                top: 16.45rem;
            }

            .sidebar-brand {
                justify-content: center;
                margin-bottom: 1.45rem;
            }

            .brand-copy,
            .sidebar-link span:not(.nav-icon) {
                display: none;
            }

            .sidebar-section-label {
                display: none;
            }

            .sidebar-link {
                justify-content: center;
                padding: 0;
            }

            .block-container {
                width: calc(100vw - var(--sidebar-width) - 32px);
                margin-left: calc(var(--sidebar-width) + 16px);
                margin-right: 16px;
                padding-top: 0.9rem;
            }

            .app-hero {
                min-height: auto;
                padding: 1.45rem;
            }

            .app-hero h1 {
                font-size: 1.75rem;
            }

            .intro-card {
                padding: 1.2rem;
            }

            .suggestion-grid [data-testid="stHorizontalBlock"] {
                display: block;
            }

            .suggestion-grid [data-testid="column"] {
                width: 100% !important;
                margin-bottom: 0.65rem;
            }

            .example-list {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 560px) {
            .intro-card {
                display: block;
            }

            .intro-icon {
                margin-bottom: 0.9rem;
            }

            [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
                display: flex;
            }

            .chat-bubble {
                max-width: 92%;
            }

            .chat-bubble.user {
                max-width: 88%;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_messages() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None

    if "auth_panel" not in st.session_state:
        st.session_state.auth_panel = None

    if "auth_modal_mode" not in st.session_state:
        st.session_state.auth_modal_mode = None

    if "auth_redirect_on_close" not in st.session_state:
        st.session_state.auth_redirect_on_close = None

    if "auth_target_page_on_success" not in st.session_state:
        st.session_state.auth_target_page_on_success = None

    if "current_page" not in st.session_state:
        st.session_state.current_page = DEFAULT_PAGE

    if "is_authenticated" not in st.session_state:
        st.session_state.is_authenticated = bool(st.session_state.get("auth_user"))


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


def _sanitize_text(value: Any) -> str:
    text = str(value if value is not None else "").translate(_SPECIAL_CHAR_TRANSLATION)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _friendly_response(value: Any) -> str:
    text = _sanitize_text(value)
    normalized = text.casefold()

    if not text:
        return UNEXPECTED_FORMAT_ERROR_MESSAGE

    if any(pattern in normalized for pattern in _UNSAFE_RESPONSE_PATTERNS):
        logger.warning("Resposta tecnica da IA substituida por mensagem amigavel.")
        return GENERIC_ERROR_MESSAGE

    if "não foi possível processar a pergunta" in normalized:
        return GENERIC_ERROR_MESSAGE

    if "configuração incompleta da camada de ia" in normalized:
        return DATA_ACCESS_ERROR_MESSAGE

    if "formato esperado" in normalized or "não retornou o resultado" in normalized:
        return UNEXPECTED_FORMAT_ERROR_MESSAGE

    if (
        "dependências da ia" in normalized
        or "erro ao executar" in normalized
        or "configuração inválida da ia" in normalized
        or "provedor de ia" in normalized
    ):
        return GENERIC_ERROR_MESSAGE

    return text


def _is_number_like(value: str) -> bool:
    return bool(_NUMBER_RE.match(value.strip()))


def _try_parse_structured(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None

    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(stripped)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue

    return None


def _structured_to_frame(value: Any) -> Any | None:
    pandas_module = _get_pandas_module()

    if isinstance(value, dict) and "value" in value:
        value = value["value"]

    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return pandas_module.DataFrame(value)

    if isinstance(value, dict):
        if all(not isinstance(item, (dict, list, tuple, set)) for item in value.values()):
            return pandas_module.DataFrame([value])

    return None


def _structured_to_list(value: Any) -> list[str] | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]

    if isinstance(value, list) and all(not isinstance(item, (dict, list, tuple, set)) for item in value):
        return [_sanitize_text(item) for item in value]

    return None


def _dataframe_to_html(df: Any) -> str:
    display_df = df.head(50).copy()
    table_html = display_df.to_html(
        index=False,
        border=0,
        classes="assistant-table",
        escape=True,
    )
    note = ""
    if len(df) > len(display_df):
        note = f'<p class="assistant-muted">Mostrando 50 de {len(df)} linhas.</p>'

    return f'<div class="assistant-table-wrap">{table_html}</div>{note}'


def _markdown_table_to_frame(value: str) -> Any | None:
    lines = [line.strip() for line in value.splitlines() if "|" in line]
    if len(lines) < 2 or not any(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", line) for line in lines):
        return None

    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)

    if len(rows) < 2:
        return None

    header = rows[0]
    body = [row for row in rows[1:] if len(row) == len(header)]
    if not body:
        return None

    return _get_pandas_module().DataFrame(body, columns=header)


def _pair_lines_to_frame(value: str) -> tuple[list[str], Any | None]:
    intro_lines: list[str] = []
    rows: list[dict[str, str]] = []

    for line in value.splitlines():
        clean_line = line.strip()
        if not clean_line:
            continue

        match = _PAIR_LINE_RE.match(clean_line)
        if match:
            rows.append({"Categoria": match.group(1).strip(), "Resultado": match.group(2).strip()})
        else:
            intro_lines.append(clean_line)

    if len(rows) < 2:
        return intro_lines, None

    return intro_lines, _get_pandas_module().DataFrame(rows)


def _plain_list_to_html(value: str) -> str | None:
    items = []
    ordered = False
    for line in value.splitlines():
        clean_line = line.strip()
        match = _LIST_LINE_RE.match(clean_line)
        if not match:
            continue
        if re.match(r"^\d+[.)]", clean_line):
            ordered = True
        items.append(match.group(1).strip())

    if len(items) < 2:
        return None

    tag = "ol" if ordered else "ul"
    rendered_items = "".join(f"<li>{_escape_text(item)}</li>" for item in items)
    return f'<{tag} class="assistant-list">{rendered_items}</{tag}>'


def _paragraphs_to_html(value: str) -> str:
    blocks = []
    for block in re.split(r"\n\s*\n", value):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        blocks.append(f"<p>{_escape_text(' '.join(lines))}</p>")

    return "".join(blocks) or f"<p>{_escape_text(value)}</p>"


def _render_assistant_content(content: str) -> str:
    text = _friendly_response(content)

    if _is_number_like(text):
        return f'<div class="assistant-result"><span>Resultado</span>{_escape_text(text)}</div>'

    parsed = _try_parse_structured(text)
    if parsed is not None:
        parsed_frame = _structured_to_frame(parsed)
        if parsed_frame is not None:
            return _dataframe_to_html(parsed_frame)

        parsed_list = _structured_to_list(parsed)
        if parsed_list is not None and parsed_list:
            items = "".join(f"<li>{_escape_text(item)}</li>" for item in parsed_list)
            return f'<ul class="assistant-list">{items}</ul>'

    markdown_frame = _markdown_table_to_frame(text)
    if markdown_frame is not None:
        return _dataframe_to_html(markdown_frame)

    intro_lines, pair_frame = _pair_lines_to_frame(text)
    if pair_frame is not None:
        intro_html = _paragraphs_to_html("\n".join(intro_lines)) if intro_lines else ""
        return f"{intro_html}{_dataframe_to_html(pair_frame)}"

    list_html = _plain_list_to_html(text)
    if list_html is not None:
        return list_html

    return _paragraphs_to_html(text)


def _render_hero(
    title: str = APP_TITLE,
    subtitle: str = APP_SUBTITLE,
    badge: str = "Análise estatística",
) -> None:
    st.markdown(
        f"""
        <section class="app-hero">
            <div class="hero-content">
                <span class="hero-badge">{_escape_text(badge)}</span>
                <h1>{_escape_text(title)}</h1>
                <p class="app-subtitle">{_escape_text(subtitle)}</p>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_intro_card() -> None:
    st.markdown(
        """
        <section class="intro-card">
            <div class="intro-icon" aria-hidden="true"></div>
            <div class="intro-body">
                <h2>Olá! Como posso ajudar?</h2>
                <p>
                    Explore os dados disponíveis com perguntas diretas sobre produção,
                    valores, perfis de atendimento e rankings.
                </p>
                <div class="usage-note">
                    Faça perguntas sobre totais, frequências, médias, rankings e comparações dos dados disponíveis.
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_suggestions() -> str | None:
    selected_prompt = None
    st.markdown(
        '<p class="suggestion-heading">Sugestões de perguntas</p><div class="suggestion-grid">',
        unsafe_allow_html=True,
    )
    rows = [EXAMPLE_PROMPTS[index : index + 3] for index in range(0, len(EXAMPLE_PROMPTS), 3)]

    for row_index, row in enumerate(rows):
        columns = st.columns(len(row), gap="small")
        for column_index, prompt in enumerate(row):
            with columns[column_index]:
                if st.button(prompt, key=f"suggestion-{row_index}-{column_index}"):
                    selected_prompt = prompt

    st.markdown("</div>", unsafe_allow_html=True)
    return selected_prompt


def _render_message(role: str, content: str) -> None:
    normalized_role = "user" if role == "user" else "assistant"
    label = "Você" if normalized_role == "user" else "Assistente"
    rendered_content = (
        f"<p>{_escape_text(_sanitize_text(content))}</p>"
        if normalized_role == "user"
        else _render_assistant_content(content)
    )
    st.markdown(
        f"""
        <div class="chat-row {normalized_role}">
            <div class="chat-bubble {normalized_role}">
                <span class="chat-label">{label}</span>
                <div class="chat-content">{rendered_content}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_processing_message() -> None:
    st.markdown(
        """
        <div class="chat-row assistant">
            <div class="chat-bubble assistant">
                <span class="chat-label">Assistente</span>
                <div class="chat-content">
                    <div class="processing-content">
                        <span>Processando pergunta...</span>
                        <span class="processing-dots" aria-hidden="true">
                            <span></span><span></span><span></span>
                        </span>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_chat_history(show_processing: bool = False) -> None:
    if not st.session_state.messages and not show_processing:
        return

    st.markdown('<section class="chat-stack">', unsafe_allow_html=True)
    for message in st.session_state.messages:
        _render_message(message["role"], message["content"])
    if show_processing:
        _render_processing_message()
    st.markdown("</section>", unsafe_allow_html=True)


def _render_input_form(disabled: bool = False) -> tuple[bool, str]:
    with st.form("chat-form", clear_on_submit=True):
        prompt_column, send_column = st.columns([12, 1], vertical_alignment="center")

        with prompt_column:
            prompt = st.text_input(
                "Pergunta estatística",
                placeholder=PROMPT_PLACEHOLDER,
                label_visibility="collapsed",
                disabled=disabled,
            )

        with send_column:
            submitted = st.form_submit_button("➤", use_container_width=True, disabled=disabled)

    return submitted, prompt.strip()


def _queue_prompt(prompt: str) -> None:
    clean_prompt = _sanitize_text(prompt)
    if not clean_prompt:
        return

    if not can_access_chat(st.session_state):
        open_auth_modal(
            mode="login",
            redirect_on_close=DEFAULT_PAGE,
            target_page_on_success=CHAT_PAGE,
        )
        return

    if not _can_use_chat_with_email_verification():
        return

    if st.session_state.get("pending_prompt") == clean_prompt:
        return

    st.session_state.pending_prompt = clean_prompt


def _process_pending_prompt() -> bool:
    prompt = st.session_state.get("pending_prompt")
    if not prompt:
        return False

    if not can_access_chat(st.session_state):
        st.session_state.pending_prompt = None
        open_auth_modal(
            mode="login",
            redirect_on_close=DEFAULT_PAGE,
            target_page_on_success=CHAT_PAGE,
        )
        logger.warning("Tentativa bloqueada de chat sem usuario autenticado.")
        return False

    if not _can_use_chat_with_email_verification():
        st.session_state.pending_prompt = None
        logger.warning("Tentativa bloqueada de chat com e-mail nao verificado.")
        return False

    user = get_authenticated_user(st.session_state)
    user_id = int(user["id"]) if user else 0
    st.session_state.pending_prompt = None
    track_event("ai_question_submitted", {"page": "chat"})
    if user_id:
        _persist_chat_history_message(
            user_id=user_id,
            role="user",
            content=prompt,
            status="ok",
            prompt_for_title=prompt,
        )
    st.session_state.messages.append({"role": "user", "content": prompt})
    _render_chat_history(show_processing=True)
    _render_input_form(disabled=True)

    assistant_status = "ok"
    try:
        perguntar_datasus = _get_datasus_question_runner()
        resposta = perguntar_datasus(prompt, user_context=get_authenticated_user(st.session_state))
    except Exception as exc:
        logger.warning(
            "Erro seguro app_ai_chat | operacao=processar_prompt | tipo=%s | fallback=mensagem_amigavel",
            type(exc).__name__,
        )
        _log_audit_event(
            "chat_processing_error",
            user_id=user_id or None,
            user_email=user.get("email") if user else None,
            prompt_text=prompt,
            detalhe=f"tipo={type(exc).__name__}",
            status="failure",
            source="chat_ia",
            action="process_prompt",
        )
        resposta = GENERIC_ERROR_MESSAGE
        assistant_status = "error"

    from src.ai.datasus_ai import (
        DATABASE_UNAVAILABLE_MESSAGE as AI_DATABASE_UNAVAILABLE_MESSAGE,
        ENGINE_UNAVAILABLE_MESSAGE,
        GENERIC_AI_ERROR_MESSAGE,
        LLM_SIMPLE_FALLBACK_NOTICE,
    )

    if assistant_status == "error" or resposta in {
        AI_DATABASE_UNAVAILABLE_MESSAGE,
        ENGINE_UNAVAILABLE_MESSAGE,
        GENERIC_AI_ERROR_MESSAGE,
    }:
        track_event("ai_question_failed", {"result": "failure"})
    elif resposta == BLOCK_MESSAGE:
        track_event("ai_question_blocked", {"result": "blocked"})
    else:
        if resposta.startswith(LLM_SIMPLE_FALLBACK_NOTICE):
            track_event("ai_fallback_used", {"execution_mode": "fallback"})
        track_event("ai_question_succeeded", {"result": "success"})

    if user_id:
        _persist_chat_history_message(
            user_id=user_id,
            role="assistant",
            content=resposta,
            status=assistant_status,
            prompt_for_title=prompt,
        )
    st.session_state.messages.append({"role": "assistant", "content": resposta})
    st.rerun()
    return True


def _handle_prompt(prompt: str) -> None:
    _queue_prompt(prompt)
    st.rerun()


def _render_chat_page() -> None:
    _render_hero("Chat IA", APP_SUBTITLE, "Área protegida")

    if not can_access_chat(st.session_state):
        st.session_state.pending_prompt = None
        render_chat_auth_gate(open_login=True)
        return

    if not _can_use_chat_with_email_verification():
        st.session_state.pending_prompt = None
        render_chat_email_verification_gate()
        return

    _render_intro_card()
    selected_prompt = _render_suggestions()

    if selected_prompt:
        _handle_prompt(selected_prompt)

    if _process_pending_prompt():
        return

    _render_chat_history()

    submitted, prompt = _render_input_form()

    if submitted and prompt:
        _handle_prompt(prompt)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")
    configure_umami()
    _log_startup_diagnostics_once()
    _apply_style()
    _init_messages()
    render_pending_toast()
    _handle_healthcheck_query_param()
    _handle_google_oauth_query_param()
    _handle_password_reset_query_param()
    _handle_email_verification_query_param()
    current_page = _resolve_authorized_page(get_current_page())
    logical_pages = {
        DEFAULT_PAGE: "/estatisticas",
        CHAT_PAGE: "/chat-ia",
        ADMIN_PAGE: "/auditoria",
    }
    track_page_view(logical_pages[current_page])
    if current_page == DEFAULT_PAGE:
        track_event_once("statistics_viewed", {"page": "statistics"})
    elif current_page == CHAT_PAGE and can_access_chat(st.session_state):
        track_event_once("ai_chat_opened", {"page": "chat"})
    elif current_page == ADMIN_PAGE:
        track_event_once("audit_page_viewed", {"page": "audit"})
    if (
        current_page == CHAT_PAGE
        and not can_access_chat(st.session_state)
        and not st.session_state.get("auth_panel")
    ):
        open_auth_modal(
            mode="login",
            redirect_on_close=DEFAULT_PAGE,
            target_page_on_success=CHAT_PAGE,
    )
    render_auth_header()
    render_auth_panel()
    _render_google_oauth_feedback()
    _render_email_verification_feedback()
    render_sidebar(current_page)
    _render_admin_access_feedback()

    if current_page == CHAT_PAGE:
        _render_chat_page()
    elif current_page == ADMIN_PAGE:
        render_admin_page()
    else:
        render_statistics_page()


if __name__ == "__main__":
    main()
