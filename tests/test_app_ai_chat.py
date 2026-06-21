from pathlib import Path
import unittest

APP_PATH = Path("app_ai_chat.py")
AUTH_MODAL_PATH = Path("src/ui/auth_modal.py")
HEADER_PATH = Path("src/ui/header.py")
SIDEBAR_PATH = Path("src/ui/sidebar.py")
STATISTICS_PATH = Path("src/ui/statistics_page.py")
PROTECTED_CHAT_PATH = Path("src/ui/protected_chat.py")


class TestAppAiChat(unittest.TestCase):
    def test_app_existe(self):
        self.assertTrue(APP_PATH.exists())

    def test_app_carrega_ia_apenas_no_processamento_do_chat(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertNotRegex(source, r"(?m)^from src\.ai\.datasus_ai import perguntar_datasus$")
        self.assertNotRegex(source, r"(?m)^import pandas\b")
        self.assertIn("def _get_datasus_question_runner", source)
        self.assertIn("def _get_pandas_module", source)
        self.assertIn("@st.cache_resource(show_spinner=False)", source)
        self.assertIn("perguntar_datasus = _get_datasus_question_runner()", source)
        self.assertIn("resposta = perguntar_datasus(prompt)", source)

    def test_app_valida_autenticacao_antes_do_chat(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.auth.session import can_access_chat", source)
        self.assertIn("if not can_access_chat(st.session_state):", source)
        self.assertIn("st.session_state.pending_prompt = None", source)
        self.assertIn("open_auth_modal(", source)
        self.assertIn("Tentativa bloqueada de chat sem usuario autenticado", source)

    def test_estatisticas_permanece_publica_e_chat_fica_protegido(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        statistics_source = STATISTICS_PATH.read_text(encoding="utf-8")
        protected_source = PROTECTED_CHAT_PATH.read_text(encoding="utf-8")

        self.assertIn("if current_page == CHAT_PAGE:", app_source)
        self.assertIn("_render_chat_page()", app_source)
        self.assertIn("else:\n        render_statistics_page()", app_source)
        self.assertNotIn("can_access_chat", statistics_source)
        self.assertIn("sem login", statistics_source)
        self.assertIn("open_auth_modal(", protected_source)
        self.assertIn("redirect_on_close=DEFAULT_PAGE", protected_source)

    def test_app_contem_referencias_visuais_esperadas(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [APP_PATH, SIDEBAR_PATH, STATISTICS_PATH]
        )

        expected_texts = [
            "Assistente Estatístico SIA/DATASUS",
            "Chat IA",
            "Estatísticas",
            "Painel de Estatísticas",
            "Ver painel de estatÃ­sticas",
            "O painel serÃ¡ aberto em uma nova aba.",
            "app.powerbi.com/view",
            "images",
            "logo.png",
            "brand-logo",
            "Digite uma pergunta estatística",
        ]

        expected_texts = [
            text
            for text in expected_texts
            if not text.startswith(("Ver painel de estat", "O painel ser"))
        ] + ["Ver painel de estat", "O painel ser"]

        for text in expected_texts:
            self.assertIn(text, source)

    def test_sidebar_usa_logo_real_e_hero_nao_tem_grafico_decorativo(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")
        statistics_source = STATISTICS_PATH.read_text(encoding="utf-8")

        self.assertIn("LOGO_PATH", sidebar_source)
        self.assertIn("_get_sidebar_logo_data_uri", sidebar_source)
        self.assertIn("images", sidebar_source)
        self.assertIn("logo.png", sidebar_source)
        self.assertIn('<img class="brand-logo"', sidebar_source)
        self.assertIn(".brand-logo", app_source)
        self.assertNotIn("brand-spark", app_source + sidebar_source)
        self.assertNotIn("hero-chart", app_source + statistics_source)

    def test_app_usa_sidebar_como_navegacao_unica(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.ui.sidebar import", app_source)
        self.assertIn("def render_sidebar", sidebar_source)
        self.assertIn('st.button("Estatísticas"', sidebar_source)
        self.assertIn('st.button("Chat IA"', sidebar_source)
        self.assertIn("sidebar-click-targets", app_source + sidebar_source)
        self.assertIn(".st-key-sidebar-nav-estatisticas", app_source)
        self.assertIn(".st-key-sidebar-nav-chat-ia", app_source)
        self.assertIn("position: fixed", app_source)
        self.assertIn("color: transparent", app_source)
        self.assertNotIn('href="?page=', sidebar_source)
        self.assertIn('"estatisticas": DEFAULT_PAGE', sidebar_source)
        self.assertIn('"chat-ia": CHAT_PAGE', sidebar_source)
        self.assertNotIn("st.radio(", app_source + sidebar_source)
        self.assertNotIn("nav-tabs", app_source + sidebar_source)

        removed_pages = [
            "Visão Geral",
            "Análise Mensal",
            "Análise Anual",
            "Demografia",
        ]

        for page in removed_pages:
            self.assertNotIn(page, app_source + sidebar_source)

    def test_app_usa_dialog_para_fluxos_de_autenticacao(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("render_auth_panel", app_source)
        self.assertIn('@st.dialog("Acesso ao Chat IA"', auth_source)
        self.assertIn('@st.dialog("Meu perfil"', auth_source)
        self.assertIn('on_dismiss=_clear_auth_panel', auth_source)
        self.assertIn("auth_modal_mode", auth_source)
        self.assertIn("def open_auth_modal", auth_source)
        self.assertIn("def switch_auth_modal_mode", auth_source)
        self.assertIn("def close_auth_modal", auth_source)
        self.assertIn("if mode in {\"signup\", \"register\"}", auth_source)
        self.assertIn("auth-dialog-subtitle", auth_source)
        self.assertNotIn("auth-card-heading", auth_source)
        self.assertNotIn("auth-profile-card", auth_source)

    def test_modal_auth_nao_reseta_cadastro_no_chat_protegido(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")
        header_source = HEADER_PATH.read_text(encoding="utf-8")
        protected_source = PROTECTED_CHAT_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.ui.auth_modal import open_auth_modal, render_auth_panel", app_source)
        self.assertIn("and not st.session_state.get(\"auth_panel\")", app_source)
        self.assertIn("open_auth_modal(", app_source)
        self.assertIn("open_auth_modal(", header_source)
        self.assertIn("open_auth_modal(", protected_source)
        self.assertIn('mode="register"', protected_source)
        self.assertIn("switch_auth_modal_mode(switch_mode)", auth_source)
        self.assertIn('switch_mode="register"', auth_source)
        self.assertIn('switch_mode="login"', auth_source)

    def test_modal_auth_redireciona_cancelamento_do_chat_para_estatisticas(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")
        protected_source = PROTECTED_CHAT_PATH.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")

        self.assertIn("auth_redirect_on_close", app_source)
        self.assertIn("auth_target_page_on_success", app_source)
        self.assertIn("redirect_on_close=DEFAULT_PAGE", app_source)
        self.assertIn("target_page_on_success=CHAT_PAGE", app_source)
        self.assertIn("redirect_on_close=DEFAULT_PAGE", protected_source)
        self.assertIn("target_page_on_success=CHAT_PAGE", protected_source)
        self.assertIn("def close_auth_panel", auth_source)
        self.assertIn("set_current_page(str(redirect_page))", auth_source)
        self.assertIn("def _finish_auth_success", auth_source)
        self.assertIn("set_current_page(str(target_page))", auth_source)
        self.assertIn("def set_current_page", sidebar_source)
        self.assertIn('st.query_params["page"]', sidebar_source)

    def test_modal_auth_tem_backdrop_suave_e_card_claro(self):
        source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("AUTH_MODAL_CSS", source)
        self.assertIn("def _render_auth_modal_style", source)
        self.assertIn('[data-testid="stDialog"]::backdrop', source)
        self.assertIn("rgba(15, 23, 42, 0.18)", source)
        self.assertIn("background: rgba(15, 23, 42, 0.14)", source)
        self.assertIn("backdrop-filter: blur(4px)", source)
        self.assertIn("backdrop-filter: blur(5px)", source)
        self.assertIn("max-width: 28rem", source)
        self.assertIn("background: #FFFFFF !important", source)
        self.assertIn("color: #0F172A !important", source)
        self.assertIn('[data-testid="InputInstructions"]', source)
        self.assertIn("color: #FFFFFF !important", source)
        self.assertIn("border-radius: 0.875rem", source)
        self.assertIn("input:focus", source)
        self.assertIn("box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.16)", source)

    def test_inputs_e_acoes_do_modal_tem_estilo_polido(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn('[data-testid="stTextInput"] input', app_source)
        self.assertIn("input:focus-visible", app_source)
        self.assertIn("border-radius: 0.875rem", app_source)
        self.assertIn("box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.16)", app_source)
        self.assertIn("validate_login_fields", auth_source)
        self.assertIn("validate_register_fields", auth_source)
        self.assertIn("auth-global-error", auth_source)
        self.assertIn("auth-field-error", auth_source)
        self.assertIn("auth-info-message", auth_source)
        self.assertIn('role="alert"', auth_source)
        self.assertIn("#991B1B", auth_source)
        self.assertIn("#B42318", auth_source)
        self.assertIn("_render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)", auth_source)
        self.assertIn("_render_field_errors(field_error_slots, field_errors)", auth_source)
        self.assertIn("Não foi possível acessar a autenticação agora.", auth_source)
        self.assertIn("auth-login-forgot-password", auth_source)
        self.assertIn("A recuperação de senha por e-mail ainda não está disponível.", auth_source)
        self.assertIn("def _render_auth_footer", auth_source)
        self.assertIn('switch_key="auth-login-go-signup"', auth_source)
        self.assertIn('switch_key="auth-signup-go-login"', auth_source)
        self.assertIn('switch_mode="register"', auth_source)
        self.assertIn('switch_mode="login"', auth_source)
        self.assertIn("auth-dialog-footer", auth_source)
        self.assertIn(".st-key-auth-login-go-signup", auth_source)
        self.assertIn(".st-key-auth-signup-go-login", auth_source)
        self.assertIn("border: 1px solid rgba(123, 44, 191, 0.42)", auth_source)
        self.assertIn("height: 2.85rem", auth_source)
        self.assertNotIn("prompt_text=", auth_source)
        self.assertNotIn("Não tem conta?", auth_source)
        self.assertNotIn("Já tem conta?", auth_source)
        self.assertIn('action_label="Criar conta"', auth_source)
        self.assertIn('action_label="Entrar"', auth_source)
        self.assertIn("Acesso ao Chat IA", auth_source)
        self.assertIn("Entre para continuar usando o chat inteligente.", auth_source)
        self.assertIn("Preencha seus dados para acessar o Chat IA.", auth_source)
        self.assertNotIn("auth-dialog-cancel", auth_source)
        self.assertNotIn('st.button("Cancelar"', auth_source)
        self.assertNotIn('st.button("Fechar", key="auth-login-close"', auth_source)
        self.assertNotIn('st.button("Fechar", key="auth-signup-close"', auth_source)

    def test_profile_menu_e_modal_tem_fluxo_enxuto(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")
        header_source = HEADER_PATH.read_text(encoding="utf-8")

        self.assertIn('st.button("Meu perfil"', header_source)
        self.assertIn('st.button("Sair"', header_source)
        self.assertIn("queue_toast(st.session_state, \"Sessão encerrada.\")", header_source)
        self.assertNotIn('key="auth-menu-name"', header_source)
        self.assertNotIn('key="auth-menu-password"', header_source)
        self.assertNotIn('key="auth-menu-email"', header_source)
        self.assertIn("Alterar nome\\nAtualize o nome exibido na sua conta.", auth_source)
        self.assertIn("Alterar e-mail\\nSolicite a alteracao do e-mail usado no acesso.", auth_source)
        self.assertIn("Alterar senha\\nTroque sua senha de acesso com seguranca.", auth_source)
        self.assertIn("Zona de seguranca", auth_source)
        self.assertIn("Desativar conta", auth_source)
        self.assertIn("auth-profile-deactivate", auth_source)
        self.assertIn("auth-deactivate-account-form", auth_source)
        self.assertIn("service.soft_delete_user(int(user[\"id\"]))", auth_source)
        self.assertIn("logout_session(st.session_state)", auth_source)
        self.assertIn("set_current_page(DEFAULT_PAGE)", auth_source)
        self.assertIn("queue_toast(st.session_state, \"Conta desativada com sucesso.\")", auth_source)
        self.assertIn("auth-profile-actions", auth_source)
        self.assertIn("auth-profile-info-card", auth_source)
        self.assertIn("auth-profile-info-grid", auth_source)
        self.assertIn("Gerenciar conta", auth_source)
        self.assertIn('@st.dialog("Meu perfil", width="large"', auth_source)
        self.assertIn(".st-key-auth-menu-logout button", app_source)
        self.assertIn("#FEF2F2", app_source)
        self.assertIn("#B42318", app_source)

    def test_app_ui_foi_separada_em_componentes(self):
        source = APP_PATH.read_text(encoding="utf-8")

        expected_imports = [
            "from src.ui.auth_modal import open_auth_modal, render_auth_panel",
            "from src.ui.header import render_auth_header",
            "from src.ui.protected_chat import render_chat_auth_gate",
            "from src.ui.sidebar import CHAT_PAGE, DEFAULT_PAGE, get_current_page, render_sidebar",
            "from src.ui.statistics_page import render_statistics_page",
        ]

        for import_line in expected_imports:
            self.assertIn(import_line, source)

        self.assertNotIn("def render_auth_header", source)
        self.assertNotIn("def render_sidebar", source)
        self.assertNotIn("def render_auth_panel", source)

    def test_app_nao_chama_etl_principal(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_PATH,
                AUTH_MODAL_PATH,
                HEADER_PATH,
                SIDEBAR_PATH,
                STATISTICS_PATH,
                PROTECTED_CHAT_PATH,
            ]
        )

        for name in ["extract_data", "transform_datasus", "load_data_sus", "main.py"]:
            self.assertNotIn(name, source)

    def test_app_nao_importa_pandasai_ou_banco_diretamente(self):
        source = APP_PATH.read_text(encoding="utf-8")

        forbidden_fragments = [
            "pandasai",
            "psycopg2",
            "sqlalchemy",
            "read_only_datasus",
            "data_provider",
        ]

        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)

    def test_app_nao_contem_comandos_sql_de_escrita(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_PATH,
                AUTH_MODAL_PATH,
                HEADER_PATH,
                SIDEBAR_PATH,
                STATISTICS_PATH,
                PROTECTED_CHAT_PATH,
            ]
        ).upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")

    def test_app_nao_contem_to_sql(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_PATH,
                AUTH_MODAL_PATH,
                HEADER_PATH,
                SIDEBAR_PATH,
                STATISTICS_PATH,
                PROTECTED_CHAT_PATH,
            ]
        )

        self.assertNotIn("DataFrame.to_sql", source)
        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)


if __name__ == "__main__":
    unittest.main()
