"""Componentes para a area protegida do Chat IA."""

from __future__ import annotations

import streamlit as st

from src.ui.auth_modal import open_auth_modal
from src.ui.sidebar import CHAT_PAGE, DEFAULT_PAGE

AUTH_REQUIRED_MESSAGE = (
    "Para acessar o Chat IA e fazer perguntas sobre a base SIA/DATASUS, "
    "faça login ou crie uma conta."
)


def _centered_column():
    _left_column, center_column, _right_column = st.columns([1, 2, 1])
    return center_column


def render_chat_auth_gate(open_login: bool = False) -> None:
    if open_login and not st.session_state.get("auth_panel"):
        open_auth_modal(
            mode="login",
            redirect_on_close=DEFAULT_PAGE,
            target_page_on_success=CHAT_PAGE,
        )

    with _centered_column():
        st.markdown(
            f"""
            <section class="auth-gate">
                <h2>Chat inteligente protegido</h2>
                <p>{AUTH_REQUIRED_MESSAGE}</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        login_column, signup_column = st.columns(2)
        with login_column:
            if st.button("Entrar", key="chat-gate-login", use_container_width=True):
                open_auth_modal(
                    mode="login",
                    redirect_on_close=DEFAULT_PAGE,
                    target_page_on_success=CHAT_PAGE,
                )
                st.rerun()
        with signup_column:
            if st.button("Criar conta", key="chat-gate-signup", use_container_width=True):
                open_auth_modal(
                    mode="register",
                    redirect_on_close=DEFAULT_PAGE,
                    target_page_on_success=CHAT_PAGE,
                )
                st.rerun()
