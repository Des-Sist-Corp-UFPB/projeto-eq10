"""Sidebar e estado de navegacao principal."""

from __future__ import annotations

import base64
import html
import logging
from pathlib import Path
from typing import Any

import streamlit as st

from src.auth.roles import can_view_audit_log
from src.auth.session import get_authenticated_user
from src.ui.styles import get_configured_logo_url

logger = logging.getLogger(__name__)

DEFAULT_PAGE = "Estatísticas"
CHAT_PAGE = "Chat IA"
ADMIN_PAGE = "Auditoria"
BASE_DIR = Path(__file__).resolve().parents[2]
LOGO_PATH = BASE_DIR / "images" / "logo.png"

PAGE_SLUGS = {
    "estatisticas": DEFAULT_PAGE,
    "chat-ia": CHAT_PAGE,
    "auditoria": ADMIN_PAGE,
    "uso-restrito": ADMIN_PAGE,
}
PAGE_TO_SLUG = {
    DEFAULT_PAGE: "estatisticas",
    CHAT_PAGE: "chat-ia",
    ADMIN_PAGE: "auditoria",
}


def _escape_text(value: Any) -> str:
    return html.escape(str(value), quote=False)


@st.cache_data(show_spinner=False)
def _get_sidebar_logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""

    encoded_logo = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_logo}"


def _get_sidebar_logo_source() -> str:
    """Return the first configured logo source for tests and fallback-aware callers."""
    return get_configured_logo_url() or _get_sidebar_logo_data_uri()


def _sidebar_logo_markup() -> str:
    configured_logo_url = get_configured_logo_url()
    local_logo = _get_sidebar_logo_data_uri()

    if not configured_logo_url and not local_logo:
        logger.debug("Sidebar logo URL/local logo not available; using text fallback.")
        return '<span class="brand-logo-fallback">SM</span>'

    if not configured_logo_url:
        safe_local_logo = html.escape(local_logo, quote=True)
        return (
            f'<img class="brand-logo" src="{safe_local_logo}" alt="Brasao de Mamanguape" '
            'onerror="this.hidden=true;this.nextElementSibling.hidden=false;">'
            '<span class="brand-logo-fallback" hidden>SM</span>'
        )

    safe_logo_source = html.escape(configured_logo_url, quote=True)
    if not local_logo:
        return (
            f'<img class="brand-logo" src="{safe_logo_source}" alt="Brasao de Mamanguape" '
            'onerror="this.hidden=true;this.nextElementSibling.hidden=false;">'
            '<span class="brand-logo-fallback" hidden>SM</span>'
        )

    safe_local_logo = html.escape(local_logo, quote=True)
    return (
        f'<img class="brand-logo" src="{safe_logo_source}" alt="Brasao de Mamanguape" '
        f'onerror="this.onerror=function(){{this.hidden=true;this.nextElementSibling.hidden=false;}};'
        f'this.src=\'{safe_local_logo}\';">'
        '<span class="brand-logo-fallback" hidden>SM</span>'
    )


def get_current_page() -> str:
    current_page = st.session_state.get("current_page")
    if not current_page:
        raw_page = st.query_params.get("page")
        if isinstance(raw_page, list):
            raw_page = raw_page[0] if raw_page else None
        current_page = PAGE_SLUGS.get(str(raw_page or ""), DEFAULT_PAGE)

    if current_page not in PAGE_TO_SLUG:
        current_page = DEFAULT_PAGE

    st.session_state.current_page = current_page
    return current_page


def set_current_page(page_name: str) -> None:
    if page_name not in PAGE_TO_SLUG:
        page_name = DEFAULT_PAGE

    st.session_state.current_page = page_name
    st.query_params["page"] = PAGE_TO_SLUG[page_name]


def _sidebar_link(page_name: str, icon_class: str, active_page: str) -> str:
    active_class = " active" if page_name == active_page else ""
    return (
        f'<div class="sidebar-link{active_class}">'
        f'<span class="nav-icon {icon_class}"></span>'
        f"<span>{_escape_text(page_name)}</span>"
        "</div>"
    )


def _sidebar_nav_markup(active_page: str, *, show_admin: bool) -> str:
    nav_items = [
        f'<div class="sidebar-nav-item">{_sidebar_link(DEFAULT_PAGE, "stats", active_page)}</div>',
        f'<div class="sidebar-nav-item">{_sidebar_link(CHAT_PAGE, "chat", active_page)}</div>',
    ]
    if show_admin:
        nav_items.append(f'<div class="sidebar-nav-item">{_sidebar_link(ADMIN_PAGE, "audit", active_page)}</div>')
    return "\n".join(nav_items)


def render_sidebar(active_page: str = DEFAULT_PAGE) -> None:
    user = get_authenticated_user(st.session_state)
    show_admin = can_view_audit_log(user)

    logo_markup = _sidebar_logo_markup()
    nav_markup = _sidebar_nav_markup(active_page, show_admin=show_admin)
    st.markdown(
        f"""
        <aside class="app-sidebar">
            <div class="sidebar-brand">
                <div class="brand-mark">{logo_markup}</div>
                <div class="brand-copy">
                    <p class="brand-title">Secretaria de Saúde</p>
                    <p class="brand-subtitle">Mamanguape</p>
                </div>
            </div>
            <div class="sidebar-nav" role="navigation" aria-label="Navegação principal">
                {nav_markup}
            </div>
            <div class="sidebar-click-targets" aria-hidden="true"></div>
        </aside>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Estatísticas", key="sidebar-nav-estatisticas", use_container_width=True):
        set_current_page(DEFAULT_PAGE)
        st.rerun()
    if st.button("Chat IA", key="sidebar-nav-chat-ia", use_container_width=True):
        set_current_page(CHAT_PAGE)
        st.rerun()
    if show_admin:
        if st.button("Auditoria", key="sidebar-nav-auditoria", use_container_width=True):
            set_current_page(ADMIN_PAGE)
            st.rerun()
