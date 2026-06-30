"""Header autenticado da interface Streamlit."""

from __future__ import annotations

import html
import logging
from contextlib import nullcontext
from typing import Any

import streamlit as st

from src.auth.session import get_authenticated_user, logout_session
from src.ui.auth_modal import open_auth_modal, set_auth_panel
from src.ui.notifications import queue_toast

logger = logging.getLogger(__name__)


HEADER_CSS = """
<style>
    .st-key-auth-header-actions [data-testid="stPopover"] > button,
    .st-key-auth-header-actions [data-testid="stPopover"] button,
    .st-key-auth-header-actions [data-testid="stPopover"] [role="button"],
    .st-key-auth-header-actions [data-testid="stPopover"] [data-testid="baseButton-secondary"] {
        border: 1px solid rgba(123, 44, 191, 0.20) !important;
        border-radius: 0.85rem !important;
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
        color: #4C1D95 !important;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.07) !important;
        font-weight: 740 !important;
        min-height: 2.45rem !important;
    }

    .st-key-auth-header-actions [data-testid="stPopover"] > button *,
    .st-key-auth-header-actions [data-testid="stPopover"] button *,
    .st-key-auth-header-actions [data-testid="stPopover"] [role="button"] *,
    .st-key-auth-header-actions [data-testid="stPopover"] [data-testid="baseButton-secondary"] * {
        color: #4C1D95 !important;
    }

    .st-key-auth-header-actions [data-testid="stPopover"] > button:hover,
    .st-key-auth-header-actions [data-testid="stPopover"] > button:focus,
    .st-key-auth-header-actions [data-testid="stPopover"] button:hover,
    .st-key-auth-header-actions [data-testid="stPopover"] button:focus,
    .st-key-auth-header-actions [data-testid="stPopover"] [role="button"]:hover,
    .st-key-auth-header-actions [data-testid="stPopover"] [role="button"]:focus,
    .st-key-auth-header-actions [data-testid="stPopover"] [data-testid="baseButton-secondary"]:hover,
    .st-key-auth-header-actions [data-testid="stPopover"] [data-testid="baseButton-secondary"]:focus {
        border-color: rgba(37, 99, 235, 0.34) !important;
        background: #F8FAFC !important;
        background-color: #F8FAFC !important;
        color: #2563EB !important;
        box-shadow: 0 10px 22px rgba(76, 29, 149, 0.10) !important;
    }

    [data-testid="stPopoverBody"] {
        min-width: 13.25rem !important;
        padding: 0.55rem !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 0.9rem !important;
        background: #FFFFFF !important;
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        box-shadow: 0 16px 34px rgba(15, 23, 42, 0.13) !important;
    }

    [data-testid="stPopoverBody"] *,
    [data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] *,
    .profile-menu,
    .profile-menu * {
        color: #0F172A !important;
    }

    .profile-menu {
        display: grid;
        gap: 0.4rem;
        min-width: 12.25rem;
        background: #FFFFFF !important;
    }

    .profile-menu-email {
        margin: 0 0 0.08rem;
        color: #64748B !important;
        font-size: 0.8rem;
        line-height: 1.25;
        word-break: break-word;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-profile button,
    .st-key-auth-menu-profile button {
        width: 100% !important;
        min-height: 2.18rem !important;
        border: 1px solid rgba(123, 44, 191, 0.18) !important;
        border-radius: 0.65rem !important;
        background: #FFFFFF !important;
        color: #4C1D95 !important;
        box-shadow: none !important;
        font-size: 0.86rem !important;
        font-weight: 680 !important;
        padding: 0.34rem 0.65rem !important;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-profile button *,
    .st-key-auth-menu-profile button * {
        color: #4C1D95 !important;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-profile button:hover,
    [data-testid="stPopoverBody"] .st-key-auth-menu-profile button:focus,
    .st-key-auth-menu-profile button:hover,
    .st-key-auth-menu-profile button:focus {
        border-color: rgba(37, 99, 235, 0.38) !important;
        background: #F8FAFC !important;
        color: #2563EB !important;
        box-shadow: 0 0 0 2px rgba(123, 44, 191, 0.08) !important;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-profile button:hover *,
    [data-testid="stPopoverBody"] .st-key-auth-menu-profile button:focus *,
    .st-key-auth-menu-profile button:hover *,
    .st-key-auth-menu-profile button:focus * {
        color: #2563EB !important;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-logout button,
    .st-key-auth-menu-logout button {
        width: 100% !important;
        min-height: 2.18rem !important;
        border: 1px solid #FECACA !important;
        border-radius: 0.65rem !important;
        background: #FEF2F2 !important;
        color: #B42318 !important;
        box-shadow: none !important;
        font-size: 0.86rem !important;
        font-weight: 700 !important;
        padding: 0.34rem 0.65rem !important;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-logout button *,
    .st-key-auth-menu-logout button * {
        color: #B42318 !important;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-logout button:hover,
    [data-testid="stPopoverBody"] .st-key-auth-menu-logout button:focus,
    .st-key-auth-menu-logout button:hover,
    .st-key-auth-menu-logout button:focus {
        border-color: #FCA5A5 !important;
        background: #FEE2E2 !important;
        color: #991B1B !important;
        box-shadow: 0 0 0 2px rgba(180, 35, 24, 0.08) !important;
    }

    [data-testid="stPopoverBody"] .st-key-auth-menu-logout button:hover *,
    [data-testid="stPopoverBody"] .st-key-auth-menu-logout button:focus *,
    .st-key-auth-menu-logout button:hover *,
    .st-key-auth-menu-logout button:focus * {
        color: #991B1B !important;
    }
</style>
"""


def _escape_text(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _render_header_style() -> None:
    st.markdown(HEADER_CSS, unsafe_allow_html=True)


def _auth_header_actions_container():
    try:
        return st.container(key="auth-header-actions")
    except (AttributeError, TypeError):
        return nullcontext()


def _log_logout_audit(user: dict[str, Any]) -> None:
    try:
        from src.audit.audit_log_service import AuditLogService, EVENT_LOGOUT

        AuditLogService.from_environment().log_event(
            EVENT_LOGOUT,
            user_id=int(user["id"]) if user.get("id") else None,
            user_email=user.get("email"),
            detalhe="logout_usuario",
            status="info",
            source="auth",
            action="logout",
        )
    except Exception as exc:
        logger.warning("Erro seguro audit_logout | tipo=%s", type(exc).__name__)


def render_auth_header() -> None:
    _render_header_style()
    user = get_authenticated_user(st.session_state)
    left_column, right_column = st.columns([7, 2], vertical_alignment="center")

    with left_column:
        if user:
            st.markdown(
                f"""
                <div class="top-auth-bar">
                    <div>
                        <p class="top-auth-title">Sessão ativa</p>
                        <p class="top-auth-user">{_escape_text(user["nome"])}</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="top-auth-bar">
                    <div>
                        <p class="top-auth-title">Áreas públicas liberadas</p>
                        <p class="top-auth-user">Entre para usar o chat inteligente</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right_column:
        with _auth_header_actions_container():
            if not user:
                if st.button("Entrar", key="auth-header-login", use_container_width=True):
                    open_auth_modal(mode="login")
                    st.rerun()
                return

            profile_label = _escape_text(user.get("nome") or "Perfil")
            with st.popover(f"Perfil · {profile_label}", use_container_width=True):
                st.markdown('<div class="profile-menu">', unsafe_allow_html=True)
                st.markdown(
                    f'<p class="profile-menu-email">{_escape_text(user["email"])}</p>',
                    unsafe_allow_html=True,
                )
                if st.button("Meu perfil", key="auth-menu-profile", use_container_width=True):
                    set_auth_panel("profile")
                    st.rerun()
                if st.button("Sair", key="auth-menu-logout", use_container_width=True):
                    _log_logout_audit(user)
                    logout_session(st.session_state)
                    set_auth_panel(None)
                    queue_toast(st.session_state, "Sessão encerrada.")
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
