"""Interface Streamlit para testar a camada de IA do SIA/DATASUS."""

from __future__ import annotations

import html

import streamlit as st

from src.ai.datasus_ai import perguntar_datasus

APP_TITLE = "Assistente Estatístico SIA/DATASUS"
APP_SUBTITLE = "Converse com os dados disponíveis do SIA/DATASUS"
PROMPT_PLACEHOLDER = "Digite uma pergunta estatística..."
GENERIC_ERROR_MESSAGE = (
    "Não foi possível processar a pergunta. "
    "Verifique a configuração da camada de IA."
)

EXAMPLE_PROMPTS = (
    "Total de valor aprovado por município",
    "Frequência total por sexo",
    "Unidades com maior quantidade apresentada",
    "Média de idade dos atendimentos",
)


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
            --color-input: #F1F5F9;
            --color-text: #1E293B;
            --color-muted: #64748B;
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
            border: 1px solid rgba(15, 23, 42, 0.04);
            border-radius: 1rem;
            padding: 2rem;
            margin: 0 0 1.5rem;
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
            font-size: 1.5rem;
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
            gap: 0.85rem;
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
            max-width: 78%;
            border-radius: 1rem;
            padding: 0.8rem 1rem 0.92rem;
            line-height: 1.62;
            font-size: 0.98rem;
            box-shadow: var(--shadow-soft);
            overflow-wrap: anywhere;
        }

        .chat-bubble.user {
            background: linear-gradient(135deg, var(--color-purple) 0%, var(--color-violet) 100%);
            color: #FFFFFF;
            border-bottom-right-radius: 0.35rem;
        }

        .chat-bubble.assistant {
            background: #FFFFFF;
            color: var(--color-text);
            border: 1px solid rgba(123, 44, 191, 0.12);
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
            white-space: pre-wrap;
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
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_messages() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


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
    chips = "".join(
        f'<span class="example-chip">{_escape_text(example)}</span>'
        for example in EXAMPLE_PROMPTS
    )
    st.markdown(
        f"""
        <section class="intro-card">
            <div class="intro-icon" aria-hidden="true"></div>
            <div class="intro-body">
                <h2>Olá! Como posso ajudar?</h2>
                <p>
                    Faça perguntas sobre totais, frequências, médias, rankings e
                    comparações dos dados disponíveis.
                </p>
                <div class="example-list">{chips}</div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_message(role: str, content: str) -> None:
    normalized_role = "user" if role == "user" else "assistant"
    label = "Você" if normalized_role == "user" else "Assistente"
    safe_content = _escape_text(content)
    st.markdown(
        f"""
        <div class="chat-row {normalized_role}">
            <div class="chat-bubble {normalized_role}">
                <span class="chat-label">{label}</span>
                <div class="chat-content">{safe_content}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_chat_history() -> None:
    if not st.session_state.messages:
        return

    st.markdown('<section class="chat-stack">', unsafe_allow_html=True)
    for message in st.session_state.messages:
        _render_message(message["role"], message["content"])
    st.markdown("</section>", unsafe_allow_html=True)


def _render_input_form() -> tuple[bool, str]:
    with st.form("chat-form", clear_on_submit=True):
        prompt_column, send_column = st.columns([12, 1], vertical_alignment="center")

        with prompt_column:
            prompt = st.text_input(
                "Pergunta estatística",
                placeholder=PROMPT_PLACEHOLDER,
                label_visibility="collapsed",
            )

        with send_column:
            submitted = st.form_submit_button("➤", use_container_width=True)

    return submitted, prompt.strip()


def _handle_prompt(prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})

    try:
        with st.spinner("Analisando pergunta estatística..."):
            resposta = perguntar_datasus(prompt)
    except Exception:
        resposta = GENERIC_ERROR_MESSAGE

    st.session_state.messages.append({"role": "assistant", "content": resposta})
    st.rerun()


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")
    _apply_style()
    _init_messages()
    _render_sidebar()
    _render_hero()
    _render_intro_card()
    _render_chat_history()

    submitted, prompt = _render_input_form()

    if submitted and prompt:
        _handle_prompt(prompt)


if __name__ == "__main__":
    main()
