"""Environment/settings loader for the FastAPI app. No new env vars beyond SESSION_SECRET_KEY."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

# Read-only reuse of src/analytics/umami.py's pure validators (no Streamlit dependency —
# only configure_umami()/track_event()/etc. in that module touch st.session_state). Keeps
# the same HTTPS-only / valid-UUID / bare-domain rules instead of re-deriving them.
from src.analytics.umami import _safe_domain as _umami_safe_domain
from src.analytics.umami import _safe_https_url as _umami_safe_https_url
from src.analytics.umami import _safe_website_id as _umami_safe_website_id

LOGO_URL_ENV_VARS = (
    "APP_LOGO_URL",
    "APP_LOGO_PUBLIC_URL",
    "APP_BRAND_LOGO_URL",
    "SIDEBAR_LOGO_URL",
    "PUBLIC_LOGO_URL",
    "MINIO_LOGO_URL",
    "MINIO_PUBLIC_LOGO_URL",
    "MINIO_APP_LOGO_URL",
    "LOGO_URL",
)
MINIO_LOGO_ENDPOINT_ENV_VARS = ("MINIO_LOGO_ENDPOINT",)
MINIO_LOGO_BUCKET_ENV_VARS = ("MINIO_LOGO_BUCKET",)
MINIO_LOGO_OBJECT_ENV_VARS = ("MINIO_LOGO_OBJECT", "MINIO_LOGO_FILENAME")
DEFAULT_MINIO_LOGO_BUCKET = "eq10"
DEFAULT_MINIO_LOGO_OBJECT = "logo.png"

DEV_SESSION_SECRET_KEY = "dev-insecure-session-secret-change-me"


@dataclass(frozen=True)
class Settings:
    environment: str
    session_secret_key: str
    email_verification_required: bool
    otel_enabled: bool
    logo_url: str = field(default="")
    umami_enabled: bool = False
    umami_script_url: str = ""
    umami_website_id: str = ""
    umami_host_url: str = ""
    umami_allowed_domain: str = ""


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _first_env_value(env: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def _is_safe_logo_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_logo_url(value: str) -> str:
    if not _is_safe_logo_url(value):
        return ""
    parsed = urlparse(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0] == "browser":
        return ""
    return value


def _build_minio_logo_url(env: dict[str, str]) -> str:
    endpoint = _first_env_value(env, MINIO_LOGO_ENDPOINT_ENV_VARS)
    if not endpoint:
        return ""

    parsed_endpoint = urlparse(endpoint.strip())
    if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
        return ""

    bucket = (_first_env_value(env, MINIO_LOGO_BUCKET_ENV_VARS) or DEFAULT_MINIO_LOGO_BUCKET).strip().strip("/")
    object_name = (
        _first_env_value(env, MINIO_LOGO_OBJECT_ENV_VARS) or DEFAULT_MINIO_LOGO_OBJECT
    ).strip().lstrip("/")
    if not bucket or not object_name:
        return ""

    base_path = parsed_endpoint.path.rstrip("/")
    logo_path = f"{base_path}/{bucket}/{object_name}" if base_path else f"/{bucket}/{object_name}"
    return _normalize_logo_url(
        urlunparse(parsed_endpoint._replace(path=logo_path, params="", query="", fragment=""))
    )


def get_configured_logo_url(environ: dict[str, str] | None = None) -> str:
    """Return the configured public/signed logo URL without exposing MinIO credentials."""
    env = environ if environ is not None else os.environ
    for name in LOGO_URL_ENV_VARS:
        normalized_value = _normalize_logo_url(str(env.get(name) or "").strip())
        if normalized_value:
            return normalized_value

    return _build_minio_logo_url(env)


def get_settings() -> Settings:
    environment = os.environ.get("ENVIRONMENT", "development").strip() or "development"
    session_secret_key = os.environ.get("SESSION_SECRET_KEY", "").strip()
    if not session_secret_key:
        session_secret_key = DEV_SESSION_SECRET_KEY

    umami_script_url = _umami_safe_https_url(os.environ.get("UMAMI_SCRIPT_URL"))
    umami_website_id = _umami_safe_website_id(os.environ.get("UMAMI_WEBSITE_ID"))
    umami_host_url = _umami_safe_https_url(os.environ.get("UMAMI_HOST_URL"))
    umami_allowed_domain = _umami_safe_domain(os.environ.get("UMAMI_ALLOWED_DOMAIN"))
    umami_requested = _bool_env("UMAMI_ENABLED", False)

    return Settings(
        environment=environment,
        session_secret_key=session_secret_key,
        email_verification_required=_bool_env("EMAIL_VERIFICATION_REQUIRED", False),
        otel_enabled=_bool_env("OTEL_ENABLED", False),
        logo_url=get_configured_logo_url(),
        # enabled = requested AND both required values passed validation — mirrors
        # src/analytics/umami.py's _configuration()["enabled"] logic exactly.
        umami_enabled=bool(umami_requested and umami_script_url and umami_website_id),
        umami_script_url=umami_script_url,
        umami_website_id=umami_website_id,
        umami_host_url=umami_host_url,
        umami_allowed_domain=umami_allowed_domain,
    )
