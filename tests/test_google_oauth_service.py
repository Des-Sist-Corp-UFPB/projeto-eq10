import unittest
from urllib.parse import parse_qs, urlsplit

from src.auth.google_oauth_service import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_OAUTH_SCOPES,
    GoogleOAuthConfig,
    GoogleOAuthError,
    GoogleOAuthService,
    clear_oauth_state,
    store_oauth_state,
    validate_oauth_state,
)


class TestGoogleOAuthService(unittest.TestCase):
    def test_config_desabilitada_nao_fica_disponivel(self):
        service = GoogleOAuthService(GoogleOAuthConfig(enabled=False))

        self.assertFalse(service.is_available())

    def test_authorization_url_inclui_escopos_e_state(self):
        service = GoogleOAuthService(
            GoogleOAuthConfig(
                enabled=True,
                client_id="client-id.apps.googleusercontent.com",
                client_secret="client-secret",
                redirect_uri="http://localhost:8501",
            )
        )

        url = service.build_authorization_url("state-seguro")
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)

        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", GOOGLE_AUTHORIZATION_ENDPOINT)
        self.assertEqual(query["client_id"], ["client-id.apps.googleusercontent.com"])
        self.assertEqual(query["redirect_uri"], ["http://localhost:8501"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["state"], ["state-seguro"])
        self.assertEqual(set(query["scope"][0].split()), set(GOOGLE_OAUTH_SCOPES))

    def test_state_e_gerado_validado_e_limpo(self):
        session = {}
        state = store_oauth_state(session, "abc123")

        self.assertEqual(state, "abc123")
        self.assertTrue(validate_oauth_state(session, "abc123"))
        self.assertFalse(validate_oauth_state(session, "outro"))

        clear_oauth_state(session)

        self.assertFalse(validate_oauth_state(session, "abc123"))

    def test_exchange_code_for_identity_valida_id_token(self):
        service = GoogleOAuthService(
            GoogleOAuthConfig(
                enabled=True,
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="http://localhost:8501",
            ),
            post_json=lambda url, data: {"id_token": "id-token-seguro"},
            get_json=lambda url, params: {
                "aud": "client-id",
                "iss": "https://accounts.google.com",
                "sub": "google-sub-123",
                "email": "ana@example.com",
                "email_verified": "true",
                "name": "Ana Silva",
                "picture": "https://example.com/ana.png",
            },
        )

        identity = service.exchange_code_for_identity("authorization-code")

        self.assertEqual(identity.sub, "google-sub-123")
        self.assertEqual(identity.email, "ana@example.com")
        self.assertTrue(identity.email_verified)
        self.assertEqual(identity.name, "Ana Silva")
        self.assertEqual(identity.picture, "https://example.com/ana.png")

    def test_email_google_nao_verificado_e_rejeitado(self):
        service = GoogleOAuthService(
            GoogleOAuthConfig(
                enabled=True,
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="http://localhost:8501",
            ),
            get_json=lambda url, params: {
                "aud": "client-id",
                "iss": "accounts.google.com",
                "sub": "google-sub-123",
                "email": "ana@example.com",
                "email_verified": "false",
            },
        )

        with self.assertRaises(GoogleOAuthError) as context:
            service.verify_id_token("id-token-seguro")

        self.assertEqual(context.exception.error_code, "email_not_verified")

    def test_id_token_de_outro_client_e_rejeitado(self):
        service = GoogleOAuthService(
            GoogleOAuthConfig(
                enabled=True,
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="http://localhost:8501",
            ),
            get_json=lambda url, params: {
                "aud": "outro-client",
                "iss": "accounts.google.com",
                "sub": "google-sub-123",
                "email": "ana@example.com",
                "email_verified": "true",
            },
        )

        with self.assertRaises(GoogleOAuthError) as context:
            service.verify_id_token("id-token-seguro")

        self.assertEqual(context.exception.error_code, "invalid_id_token")

    def test_resultados_nao_expoem_client_secret(self):
        config = GoogleOAuthConfig(
            enabled=True,
            client_id="client-id",
            client_secret="segredo-google",
            redirect_uri="http://localhost:8501",
        )
        service = GoogleOAuthService(config)

        self.assertNotIn("segredo-google", service.build_authorization_url("state-seguro"))


if __name__ == "__main__":
    unittest.main()
