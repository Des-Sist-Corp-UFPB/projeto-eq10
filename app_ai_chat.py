"""Interface Streamlit para testar a camada de IA do SIA/DATASUS."""

from __future__ import annotations

import ast
import html
import json
import logging
import re
from typing import Any

import pandas as pd
import streamlit as st

from src.ai.datasus_ai import perguntar_datasus

APP_TITLE = "Assistente Estatístico SIA/DATASUS"
APP_SUBTITLE = "Converse com os dados disponíveis do SIA/DATASUS"
PROMPT_PLACEHOLDER = "Digite uma pergunta estatística..."
GENERIC_ERROR_MESSAGE = (
    "Não consegui responder essa pergunta com segurança agora. "
    "Tente usar uma pergunta estatística mais direta, como totais, "
    "médias, frequências, rankings por município, procedimento, "
    "unidade ou raça/cor."
)
DATA_ACCESS_ERROR_MESSAGE = (
    "Não consegui acessar os dados no momento. "
    "Tente novamente em alguns instantes."
)
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


def _apply_style() -> None:
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
            --sidebar-width: 230px;
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
            padding: 0.7rem 0.7rem 1rem;
            background: linear-gradient(180deg, var(--color-purple) 0%, var(--color-purple-dark) 100%);
            color: #FFFFFF;
            box-shadow: 14px 0 34px rgba(76, 29, 149, 0.18);
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-height: 3.2rem;
            margin-bottom: 1.9rem;
        }

        .brand-mark {
            display: grid;
            place-items: center;
            width: 2.55rem;
            height: 2.55rem;
            border-radius: 0.7rem;
            background: rgba(255, 255, 255, 0.16);
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.16);
        }

        .brand-spark {
            position: relative;
            width: 1.35rem;
            height: 1.1rem;
        }

        .brand-spark::before {
            content: "";
            position: absolute;
            inset: 0;
            border-left: 2px solid #FFFFFF;
            border-bottom: 2px solid #FFFFFF;
            border-radius: 0 0 0 8px;
            transform: skewX(-18deg);
        }

        .brand-spark::after {
            content: "";
            position: absolute;
            right: 0;
            top: 0.12rem;
            width: 0.56rem;
            height: 0.56rem;
            border-top: 2px solid #FFFFFF;
            border-right: 2px solid #FFFFFF;
            transform: rotate(45deg);
        }

        .brand-title {
            margin: 0;
            color: #FFFFFF;
            font-size: 0.93rem;
            line-height: 1.1;
            font-weight: 800;
            letter-spacing: 0;
        }

        .brand-subtitle {
            margin: 0.28rem 0 0;
            color: rgba(255, 255, 255, 0.82);
            font-size: 0.76rem;
            line-height: 1.1;
        }

        .sidebar-nav {
            display: grid;
            gap: 0.6rem;
        }

        .sidebar-link {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-height: 2.75rem;
            padding: 0 0.95rem;
            border-radius: 0.62rem;
            color: rgba(255, 255, 255, 0.86);
            font-size: 0.88rem;
            font-weight: 760;
        }

        .sidebar-link.active {
            background: var(--color-purple-soft);
            color: #FFFFFF;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
        }

        .nav-icon {
            position: relative;
            display: inline-block;
            width: 1.2rem;
            height: 1.2rem;
            flex: 0 0 1.2rem;
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
        .nav-icon.stats::after,
        .hero-chart span {
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

        .hero-chart {
            position: relative;
            display: grid;
            place-items: center;
            width: 4rem;
            height: 4rem;
            flex: 0 0 4rem;
            border-radius: 0.9rem;
            background: rgba(255, 255, 255, 0.16);
            color: #FFFFFF;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
        }

        .hero-chart::before {
            content: "";
            position: absolute;
            left: 1.18rem;
            bottom: 1.08rem;
            width: 1.6rem;
            height: 1.5rem;
            border-left: 3px solid #FFFFFF;
            border-bottom: 3px solid #FFFFFF;
            border-radius: 0 0 0 0.16rem;
        }

        .hero-chart span:nth-child(1) {
            left: 1.52rem;
            height: 0.72rem;
        }

        .hero-chart span:nth-child(2) {
            left: 2rem;
            height: 1.24rem;
        }

        .hero-chart span:nth-child(3) {
            left: 2.48rem;
            height: 0.92rem;
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

        [data-testid="stForm"] div[data-testid="stTextInput"] {
            margin: 0;
        }

        [data-testid="stForm"] div[data-testid="stTextInput"] > div,
        [data-testid="stForm"] div[data-testid="stTextInput"] > div > div {
            background: transparent;
        }

        [data-testid="stForm"] input {
            min-height: 3rem;
            background: var(--color-input);
            color: var(--color-text);
            border: 1px solid transparent;
            border-radius: 0.82rem;
            padding: 0 1rem;
            font-size: 0.98rem;
            box-shadow: none;
        }

        [data-testid="stForm"] input::placeholder {
            color: #94A3B8;
            opacity: 1;
        }

        [data-testid="stForm"] input:focus {
            border-color: rgba(123, 44, 191, 0.42);
            box-shadow: 0 0 0 4px rgba(123, 44, 191, 0.10);
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

            .sidebar-brand {
                justify-content: center;
                margin-bottom: 1.45rem;
            }

            .brand-copy,
            .sidebar-link span:not(.nav-icon) {
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

            .hero-chart {
                display: none;
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


def _structured_to_frame(value: Any) -> pd.DataFrame | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]

    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return pd.DataFrame(value)

    if isinstance(value, dict):
        if all(not isinstance(item, (dict, list, tuple, set)) for item in value.values()):
            return pd.DataFrame([value])

    return None


def _structured_to_list(value: Any) -> list[str] | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]

    if isinstance(value, list) and all(not isinstance(item, (dict, list, tuple, set)) for item in value):
        return [_sanitize_text(item) for item in value]

    return None


def _dataframe_to_html(df: pd.DataFrame) -> str:
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


def _markdown_table_to_frame(value: str) -> pd.DataFrame | None:
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

    return pd.DataFrame(body, columns=header)


def _pair_lines_to_frame(value: str) -> tuple[list[str], pd.DataFrame | None]:
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

    return intro_lines, pd.DataFrame(rows)


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


def _render_sidebar() -> None:
    st.markdown(
        """
        <aside class="app-sidebar">
            <div class="sidebar-brand">
                <div class="brand-mark"><span class="brand-spark"></span></div>
                <div class="brand-copy">
                    <p class="brand-title">SIA/DATASUS</p>
                    <p class="brand-subtitle">Estatística</p>
                </div>
            </div>
            <nav class="sidebar-nav" aria-label="Navegação principal">
                <div class="sidebar-link active">
                    <span class="nav-icon chat"></span>
                    <span>Chat</span>
                </div>
                <div class="sidebar-link">
                    <span class="nav-icon stats"></span>
                    <span>Estatísticas</span>
                </div>
            </nav>
        </aside>
        """,
        unsafe_allow_html=True,
    )


def _render_hero() -> None:
    st.markdown(
        f"""
        <section class="app-hero">
            <div class="hero-content">
                <span class="hero-badge">Análise estatística</span>
                <h1>{APP_TITLE}</h1>
                <p class="app-subtitle">{APP_SUBTITLE}</p>
            </div>
            <div class="hero-chart" aria-hidden="true">
                <span></span><span></span><span></span>
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
                        <span>Processando pergunta</span>
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

    if st.session_state.get("pending_prompt") == clean_prompt:
        return

    st.session_state.pending_prompt = clean_prompt


def _process_pending_prompt() -> bool:
    prompt = st.session_state.get("pending_prompt")
    if not prompt:
        return False

    st.session_state.pending_prompt = None
    st.session_state.messages.append({"role": "user", "content": prompt})
    _render_chat_history(show_processing=True)
    _render_input_form(disabled=True)

    try:
        resposta = perguntar_datasus(prompt)
    except Exception as exc:
        logger.warning("Erro seguro app_ai_chat | tipo=%s", type(exc).__name__)
        resposta = GENERIC_ERROR_MESSAGE

    st.session_state.messages.append({"role": "assistant", "content": resposta})
    st.rerun()
    return True


def _handle_prompt(prompt: str) -> None:
    _queue_prompt(prompt)
    st.rerun()


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")
    _apply_style()
    _init_messages()
    _render_sidebar()
    _render_hero()
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


if __name__ == "__main__":
    main()
