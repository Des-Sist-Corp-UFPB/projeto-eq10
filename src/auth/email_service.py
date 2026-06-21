"""Servico interno de e-mail para fluxos futuros de autenticacao.

Esta fundacao nao implementa envio real ainda. O modo padrao e fake/local para
permitir que verificacao de e-mail e recuperacao de senha sejam integradas no
futuro sem prometer envio real antes da configuracao do provedor.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

FAKE_PROVIDERS = {"fake", "local", "dev"}
API_PROVIDERS = {"resend", "sendgrid", "mailgun"}
SMTP_PROVIDER = "smtp"
SUPPORTED_PROVIDERS = FAKE_PROVIDERS | API_PROVIDERS | {SMTP_PROVIDER}

EMAIL_DISABLED_MESSAGE = "Envio real de e-mail desativado; nenhum e-mail foi enviado."
EMAIL_CONFIG_INCOMPLETE_MESSAGE = "Configuracao do provedor de e-mail incompleta."
EMAIL_UNSUPPORTED_PROVIDER_MESSAGE = "Provedor de e-mail nao suportado."
EMAIL_PROVIDER_NOT_IMPLEMENTED_MESSAGE = (
    "Envio real por este provedor ainda nao foi implementado."
)


def _is_env_flag_enabled(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    return raw_value.strip().strip("\"'").lower() in {"1", "true", "yes", "on"}


def _normalize_provider(value: str | None) -> str:
    provider = (value or "fake").strip().lower()
    return provider or "fake"


def _parse_port(value: str | None) -> int | None:
    if not value:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def mask_email(email: str | None) -> str:
    """Mascara e-mail para logs sem esconder totalmente o dominio."""
    clean_email = (email or "").strip()
    if "@" not in clean_email:
        return "***"

    local_part, domain = clean_email.split("@", 1)
    if not local_part:
        masked_local = "***"
    elif len(local_part) == 1:
        masked_local = f"{local_part[0]}***"
    else:
        masked_local = f"{local_part[0]}***{local_part[-1]}"

    return f"{masked_local}@{domain}"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool = False
    provider: str = "fake"
    from_email: str = ""
    smtp_host: str = ""
    smtp_port: int | None = None
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    api_key: str = ""

    @classmethod
    def from_environment(cls) -> "EmailConfig":
        return cls(
            enabled=_is_env_flag_enabled("EMAIL_ENABLED", default=False),
            provider=_normalize_provider(os.getenv("EMAIL_PROVIDER")),
            from_email=os.getenv("EMAIL_FROM", "").strip(),
            smtp_host=os.getenv("EMAIL_SMTP_HOST", "").strip(),
            smtp_port=_parse_port(os.getenv("EMAIL_SMTP_PORT")),
            smtp_username=os.getenv("EMAIL_SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("EMAIL_SMTP_PASSWORD", ""),
            smtp_use_tls=_is_env_flag_enabled("EMAIL_USE_TLS", default=True),
            api_key=os.getenv("EMAIL_API_KEY", ""),
        )


@dataclass(frozen=True)
class EmailSendResult:
    success: bool
    sent: bool
    provider: str
    mode: str
    message: str
    error_code: str | None = None
    message_type: str = "generic"
    recipient: str | None = None
    timestamp: str = field(default_factory=_utc_timestamp)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "sent": self.sent,
            "provider": self.provider,
            "mode": self.mode,
            "message": self.message,
            "error_code": self.error_code,
            "message_type": self.message_type,
            "recipient": self.recipient,
            "timestamp": self.timestamp,
        }


class EmailService:
    """Abstracao segura de envio de e-mails.

    Por enquanto, apenas fake/local e totalmente funcional. Provedores reais
    sao validados e retornam erro seguro ate que a integracao seja implementada.
    """

    def __init__(self, config: EmailConfig | None = None):
        self.config = config or EmailConfig.from_environment()

    @classmethod
    def from_environment(cls) -> "EmailService":
        return cls(EmailConfig.from_environment())

    def send_email(
        self,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        *,
        message_type: str = "generic",
    ) -> EmailSendResult:
        del body_text, body_html

        recipient = mask_email(to)
        provider = self.config.provider

        if not (to or "").strip() or "@" not in to:
            return self._result(
                success=False,
                sent=False,
                mode="validation",
                message="Destinatario de e-mail invalido.",
                error_code="invalid_recipient",
                message_type=message_type,
                recipient=recipient,
            )

        if not (subject or "").strip():
            return self._result(
                success=False,
                sent=False,
                mode="validation",
                message="Assunto de e-mail invalido.",
                error_code="invalid_subject",
                message_type=message_type,
                recipient=recipient,
            )

        if not self.config.enabled or provider in FAKE_PROVIDERS:
            return self._fake_result(message_type, recipient)

        if provider not in SUPPORTED_PROVIDERS:
            return self._failure_result(
                mode="configuration",
                message=EMAIL_UNSUPPORTED_PROVIDER_MESSAGE,
                error_code="unsupported_provider",
                message_type=message_type,
                recipient=recipient,
            )

        missing_error = self._config_error_code()
        if missing_error:
            return self._failure_result(
                mode="configuration",
                message=EMAIL_CONFIG_INCOMPLETE_MESSAGE,
                error_code=missing_error,
                message_type=message_type,
                recipient=recipient,
            )

        return self._failure_result(
            mode="not_implemented",
            message=EMAIL_PROVIDER_NOT_IMPLEMENTED_MESSAGE,
            error_code="provider_not_implemented",
            message_type=message_type,
            recipient=recipient,
        )

    def send_verification_email(self, to: str, verification_url_or_code: str) -> EmailSendResult:
        body_text = (
            "Use o link ou codigo de verificacao enviado para confirmar seu e-mail. "
            "Se voce nao solicitou esta acao, ignore esta mensagem."
        )
        body_html = (
            "<p>Use o link ou codigo de verificacao enviado para confirmar seu e-mail.</p>"
            "<p>Se voce nao solicitou esta acao, ignore esta mensagem.</p>"
        )
        del verification_url_or_code
        return self.send_email(
            to,
            "Verificacao de e-mail",
            body_text,
            body_html,
            message_type="verification",
        )

    def send_password_reset_email(self, to: str, reset_url: str) -> EmailSendResult:
        body_text = (
            "Use o link de recuperacao enviado para definir uma nova senha. "
            "Se voce nao solicitou esta acao, ignore esta mensagem."
        )
        body_html = (
            "<p>Use o link de recuperacao enviado para definir uma nova senha.</p>"
            "<p>Se voce nao solicitou esta acao, ignore esta mensagem.</p>"
        )
        del reset_url
        return self.send_email(
            to,
            "Recuperacao de senha",
            body_text,
            body_html,
            message_type="password_reset",
        )

    def _config_error_code(self) -> str | None:
        provider = self.config.provider
        if provider == SMTP_PROVIDER:
            if not self.config.from_email:
                return "missing_from_email"
            if not self.config.smtp_host:
                return "missing_smtp_host"
            if self.config.smtp_port is None:
                return "missing_smtp_port"
            if not self.config.smtp_username:
                return "missing_smtp_username"
            if not self.config.smtp_password:
                return "missing_smtp_password"
            return None

        if provider in API_PROVIDERS:
            if not self.config.from_email:
                return "missing_from_email"
            if not self.config.api_key:
                return "missing_api_key"
            return None

        return None

    def _fake_result(self, message_type: str, recipient: str) -> EmailSendResult:
        return self._result(
            success=True,
            sent=False,
            mode="fake",
            message=EMAIL_DISABLED_MESSAGE,
            error_code="email_disabled",
            message_type=message_type,
            recipient=recipient,
        )

    def _failure_result(
        self,
        *,
        mode: str,
        message: str,
        error_code: str,
        message_type: str,
        recipient: str,
    ) -> EmailSendResult:
        return self._result(
            success=False,
            sent=False,
            mode=mode,
            message=message,
            error_code=error_code,
            message_type=message_type,
            recipient=recipient,
        )

    def _result(
        self,
        *,
        success: bool,
        sent: bool,
        mode: str,
        message: str,
        error_code: str | None,
        message_type: str,
        recipient: str,
    ) -> EmailSendResult:
        result = EmailSendResult(
            success=success,
            sent=sent,
            provider=self.config.provider,
            mode=mode,
            message=message,
            error_code=error_code,
            message_type=message_type,
            recipient=recipient,
        )
        logger.info(
            "Email service | provider=%s | mode=%s | type=%s | recipient=%s | sent=%s | success=%s | code=%s",
            result.provider,
            result.mode,
            result.message_type,
            result.recipient,
            result.sent,
            result.success,
            result.error_code or "none",
        )
        return result
