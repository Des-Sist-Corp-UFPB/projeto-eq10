"""app/service/email_service.py — no real SMTP/network calls."""

from __future__ import annotations

from unittest import mock

import pytest

from app.service.email_service import EmailConfig, EmailService, mask_email


def test_mask_email_various_lengths():
    assert mask_email("a@example.com") == "a***@example.com"
    assert mask_email("ab@example.com") == "a***b@example.com"
    assert mask_email("abcdef@example.com") == "a***f@example.com"
    assert mask_email(None) == "***"
    assert mask_email("not-an-email") == "***"


def test_config_from_environment_defaults(monkeypatch):
    for name in ("EMAIL_ENABLED", "EMAIL_PROVIDER", "EMAIL_FROM", "EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_SMTP_USERNAME", "EMAIL_SMTP_PASSWORD", "EMAIL_USE_TLS", "EMAIL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = EmailConfig.from_environment()
    assert config.enabled is False
    assert config.provider == "fake"
    assert config.smtp_use_tls is True


def test_config_from_environment_reads_smtp_settings(monkeypatch):
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_SMTP_USERNAME", "user")
    monkeypatch.setenv("EMAIL_SMTP_PASSWORD", "pw")

    config = EmailConfig.from_environment()
    assert config.enabled is True
    assert config.provider == "smtp"
    assert config.smtp_port == 587


def test_send_email_invalid_recipient():
    service = EmailService(EmailConfig(enabled=True, provider="smtp"))
    result = service.send_email("not-an-email", "Subject", "body")
    assert result.success is False
    assert result.error_code == "invalid_recipient"


def test_send_email_invalid_subject():
    service = EmailService(EmailConfig(enabled=True, provider="smtp"))
    result = service.send_email("a@b.com", "", "body")
    assert result.error_code == "invalid_subject"


def test_send_email_disabled_returns_fake_mode():
    service = EmailService(EmailConfig(enabled=False, provider="smtp"))
    result = service.send_email("a@b.com", "Subject", "body")
    assert result.success is True
    assert result.sent is False
    assert result.mode == "fake"


def test_send_email_fake_provider_short_circuits():
    service = EmailService(EmailConfig(enabled=True, provider="fake"))
    result = service.send_email("a@b.com", "Subject", "body")
    assert result.mode == "fake"


def test_send_email_unsupported_provider():
    service = EmailService(EmailConfig(enabled=True, provider="carrier-pigeon"))
    result = service.send_email("a@b.com", "Subject", "body")
    assert result.error_code == "unsupported_provider"


def test_send_email_smtp_missing_config():
    service = EmailService(EmailConfig(enabled=True, provider="smtp"))
    result = service.send_email("a@b.com", "Subject", "body")
    assert result.error_code == "missing_from_email"


def test_send_email_smtp_success(monkeypatch):
    config = EmailConfig(
        enabled=True, provider="smtp", from_email="noreply@example.com",
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="user", smtp_password="pw",
    )
    service = EmailService(config)

    fake_smtp = mock.MagicMock()
    fake_smtp.__enter__.return_value = fake_smtp
    fake_smtp.__exit__.return_value = False
    with mock.patch("smtplib.SMTP", return_value=fake_smtp), mock.patch("ssl.create_default_context"):
        result = service.send_email("a@b.com", "Subject", "body")

    assert result.success is True
    assert result.sent is True
    assert result.mode == "smtp"
    fake_smtp.send_message.assert_called_once()


def test_send_email_smtp_auth_failure(monkeypatch):
    import smtplib

    config = EmailConfig(
        enabled=True, provider="smtp", from_email="noreply@example.com",
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="user", smtp_password="wrong",
    )
    service = EmailService(config)

    with mock.patch("smtplib.SMTP", side_effect=smtplib.SMTPAuthenticationError(535, b"bad creds")):
        result = service.send_email("a@b.com", "Subject", "body")

    assert result.success is False
    assert result.error_code == "smtp_auth_failed"


def test_send_email_smtp_connection_failure():
    config = EmailConfig(
        enabled=True, provider="smtp", from_email="noreply@example.com",
        smtp_host="smtp.example.com", smtp_port=587, smtp_username="user", smtp_password="pw",
    )
    service = EmailService(config)

    with mock.patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        result = service.send_email("a@b.com", "Subject", "body")

    assert result.success is False
    assert result.error_code == "smtp_send_failed"


def test_send_password_reset_email_fake_mode():
    service = EmailService(EmailConfig(enabled=False))
    result = service.send_password_reset_email("a@b.com", "https://example.com/reset?token=abc", expires_in_minutes=60)
    assert result.message_type == "password_reset"
    assert result.mode == "fake"


def test_api_provider_missing_api_key():
    service = EmailService(EmailConfig(enabled=True, provider="sendgrid", from_email="a@b.com"))
    result = service.send_email("a@b.com", "Subject", "body")
    assert result.error_code == "missing_api_key"


def test_api_provider_not_implemented():
    service = EmailService(EmailConfig(enabled=True, provider="sendgrid", from_email="a@b.com", api_key="key"))
    result = service.send_email("a@b.com", "Subject", "body")
    assert result.error_code == "provider_not_implemented"
