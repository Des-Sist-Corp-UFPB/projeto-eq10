"""Modais de autenticacao da interface Streamlit."""

from __future__ import annotations

import html
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import streamlit as st

from src.auth.account_reactivation_service import (
    AccountReactivationService,
)
from src.auth.email_change_service import (
    EMAIL_CHANGE_CODE_SENT_MESSAGE,
    EMAIL_CHANGE_DUPLICATE_MESSAGE,
    EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE,
    EMAIL_CHANGE_EXPIRED_CODE_MESSAGE,
    EMAIL_CHANGE_INVALID_CODE_MESSAGE,
    EMAIL_CHANGE_SEND_FAILED_MESSAGE,
    EmailChangeService,
)
from src.auth.email_verification_service import (
    EMAIL_VERIFICATION_SEND_FAILED_MESSAGE,
    EmailVerificationService,
)
from src.auth.google_oauth_service import (
    GOOGLE_OAUTH_TARGET_PAGE_KEY,
    GOOGLE_OAUTH_UNAVAILABLE_MESSAGE,
    GoogleOAuthError,
    GoogleOAuthService,
    store_oauth_state,
)
from src.auth.password_reset_service import (
    PASSWORD_RESET_INVALID_MESSAGE,
    PASSWORD_RESET_NEUTRAL_MESSAGE,
    PasswordResetService,
)
from src.auth.pending_registration_service import (
    PendingRegistrationService,
)
from src.auth.session import login_session, logout_session
from src.auth.security import MIN_PASSWORD_LENGTH
from src.auth.user_service import AuthValidationError, UserService, safe_auth_exception_summary
from src.auth.validation import validate_login_fields, validate_register_fields
from src.ui.notifications import queue_toast
from src.ui.sidebar import DEFAULT_PAGE, set_current_page

AUTH_UNAVAILABLE_MESSAGE = (
    "Não foi possível acessar a autenticação agora. Tente novamente em alguns instantes."
)

GOOGLE_SIGN_IN_UNAVAILABLE_MESSAGE = GOOGLE_OAUTH_UNAVAILABLE_MESSAGE
REGISTRATION_PUBLIC_NEUTRAL_MESSAGE = (
    "Se for possivel continuar com este e-mail, enviaremos instrucoes para ele."
)
REGISTRATION_PUBLIC_EMAIL_UNAVAILABLE_MESSAGE = (
    "O envio de e-mail ainda nao esta configurado. Nao foi possivel continuar agora."
)
CONFIRM_EMAIL_DESCRIPTION = "Digite o codigo enviado para seu e-mail para continuar."
CONFIRM_EMAIL_INVALID_MESSAGE = "Codigo invalido ou expirado."
CONFIRM_EMAIL_STALE_MESSAGE = "Codigo invalido ou expirado. Inicie o processo novamente."
CONFIRM_EMAIL_REACTIVATION_SUCCESS_MESSAGE = (
    "E-mail confirmado. Sua conta foi reativada. Voce ja pode entrar."
)
AUTH_MODAL_FEEDBACK_KEY = "auth_modal_feedback_message"
AUTH_MODAL_FEEDBACK_KIND_KEY = "auth_modal_feedback_kind"
AUTH_MODAL_PROCESSING_KEY = "auth_modal_processing_message"
PROFILE_SUBPANELS = {
    "change_name",
    "change_email",
    "confirm_email_change",
    "change_password",
    "deactivate_account",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistrationNextStep:
    status: str
    message: str
    panel: str | None = None
    email: str | None = None
    generic_error: bool = False
    pending_registration_id: int | None = None
    reactivation_token_id: int | None = None
    flow_kind: str | None = None


@dataclass(frozen=True)
class EmailCodeConfirmationResult:
    success: bool
    status: str
    message: str
    flow_kind: str | None = None
    user: Any | None = None
    generic_error: bool = False


def resolve_registration_next_step(result: Any, submitted_email: str) -> RegistrationNextStep:
    """Resolve o proximo painel do cadastro sem depender de excecoes da UI."""
    status = str(getattr(result, "status", "") or "unexpected_error")
    message = str(getattr(result, "message", "") or "")
    email = str(getattr(result, "email", "") or submitted_email or "").strip()

    if bool(getattr(result, "success", False)):
        return RegistrationNextStep(
            status="email_instructions_available",
            message=REGISTRATION_PUBLIC_NEUTRAL_MESSAGE,
            panel="confirm_email",
            email=email,
            pending_registration_id=getattr(result, "pending_registration_id", None),
            flow_kind="pending_registration",
        )

    if status == "active_email_exists":
        return RegistrationNextStep(
            status="email_instructions_available",
            message=REGISTRATION_PUBLIC_NEUTRAL_MESSAGE,
            panel="confirm_email",
            email=email,
            flow_kind="neutral",
        )

    if status == "deactivated_user_found":
        return RegistrationNextStep(
            status="email_instructions_available",
            message=REGISTRATION_PUBLIC_NEUTRAL_MESSAGE,
            panel="confirm_email",
            email=email,
            flow_kind="neutral",
        )

    if status == "email_not_sent":
        error_code = getattr(getattr(result, "send_result", None), "error_code", None)
        next_status = "email_sending_disabled" if error_code == "email_disabled" else "email_sending_failed"
        return RegistrationNextStep(
            status=next_status,
            message=REGISTRATION_PUBLIC_EMAIL_UNAVAILABLE_MESSAGE,
            email=email,
        )

    if status == "window_expired":
        return RegistrationNextStep(
            status="email_instructions_available",
            message=REGISTRATION_PUBLIC_NEUTRAL_MESSAGE,
            panel="confirm_email",
            email=email,
            flow_kind="neutral",
        )

    logger.warning(
        "Erro seguro cadastro_next_step | status=%s | tipo_resultado=%s",
        status,
        type(result).__name__,
    )
    return RegistrationNextStep(
        status="unexpected_error",
        message=AUTH_UNAVAILABLE_MESSAGE,
        email=email,
        generic_error=True,
    )


_REGISTER_STALE_STATE_KEYS = (
    "auth_error",
    "auth_global_error",
    "register_error",
    "registration_error",
    "reactivation_error",
    "auth_success",
    "registration_success",
    "reactivation_success",
    "registration_flow_kind",
    "registration_email",
    "pending_registration_id",
    "pending_registration_email",
    "account_reactivation_token_id",
    "account_reactivation_email",
)


def _clear_register_submit_state(session_state: Any) -> None:
    for key in _REGISTER_STALE_STATE_KEYS:
        session_state.pop(key, None)


def _clear_email_confirmation_state(session_state: Any) -> None:
    for key in (
        "registration_flow_kind",
        "registration_email",
        "pending_registration_id",
        "pending_registration_email",
        "account_reactivation_token_id",
        "account_reactivation_email",
    ):
        session_state.pop(key, None)


def _clear_pending_email_change_state(session_state: Any) -> None:
    for key in (
        "pending_email_change_id",
        "pending_email_change_user_id",
        "pending_email_change_new_email",
    ):
        session_state.pop(key, None)


def _registration_email_state(status: str) -> str:
    if status == "active_email_exists":
        return "active_user"
    if status == "email_instructions_available":
        return "handled_internally"
    return "unknown"


def _email_delivery_is_disabled(service: Any) -> bool:
    email_service = getattr(service, "email_service", None)
    config = getattr(email_service, "config", None)
    if config is None:
        return False

    provider = str(getattr(config, "provider", "") or "").strip().lower()
    return not bool(getattr(config, "enabled", False)) or provider in {"fake", "local", "dev"}


def handle_register_submit(
    session_state: Any,
    pending_registration_service: PendingRegistrationService,
    account_reactivation_service: AccountReactivationService,
    *,
    nome: str,
    email: str,
    senha: str,
    confirmar_senha: str,
) -> RegistrationNextStep:
    """Processa o submit real do cadastro e atualiza o estado da modal."""
    _clear_register_submit_state(session_state)

    if _email_delivery_is_disabled(pending_registration_service) or _email_delivery_is_disabled(account_reactivation_service):
        next_step = RegistrationNextStep(
            status="email_sending_disabled",
            message=REGISTRATION_PUBLIC_EMAIL_UNAVAILABLE_MESSAGE,
            email=email.strip(),
        )
        logger.info(
            "register_submit operation=register_submit decision_status=%s panel=%s error_code=%s email_state=%s",
            next_step.status,
            next_step.panel or "none",
            next_step.status,
            "not_checked",
        )
        return next_step

    try:
        result = pending_registration_service.start_registration(nome, email, senha, confirmar_senha)
    except AuthValidationError as exc:
        next_step = RegistrationNextStep(
            status="validation_error",
            message=exc.public_message,
            email=email.strip(),
        )
    except Exception as exc:
        logger.warning(
            "Erro seguro register_submit | operation=register_submit | error_code=unexpected_error | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        next_step = RegistrationNextStep(
            status="unexpected_error",
            message=AUTH_UNAVAILABLE_MESSAGE,
            email=email.strip(),
            generic_error=True,
        )
    else:
        result_status = str(getattr(result, "status", "") or "")
        if result_status == "deactivated_user_found":
            try:
                reactivation_result = account_reactivation_service.request_reactivation(email)
            except Exception as exc:
                logger.warning(
                    "Erro seguro register_submit | operation=register_submit | error_code=reactivation_request_failed | causa=%s | tipo=%s",
                    safe_auth_exception_summary(exc),
                    type(exc).__name__,
                )
                next_step = RegistrationNextStep(
                    status="unexpected_error",
                    message=AUTH_UNAVAILABLE_MESSAGE,
                    email=email.strip(),
                    generic_error=True,
                )
            else:
                if reactivation_result.success and reactivation_result.reactivation_token_id:
                    next_step = RegistrationNextStep(
                        status="email_instructions_available",
                        message=REGISTRATION_PUBLIC_NEUTRAL_MESSAGE,
                        panel="confirm_email",
                        email=reactivation_result.email or email.strip(),
                        reactivation_token_id=reactivation_result.reactivation_token_id,
                        flow_kind="reactivation",
                    )
                elif reactivation_result.status == "email_not_sent":
                    next_step = RegistrationNextStep(
                        status="email_sending_disabled",
                        message=REGISTRATION_PUBLIC_EMAIL_UNAVAILABLE_MESSAGE,
                        email=reactivation_result.email or email.strip(),
                    )
                else:
                    next_step = RegistrationNextStep(
                        status="email_instructions_available",
                        message=REGISTRATION_PUBLIC_NEUTRAL_MESSAGE,
                        panel="confirm_email",
                        email=reactivation_result.email or email.strip(),
                        flow_kind="neutral",
                    )
        else:
            next_step = resolve_registration_next_step(result, email)

    logger.info(
        "register_submit operation=register_submit decision_status=%s panel=%s error_code=%s email_state=%s",
        next_step.status,
        next_step.panel or "none",
        "none" if not next_step.generic_error else next_step.status,
        _registration_email_state(next_step.status),
    )

    if next_step.panel == "confirm_email":
        session_state["registration_flow_kind"] = next_step.flow_kind or "neutral"
        session_state["registration_email"] = next_step.email or email.strip()
    if next_step.pending_registration_id:
        session_state["pending_registration_id"] = next_step.pending_registration_id
        session_state["pending_registration_email"] = next_step.email or email.strip()
    if next_step.reactivation_token_id:
        session_state["account_reactivation_token_id"] = next_step.reactivation_token_id
        session_state["account_reactivation_email"] = next_step.email or email.strip()

    return next_step


def handle_email_code_confirmation(
    session_state: Any,
    pending_registration_service: PendingRegistrationService,
    account_reactivation_service: AccountReactivationService,
    *,
    code: str,
) -> EmailCodeConfirmationResult:
    """Confirma o codigo generico de e-mail usando o fluxo interno correto."""
    clean_code = (code or "").strip()
    if not clean_code:
        return EmailCodeConfirmationResult(
            False,
            "empty_code",
            "Informe o codigo enviado por e-mail.",
        )

    flow_kind = str(session_state.get("registration_flow_kind") or "").strip()

    if flow_kind == "pending_registration":
        pending_id = session_state.get("pending_registration_id")
        pending_email = session_state.get("pending_registration_email")
        if not pending_id or not pending_email:
            return EmailCodeConfirmationResult(False, "invalid_or_expired", CONFIRM_EMAIL_STALE_MESSAGE)

        try:
            result = pending_registration_service.confirm_registration_code(
                int(pending_id),
                str(pending_email),
                clean_code,
            )
        except AuthValidationError as exc:
            return EmailCodeConfirmationResult(False, "validation_error", exc.public_message, flow_kind=flow_kind)
        except Exception as exc:
            logger.warning(
                "Erro seguro confirmar_email | fluxo=pending_registration | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            return EmailCodeConfirmationResult(
                False,
                "unexpected_error",
                AUTH_UNAVAILABLE_MESSAGE,
                flow_kind=flow_kind,
                generic_error=True,
            )

        if not result.success:
            return EmailCodeConfirmationResult(
                False,
                str(result.status or "invalid_code"),
                result.message or CONFIRM_EMAIL_INVALID_MESSAGE,
                flow_kind=flow_kind,
            )
        if result.user is None:
            return EmailCodeConfirmationResult(
                False,
                "unexpected_error",
                AUTH_UNAVAILABLE_MESSAGE,
                flow_kind=flow_kind,
                generic_error=True,
            )

        _clear_email_confirmation_state(session_state)
        return EmailCodeConfirmationResult(
            True,
            str(result.status or "created"),
            result.message,
            flow_kind=flow_kind,
            user=result.user,
        )

    if flow_kind == "reactivation":
        token_id = session_state.get("account_reactivation_token_id")
        reactivation_email = session_state.get("account_reactivation_email")
        if not token_id or not reactivation_email:
            return EmailCodeConfirmationResult(False, "invalid_or_expired", CONFIRM_EMAIL_STALE_MESSAGE)

        try:
            result = account_reactivation_service.confirm_reactivation_code(
                int(token_id),
                str(reactivation_email),
                clean_code,
            )
        except AuthValidationError as exc:
            return EmailCodeConfirmationResult(False, "validation_error", exc.public_message, flow_kind=flow_kind)
        except Exception as exc:
            logger.warning(
                "Erro seguro confirmar_email | fluxo=reactivation | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            return EmailCodeConfirmationResult(
                False,
                "unexpected_error",
                AUTH_UNAVAILABLE_MESSAGE,
                flow_kind=flow_kind,
                generic_error=True,
            )

        if not result.success:
            friendly_message = (
                CONFIRM_EMAIL_INVALID_MESSAGE
                if result.status in {"invalid_code", "expired", "used"}
                else result.message
            )
            return EmailCodeConfirmationResult(
                False,
                str(result.status or "invalid_code"),
                friendly_message or CONFIRM_EMAIL_INVALID_MESSAGE,
                flow_kind=flow_kind,
            )
        if result.user is None:
            return EmailCodeConfirmationResult(
                False,
                "unexpected_error",
                AUTH_UNAVAILABLE_MESSAGE,
                flow_kind=flow_kind,
                generic_error=True,
            )

        _clear_email_confirmation_state(session_state)
        return EmailCodeConfirmationResult(
            True,
            str(result.status or "reactivated"),
            CONFIRM_EMAIL_REACTIVATION_SUCCESS_MESSAGE,
            flow_kind=flow_kind,
            user=result.user,
        )

    return EmailCodeConfirmationResult(False, "invalid_or_expired", CONFIRM_EMAIL_STALE_MESSAGE)

PROFILE_WIDGET_KEYS = (
    "auth-change-name-input",
    "auth-change-email-input",
    "auth-change-email-password-input",
    "auth-email-change-code-input",
    "auth-current-password-input",
    "auth-new-password-input",
    "auth-confirm-password-input",
    "auth-deactivate-email-input",
    "auth-reset-request-email-input",
    "auth-reset-new-password-input",
    "auth-reset-confirm-password-input",
    "auth-registration-code-input",
    "auth-reactivation-code-input",
)

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

    [data-testid="stDialog"] .auth-global-success,
    .auth-global-success {
        margin: -0.25rem 0 0.95rem;
        padding: 0.78rem 0.9rem;
        border: 1px solid #BBF7D0;
        border-radius: 0.85rem;
        background: #F0FDF4;
        color: #166534 !important;
        font-size: 0.9rem;
        font-weight: 760;
        line-height: 1.45;
    }

    [data-testid="stDialog"] .auth-global-success *,
    .auth-global-success * {
        color: #166534 !important;
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

    [data-testid="stDialog"] [data-testid="stTextInput"] button,
    [data-testid="stDialog"] [data-testid="stTextInput"] [role="button"] {
        min-width: 2.2rem !important;
        min-height: 2.2rem !important;
        width: 2.2rem !important;
        height: 2.2rem !important;
        margin-right: 0.24rem !important;
        border: 0 !important;
        border-radius: 999px !important;
        background: transparent !important;
        color: #64748B !important;
        box-shadow: none !important;
    }

    [data-testid="stDialog"] [data-testid="stTextInput"] button:hover,
    [data-testid="stDialog"] [data-testid="stTextInput"] button:focus,
    [data-testid="stDialog"] [data-testid="stTextInput"] [role="button"]:hover,
    [data-testid="stDialog"] [data-testid="stTextInput"] [role="button"]:focus {
        background: rgba(123, 44, 191, 0.08) !important;
        color: #4C1D95 !important;
        box-shadow: none !important;
    }

    [data-testid="stDialog"] [data-testid="stTextInput"]:has(input[type="password"]) button,
    [data-testid="stDialog"] [data-testid="stTextInput"]:has(input[type="password"]) [role="button"] {
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

    [data-testid="stDialog"] [data-testid="stTextInput"]:has(input[type="password"]) input {
        padding-right: 0.85rem !important;
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

    [data-testid="stDialog"] .st-key-auth-login-submit button,
    .st-key-auth-login-submit button {
        width: 100% !important;
        height: 2.85rem !important;
        min-height: 2.85rem !important;
        padding: 0 1rem !important;
        border: 0 !important;
        border-radius: 0.78rem !important;
        background: linear-gradient(135deg, #7B2CBF 0%, #2563EB 100%) !important;
        color: #FFFFFF !important;
        font-size: 0.96rem !important;
        font-weight: 800 !important;
        box-shadow: 0 12px 22px rgba(76, 29, 149, 0.20) !important;
        text-align: center !important;
    }

    [data-testid="stDialog"] .st-key-auth-login-submit button *,
    .st-key-auth-login-submit button * {
        color: #FFFFFF !important;
        fill: #FFFFFF !important;
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

    [data-testid="stDialog"] .st-key-auth-login-submit [data-testid="stButton"] button,
    [data-testid="stDialog"] .st-key-auth-login-submit button,
    .st-key-auth-login-submit [data-testid="stButton"] button,
    .st-key-auth-login-submit button {
        width: 100% !important;
        height: 2.85rem !important;
        min-height: 2.85rem !important;
        padding: 0 1rem !important;
        border: 0 !important;
        border-radius: 0.78rem !important;
        background: linear-gradient(135deg, #7B2CBF 0%, #2563EB 100%) !important;
        color: #FFFFFF !important;
        box-shadow: 0 12px 22px rgba(76, 29, 149, 0.20) !important;
        font-size: 0.96rem !important;
        font-weight: 800 !important;
        text-align: center !important;
    }

    [data-testid="stDialog"] .st-key-auth-login-submit [data-testid="stButton"] button *,
    [data-testid="stDialog"] .st-key-auth-login-submit button *,
    .st-key-auth-login-submit [data-testid="stButton"] button *,
    .st-key-auth-login-submit button * {
        color: #FFFFFF !important;
        fill: #FFFFFF !important;
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

    [data-testid="stDialog"] .st-key-auth-login-forgot-password,
    .st-key-auth-login-forgot-password {
        display: flex !important;
        justify-content: flex-end !important;
        margin: -0.08rem 0 0.28rem !important;
    }

    [data-testid="stDialog"] .st-key-auth-login-forgot-password button,
    .st-key-auth-login-forgot-password button {
        width: auto !important;
        min-height: 1.55rem !important;
        margin-top: 0 !important;
        padding: 0.08rem 0.18rem !important;
        border: 0 !important;
        border-radius: 0.45rem !important;
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

    .auth-login-divider {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin: 0.72rem 0 0.58rem;
        color: #94A3B8 !important;
        font-size: 0.82rem;
        font-weight: 760;
        text-transform: lowercase;
    }

    .auth-login-divider::before,
    .auth-login-divider::after {
        content: "";
        flex: 1;
        height: 1px;
        background: #E2E8F0;
    }

    [data-testid="stDialog"] .st-key-auth-login-google-action button,
    [data-testid="stDialog"] .st-key-auth-signup-google-action button,
    .st-key-auth-login-google-action button,
    .st-key-auth-signup-google-action button,
    [data-testid="stDialog"] [data-testid="stLinkButton"] a[href*="accounts.google.com"],
    [data-testid="stDialog"] a[href*="accounts.google.com"] {
        width: 100% !important;
        height: 2.72rem !important;
        min-height: 2.72rem !important;
        padding: 0 1rem !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 0.78rem !important;
        background: #FFFFFF !important;
        color: #334155 !important;
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06) !important;
        font-size: 0.94rem !important;
        font-weight: 780 !important;
        text-align: center !important;
        text-decoration: none !important;
    }

    [data-testid="stDialog"] .st-key-auth-login-google-action button:hover,
    [data-testid="stDialog"] .st-key-auth-login-google-action button:focus,
    [data-testid="stDialog"] .st-key-auth-signup-google-action button:hover,
    [data-testid="stDialog"] .st-key-auth-signup-google-action button:focus,
    .st-key-auth-login-google-action button:hover,
    .st-key-auth-login-google-action button:focus,
    .st-key-auth-signup-google-action button:hover,
    .st-key-auth-signup-google-action button:focus,
    [data-testid="stDialog"] [data-testid="stLinkButton"] a[href*="accounts.google.com"]:hover,
    [data-testid="stDialog"] [data-testid="stLinkButton"] a[href*="accounts.google.com"]:focus,
    [data-testid="stDialog"] a[href*="accounts.google.com"]:hover,
    [data-testid="stDialog"] a[href*="accounts.google.com"]:focus {
        background: #F8FAFC !important;
        border-color: rgba(100, 116, 139, 0.54) !important;
        color: #0F172A !important;
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.10) !important;
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
        grid-template-columns: repeat(2, minmax(0, 1fr));
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

    .auth-profile-email-status {
        display: inline-flex;
        align-items: center;
        width: fit-content;
        max-width: 100%;
        padding: 0.18rem 0.5rem;
        border-radius: 999px;
        font-size: 0.82rem;
        font-weight: 820;
        line-height: 1.25;
    }

    .auth-profile-email-status.is-verified {
        border: 1px solid #BBF7D0;
        background: #ECFDF3;
        color: #166534 !important;
    }

    .auth-profile-email-status.is-pending {
        border: 1px solid #FED7AA;
        background: #FFF7ED;
        color: #9A3412 !important;
    }

    .auth-profile-verification-note {
        margin: -0.55rem 0 1.05rem;
        padding: 0.82rem 0.9rem;
        border: 1px solid rgba(251, 146, 60, 0.34);
        border-radius: 0.9rem;
        background: #FFF7ED;
        color: #9A3412 !important;
        font-size: 0.9rem;
        line-height: 1.45;
    }

    [data-testid="stDialog"] .st-key-auth-profile-resend-verification button,
    .st-key-auth-profile-resend-verification button {
        width: auto !important;
        min-height: 2.35rem !important;
        margin: -0.55rem 0 1.05rem !important;
        padding: 0 0.9rem !important;
        border: 1px solid rgba(234, 88, 12, 0.28) !important;
        border-radius: 0.78rem !important;
        background: #FFFFFF !important;
        color: #9A3412 !important;
        box-shadow: none !important;
        font-size: 0.9rem !important;
        font-weight: 820 !important;
    }

    [data-testid="stDialog"] .st-key-auth-profile-resend-verification button:hover,
    [data-testid="stDialog"] .st-key-auth-profile-resend-verification button:focus,
    .st-key-auth-profile-resend-verification button:hover,
    .st-key-auth-profile-resend-verification button:focus {
        background: #FFEDD5 !important;
        color: #7C2D12 !important;
        box-shadow: 0 0 0 3px rgba(234, 88, 12, 0.10) !important;
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

    .auth-profile-action-card {
        min-height: 8.2rem;
        margin: 0 0 0.55rem;
        padding: 1rem;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #7B2CBF;
        border-radius: 1rem;
        background: #FFFFFF;
        box-shadow: 0 10px 22px rgba(15, 23, 42, 0.06);
        transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
    }

    .auth-profile-action-card:hover {
        border-color: rgba(37, 99, 235, 0.34);
        box-shadow: 0 13px 27px rgba(15, 23, 42, 0.09);
        transform: translateY(-1px);
    }

    .auth-profile-action-card::before {
        content: "";
        display: block;
        width: 0.58rem;
        height: 0.58rem;
        margin-bottom: 0.62rem;
        border-radius: 999px;
        background: linear-gradient(135deg, #7B2CBF, #2563EB);
        box-shadow: 0 0 0 4px rgba(123, 44, 191, 0.10);
    }

    .auth-profile-action-title {
        display: block;
        margin: 0 0 0.38rem;
        color: #0F172A !important;
        font-size: 0.98rem;
        font-weight: 840;
        line-height: 1.22;
    }

    .auth-profile-action-description {
        display: block;
        margin: 0;
        color: #64748B !important;
        font-size: 0.86rem;
        line-height: 1.42;
    }

    .auth-profile-danger-section {
        margin-top: 1.15rem;
        padding: 1rem;
        border: 1px solid #FECACA;
        border-radius: 1rem;
        background: #FEF2F2;
    }

    .auth-profile-danger-title {
        margin: 0;
        color: #991B1B !important;
        font-size: 1rem;
        font-weight: 840;
    }

    .auth-profile-danger-copy {
        margin: 0.3rem 0 0.8rem;
        color: #B42318 !important;
        font-size: 0.9rem;
        line-height: 1.45;
    }

    [data-testid="stDialog"] .st-key-auth-profile-change-name button,
    [data-testid="stDialog"] .st-key-auth-profile-change-email button,
    [data-testid="stDialog"] .st-key-auth-profile-change-password button,
    .st-key-auth-profile-change-name button,
    .st-key-auth-profile-change-email button,
    .st-key-auth-profile-change-password button {
        width: 100% !important;
        min-height: 2.55rem !important;
        padding: 0 0.9rem !important;
        border: 1px solid rgba(123, 44, 191, 0.34) !important;
        border-radius: 0.78rem !important;
        background: #F8FAFC !important;
        color: #4C1D95 !important;
        box-shadow: none !important;
        font-size: 0.92rem !important;
        font-weight: 820 !important;
        line-height: 1.2 !important;
        text-align: center !important;
        white-space: pre-line !important;
    }

    [data-testid="stDialog"] .st-key-auth-profile-change-name button:hover,
    [data-testid="stDialog"] .st-key-auth-profile-change-name button:focus,
    [data-testid="stDialog"] .st-key-auth-profile-change-email button:hover,
    [data-testid="stDialog"] .st-key-auth-profile-change-email button:focus,
    [data-testid="stDialog"] .st-key-auth-profile-change-password button:hover,
    [data-testid="stDialog"] .st-key-auth-profile-change-password button:focus,
    .st-key-auth-profile-change-name button:hover,
    .st-key-auth-profile-change-name button:focus,
    .st-key-auth-profile-change-email button:hover,
    .st-key-auth-profile-change-email button:focus,
    .st-key-auth-profile-change-password button:hover,
    .st-key-auth-profile-change-password button:focus {
        border-color: rgba(37, 99, 235, 0.34) !important;
        background: #FFFFFF !important;
        color: #4C1D95 !important;
        box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.10), 0 12px 26px rgba(15, 23, 42, 0.08) !important;
    }

    [data-testid="stDialog"] .st-key-auth-profile-deactivate button,
    .st-key-auth-profile-deactivate button {
        width: 100% !important;
        min-height: 2.75rem !important;
        border: 1px solid #FECACA !important;
        border-radius: 0.82rem !important;
        background: #FFFFFF !important;
        color: #991B1B !important;
        box-shadow: none !important;
        font-weight: 820 !important;
    }

    [data-testid="stDialog"] .st-key-auth-profile-deactivate button:hover,
    [data-testid="stDialog"] .st-key-auth-profile-deactivate button:focus,
    .st-key-auth-profile-deactivate button:hover,
    .st-key-auth-profile-deactivate button:focus {
        background: #FEE2E2 !important;
        color: #7F1D1D !important;
        box-shadow: 0 0 0 3px rgba(185, 28, 28, 0.10) !important;
    }

    [data-testid="stDialog"]:has(.auth-deactivate-panel) [data-testid="stFormSubmitButton"] button {
        background: #B42318 !important;
        box-shadow: 0 12px 22px rgba(153, 27, 27, 0.16) !important;
    }

    .st-key-auth-name-back button,
    .st-key-auth-password-back button,
    .st-key-auth-email-back button,
    .st-key-auth-deactivate-back button {
        margin-top: 0.55rem !important;
        width: 100% !important;
        min-height: 2.7rem !important;
        border: 1px solid rgba(123, 44, 191, 0.24) !important;
        border-radius: 0.78rem !important;
        background: #FFFFFF !important;
        color: #4C1D95 !important;
        font-weight: 780 !important;
    }

    [data-testid="stDialog"]:has(.auth-password-form-panel) [data-testid="stForm"] {
        max-width: 30rem !important;
        margin: 0 auto !important;
        padding: 0.35rem 0 0.55rem !important;
    }

    [data-testid="stDialog"]:has(.auth-password-form-panel) [data-testid="stTextInput"] {
        margin-bottom: 0.68rem !important;
    }

    [data-testid="stDialog"]:has(.auth-password-form-panel) input[type="password"] {
        min-height: 2.95rem !important;
        border-radius: 0.92rem !important;
        padding-left: 0.95rem !important;
        padding-right: 0.95rem !important;
        background: #FFFFFF !important;
        border-color: rgba(100, 116, 139, 0.26) !important;
    }

    [data-testid="stDialog"]:has(.auth-password-form-panel) [data-testid="stFormSubmitButton"] {
        margin-top: 0.62rem !important;
    }

    [data-testid="stDialog"] .st-key-auth-password-back,
    .st-key-auth-password-back {
        display: flex !important;
        justify-content: center !important;
        margin-top: 0.78rem !important;
    }

    [data-testid="stDialog"] .st-key-auth-password-back button,
    .st-key-auth-password-back button {
        width: auto !important;
        min-width: 11rem !important;
        min-height: 2.45rem !important;
        padding: 0 1.05rem !important;
        border: 1px solid rgba(123, 44, 191, 0.28) !important;
        border-radius: 999px !important;
        background: #FFFFFF !important;
        color: #5B21B6 !important;
        box-shadow: 0 8px 18px rgba(76, 29, 149, 0.07) !important;
        font-size: 0.9rem !important;
        font-weight: 780 !important;
    }

    [data-testid="stDialog"] .st-key-auth-password-back button:hover,
    [data-testid="stDialog"] .st-key-auth-password-back button:focus,
    .st-key-auth-password-back button:hover,
    .st-key-auth-password-back button:focus {
        background: #F8FAFC !important;
        border-color: rgba(37, 99, 235, 0.42) !important;
        color: #4C1D95 !important;
        box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.10) !important;
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


@st.cache_resource(show_spinner=False)
def _get_email_verification_service() -> EmailVerificationService:
    return EmailVerificationService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_email_change_service() -> EmailChangeService:
    return EmailChangeService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_password_reset_service() -> PasswordResetService:
    return PasswordResetService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_pending_registration_service() -> PendingRegistrationService:
    return PendingRegistrationService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_account_reactivation_service() -> AccountReactivationService:
    return AccountReactivationService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_google_oauth_service() -> GoogleOAuthService:
    return GoogleOAuthService.from_environment()


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
    _clear_modal_feedback(st.session_state)
    _clear_modal_processing()
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
    _clear_modal_feedback(st.session_state)
    _clear_modal_processing()
    st.session_state.pop("password_reset_token", None)
    st.session_state.pop("pending_registration_id", None)
    st.session_state.pop("pending_registration_email", None)
    st.session_state.pop("account_reactivation_token_id", None)
    st.session_state.pop("account_reactivation_email", None)
    _clear_pending_email_change_state(st.session_state)

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


def _clear_profile_form_state() -> None:
    for key in PROFILE_WIDGET_KEYS:
        st.session_state.pop(key, None)


def switch_profile_panel(panel: str) -> None:
    # Profile action clicks only change panels; persistence runs in form submits.
    _clear_profile_form_state()
    if panel not in {"confirm_email_change"}:
        _clear_pending_email_change_state(st.session_state)
    _clear_modal_feedback(st.session_state)
    _clear_modal_processing()
    set_auth_panel(panel)


def handle_profile_modal_close() -> None:
    if st.session_state.get("auth_panel") in PROFILE_SUBPANELS:
        _clear_profile_form_state()
        _clear_pending_email_change_state(st.session_state)
        st.session_state.pop(AUTH_MODAL_FEEDBACK_KEY, None)
        st.session_state.pop(AUTH_MODAL_FEEDBACK_KIND_KEY, None)
        set_auth_panel("profile")
        return

    close_auth_modal(redirect=False)


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


def _get_email_verification_service_or_none() -> EmailVerificationService | None:
    try:
        return _get_email_verification_service()
    except Exception as exc:
        logger.warning(
            "Erro seguro email_verification_service | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return None


def _get_email_change_service_or_none() -> EmailChangeService | None:
    try:
        return _get_email_change_service()
    except Exception as exc:
        logger.warning(
            "Erro seguro email_change_service | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return None


def _get_password_reset_service_or_none() -> PasswordResetService | None:
    try:
        return _get_password_reset_service()
    except Exception as exc:
        logger.warning(
            "Erro seguro password_reset_service | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return None


def _get_pending_registration_service_or_none() -> PendingRegistrationService | None:
    try:
        return _get_pending_registration_service()
    except Exception as exc:
        logger.warning(
            "Erro seguro pending_registration_service | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return None


def _get_account_reactivation_service_or_none() -> AccountReactivationService | None:
    try:
        return _get_account_reactivation_service()
    except Exception as exc:
        logger.warning(
            "Erro seguro account_reactivation_service | causa=%s | tipo=%s",
            safe_auth_exception_summary(exc),
            type(exc).__name__,
        )
        return None


def _get_google_oauth_service_or_none() -> GoogleOAuthService | None:
    try:
        return _get_google_oauth_service()
    except Exception as exc:
        logger.warning(
            "Erro seguro google_oauth_service | causa=%s | tipo=%s",
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
    _render_modal_feedback()


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


def _clear_modal_feedback(session_state: Any) -> None:
    session_state.pop(AUTH_MODAL_FEEDBACK_KEY, None)
    session_state.pop(AUTH_MODAL_FEEDBACK_KIND_KEY, None)


def set_modal_feedback(session_state: Any, message: str, kind: str = "success") -> None:
    session_state[AUTH_MODAL_FEEDBACK_KEY] = str(message)
    session_state[AUTH_MODAL_FEEDBACK_KIND_KEY] = kind if kind in {"success", "error", "info"} else "success"


def _start_modal_processing(message: str) -> None:
    st.session_state[AUTH_MODAL_PROCESSING_KEY] = message


def _clear_modal_processing() -> None:
    st.session_state.pop(AUTH_MODAL_PROCESSING_KEY, None)


def _is_modal_processing(message: str | None = None) -> bool:
    current_message = st.session_state.get(AUTH_MODAL_PROCESSING_KEY)
    if message is None:
        return bool(current_message)
    return current_message == message


def _processing_label(default_label: str, processing_label: str) -> str:
    return processing_label if _is_modal_processing(processing_label) else default_label


def _should_process(submitted: bool, processing_label: str) -> bool:
    return bool(submitted or _is_modal_processing(processing_label))


@contextmanager
def modal_action_processing(message: str):
    _start_modal_processing(message)
    try:
        with st.spinner(message):
            yield
    finally:
        _clear_modal_processing()


def _render_modal_feedback() -> None:
    message = st.session_state.pop(AUTH_MODAL_FEEDBACK_KEY, None)
    if not message:
        st.session_state.pop(AUTH_MODAL_FEEDBACK_KIND_KEY, None)
        return

    kind = st.session_state.pop(AUTH_MODAL_FEEDBACK_KIND_KEY, "success")
    if kind == "error":
        st.markdown(
            f'<section class="auth-global-error" role="alert">{_escape_text(message)}</section>',
            unsafe_allow_html=True,
        )
        return
    if kind == "info":
        st.markdown(
            f'<section class="auth-info-message">{_escape_text(message)}</section>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<section class="auth-global-success" role="status">{_escape_text(message)}</section>',
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
    if st.button(action_label, key=switch_key, use_container_width=True, disabled=_is_modal_processing()):
        switch_auth_modal_mode(switch_mode)
        st.rerun()
    st.markdown("</section>", unsafe_allow_html=True)


def _render_google_oauth_action(
    global_info_slot: Any,
    *,
    key: str,
    label: str = "G  Entrar com Google",
) -> None:
    service = _get_google_oauth_service_or_none()
    if service is not None and service.is_available():
        try:
            state = store_oauth_state(st.session_state)
            target_page = st.session_state.get("auth_target_page_on_success")
            if target_page:
                st.session_state[GOOGLE_OAUTH_TARGET_PAGE_KEY] = target_page
            auth_url = service.build_authorization_url(state)
        except GoogleOAuthError as exc:
            logger.warning(
                "Erro seguro google_oauth_url | code=%s",
                exc.error_code,
            )
            if st.button(label, key=key, use_container_width=True, disabled=_is_modal_processing()):
                _render_global_info(global_info_slot, exc.public_message)
            return
        except Exception as exc:
            logger.warning(
                "Erro seguro google_oauth_url | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            if st.button(label, key=key, use_container_width=True, disabled=_is_modal_processing()):
                _render_global_info(global_info_slot, GOOGLE_SIGN_IN_UNAVAILABLE_MESSAGE)
            return

        st.link_button(label, auth_url, use_container_width=True, disabled=_is_modal_processing())
        return

    if st.button(label, key=key, use_container_width=True, disabled=_is_modal_processing()):
        _render_global_info(global_info_slot, GOOGLE_SIGN_IN_UNAVAILABLE_MESSAGE)


def _render_profile_action_card(
    *,
    title: str,
    description: str,
    button_label: str,
    button_key: str,
    target_panel: str,
) -> None:
    st.markdown(
        f"""
        <section class="auth-profile-action-card">
            <span class="auth-profile-action-title">{_escape_text(title)}</span>
            <span class="auth-profile-action-description">{_escape_text(description)}</span>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if st.button(button_label, key=button_key, use_container_width=True, disabled=_is_modal_processing()):
        switch_profile_panel(target_panel)
        st.rerun()


def _render_login_panel() -> None:
    _render_auth_dialog_heading("Acesso ao Chat IA", "Entre para continuar usando o chat inteligente.")
    global_error_slot = st.empty()
    global_info_slot = st.empty()
    login_processing_label = "Entrando..."
    is_processing = _is_modal_processing()

    email = st.text_input("E-mail", placeholder="seu.email@exemplo.com")
    field_error_slots = {"email": st.empty()}
    senha = st.text_input("Senha", type="password", placeholder="Sua senha")
    field_error_slots["senha"] = st.empty()

    if st.button(
        "Esqueci minha senha",
        key="auth-login-forgot-password",
        use_container_width=False,
        disabled=is_processing,
    ):
        set_auth_panel("forgot_password")
        st.rerun()

    submitted = st.button(
        _processing_label("Entrar", login_processing_label),
        key="auth-login-submit",
        use_container_width=True,
        disabled=is_processing,
        on_click=_start_modal_processing,
        args=(login_processing_label,),
    )

    st.markdown('<div class="auth-login-divider">ou</div>', unsafe_allow_html=True)

    _render_google_oauth_action(global_info_slot, key="auth-login-google-action")

    _render_auth_footer(
        action_label="Criar conta",
        switch_mode="register",
        switch_key="auth-login-go-signup",
    )

    if _should_process(submitted, login_processing_label):
        try:
            field_errors = validate_login_fields(email, senha)
            if field_errors:
                _render_field_errors(field_error_slots, field_errors)
                return

            service = _get_auth_service_or_none()
            if service is None:
                _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
                return

            try:
                with modal_action_processing(login_processing_label):
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
        finally:
            _clear_modal_processing()


def _render_signup_panel() -> None:
    _render_auth_dialog_heading("Criar conta", "Preencha seus dados para acessar o Chat IA.")
    global_error_slot = st.empty()
    global_info_slot = st.empty()
    signup_processing_label = "Enviando codigo..."
    is_processing = _is_modal_processing()

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
        submitted = st.form_submit_button(
            _processing_label("Criar conta", signup_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(signup_processing_label,),
        )

    st.markdown('<div class="auth-login-divider">ou</div>', unsafe_allow_html=True)
    _render_google_oauth_action(global_info_slot, key="auth-signup-google-action", label="G  Criar conta com Google")

    _render_auth_footer(
        action_label="Entrar",
        switch_mode="login",
        switch_key="auth-signup-go-login",
    )

    if _should_process(submitted, signup_processing_label):
        try:
            field_errors = validate_register_fields(nome, email, senha, confirmar_senha)
            if field_errors:
                _render_field_errors(field_error_slots, field_errors)
                return

            service = _get_pending_registration_service_or_none()
            if service is None:
                _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
                return
            reactivation_service = _get_account_reactivation_service_or_none()
            if reactivation_service is None:
                _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
                return

            with modal_action_processing(signup_processing_label):
                next_step = handle_register_submit(
                    st.session_state,
                    service,
                    reactivation_service,
                    nome=nome,
                    email=email,
                    senha=senha,
                    confirmar_senha=confirmar_senha,
                )
            if next_step.panel == "confirm_email":
                set_auth_panel("confirm_email")
                st.rerun()
                return

            _render_global_error(global_error_slot, next_step.message)
        finally:
            _clear_modal_processing()


def _render_confirm_email_panel() -> None:
    _render_auth_dialog_heading(
        "Confirme seu e-mail",
        CONFIRM_EMAIL_DESCRIPTION,
    )
    global_error_slot = st.empty()
    confirm_processing_label = "Verificando codigo..."
    is_processing = _is_modal_processing()
    flow_kind = st.session_state.get("registration_flow_kind")
    pending_id = st.session_state.get("pending_registration_id")
    pending_email = st.session_state.get("pending_registration_email")
    token_id = st.session_state.get("account_reactivation_token_id")
    reactivation_email = st.session_state.get("account_reactivation_email")

    _render_global_info(
        global_error_slot,
        "Se houver instrucoes para este cadastro, elas foram enviadas ao e-mail informado.",
    )

    with st.form("auth-confirm-email-form", clear_on_submit=False):
        codigo = st.text_input(
            "Codigo",
            placeholder="000000",
            key="auth-registration-code-input",
        )
        field_error_slots = {"codigo": st.empty()}
        submitted = st.form_submit_button(
            _processing_label("Confirmar e-mail", confirm_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(confirm_processing_label,),
        )

    if st.button(
        "Voltar para entrar",
        key="auth-confirm-registration-go-login",
        use_container_width=True,
        disabled=is_processing,
    ):
        set_auth_panel("login")
        st.rerun()

    if not _should_process(submitted, confirm_processing_label):
        return

    try:
        if not (codigo or "").strip():
            _render_field_errors(field_error_slots, {"codigo": "Informe o codigo enviado por e-mail."})
            return

        pending_service = _get_pending_registration_service_or_none()
        reactivation_service = _get_account_reactivation_service_or_none()
        if pending_service is None or reactivation_service is None:
            _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
            return

        with modal_action_processing(confirm_processing_label):
            result = handle_email_code_confirmation(
                st.session_state,
                pending_service,
                reactivation_service,
                code=codigo,
            )
        if not result.success:
            _render_global_error(global_error_slot, result.message)
            return

        if result.flow_kind == "pending_registration":
            login_session(st.session_state, result.user)
            _finish_auth_success()
            queue_toast(st.session_state, result.message)
            st.rerun()
            return

        if result.flow_kind == "reactivation":
            set_auth_panel("login")
            set_modal_feedback(st.session_state, result.message)
            st.rerun()
            return

        _render_global_error(global_error_slot, CONFIRM_EMAIL_STALE_MESSAGE)
    finally:
        _clear_modal_processing()


def _render_confirm_registration_panel() -> None:
    _render_confirm_email_panel()


def _render_confirm_reactivation_panel() -> None:
    _render_confirm_email_panel()


def _render_forgot_password_panel() -> None:
    _render_auth_dialog_heading(
        "Recuperar senha",
        "Informe seu e-mail para solicitar instrucoes de recuperacao.",
    )

    global_info_slot = st.empty()
    global_error_slot = st.empty()
    reset_request_processing_label = "Enviando instrucoes..."
    is_processing = _is_modal_processing()

    with st.form("auth-password-reset-request-form", clear_on_submit=False):
        email = st.text_input(
            "E-mail",
            placeholder="seu.email@exemplo.com",
            key="auth-reset-request-email-input",
        )
        field_error_slots = {"email": st.empty()}
        submitted = st.form_submit_button(
            _processing_label("Enviar instrucoes", reset_request_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(reset_request_processing_label,),
        )

    if st.button("Voltar para entrar", key="auth-forgot-back-login", use_container_width=True, disabled=is_processing):
        set_auth_panel("login")
        st.rerun()

    if _should_process(submitted, reset_request_processing_label):
        try:
            field_errors = validate_login_fields(email, "senha-temporaria")
            if field_errors.get("email"):
                _render_field_errors(field_error_slots, {"email": field_errors["email"]})
                return

            service = _get_password_reset_service_or_none()
            if service is None:
                _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
                return

            try:
                with modal_action_processing(reset_request_processing_label):
                    result = service.request_password_reset(email)
            except Exception as exc:
                logger.warning(
                    "Erro seguro solicitar_recuperacao_senha | causa=%s | tipo=%s",
                    safe_auth_exception_summary(exc),
                    type(exc).__name__,
                )
                _render_global_info(global_info_slot, PASSWORD_RESET_NEUTRAL_MESSAGE)
            else:
                _render_global_info(global_info_slot, result.message)
        finally:
            _clear_modal_processing()


def _render_reset_password_panel() -> None:
    _render_auth_dialog_heading(
        "Redefinir senha",
        "Defina uma nova senha para acessar sua conta.",
    )

    reset_token = str(st.session_state.get("password_reset_token") or "").strip()
    global_error_slot = st.empty()
    reset_password_processing_label = "Redefinindo senha..."
    is_processing = _is_modal_processing()

    if not reset_token:
        _render_global_error(global_error_slot, PASSWORD_RESET_INVALID_MESSAGE)
        if st.button("Voltar para entrar", key="auth-reset-back-login-missing", use_container_width=True):
            st.session_state.pop("password_reset_token", None)
            set_auth_panel("login")
            st.rerun()
        return

    with st.form("auth-password-reset-confirm-form", clear_on_submit=True):
        nova_senha = st.text_input(
            "Nova senha",
            type="password",
            placeholder="No minimo 8 caracteres",
            key="auth-reset-new-password-input",
        )
        field_error_slots = {"nova_senha": st.empty()}
        confirmar_senha = st.text_input(
            "Confirmar nova senha",
            type="password",
            placeholder="Repita sua nova senha",
            key="auth-reset-confirm-password-input",
        )
        field_error_slots["confirmar_senha"] = st.empty()
        submitted = st.form_submit_button(
            _processing_label("Redefinir senha", reset_password_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(reset_password_processing_label,),
        )

    if st.button("Voltar para entrar", key="auth-reset-back-login", use_container_width=True, disabled=is_processing):
        st.session_state.pop("password_reset_token", None)
        set_auth_panel("login")
        st.rerun()

    if _should_process(submitted, reset_password_processing_label):
        try:
            field_errors: dict[str, str] = {}
            if not nova_senha:
                field_errors["nova_senha"] = "Informe a nova senha."
            elif len(nova_senha) < MIN_PASSWORD_LENGTH:
                field_errors["nova_senha"] = f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
            if not confirmar_senha or nova_senha != confirmar_senha:
                field_errors["confirmar_senha"] = "As senhas nao coincidem."
            if field_errors:
                _render_field_errors(field_error_slots, field_errors)
                return

            service = _get_password_reset_service_or_none()
            if service is None:
                _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
                return

            try:
                with modal_action_processing(reset_password_processing_label):
                    result = service.reset_password_with_token(reset_token, nova_senha, confirmar_senha)
            except AuthValidationError as exc:
                _render_global_error(global_error_slot, exc.public_message)
            except Exception as exc:
                logger.warning(
                    "Erro seguro redefinir_senha | causa=%s | tipo=%s",
                    safe_auth_exception_summary(exc),
                    type(exc).__name__,
                )
                _render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)
            else:
                if not result.success:
                    _render_global_error(global_error_slot, result.message)
                    return
                st.session_state.pop("password_reset_token", None)
                set_auth_panel("login")
                set_modal_feedback(st.session_state, result.message)
                st.rerun()
        finally:
            _clear_modal_processing()


def _render_profile_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    verification_service = _get_email_verification_service_or_none()
    email_verified = False
    email_status_label = "E-mail nao verificado"
    email_status_class = "is-pending"
    if verification_service is not None:
        try:
            email_verified = verification_service.is_email_verified(int(user["id"]))
            if email_verified:
                email_status_label = "E-mail verificado"
                email_status_class = "is-verified"
        except Exception as exc:
            logger.warning(
                "Erro seguro status_verificacao_email | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )

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
                        <span class="auth-profile-field-label">Status do e-mail</span>
                        <span class="auth-profile-email-status {email_status_class}">
                            {_escape_text(email_status_label)}
                        </span>
                    </div>
                </div>
            </div>
            <h3 class="auth-profile-section-title">Gerenciar conta</h3>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if not email_verified:
        resend_processing_label = "Enviando verificacao..."
        is_processing = _is_modal_processing()
        st.markdown(
            """
            <section class="auth-profile-verification-note">
                A verificacao de e-mail ainda nao e obrigatoria neste ambiente.
            </section>
            """,
            unsafe_allow_html=True,
        )
        submitted_resend = st.button(
            _processing_label("Reenviar verificacao", resend_processing_label),
            key="auth-profile-resend-verification",
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(resend_processing_label,),
        )
        if _should_process(submitted_resend, resend_processing_label):
            try:
                if verification_service is None:
                    set_modal_feedback(st.session_state, EMAIL_VERIFICATION_SEND_FAILED_MESSAGE, "error")
                else:
                    try:
                        with modal_action_processing(resend_processing_label):
                            verification_result = verification_service.resend_verification_email(int(user["id"]))
                        set_modal_feedback(st.session_state, verification_result.message)
                    except Exception as exc:
                        logger.warning(
                            "Erro seguro reenviar_verificacao_email | causa=%s | tipo=%s",
                            safe_auth_exception_summary(exc),
                            type(exc).__name__,
                        )
                        set_modal_feedback(st.session_state, EMAIL_VERIFICATION_SEND_FAILED_MESSAGE, "error")
                st.rerun()
            finally:
                _clear_modal_processing()

    action_columns = st.columns(3, gap="small")
    with action_columns[0]:
        _render_profile_action_card(
            title="Alterar nome",
            description="Atualize o nome exibido na sua conta.",
            button_label="Alterar nome",
            button_key="auth-profile-change-name",
            target_panel="change_name",
        )
    with action_columns[1]:
        _render_profile_action_card(
            title="Alterar e-mail",
            description="Atualize o e-mail usado para acessar sua conta.",
            button_label="Alterar e-mail",
            button_key="auth-profile-change-email",
            target_panel="change_email",
        )
    with action_columns[2]:
        _render_profile_action_card(
            title="Alterar senha",
            description="Troque sua senha de acesso com seguranca.",
            button_label="Alterar senha",
            button_key="auth-profile-change-password",
            target_panel="change_password",
        )

    st.markdown(
        """
        <section class="auth-profile-danger-section">
            <h3 class="auth-profile-danger-title">Zona de seguranca</h3>
            <p class="auth-profile-danger-copy">
                Sua conta sera ocultada e voce nao podera mais acessar o Chat IA
                com este login.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Desativar conta", key="auth-profile-deactivate", use_container_width=True):
        switch_profile_panel("deactivate_account")
        st.rerun()


def _render_change_name_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    st.markdown('<section class="auth-profile-form-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading("Alterar nome", "Atualize o nome exibido na sua conta.")

    global_slot = st.empty()
    save_name_processing_label = "Salvando..."
    is_processing = _is_modal_processing()

    with st.form("auth-change-name-form", clear_on_submit=False):
        nome = st.text_input("Nome", value=user["nome"], key="auth-change-name-input")
        field_error_slots = {"nome": st.empty()}
        submitted = st.form_submit_button(
            _processing_label("Salvar nome", save_name_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(save_name_processing_label,),
        )

    if st.button("Voltar ao perfil", key="auth-name-back", use_container_width=True, disabled=is_processing):
        switch_profile_panel("profile")
        st.rerun()

    if _should_process(submitted, save_name_processing_label):
        try:
            if not (nome or "").strip():
                _render_field_errors(field_error_slots, {"nome": "Informe o novo nome."})
                return

            service = _get_auth_service_or_none()
            if service is None:
                _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
                return

            try:
                with modal_action_processing(save_name_processing_label):
                    updated_user = service.update_name(int(user["id"]), nome)
            except AuthValidationError as exc:
                _render_global_error(global_slot, exc.public_message)
            except Exception as exc:
                logger.warning(
                    "Erro seguro alterar_nome | causa=%s | tipo=%s",
                    safe_auth_exception_summary(exc),
                    type(exc).__name__,
                )
                _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
            else:
                login_session(st.session_state, updated_user)
                switch_profile_panel("profile")
                set_modal_feedback(st.session_state, "Nome atualizado com sucesso.")
                st.rerun()
        finally:
            _clear_modal_processing()


def _render_change_password_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    st.markdown('<section class="auth-profile-form-panel auth-password-form-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading(
        "Alterar senha",
        "Informe a senha atual antes de definir uma nova senha.",
    )

    global_slot = st.empty()
    save_password_processing_label = "Alterando senha..."
    is_processing = _is_modal_processing()

    with st.form("auth-change-password-form", clear_on_submit=True):
        senha_atual = st.text_input("Senha atual", type="password", key="auth-current-password-input")
        field_error_slots = {"senha_atual": st.empty()}
        nova_senha = st.text_input(
            "Nova senha",
            type="password",
            placeholder="No mínimo 8 caracteres",
            key="auth-new-password-input",
        )
        field_error_slots["nova_senha"] = st.empty()
        confirmar_senha = st.text_input(
            "Confirmar nova senha",
            type="password",
            key="auth-confirm-password-input",
        )
        field_error_slots["confirmar_senha"] = st.empty()
        submitted = st.form_submit_button(
            _processing_label("Salvar senha", save_password_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(save_password_processing_label,),
        )

    if st.button("Voltar ao perfil", key="auth-password-back", use_container_width=False, disabled=is_processing):
        switch_profile_panel("profile")
        st.rerun()

    if _should_process(submitted, save_password_processing_label):
        field_errors: dict[str, str] = {}
        if not senha_atual:
            field_errors["senha_atual"] = "Informe sua senha atual."
        if not nova_senha:
            field_errors["nova_senha"] = "Informe uma nova senha."
        elif len(nova_senha) < MIN_PASSWORD_LENGTH:
            field_errors["nova_senha"] = f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."
        if not confirmar_senha:
            field_errors["confirmar_senha"] = "Confirme sua nova senha."
        elif nova_senha and nova_senha != confirmar_senha:
            field_errors["confirmar_senha"] = "As senhas não coincidem."
        if field_errors:
            _render_field_errors(field_error_slots, field_errors)
            _clear_modal_processing()
            return

        service = _get_auth_service_or_none()
        if service is None:
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
            _clear_modal_processing()
            return

        try:
            with modal_action_processing(save_password_processing_label):
                service.change_password(
                    int(user["id"]),
                    senha_atual,
                    nova_senha,
                    confirmar_senha,
                )
        except AuthValidationError as exc:
            _render_global_error(global_slot, exc.public_message)
        except Exception as exc:
            logger.warning(
                "Erro seguro alterar_senha | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
        else:
            switch_profile_panel("profile")
            set_modal_feedback(st.session_state, "Senha alterada com sucesso.")
            st.rerun()


def _render_change_email_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    st.markdown('<section class="auth-profile-form-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading(
        "Alterar e-mail",
        "Confirme o novo e-mail antes de atualizar sua conta.",
    )

    global_slot = st.empty()
    save_email_processing_label = "Enviando codigo..."
    is_processing = _is_modal_processing()

    with st.form("auth-change-email-form", clear_on_submit=False):
        st.markdown(
            f"""
            <section class="auth-dialog-profile">
                <p>E-mail atual: <strong>{_escape_text(user["email"])}</strong></p>
                <p>O e-mail da conta so sera alterado depois que voce informar o codigo enviado ao novo endereco.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        novo_email = st.text_input(
            "Novo e-mail",
            placeholder="novo.email@exemplo.com",
            key="auth-change-email-input",
        )
        field_error_slots = {"email": st.empty()}
        senha_atual = st.text_input(
            "Senha atual",
            type="password",
            placeholder="Confirme sua senha",
            key="auth-change-email-password-input",
        )
        field_error_slots["senha_atual"] = st.empty()
        submitted = st.form_submit_button(
            _processing_label("Enviar codigo", save_email_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(save_email_processing_label,),
        )

    if st.button("Voltar ao perfil", key="auth-email-back", use_container_width=True, disabled=is_processing):
        switch_profile_panel("profile")
        st.rerun()

    if _should_process(submitted, save_email_processing_label):
        field_errors = validate_login_fields(novo_email, "senha-temporaria")
        if field_errors.get("email"):
            _render_field_errors(field_error_slots, {"email": field_errors["email"]})
            _clear_modal_processing()
            return
        if not senha_atual:
            _render_field_errors(field_error_slots, {"senha_atual": "Informe sua senha atual."})
            _clear_modal_processing()
            return

        clean_email = novo_email.strip().casefold()
        if clean_email == str(user["email"]).strip().casefold():
            _render_field_errors(field_error_slots, {"email": "Informe um e-mail diferente do atual."})
            _clear_modal_processing()
            return

        service = _get_email_change_service_or_none()
        if service is None:
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
            _clear_modal_processing()
            return

        try:
            with modal_action_processing(save_email_processing_label):
                result = service.request_email_change(int(user["id"]), clean_email, senha_atual)
        except AuthValidationError as exc:
            public_message = exc.public_message
            normalized_message = public_message.casefold()
            if "existe" in normalized_message and "e-mail" in normalized_message:
                public_message = EMAIL_CHANGE_DUPLICATE_MESSAGE
            _render_global_error(global_slot, public_message)
        except Exception as exc:
            logger.warning(
                "Erro seguro alterar_email | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
        else:
            if result.success:
                st.session_state.pending_email_change_id = result.pending_change_id
                st.session_state.pending_email_change_user_id = result.user_id
                st.session_state.pending_email_change_new_email = result.new_email
                set_modal_feedback(st.session_state, result.message or EMAIL_CHANGE_CODE_SENT_MESSAGE, "success")
                set_auth_panel("confirm_email_change")
                st.rerun()
            elif result.status == "duplicate_email":
                _render_global_error(global_slot, EMAIL_CHANGE_DUPLICATE_MESSAGE)
            elif result.status == "email_disabled":
                _render_global_error(global_slot, EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE)
            elif result.status == "send_failed":
                _render_global_error(global_slot, EMAIL_CHANGE_SEND_FAILED_MESSAGE)
            else:
                _render_global_error(global_slot, result.message)


def _render_confirm_email_change_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    pending_change_id = st.session_state.get("pending_email_change_id")
    pending_user_id = st.session_state.get("pending_email_change_user_id")
    new_email = st.session_state.get("pending_email_change_new_email")
    if not pending_change_id or not pending_user_id or int(pending_user_id) != int(user["id"]):
        set_modal_feedback(st.session_state, "Codigo invalido ou expirado. Solicite um novo codigo.", "error")
        switch_profile_panel("profile")
        st.rerun()
        return

    st.markdown('<section class="auth-profile-form-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading(
        "Confirmar novo e-mail",
        "Digite o codigo enviado para o novo e-mail para concluir a alteracao.",
    )

    global_slot = st.empty()
    confirm_processing_label = "Verificando codigo..."
    is_processing = _is_modal_processing()

    with st.form("auth-confirm-email-change-form", clear_on_submit=False):
        st.markdown(
            f"""
            <section class="auth-dialog-profile">
                <p>Novo e-mail: <strong>{_escape_text(new_email or "")}</strong></p>
                <p>O e-mail atual permanece em uso ate a confirmacao do codigo.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        codigo = st.text_input(
            "Codigo",
            placeholder="000000",
            key="auth-email-change-code-input",
        )
        field_error_slots = {"codigo": st.empty()}
        submitted = st.form_submit_button(
            _processing_label("Confirmar novo e-mail", confirm_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(confirm_processing_label,),
        )

    if st.button("Voltar ao perfil", key="auth-email-change-back", use_container_width=True, disabled=is_processing):
        switch_profile_panel("profile")
        st.rerun()

    if _should_process(submitted, confirm_processing_label):
        if not (codigo or "").strip():
            _render_field_errors(field_error_slots, {"codigo": "Informe o codigo enviado por e-mail."})
            _clear_modal_processing()
            return

        service = _get_email_change_service_or_none()
        if service is None:
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
            _clear_modal_processing()
            return

        try:
            with modal_action_processing(confirm_processing_label):
                result = service.confirm_email_change_code(
                    int(pending_change_id),
                    int(user["id"]),
                    codigo,
                )
        except Exception as exc:
            logger.warning(
                "Erro seguro confirmar_alteracao_email | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
        else:
            if result.success and result.user is not None:
                login_session(st.session_state, result.user)
                _clear_pending_email_change_state(st.session_state)
                switch_profile_panel("profile")
                set_modal_feedback(st.session_state, result.message)
                st.rerun()
            elif result.status == "invalid_code":
                _render_global_error(global_slot, EMAIL_CHANGE_INVALID_CODE_MESSAGE)
            elif result.status == "expired":
                _render_global_error(global_slot, EMAIL_CHANGE_EXPIRED_CODE_MESSAGE)
            else:
                _render_global_error(global_slot, result.message)


def _render_deactivate_account_panel() -> None:
    user = st.session_state.get("auth_user")
    if not isinstance(user, dict) or not user.get("id"):
        set_auth_panel("login")
        return

    st.markdown('<section class="auth-profile-form-panel auth-deactivate-panel"></section>', unsafe_allow_html=True)
    _render_auth_dialog_heading(
        "Desativar conta",
        "Confirme a desativacao para encerrar seu acesso a esta conta.",
    )
    st.markdown(
        f"""
        <section class="auth-dialog-profile">
            <p>
                Para confirmar, digite seu e-mail:
                <strong>{_escape_text(user["email"])}</strong>
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    global_slot = st.empty()
    deactivate_processing_label = "Desativando..."
    is_processing = _is_modal_processing()

    with st.form("auth-deactivate-account-form", clear_on_submit=False):
        confirmar_email = st.text_input(
            "Confirme seu e-mail",
            placeholder=user["email"],
            key="auth-deactivate-email-input",
        )
        field_error_slots = {"email": st.empty()}
        submitted = st.form_submit_button(
            _processing_label("Desativar conta", deactivate_processing_label),
            use_container_width=True,
            disabled=is_processing,
            on_click=_start_modal_processing,
            args=(deactivate_processing_label,),
        )

    if st.button("Voltar ao perfil", key="auth-deactivate-back", use_container_width=True, disabled=is_processing):
        switch_profile_panel("profile")
        st.rerun()

    if _should_process(submitted, deactivate_processing_label):
        expected_email = str(user["email"]).strip().casefold()
        typed_email = confirmar_email.strip().casefold()
        if typed_email != expected_email:
            _render_field_errors(field_error_slots, {"email": "Digite seu e-mail para confirmar a desativacao."})
            _clear_modal_processing()
            return

        service = _get_auth_service_or_none()
        if service is None:
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
            _clear_modal_processing()
            return

        try:
            with modal_action_processing(deactivate_processing_label):
                service.soft_delete_user(int(user["id"]))
        except AuthValidationError as exc:
            _render_global_error(global_slot, exc.public_message)
        except Exception as exc:
            logger.warning(
                "Erro seguro desativar_conta | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _render_global_error(global_slot, AUTH_UNAVAILABLE_MESSAGE)
        else:
            close_auth_panel(redirect=False)
            logout_session(st.session_state)
            set_current_page(DEFAULT_PAGE)
            queue_toast(st.session_state, "Conta desativada com sucesso.")
            st.rerun()


@st.dialog("Acesso ao Chat IA", width="small", on_dismiss=_clear_auth_panel)
def _render_auth_dialog() -> None:
    mode = st.session_state.get("auth_modal_mode", "login")
    if mode in {"signup", "register"}:
        _render_signup_panel()
    else:
        _render_login_panel()


@st.dialog("Meu perfil", width="large", on_dismiss=handle_profile_modal_close)
def _render_profile_dialog() -> None:
    _render_profile_panel()


@st.dialog("Alterar nome", width="large", on_dismiss=handle_profile_modal_close)
def _render_change_name_dialog() -> None:
    _render_change_name_panel()


@st.dialog("Alterar senha", width="large", on_dismiss=handle_profile_modal_close)
def _render_change_password_dialog() -> None:
    _render_change_password_panel()


@st.dialog("Alterar e-mail", width="large", on_dismiss=handle_profile_modal_close)
def _render_change_email_dialog() -> None:
    _render_change_email_panel()


@st.dialog("Confirmar novo e-mail", width="large", on_dismiss=handle_profile_modal_close)
def _render_confirm_email_change_dialog() -> None:
    _render_confirm_email_change_panel()


@st.dialog("Recuperar senha", width="small", on_dismiss=_clear_auth_panel)
def _render_forgot_password_dialog() -> None:
    _render_forgot_password_panel()


@st.dialog("Confirmar e-mail", width="small", on_dismiss=_clear_auth_panel)
def _render_confirm_registration_dialog() -> None:
    _render_confirm_registration_panel()


@st.dialog("Confirmar e-mail", width="small", on_dismiss=_clear_auth_panel)
def _render_confirm_reactivation_dialog() -> None:
    _render_confirm_reactivation_panel()


@st.dialog("Redefinir senha", width="small", on_dismiss=_clear_auth_panel)
def _render_reset_password_dialog() -> None:
    _render_reset_password_panel()


@st.dialog("Desativar conta", width="large", on_dismiss=handle_profile_modal_close)
def _render_deactivate_account_dialog() -> None:
    _render_deactivate_account_panel()


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
    elif panel == "confirm_email_change":
        _render_confirm_email_change_dialog()
    elif panel == "forgot_password":
        _render_forgot_password_dialog()
    elif panel in {"confirm_email", "confirm_registration"}:
        _render_confirm_registration_dialog()
    elif panel == "confirm_reactivation":
        _render_confirm_reactivation_dialog()
    elif panel == "reset_password":
        _render_reset_password_dialog()
    elif panel == "deactivate_account":
        _render_deactivate_account_dialog()
