"""Environment/settings loader for the FastAPI app. No new env vars beyond SESSION_SECRET_KEY."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

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

    return Settings(
        environment=environment,
        session_secret_key=session_secret_key,
        email_verification_required=_bool_env("EMAIL_VERIFICATION_REQUIRED", False),
        otel_enabled=_bool_env("OTEL_ENABLED", False),
        logo_url=get_configured_logo_url(),
    )
