"""Sidebar e estado de navegacao principal."""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any

import streamlit as st

from src.auth.roles import can_view_audit_log
from src.auth.session import get_authenticated_user

DEFAULT_PAGE = "Estatísticas"
CHAT_PAGE = "Chat IA"
ADMIN_PAGE = "Uso Restrito"
BASE_DIR = Path(__file__).resolve().parents[2]
LOGO_PATH = BASE_DIR / "images" / "logo.png"

PAGE_SLUGS = {
    "estatisticas": DEFAULT_PAGE,
    "chat-ia": CHAT_PAGE,
    "uso-restrito": ADMIN_PAGE,
}
PAGE_TO_SLUG = {page: slug for slug, page in PAGE_SLUGS.items()}


def _escape_text(value: Any) -> str:
    return html.escape(str(value), quote=False)


@st.cache_data(show_spinner=False)
def _get_sidebar_logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""

    encoded_logo = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_logo}"


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


def render_sidebar(active_page: str = DEFAULT_PAGE) -> None:
    user = get_authenticated_user(st.session_state)
    show_admin = can_view_audit_log(user)

    statistics_link = _sidebar_link(DEFAULT_PAGE, "stats", active_page)
    chat_link = _sidebar_link(CHAT_PAGE, "chat", active_page)
    admin_link = _sidebar_link(ADMIN_PAGE, "lock", active_page) if show_admin else ""
    logo_data_uri = _get_sidebar_logo_data_uri()
    logo_markup = (
        f'<img class="brand-logo" src="{logo_data_uri}" alt="Brasão de Mamanguape">'
        if logo_data_uri
        else '<span class="brand-logo-fallback">SM</span>'
    )
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
            <nav class="sidebar-nav" aria-label="Navegação principal">
                <div class="sidebar-nav-item">{statistics_link}</div>
                <div class="sidebar-nav-item">{chat_link}</div>
                {f'<div class="sidebar-nav-item">{admin_link}</div>' if show_admin else ''}
            </nav>
        </aside>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="sidebar-click-targets">', unsafe_allow_html=True)
    if st.button("Estatísticas", key="sidebar-nav-estatisticas", use_container_width=True):
        set_current_page(DEFAULT_PAGE)
        st.rerun()
    if st.button("Chat IA", key="sidebar-nav-chat-ia", use_container_width=True):
        set_current_page(CHAT_PAGE)
        st.rerun()
    if show_admin:
        if st.button("Uso Restrito", key="sidebar-nav-uso-restrito", use_container_width=True):
            set_current_page(ADMIN_PAGE)
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
