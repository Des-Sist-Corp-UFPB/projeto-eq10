"""Modais de autenticacao da interface Streamlit."""

from __future__ import annotations

import html
import logging
from typing import Any

import streamlit as st

from src.auth.session import login_session
from src.auth.user_service import AuthValidationError, UserService, safe_auth_exception_summary
from src.auth.validation import validate_login_fields, validate_register_fields
from src.ui.notifications import queue_toast
from src.ui.sidebar import set_current_page

AUTH_UNAVAILABLE_MESSAGE = (
    "Não foi possível acessar a autenticação agora. Tente novamente em alguns instantes."
)

logger = logging.getLogger(__name__)

AUTH_MODAL_CSS = """
<style>
    [data-testid="stDialog"]::backdrop,
    dialog[data-testid="stDialog"]::backdrop,
    div[role="dialog"]::backdrop {
        background: rgba(15, 23, 42, 0.18) !important;
        backdrop-filter: blur(4px);
    }

    [data-testid="stDialog"] {
        background: rgba(15, 23, 42, 0.14) !important;
        backdrop-filter: blur(5px);
    }

    [data-testid="stDialog"] > div,
    [data-testid="stDialog"] [role="dialog"],
    div[role="dialog"][aria-modal="true"] {
        width: min(92vw, 28rem) !important;
        max-width: 28rem !important;
        margin: auto !important;
        background: #FFFFFF !important;
        color: #0F172A !important;
        border: 1px solid rgba(15, 23, 42, 0.08) !important;
        border-radius: 1.35rem !important;
        box-shadow: 0 26px 70px rgba(15, 23, 42, 0.22) !important;
    }

    [data-testid="stDialog"] button[aria-label="Close"],
    [data-testid="stDialog"] button[aria-label="close"],
    [data-testid="stDialog"] button[aria-label="Dismiss"],
    [data-testid="stDialog"] button[aria-label="Fechar"],
    [data-testid="stDialog"] button[title="Close"],
    [data-testid="stDialog"] button[title="Dismiss"],
    [data-testid="stDialog"] button[title="Fechar"] {
        color: #334155 !important;
        opacity: 1 !important;
        border-radius: 999px !important;
        background: rgba(15, 23, 42, 0.04) !important;
    }

    [data-testid="stDialog"] button[aria-label="Close"]:hover,
    [data-testid="stDialog"] button[aria-label="close"]:hover,
    [data-testid="stDialog"] button[aria-label="Dismiss"]:hover,
    [data-testid="stDialog"] button[aria-label="Fechar"]:hover,
    [data-testid="stDialog"] button[title="Close"]:hover,
    [data-testid="stDialog"] button[title="Dismiss"]:hover,
    [data-testid="stDialog"] button[title="Fechar"]:hover {
        color: #0F172A !important;
        background: rgba(15, 23, 42, 0.10) !important;
    }

    [data-testid="stDialog"] section,
    [data-testid="stDialog"] div,
    [data-testid="stDialog"] [data-testid="stMarkdownContainer"] {
        color: #0F172A !important;
    }

    .auth-dialog-heading {
        margin: 0 0 1rem;
    }

    .auth-dialog-heading h2 {
        margin: 0;
        color: #0F172A !important;
        font-size: 1.35rem;
        line-height: 1.2;
        font-weight: 820;
    }

    .auth-dialog-heading p {
        margin: 0.4rem 0 0;
        color: #64748B !important;
        font-size: 0.95rem;
        line-height: 1.45;
    }

    [data-testid="stDialog"] .auth-global-error,
    .auth-global-error {
        margin: -0.25rem 0 0.95rem;
        padding: 0.78rem 0.9rem;
        border: 1px solid #FECACA;
        border-radius: 0.85rem;
        background: #FEF2F2;
        color: #991B1B !important;
        font-size: 0.9rem;
        font-weight: 680;
        line-height: 1.45;
    }

    [data-testid="stDialog"] .auth-global-error *,
    .auth-global-error * {
        color: #991B1B !important;
    }

    [data-testid="stDialog"] .auth-info-message,
    .auth-info-message {
        margin: 0.2rem 0 0.95rem;
        padding: 0.78rem 0.9rem;
        border: 1px solid rgba(37, 99, 235, 0.22);
        border-radius: 0.85rem;
        background: #EFF6FF;
        color: #1E3A8A !important;
        font-size: 0.9rem;
        font-weight: 680;
        line-height: 1.45;
    }

    [data-testid="stDialog"] .auth-info-message *,
    .auth-info-message * {
        color: #1E3A8A !important;
    }

    [data-testid="stDialog"] .auth-field-error,
    .auth-field-error {
        margin: -0.3rem 0 0.58rem;
        color: #B42318 !important;
        font-size: 0.82rem;
        font-weight: 680;
        line-height: 1.35;
    }

    [data-testid="stDialog"] [data-testid="stForm"] {
        background: transparent !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 0.25rem 0 0.45rem !important;
        border: 0 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
    }

    [data-testid="stDialog"] [data-testid="InputInstructions"] {
        display: none !important;
    }

    [data-testid="stDialog"] label {
        color: #334155 !important;
        font-size: 0.9rem !important;
        font-weight: 760 !important;
    }

    [data-testid="stDialog"] input {
        min-height: 2.82rem !important;
        border-radius: 0.875rem !important;
        background: #F8FAFC !important;
        border: 1px solid rgba(100, 116, 139, 0.22) !important;
        color: #0F172A !important;
        font-size: 0.96rem !important;
        outline: none !important;
        box-shadow: none !important;
        background-clip: padding-box;
        transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
    }

    [data-testid="stDialog"] input::placeholder {
        color: #94A3B8 !important;
        opacity: 1 !important;
    }

    [data-testid="stDialog"] input:focus,
    [data-testid="stDialog"] input:focus-visible {
        border-color: rgba(37, 99, 235, 0.64) !important;
        box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.16) !important;
        outline: none !important;
    }

    [data-testid="stDialog"] [data-testid="stFormSubmitButton"] {
        justify-content: stretch !important;
        margin-top: 0.35rem !important;
    }

    [data-testid="stDialog"] [data-testid="stFormSubmitButton"] button,
    [data-testid="stDialog"] [data-testid="stFormSubmitButton"] button * {
        color: #FFFFFF !important;
        fill: #FFFFFF !important;
    }

    [data-testid="stDialog"] [data-testid="stFormSubmitButton"] button {
        width: 100% !important;
        height: 2.85rem !important;
        min-height: 2.85rem !important;
        padding: 0 1rem !important;
        border: 0 !important;
        border-radius: 0.78rem !important;
        background: linear-gradient(135deg, #7B2CBF 0%, #2563EB 100%) !important;
        font-size: 0.96rem !important;
        font-weight: 800 !important;
        box-shadow: 0 12px 22px rgba(76, 29, 149, 0.20) !important;
        text-align: center !important;
    }

    [data-testid="stDialog"] [data-testid="stButton"] button {
        width: auto !important;
        min-height: 1.5rem !important;
        padding: 0.08rem 0.18rem !important;
        border: 0 !important;
        border-radius: 0.45rem !important;
        background: transparent !important;
        color: #5B21B6 !important;
        box-shadow: none !important;
        font-size: 0.9rem !important;
        font-weight: 760 !important;
        text-align: center !important;
    }

    .auth-dialog-footer {
        margin: 0;
    }

    [data-testid="stDialog"] .st-key-auth-login-go-signup,
    [data-testid="stDialog"] .st-key-auth-signup-go-login,
    .st-key-auth-login-go-signup,
    .st-key-auth-signup-go-login {
        margin-top: 0.68rem !important;
    }

    .auth-dialog-footer [data-testid="stButton"] button,
    [data-testid="stDialog"] .st-key-auth-login-go-signup button,
    [data-testid="stDialog"] .st-key-auth-signup-go-login button,
    .st-key-auth-login-go-signup button,
    .st-key-auth-signup-go-login button {
        width: 100% !important;
        height: 2.85rem !important;
        min-height: 2.85rem !important;
        padding: 0 1rem !important;
        border: 1px solid rgba(123, 44, 191, 0.42) !important;
        border-radius: 0.78rem !important;
        background: #FFFFFF !important;
        color: #5B21B6 !important;
        box-shadow: 0 8px 18px rgba(76, 29, 149, 0.08) !important;
        font-size: 0.96rem !important;
        font-weight: 820 !important;
        text-align: center !important;
        white-space: nowrap !important;
    }

    .auth-dialog-footer [data-testid="stButton"] button:hover,
    .auth-dialog-footer [data-testid="stButton"] button:focus,
    [data-testid="stDialog"] .st-key-auth-login-go-signup button:hover,
    [data-testid="stDialog"] .st-key-auth-login-go-signup button:focus,
    [data-testid="stDialog"] .st-key-auth-signup-go-login button:hover,
    [data-testid="stDialog"] .st-key-auth-signup-go-login button:focus,
    .st-key-auth-login-go-signup button:hover,
    .st-key-auth-login-go-signup button:focus,
    .st-key-auth-signup-go-login button:hover,
    .st-key-auth-signup-go-login button:focus {
        color: #4C1D95 !important;
        border-color: rgba(37, 99, 235, 0.62) !important;
        background: #F8FAFC !important;
        box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.12) !important;
    }

    [data-testid="stDialog"] .st-key-auth-login-forgot-password button,
    .st-key-auth-login-forgot-password button {
        width: 100% !important;
        min-height: 1.9rem !important;
        margin-top: 0.42rem !important;
        padding: 0.18rem 0.4rem !important;
        border: 0 !important;
        background: transparent !important;
        color: #5B21B6 !important;
        box-shadow: none !important;
        font-size: 0.86rem !important;
        font-weight: 720 !important;
    }

    [data-testid="stDialog"] .st-key-auth-login-forgot-password button:hover,
    [data-testid="stDialog"] .st-key-auth-login-forgot-password button:focus,
    .st-key-auth-login-forgot-password button:hover,
    .st-key-auth-login-forgot-password button:focus {
        color: #2563EB !important;
        background: rgba(37, 99, 235, 0.06) !important;
        box-shadow: none !important;
    }

    .auth-dialog-subtitle {
        margin: -0.25rem 0 1rem;
        color: #64748B !important;
        font-size: 0.95rem;
        line-height: 1.48;
    }

    .auth-dialog-profile {
        margin: 0.2rem 0 1.15rem;
        padding: 1.05rem;
        border-radius: 1rem;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
    }

    .auth-dialog-profile p {
        margin: 0.36rem 0;
        color: #64748B !important;
        line-height: 1.48;
    }

    [data-testid="stDialog"]:has(.auth-profile-panel) > div,
    [data-testid="stDialog"]:has(.auth-profile-panel) [role="dialog"],
    [data-testid="stDialog"]:has(.auth-profile-form-panel) > div,
    [data-testid="stDialog"]:has(.auth-profile-form-panel) [role="dialog"] {
        width: min(94vw, 46rem) !important;
        max-width: 46rem !important;
    }

    .auth-profile-panel,
    .auth-profile-form-panel {
        margin: 0;
    }

    .auth-profile-info-card {
        margin: 0.25rem 0 1.2rem;
        padding: 1.05rem;
        border: 1px solid #E2E8F0;
        border-radius: 1rem;
        background: #F8FAFC;
    }

    .auth-profile-info-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.75rem;
    }

    .auth-profile-field {
        min-width: 0;
        padding: 0.78rem 0.82rem;
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 0.82rem;
        background: #FFFFFF;
    }

    .auth-profile-field-label {
        display: block;
        margin-bottom: 0.28rem;
        color: #64748B !important;
        font-size: 0.78rem;
        font-weight: 760;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .auth-profile-field-value {
        display: block;
        overflow-wrap: anywhere;
        color: #0F172A !important;
        font-size: 0.96rem;
        font-weight: 780;
        line-height: 1.35;
    }

    .auth-profile-section-title {
        margin: 0.2rem 0 0.75rem;
        color: #0F172A !important;
        font-size: 1rem;
        font-weight: 820;
    }

    .auth-profile-actions {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.75rem;
    }

    [data-testid="stDialog"] .auth-profile-actions [data-testid="stButton"] button,
    .auth-profile-actions [data-testid="stButton"] button {
        width: 100% !important;
        min-height: 6.2rem !important;
        padding: 0.88rem 0.95rem 0.88rem 1.05rem !important;
        border: 1px solid #E2E8F0 !important;
        border-left: 4px solid #7B2CBF !important;
        border-radius: 1rem !important;
        background: #FFFFFF !important;
        color: #0F172A !important;
        box-shadow: 0 10px 22px rgba(15, 23, 42, 0.06) !important;
        font-size: 0.92rem !important;
        font-weight: 760 !important;
        line-height: 1.35 !important;
        text-align: left !important;
        white-space: pre-line !important;
    }

    [data-testid="stDialog"] .auth-profile-actions [data-testid="stButton"] button:hover,
    [data-testid="stDialog"] .auth-profile-actions [data-testid="stButton"] button:focus,
    .auth-profile-actions [data-testid="stButton"] button:hover,
    .auth-profile-actions [data-testid="stButton"] button:focus {
        border-color: rgba(37, 99, 235, 0.34) !important;
        border-left-color: #2563EB !important;
        background: #F8FAFC !important;
        color: #4C1D95 !important;
        box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.10), 0 12px 26px rgba(15, 23, 42, 0.08) !important;
    }

    .st-key-auth-name-back button,
    .st-key-auth-password-back button,
    .st-key-auth-email-back button {
        margin-top: 0.55rem !important;
        width: 100% !important;
        min-height: 2.7rem !important;
        border: 1px solid rgba(123, 44, 191, 0.24) !important;
        border-radius: 0.78rem !important;
        background: #FFFFFF !important;
        color: #4C1D95 !important;
        font-weight: 780 !important;
    }

    @media (max-width: 720px) {
        .auth-profile-info-grid,
        .auth-profile-actions {
            grid-template-columns: 1fr;
        }
    }
</style>
"""


def _escape_text(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _render_auth_modal_style() -> None:
    st.markdown(AUTH_MODAL_CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def _get_auth_service() -> UserService:
    return UserService.from_environment()


def open_auth_modal(
    mode: str = "login",
    *,
    redirect_on_close: str | None = None,
    target_page_on_success: str | None = None,
) -> None:
    st.session_state.auth_panel = "auth"
    st.session_state.auth_modal_mode = "register" if mode in {"signup", "register"} else "login"
    st.session_state.auth_redirect_on_close = redirect_on_close
    st.session_state.auth_target_page_on_success = target_page_on_success


def switch_auth_modal_mode(mode: str) -> None:
    open_auth_modal(
        mode,
        redirect_on_close=st.session_state.get("auth_redirect_on_close"),
        target_page_on_success=st.session_state.get("auth_target_page_on_success"),
    )


def close_auth_modal(*, redirect: bool = True) -> None:
    redirect_page = st.session_state.get("auth_redirect_on_close") if redirect else None

    st.session_state.auth_panel = None
    st.session_state.auth_modal_mode = None
    st.session_state.auth_redirect_on_close = None
    st.session_state.auth_target_page_on_success = None

    if redirect_page:
        set_current_page(str(redirect_page))


def set_auth_panel(
    panel: str | None,
    *,
    redirect_on_close: str | None = None,
    target_page_on_success: str | None = None,
) -> None:
    if panel in {"login", "signup", "register"}:
        open_auth_modal(
            str(panel),
            redirect_on_close=redirect_on_close,
            target_page_on_success=target_page_on_success,
        )
        return

    st.session_state.auth_panel = panel
    if panel is None:
        st.session_state.auth_modal_mode = None

    st.session_state.auth_redirect_on_close = redirect_on_close
    st.session_state.auth_target_page_on_success = target_page_on_success


def close_auth_panel(*, redirect: bool = True) -> None:
    close_auth_modal(redirect=redirect)


def _finish_auth_success() -> None:
    target_page = st.session_state.get("auth_target_page_on_success")
    close_auth_modal(redirect=False)

    if target_page:
        set_current_page(str(target_page))


def _clear_auth_panel() -> None:
    close_auth_modal()


def _get_auth_service_or_none() -> UserService | None:
    try:
        return _get_auth_service()
    except Exception as exc:
        logger.warning(
            "Erro seguro auth_service | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return None


def _render_auth_dialog_subtitle(subtitle: str) -> None:
    st.markdown(
        f'<p class="auth-dialog-subtitle">{_escape_text(subtitle)}</p>',
        unsafe_allow_html=True,
    )


def _render_auth_dialog_heading(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <section class="auth-dialog-heading">
            <h2>{_escape_text(title)}</h2>
            <p>{_escape_text(subtitle)}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_global_error(container: Any, message: str) -> None:
    container.markdown(
        f'<section class="auth-global-error" role="alert">{_escape_text(message)}</section>',
        unsafe_allow_html=True,
    )


def _render_global_info(container: Any, message: str) -> None:
    container.markdown(
        f'<section class="auth-info-message">{_escape_text(message)}</section>',
        unsafe_allow_html=True,
    )


def _render_field_error(container: Any, message: str | None) -> None:
    if not message:
        return

    container.markdown(
        f'<p class="auth-field-error">{_escape_text(message)}</p>',
        unsafe_allow_html=True,
    )


def _render_field_errors(containers: dict[str, Any], errors: dict[str, str]) -> None:
    for field_name, message in errors.items():
        container = containers.get(field_name)
        if container is not None:
            _render_field_error(container, message)


def _render_auth_footer(
    *,
    action_label: str,
    switch_mode: str,
    switch_key: str,
) -> None:
    st.markdown('<section class="auth-dialog-footer">', unsafe_allow_html=True)
    if st.button(action_label, key=switch_key, use_container_width=True):
        switch_auth_modal_mode(switch_mode)
        st.rerun()
    st.markdown("</section>", unsafe_allow_html=True)


def _render_login_panel() -> None:
    _render_auth_dialog_heading("Acesso ao Chat IA", "Entre para continuar usando o chat inteligente.")
    global_error_slot = st.empty()

    with st.form("auth-login-form", clear_on_submit=False):
        email = st.text_input("E-mail", placeholder="seu.email@exemplo.com")
        field_error_slots = {"email": st.empty()}
        senha = st.text_input("Senha", type="password", placeholder="Sua senha")
        field_error_slots["senha"] = st.empty()
        submitted = st.form_submit_button("Entrar", use_container_width=True)

    _render_auth_footer(
        action_label="Criar conta",
        switch_mode="register",
        switch_key="auth-login-go-signup",
    )
    if st.button("Esqueci minha senha", key="auth-login-forgot-password", use_container_width=True):
        set_auth_panel("forgot_password")
        st.rerun()

    if submitted:
        field_errors = validate_login_fields(email, senha)
        if field_errors:
            _render_field_errors(field_error_slots, field_errors)
            return

        service = _get_auth_service_or_none()
        if service is None:
            _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
            return

        try:
            user = service.authenticate(email, senha)
        except AuthValidationError as exc:
            _render_global_error(global_error_slot, exc.public_message)
        except Exception as exc:
            logger.warning(
                "Erro seguro login | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
        else:
            login_session(st.session_state, user)
            _finish_auth_success()
            queue_toast(st.session_state, "Login realizado com sucesso.")
            st.rerun()


def _render_signup_panel() -> None:
    _render_auth_dialog_heading("Criar conta", "Preencha seus dados para acessar o Chat IA.")
    global_error_slot = st.empty()

    with st.form("auth-signup-form", clear_on_submit=False):
        nome = st.text_input("Nome", placeholder="Seu nome")
        field_error_slots = {"nome": st.empty()}
        email = st.text_input("E-mail", placeholder="seu.email@exemplo.com")
        field_error_slots["email"] = st.empty()
        senha = st.text_input("Senha", type="password", placeholder="No mínimo 8 caracteres")
        field_error_slots["senha"] = st.empty()
        confirmar_senha = st.text_input(
            "Confirmar senha",
            type="password",
            placeholder="Repita sua senha",
        )
        field_error_slots["confirmar_senha"] = st.empty()
        submitted = st.form_submit_button("Criar conta", use_container_width=True)

    _render_auth_footer(
        action_label="Entrar",
        switch_mode="login",
        switch_key="auth-signup-go-login",
    )

    if submitted:
        field_errors = validate_register_fields(nome, email, senha, confirmar_senha)
        if field_errors:
            _render_field_errors(field_error_slots, field_errors)
            return

        service = _get_auth_service_or_none()
        if service is None:
            _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
            return

        try:
            user = service.create_user(nome, email, senha, confirmar_senha)
        except AuthValidationError as exc:
            _render_global_error(global_error_slot, exc.public_message)
        except Exception as exc:
            logger.warning(
                "Erro seguro cadastro | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
        else:
            login_session(st.session_state, user)
            _finish_auth_success()
            queue_toast(st.session_state, "Conta criada com sucesso.")
            st.rerun()


def _render_forgot_password_panel() -> None:
    _render_auth_dialog_heading(
        "Recuperar senha",
        "A recuperação de senha por e-mail ainda não está disponível.",
    )
    st.markdown(
        """
        <section class="auth-dialog-profile">
            <p>
                Entre em contato com a equipe responsável para solicitar a recuperação
                de acesso. Nenhum e-mail foi enviado automaticamente.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Voltar para entrar", key="auth-forgot-back-login", use_container_width=True):
        set_auth_panel("login")
        st.rerun()


def _render_profile_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    _render_auth_dialog_heading("Meu perfil", "Gerencie seus dados de acesso ao Chat IA.")
    st.markdown(
        f"""
        <section class="auth-profile-panel">
            <div class="auth-profile-info-card">
                <div class="auth-profile-info-grid">
                    <div class="auth-profile-field">
                        <span class="auth-profile-field-label">Nome</span>
                        <span class="auth-profile-field-value">{_escape_text(user["nome"])}</span>
                    </div>
                    <div class="auth-profile-field">
                        <span class="auth-profile-field-label">E-mail</span>
                        <span class="auth-profile-field-value">{_escape_text(user["email"])}</span>
                    </div>
                    <div class="auth-profile-field">
                        <span class="auth-profile-field-label">Perfil</span>
                        <span class="auth-profile-field-value">{_escape_text(user.get("role", "user"))}</span>
                    </div>
                </div>
            </div>
            <h3 class="auth-profile-section-title">Gerenciar conta</h3>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<section class="auth-profile-actions">', unsafe_allow_html=True)
    if st.button(
        "Alterar nome\nAtualize o nome exibido na sua conta.",
        key="auth-profile-change-name",
        use_container_width=True,
    ):
        set_auth_panel("change_name")
        st.rerun()
    if st.button(
        "Alterar e-mail\nSolicite a alteracao do e-mail usado no acesso.",
        key="auth-profile-change-email",
        use_container_width=True,
    ):
        set_auth_panel("change_email")
        st.rerun()
    if st.button(
        "Alterar senha\nTroque sua senha de acesso com seguranca.",
        key="auth-profile-change-password",
        use_container_width=True,
    ):
        set_auth_panel("change_password")
        st.rerun()
    st.markdown("</section>", unsafe_allow_html=True)


def _render_change_name_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    st.markdown('<section class="auth-profile-form-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading("Alterar nome", "Atualize o nome exibido na sua conta.")

    service = _get_auth_service_or_none()
    if service is None:
        _render_global_error(st, AUTH_UNAVAILABLE_MESSAGE)
        return

    with st.form("auth-change-name-form", clear_on_submit=False):
        nome = st.text_input("Nome", value=user["nome"])
        submitted = st.form_submit_button("Salvar nome", use_container_width=True)

    if st.button("Voltar ao perfil", key="auth-name-back", use_container_width=True):
        set_auth_panel("profile")
        st.rerun()

    if submitted:
        try:
            updated_user = service.update_name(int(user["id"]), nome)
        except AuthValidationError as exc:
            _render_global_error(st, exc.public_message)
        except Exception as exc:
            logger.warning(
                "Erro seguro alterar_nome | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(st, AUTH_UNAVAILABLE_MESSAGE)
        else:
            login_session(st.session_state, updated_user)
            set_auth_panel("profile")
            queue_toast(st.session_state, "Nome atualizado com sucesso.")
            st.rerun()


def _render_change_password_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    st.markdown('<section class="auth-profile-form-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading(
        "Alterar senha",
        "Informe a senha atual antes de definir uma nova senha.",
    )

    service = _get_auth_service_or_none()
    if service is None:
        _render_global_error(st, AUTH_UNAVAILABLE_MESSAGE)
        return

    with st.form("auth-change-password-form", clear_on_submit=True):
        senha_atual = st.text_input("Senha atual", type="password")
        nova_senha = st.text_input("Nova senha", type="password", placeholder="No mínimo 8 caracteres")
        confirmar_senha = st.text_input("Confirmar nova senha", type="password")
        submitted = st.form_submit_button("Salvar senha", use_container_width=True)

    if st.button("Voltar ao perfil", key="auth-password-back", use_container_width=True):
        set_auth_panel("profile")
        st.rerun()

    if submitted:
        try:
            service.change_password(
                int(user["id"]),
                senha_atual,
                nova_senha,
                confirmar_senha,
            )
        except AuthValidationError as exc:
            _render_global_error(st, exc.public_message)
        except Exception as exc:
            logger.warning(
                "Erro seguro alterar_senha | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(st, AUTH_UNAVAILABLE_MESSAGE)
        else:
            set_auth_panel("profile")
            queue_toast(st.session_state, "Senha alterada com sucesso.")
            st.rerun()


def _render_change_email_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    st.markdown('<section class="auth-profile-form-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading(
        "Alterar e-mail",
        "Informe o novo e-mail para iniciar a alteracao.",
    )

    service = _get_auth_service_or_none()
    if service is None:
        _render_global_error(st, AUTH_UNAVAILABLE_MESSAGE)
        return

    global_slot = st.empty()

    with st.form("auth-change-email-form", clear_on_submit=False):
        st.markdown(
            f"""
            <section class="auth-dialog-profile">
                <p>E-mail atual: <strong>{_escape_text(user["email"])}</strong></p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        novo_email = st.text_input("Novo e-mail", placeholder="novo.email@exemplo.com")
        field_error_slots = {"email": st.empty()}
        submitted = st.form_submit_button("Continuar", use_container_width=True)

    if st.button("Voltar ao perfil", key="auth-email-back", use_container_width=True):
        set_auth_panel("profile")
        st.rerun()

    if submitted:
        field_errors = validate_login_fields(novo_email, "senha-temporaria")
        if field_errors.get("email"):
            _render_field_errors(field_error_slots, {"email": field_errors["email"]})
            return

        clean_email = novo_email.strip().casefold()
        if clean_email == str(user["email"]).strip().casefold():
            _render_field_errors(field_error_slots, {"email": "Informe um e-mail diferente do atual."})
            return

        try:
            if service.active_email_exists(clean_email):
                _render_global_error(global_slot, "Já existe uma conta ativa com este e-mail.")
                return
        except AuthValidationError as exc:
            _render_global_error(global_slot, exc.public_message)
            return
        except Exception as exc:
            logger.warning(
                "Erro seguro alterar_email | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
            return

        _render_global_info(
            global_slot,
            "A verificação de e-mail ainda não foi ativada neste ambiente.",
        )


@st.dialog("Acesso ao Chat IA", width="small", on_dismiss=_clear_auth_panel)
def _render_auth_dialog() -> None:
    mode = st.session_state.get("auth_modal_mode", "login")
    if mode in {"signup", "register"}:
        _render_signup_panel()
    else:
        _render_login_panel()


@st.dialog("Meu perfil", width="large", on_dismiss=_clear_auth_panel)
def _render_profile_dialog() -> None:
    _render_profile_panel()


@st.dialog("Alterar nome", width="large", on_dismiss=_clear_auth_panel)
def _render_change_name_dialog() -> None:
    _render_change_name_panel()


@st.dialog("Alterar senha", width="large", on_dismiss=_clear_auth_panel)
def _render_change_password_dialog() -> None:
    _render_change_password_panel()


@st.dialog("Alterar e-mail", width="large", on_dismiss=_clear_auth_panel)
def _render_change_email_dialog() -> None:
    _render_change_email_panel()


@st.dialog("Recuperar senha", width="small", on_dismiss=_clear_auth_panel)
def _render_forgot_password_dialog() -> None:
    _render_forgot_password_panel()


def render_auth_panel() -> None:
    panel = st.session_state.get("auth_panel")
    if not panel:
        return

    _render_auth_modal_style()

    if panel in {"auth", "login", "signup", "register"}:
        _render_auth_dialog()
    elif panel == "profile":
        _render_profile_dialog()
    elif panel == "change_name":
        _render_change_name_dialog()
    elif panel == "change_password":
        _render_change_password_dialog()
    elif panel == "change_email":
        _render_change_email_dialog()
    elif panel == "forgot_password":
        _render_forgot_password_dialog()
