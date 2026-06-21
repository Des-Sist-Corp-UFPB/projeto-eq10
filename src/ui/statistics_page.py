"""Pagina publica de estatisticas com link para o Power BI oficial."""

from __future__ import annotations

import streamlit as st

POWER_BI_URL = (
    "https://app.powerbi.com/view?r="
    "eyJrIjoiMzMyNGZiMDgtNTk1Yy00Y2E4LTgyOTItMTU4MzNiYWUxMDg3IiwidCI6IjlkYmYzMjZlLTIxODUtNGM3OC1iY2NhLTBmNTdmOTc4ZjNkYSJ9"
)


def render_statistics_page() -> None:
    st.markdown(
        """
        <section class="app-hero">
            <div class="hero-content">
                <span class="hero-badge">DataSUS Analytics</span>
                <h1>Painel de Estatísticas</h1>
                <p class="app-subtitle">
                    Consulte os indicadores consolidados de Saúde em um painel visual e interativo.
                </p>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <section class="public-dashboard-card">
            <div class="public-dashboard-copy">
                <h2>Painel de Estatísticas</h2>
                <p>
                    Consulte os principais indicadores de saúde em um painel visual e interativo.
                    Esta área é pública e pode ser acessada sem login.
                </p>
                <div class="powerbi-actions">
                    <a class="powerbi-link" href="{POWER_BI_URL}" target="_blank" rel="noopener noreferrer">
                        Ver painel de estatísticas
                    </a>
                    <span class="powerbi-note">O painel será aberto em uma nova aba.</span>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
