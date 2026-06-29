"""Google OAuth/OpenID Connect helpers for Streamlit authentication."""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile")
GOOGLE_OAUTH_STATE_KEY = "google_oauth_state"
GOOGLE_OAUTH_TARGET_PAGE_KEY = "google_oauth_target_page"

GOOGLE_OAUTH_UNAVAILABLE_MESSAGE = "Login com Google indisponivel no momento."
GOOGLE_OAUTH_INVALID_STATE_MESSAGE = "Nao foi possivel validar o retorno do Google. Tente novamente."
GOOGLE_OAUTH_UNVERIFIED_EMAIL_MESSAGE = "Nao foi possivel confirmar o e-mail da conta Google."
GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE = "Nao foi possivel entrar com Google agora. Tente novamente em instantes."


def _is_env_flag_enabled(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().strip("\"'").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GoogleOAuthConfig:
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""

    @classmethod
    def from_environment(cls) -> "GoogleOAuthConfig":
        return cls(
            enabled=_is_env_flag_enabled("GOOGLE_OAUTH_ENABLED", default=False),
            client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
        )

    @property
    def is_complete(self) -> bool:
        return bool(self.enabled and self.client_id and self.client_secret and self.redirect_uri)


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str = ""
    picture: str = ""


class GoogleOAuthError(RuntimeError):
    """Erro seguro do fluxo OAuth."""

    def __init__(self, public_message: str, error_code: str = "google_oauth_error"):
        super().__init__(public_message)
        self.public_message = public_message
        self.error_code = error_code


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def store_oauth_state(session_state: Any, state: str | None = None) -> str:
    clean_state = state or generate_oauth_state()
    session_state[GOOGLE_OAUTH_STATE_KEY] = clean_state
    return clean_state


def validate_oauth_state(session_state: Any, received_state: str | None) -> bool:
    expected_state = str(session_state.get(GOOGLE_OAUTH_STATE_KEY) or "")
    clean_state = str(received_state or "")
    if not expected_state or not clean_state:
        return False
    return hmac.compare_digest(expected_state, clean_state)


def clear_oauth_state(session_state: Any) -> None:
    session_state.pop(GOOGLE_OAUTH_STATE_KEY, None)


def _default_post_json(url: str, data: dict[str, str]) -> dict[str, Any]:
    encoded_data = urlencode(data).encode("utf-8")
    request = Request(
        url,
        data=encoded_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _default_get_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    with urlopen(request_url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


class GoogleOAuthService:
    """Fluxo OAuth 2.0 authorization code usando OpenID Connect."""

    def __init__(
        self,
        config: GoogleOAuthConfig | None = None,
        *,
        post_json: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
        get_json: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    ):
        self.config = config or GoogleOAuthConfig.from_environment()
        self._post_json = post_json or _default_post_json
        self._get_json = get_json or _default_get_json

    @classmethod
    def from_environment(cls) -> "GoogleOAuthService":
        return cls(GoogleOAuthConfig.from_environment())

    def is_available(self) -> bool:
        return self.config.is_complete

    def build_authorization_url(self, state: str) -> str:
        if not self.config.is_complete:
            raise GoogleOAuthError(GOOGLE_OAUTH_UNAVAILABLE_MESSAGE, "google_oauth_config_missing")
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_OAUTH_SCOPES),
            "state": state,
            "include_granted_scopes": "true",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        clean_code = (code or "").strip()
        if not clean_code:
            raise GoogleOAuthError(GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE, "missing_code")
        if not self.config.is_complete:
            raise GoogleOAuthError(GOOGLE_OAUTH_UNAVAILABLE_MESSAGE, "google_oauth_config_missing")

        try:
            token_response = self._post_json(
                GOOGLE_TOKEN_ENDPOINT,
                {
                    "code": clean_code,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "redirect_uri": self.config.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except Exception as exc:
            logger.warning(
                "Erro seguro google_oauth | acao=exchange_code | tipo=%s",
                type(exc).__name__,
            )
            raise GoogleOAuthError(GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE, "token_exchange_failed") from exc

        if not token_response.get("id_token"):
            raise GoogleOAuthError(GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE, "missing_id_token")
        return token_response

    def verify_id_token(self, id_token: str) -> GoogleIdentity:
        clean_token = (id_token or "").strip()
        if not clean_token:
            raise GoogleOAuthError(GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE, "missing_id_token")
        if not self.config.client_id:
            raise GoogleOAuthError(GOOGLE_OAUTH_UNAVAILABLE_MESSAGE, "google_oauth_config_missing")

        try:
            claims = self._get_json(GOOGLE_TOKENINFO_ENDPOINT, {"id_token": clean_token})
        except Exception as exc:
            logger.warning(
                "Erro seguro google_oauth | acao=verify_id_token | tipo=%s",
                type(exc).__name__,
            )
            raise GoogleOAuthError(GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE, "id_token_validation_failed") from exc

        audience = str(claims.get("aud") or "")
        issuer = str(claims.get("iss") or "")
        if audience != self.config.client_id or issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise GoogleOAuthError(GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE, "invalid_id_token")

        email_verified_raw = claims.get("email_verified")
        email_verified = (
            email_verified_raw is True
            or str(email_verified_raw).strip().lower() == "true"
        )
        if not email_verified:
            raise GoogleOAuthError(GOOGLE_OAUTH_UNVERIFIED_EMAIL_MESSAGE, "email_not_verified")

        sub = str(claims.get("sub") or "").strip()
        email = str(claims.get("email") or "").strip()
        if not sub or not email:
            raise GoogleOAuthError(GOOGLE_OAUTH_GENERIC_ERROR_MESSAGE, "missing_identity_claims")

        return GoogleIdentity(
            sub=sub,
            email=email,
            email_verified=email_verified,
            name=str(claims.get("name") or "").strip(),
            picture=str(claims.get("picture") or "").strip(),
        )

    def exchange_code_for_identity(self, code: str) -> GoogleIdentity:
        token_response = self.exchange_code_for_tokens(code)
        return self.verify_id_token(str(token_response["id_token"]))
