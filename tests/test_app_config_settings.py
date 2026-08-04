"""app/config/settings.py."""

from __future__ import annotations

import pytest

from app.config.settings import DEV_SESSION_SECRET_KEY, get_configured_logo_url, get_settings


@pytest.fixture()
def clean_env(monkeypatch):
    for name in (
        "ENVIRONMENT", "SESSION_SECRET_KEY", "EMAIL_VERIFICATION_REQUIRED", "OTEL_ENABLED",
        "APP_LOGO_URL", "APP_LOGO_PUBLIC_URL", "APP_BRAND_LOGO_URL", "SIDEBAR_LOGO_URL",
        "PUBLIC_LOGO_URL", "MINIO_LOGO_URL", "MINIO_PUBLIC_LOGO_URL", "MINIO_APP_LOGO_URL",
        "LOGO_URL", "MINIO_LOGO_ENDPOINT", "MINIO_LOGO_BUCKET", "MINIO_LOGO_OBJECT",
        "UMAMI_ENABLED", "UMAMI_SCRIPT_URL", "UMAMI_WEBSITE_ID", "UMAMI_HOST_URL",
        "UMAMI_ALLOWED_DOMAIN",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_get_settings_defaults(clean_env):
    settings = get_settings()
    assert settings.environment == "development"
    assert settings.session_secret_key == DEV_SESSION_SECRET_KEY
    assert settings.email_verification_required is False
    assert settings.otel_enabled is False
    assert settings.logo_url == ""
    assert settings.umami_enabled is False
    assert settings.umami_script_url == ""


def test_get_settings_reads_env(clean_env):
    clean_env.setenv("ENVIRONMENT", "production")
    clean_env.setenv("SESSION_SECRET_KEY", "real-secret")
    clean_env.setenv("EMAIL_VERIFICATION_REQUIRED", "true")
    clean_env.setenv("OTEL_ENABLED", "1")

    settings = get_settings()
    assert settings.environment == "production"
    assert settings.session_secret_key == "real-secret"
    assert settings.email_verification_required is True
    assert settings.otel_enabled is True


def test_get_settings_blank_secret_falls_back_to_dev_default(clean_env):
    clean_env.setenv("SESSION_SECRET_KEY", "   ")
    settings = get_settings()
    assert settings.session_secret_key == DEV_SESSION_SECRET_KEY


def test_umami_enabled_requires_all_three(clean_env):
    clean_env.setenv("UMAMI_ENABLED", "true")
    clean_env.setenv("UMAMI_SCRIPT_URL", "https://umami.example.com/script.js")
    # website id missing -> still disabled
    settings = get_settings()
    assert settings.umami_enabled is False
    assert settings.umami_script_url == "https://umami.example.com/script.js"


def test_umami_enabled_true_with_valid_config(clean_env):
    clean_env.setenv("UMAMI_ENABLED", "true")
    clean_env.setenv("UMAMI_SCRIPT_URL", "https://umami.example.com/script.js")
    clean_env.setenv("UMAMI_WEBSITE_ID", "339ab59d-d201-4b26-a7e5-e642385064f5")
    clean_env.setenv("UMAMI_HOST_URL", "https://umami.example.com")
    clean_env.setenv("UMAMI_ALLOWED_DOMAIN", "example.com")

    settings = get_settings()
    assert settings.umami_enabled is True
    assert settings.umami_website_id == "339ab59d-d201-4b26-a7e5-e642385064f5"
    assert settings.umami_host_url == "https://umami.example.com"
    assert settings.umami_allowed_domain == "example.com"


def test_umami_invalid_website_id_disables(clean_env):
    clean_env.setenv("UMAMI_ENABLED", "true")
    clean_env.setenv("UMAMI_SCRIPT_URL", "https://umami.example.com/script.js")
    clean_env.setenv("UMAMI_WEBSITE_ID", "not-a-uuid")

    settings = get_settings()
    assert settings.umami_website_id == ""
    assert settings.umami_enabled is False


def test_umami_non_https_script_url_rejected(clean_env):
    clean_env.setenv("UMAMI_ENABLED", "true")
    clean_env.setenv("UMAMI_SCRIPT_URL", "http://umami.example.com/script.js")
    clean_env.setenv("UMAMI_WEBSITE_ID", "339ab59d-d201-4b26-a7e5-e642385064f5")

    settings = get_settings()
    assert settings.umami_script_url == ""
    assert settings.umami_enabled is False


def test_get_configured_logo_url_prefers_app_logo_url(clean_env):
    url = get_configured_logo_url({"APP_LOGO_URL": "https://cdn.example.com/logo.png"})
    assert url == "https://cdn.example.com/logo.png"


def test_get_configured_logo_url_rejects_non_http_scheme(clean_env):
    url = get_configured_logo_url({"APP_LOGO_URL": "ftp://cdn.example.com/logo.png"})
    assert url == ""


def test_get_configured_logo_url_falls_back_to_minio(clean_env):
    url = get_configured_logo_url(
        {
            "MINIO_LOGO_ENDPOINT": "https://s3.example.com",
            "MINIO_LOGO_BUCKET": "eq10",
            "MINIO_LOGO_OBJECT": "logo.png",
        }
    )
    assert url == "https://s3.example.com/eq10/logo.png"


def test_get_configured_logo_url_empty_when_nothing_configured(clean_env):
    assert get_configured_logo_url({}) == ""


def test_get_configured_logo_url_rejects_browser_path():
    # MinIO console URLs (path starting with /browser/) are never a real object URL.
    url = get_configured_logo_url({"APP_LOGO_URL": "https://minio.example.com/browser/eq10/logo.png"})
    assert url == ""
