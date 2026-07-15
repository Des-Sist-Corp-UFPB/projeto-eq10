"""Health checks e diagnosticos seguros do app SIA/DATASUS.

Este modulo nao cria schema, nao altera tabelas e nao executa envio real de
e-mail. Os checks retornam apenas metadados seguros para suporte interno.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.ai.config import AI_DATA_SOURCE
from src.ai.pandasai_runner import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_OPENROUTER_MODEL,
)
from src.ai.read_only_datasus import get_readonly_engine
from src.auth.email_service import API_PROVIDERS, FAKE_PROVIDERS, SMTP_PROVIDER, SUPPORTED_PROVIDERS, EmailConfig
from src.auth.email_verification_service import is_email_verification_required
from src.auth.user_service import get_auth_engine, safe_auth_exception_summary

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"

SENSITIVE_KEY_RE = re.compile(
    r"(password|senha|token|secret|credential|credentials|connection_string|database_url|smtp_password|api_key)$",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(password|senha|api[_-]?key|token|secret|smtp[_-]?password)\s*[:=]\s*([^\s;]+)",
    re.IGNORECASE,
)
CONNECTION_URL_RE = re.compile(r"([a-z0-9+]+://[^:\s]+:)([^@\s]+)(@)", re.IGNORECASE)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().strip("\"'").lower() in {"1", "true", "yes", "on"}


def _redact_text(value: str) -> str:
    redacted = CONNECTION_URL_RE.sub(r"\1[REDACTED]\3", value)
    return SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", redacted)


def _sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    safe_details: dict[str, Any] = {}
    for key, value in (details or {}).items():
        safe_details[key] = _sanitize_value(key, value)
    return safe_details


def _sanitize_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_details(value)
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value

    if SENSITIVE_KEY_RE.search(key):
        return "[REDACTED]"

    return _redact_text(str(value))


def _safe_exception_summary(exc: BaseException) -> str:
    if isinstance(exc, SQLAlchemyError):
        return safe_auth_exception_summary(exc)
    return type(exc).__name__


def _default_model_for_provider(provider: str) -> str:
    if provider == "gemini":
        return DEFAULT_GEMINI_MODEL
    if provider == "openrouter":
        return DEFAULT_OPENROUTER_MODEL
    return DEFAULT_LLM_MODEL


def _provider_key_names(provider: str) -> list[str]:
    if provider == "gemini":
        return ["AI_LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]
    if provider == "openrouter":
        return ["AI_LLM_API_KEY", "OPENROUTER_API_KEY"]
    if provider == "openai":
        return ["AI_LLM_API_KEY", "OPENAI_API_KEY"]
    return ["AI_LLM_API_KEY"]


def _is_present(value: str | None) -> bool:
    return bool((value or "").strip())


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(default_factory=_utc_timestamp)

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", _redact_text(self.message))
        object.__setattr__(self, "details", _sanitize_details(self.details))

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at,
        }


class HealthService:
    """Executa diagnosticos internos sem expor segredos."""

    def __init__(
        self,
        *,
        auth_engine: Any | None = None,
        analytics_engine: Any | None = None,
        auth_engine_factory: Callable[[], Any] | None = None,
        analytics_engine_factory: Callable[[], Any] | None = None,
    ):
        self.auth_engine = auth_engine
        self.analytics_engine = analytics_engine
        self.auth_engine_factory = auth_engine_factory or get_auth_engine
        self.analytics_engine_factory = analytics_engine_factory or get_readonly_engine

    def run_all_checks(self) -> list[HealthCheckResult]:
        return [
            self.check_app(),
            self.check_application_database(),
            self.check_application_tables(),
            self.check_datasus_view(),
            self.check_ai_configuration(),
            self.check_email_configuration(),
        ]

    def run_heartbeat(self) -> HealthCheckResult:
        """Executa um ping rapido nas duas bases de dados para o Uptime Kuma.

        Este metodo e chamado em cada ciclo de heartbeat para confirmar que
        o banco de dados de aplicacao E o banco analitico SIA/DATASUS estao
        respondendo. Se qualquer um deles falhar, retorna STATUS_ERROR para
        que o Uptime Kuma sinalize o sistema como offline.

        Returns:
            HealthCheckResult com status 'ok' se ambas as bases responderam,
            ou 'error' com detalhes sobre qual banco falhou.
        """
        results: dict[str, Any] = {
            "auth_db_ok": False,
            "analytics_db_ok": False,
        }
        errors: list[str] = []

        # Ping no banco de autenticacao / aplicacao
        try:
            engine = self._get_auth_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            results["auth_db_ok"] = True
        except Exception as exc:
            safe_cause = _safe_exception_summary(exc)
            errors.append(f"auth_db: {safe_cause}")
            logger.warning(
                "Heartbeat: banco de autenticacao falhou | causa=%s | tipo=%s",
                safe_cause,
                type(exc).__name__,
            )

        # Ping no banco analitico SIA/DATASUS (SELECT 1 simples, sem tocar na view)
        try:
            engine = self._get_analytics_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            results["analytics_db_ok"] = True
        except Exception as exc:
            safe_cause = _safe_exception_summary(exc)
            errors.append(f"analytics_db: {safe_cause}")
            logger.warning(
                "Heartbeat: banco analitico falhou | causa=%s | tipo=%s",
                safe_cause,
                type(exc).__name__,
            )

        if errors:
            return self._result(
                "heartbeat",
                STATUS_ERROR,
                f"Heartbeat falhou: {'; '.join(errors)}",
                {**results, "errors": errors},
            )

        return self._result(
            "heartbeat",
            STATUS_OK,
            "Heartbeat OK: ambas as bases de dados responderam.",
            results,
        )

    def check_app(self) -> HealthCheckResult:
        return self._result(
            "app",
            STATUS_OK,
            "Aplicacao respondendo.",
            {"component": "streamlit", "diagnostics_scope": "internal"},
        )

    def check_application_database(self) -> HealthCheckResult:
        try:
            engine = self._get_auth_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            safe_cause = _safe_exception_summary(exc)
            logger.warning("Diagnostico banco aplicacao falhou | causa=%s | tipo=%s", safe_cause, type(exc).__name__)
            return self._result(
                "application_database",
                STATUS_ERROR,
                "Nao foi possivel conectar ao banco de aplicacao.",
                {"database": "application", "connectivity": False, "safe_cause": safe_cause},
            )

        return self._result(
            "application_database",
            STATUS_OK,
            "Banco de aplicacao acessivel.",
            {"database": "application", "connectivity": True},
        )

    def check_application_tables(self) -> HealthCheckResult:
        required_tables = ["usuarios", "chat_sessions", "chat_messages"]
        try:
            engine = self._get_auth_engine()
            with engine.connect() as conn:
                tables = {table_name: self._table_exists(conn, table_name) for table_name in required_tables}
        except Exception as exc:
            safe_cause = _safe_exception_summary(exc)
            logger.warning("Diagnostico tabelas aplicacao falhou | causa=%s | tipo=%s", safe_cause, type(exc).__name__)
            return self._result(
                "application_tables",
                STATUS_ERROR,
                "Nao foi possivel verificar as tabelas de aplicacao.",
                {"safe_cause": safe_cause},
            )

        missing = [table_name for table_name, exists in tables.items() if not exists]
        if missing:
            return self._result(
                "application_tables",
                STATUS_WARNING,
                "Algumas tabelas de aplicacao ainda nao foram encontradas.",
                {"tables": tables, "missing_tables": missing},
            )

        return self._result(
            "application_tables",
            STATUS_OK,
            "Tabelas de aplicacao encontradas.",
            {"tables": tables},
        )

    def check_datasus_view(self) -> HealthCheckResult:
        try:
            engine = self._get_analytics_engine()
            with engine.connect() as conn:
                row = conn.execute(
                    text(f"SELECT MAX(data) AS ultima_data FROM {AI_DATA_SOURCE}")
                ).mappings().first()
        except Exception as exc:
            safe_cause = _safe_exception_summary(exc)
            logger.warning("Diagnostico view DATASUS falhou | causa=%s | tipo=%s", safe_cause, type(exc).__name__)
            return self._result(
                "datasus_view",
                STATUS_WARNING,
                "Nao foi possivel validar a view analitica readonly.",
                {
                    "source": AI_DATA_SOURCE,
                    "read_only": True,
                    "safe_cause": safe_cause,
                },
            )

        ultima_data = None
        if row and row.get("ultima_data") is not None:
            ultima_data = str(row["ultima_data"])

        return self._result(
            "datasus_view",
            STATUS_OK,
            "View analitica acessivel em modo somente leitura.",
            {
                "source": AI_DATA_SOURCE,
                "read_only": True,
                "latest_date_available": ultima_data,
            },
        )

    def check_ai_configuration(self) -> HealthCheckResult:
        use_llm = _env_flag("AI_USE_LLM", default=True)
        fallback_to_simple = _env_flag("AI_FALLBACK_TO_SIMPLE", default=True)
        provider = (os.getenv("AI_LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).strip().lower()
        model = (os.getenv("AI_LLM_MODEL") or _default_model_for_provider(provider)).strip()
        base_url = (os.getenv("AI_LLM_BASE_URL") or "").strip()
        key_names = _provider_key_names(provider)
        api_key_configured = any(_is_present(os.getenv(key_name)) for key_name in key_names)
        provider_supported = provider in {"openai", "gemini", "openrouter"}

        details = {
            "use_llm": use_llm,
            "provider": provider,
            "provider_supported": provider_supported,
            "model_configured": bool(model),
            "api_key_configured": api_key_configured,
            "base_url_configured": bool(base_url),
            "fallback_to_simple": fallback_to_simple,
        }

        if not use_llm:
            return self._result(
                "ai_configuration",
                STATUS_OK,
                "IA em modo estatistico local; LLM desativado.",
                details,
            )

        if not provider_supported:
            return self._result(
                "ai_configuration",
                STATUS_WARNING,
                "Provedor de IA nao suportado na configuracao atual.",
                details,
            )

        if not model or not api_key_configured:
            return self._result(
                "ai_configuration",
                STATUS_WARNING,
                "Configuracao de IA incompleta.",
                details,
            )

        return self._result(
            "ai_configuration",
            STATUS_OK,
            "Configuracao de IA presente.",
            details,
        )

    def check_email_configuration(self) -> HealthCheckResult:
        config = EmailConfig.from_environment()
        provider = config.provider
        enabled = bool(config.enabled)
        verification_required = is_email_verification_required()
        details = {
            "enabled": enabled,
            "provider": provider,
            "verification_required": verification_required,
            "from_configured": bool(config.from_email),
            "smtp_host_configured": bool(config.smtp_host),
            "smtp_port_configured": config.smtp_port is not None,
            "smtp_username_configured": bool(config.smtp_username),
            "smtp_password_configured": bool(config.smtp_password),
            "api_key_configured": bool(config.api_key),
        }

        if not enabled or provider in FAKE_PROVIDERS:
            return self._result(
                "email_configuration",
                STATUS_OK,
                "E-mail em modo fake/local; nenhum envio real sera feito.",
                details,
            )

        if provider not in SUPPORTED_PROVIDERS:
            return self._result(
                "email_configuration",
                STATUS_ERROR,
                "Provedor de e-mail nao suportado.",
                details,
            )

        missing_fields = self._missing_email_fields(config)
        details["missing_fields"] = missing_fields
        if missing_fields:
            return self._result(
                "email_configuration",
                STATUS_WARNING,
                "Configuracao do provedor de e-mail incompleta.",
                details,
            )

        if provider == SMTP_PROVIDER:
            return self._result(
                "email_configuration",
                STATUS_OK,
                "SMTP configurado para envio real quando EMAIL_ENABLED=true.",
                details,
            )

        return self._result(
            "email_configuration",
            STATUS_WARNING,
            "Provedor por API configurado, mas envio real ainda depende da implementacao do EmailService.",
            details,
        )

    def _get_auth_engine(self) -> Any:
        return self.auth_engine or self.auth_engine_factory()

    def _get_analytics_engine(self) -> Any:
        return self.analytics_engine or self.analytics_engine_factory()

    @staticmethod
    def _table_exists(conn: Any, table_name: str) -> bool:
        if conn.dialect.name == "sqlite":
            row = conn.execute(
                text(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = :table_name
                    LIMIT 1
                    """
                ),
                {"table_name": table_name},
            ).mappings().first()
            return row is not None

        row = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                LIMIT 1
                """
            ),
            {"table_name": table_name},
        ).mappings().first()
        return row is not None

    @staticmethod
    def _missing_email_fields(config: EmailConfig) -> list[str]:
        if config.provider == SMTP_PROVIDER:
            fields = {
                "EMAIL_FROM": config.from_email,
                "EMAIL_SMTP_HOST": config.smtp_host,
                "EMAIL_SMTP_PORT": config.smtp_port,
                "EMAIL_SMTP_USERNAME": config.smtp_username,
                "EMAIL_SMTP_PASSWORD": config.smtp_password,
            }
            return [name for name, value in fields.items() if not value]

        if config.provider in API_PROVIDERS:
            fields = {
                "EMAIL_FROM": config.from_email,
                "EMAIL_API_KEY": config.api_key,
            }
            return [name for name, value in fields.items() if not value]

        return []

    @staticmethod
    def _result(name: str, status: str, message: str, details: dict[str, Any] | None = None) -> HealthCheckResult:
        return HealthCheckResult(
            name=name,
            status=status,
            message=_redact_text(message),
            details=_sanitize_details(details or {}),
        )
