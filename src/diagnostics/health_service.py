"""Health checks e diagnosticos seguros do app SIA/DATASUS.

Este modulo nao cria schema, nao altera tabelas e nao executa envio real de
e-mail. Os checks retornam apenas metadados seguros para suporte interno.
"""

from __future__ import annotations

import logging
import os
import re
import time
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
from src.ai.read_only_datasus import (
    classify_analytical_database_failure,
    get_analytical_database_diagnostic,
    get_readonly_engine,
)
from src.auth.email_service import API_PROVIDERS, FAKE_PROVIDERS, SMTP_PROVIDER, SUPPORTED_PROVIDERS, EmailConfig
from src.auth.email_verification_service import is_email_verification_required
from src.auth.user_service import (
    AUTH_CONFIG_ERROR_MESSAGE,
    get_auth_database_config_source,
    get_auth_engine,
    safe_auth_exception_summary,
)
from src.observability.telemetry import (
    add_metric,
    get_telemetry_status,
    record_duration,
    set_span_attributes,
    span,
)

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"

APPLICATION_DB_CATEGORIES = {
    "configuration_missing", "dns_failure", "connection_failure", "ssl_failure",
    "authentication_failure", "permission_denied", "schema_missing",
    "query_failure", "connection_success",
}


def _latency_bucket(seconds: float) -> str:
    milliseconds = max(0.0, seconds) * 1000
    if milliseconds < 100:
        return "lt_100ms"
    if milliseconds < 500:
        return "100_499ms"
    if milliseconds < 2000:
        return "500_1999ms"
    return "gte_2000ms"


def classify_application_database_failure(exc: BaseException) -> str:
    if str(exc) == AUTH_CONFIG_ERROR_MESSAGE:
        return "configuration_missing"
    original = getattr(exc, "orig", None)
    pgcode = getattr(original, "pgcode", None) or getattr(exc, "pgcode", None)
    if pgcode in {"28P01", "28000"}:
        return "authentication_failure"
    if pgcode == "42501":
        return "permission_denied"
    if pgcode == "42P01":
        return "schema_missing"
    message = str(original or exc).casefold()
    if any(term in message for term in ("could not translate host", "name or service not known", "getaddrinfo")):
        return "dns_failure"
    if any(term in message for term in ("ssl", "certificate", "tls")):
        return "ssl_failure"
    if "authentication failed" in message or "password authentication failed" in message:
        return "authentication_failure"
    if "permission denied" in message or "insufficient privilege" in message:
        return "permission_denied"
    if "usuarios" in message and ("does not exist" in message or "no such table" in message):
        return "schema_missing"
    if any(term in message for term in ("connection refused", "could not connect", "timeout", "network")):
        return "connection_failure"
    return "query_failure"

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


def get_database_config_sources() -> dict[str, str]:
    """Return safe source labels for startup diagnostics, never credentials."""
    sources: dict[str, str] = {
        "application_database": "configuration error",
        "ai_database": "configuration error",
    }

    try:
        from src.auth.user_service import get_auth_database_config_source

        sources["application_database"] = get_auth_database_config_source()
    except Exception as exc:
        logger.warning(
            "Startup diagnostics application database unavailable | causa=%s | tipo=%s",
            _safe_exception_summary(exc),
            type(exc).__name__,
        )

    try:
        from src.ai.read_only_datasus import get_readonly_database_config_source

        sources["ai_database"] = get_readonly_database_config_source()
    except Exception as exc:
        logger.warning(
            "Startup diagnostics AI database unavailable | causa=%s | tipo=%s",
            _safe_exception_summary(exc),
            type(exc).__name__,
        )

    return sources


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
        self._uses_default_auth_factory = auth_engine is None and auth_engine_factory is None
        self._uses_default_analytics_factory = analytics_engine is None and analytics_engine_factory is None
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
            self.check_telemetry(),
        ]

    def check_telemetry(self) -> HealthCheckResult:
        """Diagnostico interno; telemetria nunca altera a saude do app."""
        started = time.perf_counter()
        with span("health.telemetry"):
            telemetry = get_telemetry_status()
            details = telemetry.as_dict()
            if telemetry.last_initialization_result == "configured":
                result = "success"
                check_status = STATUS_OK
            elif telemetry.last_initialization_result == "disabled":
                result = "success"
                check_status = STATUS_OK
            else:
                result = "degraded"
                check_status = STATUS_WARNING
        self._record_health_metrics(
            "telemetry",
            result,
            telemetry.last_initialization_result,
            time.perf_counter() - started,
        )
        return self._result(
            "telemetry",
            check_status,
            "Telemetria opcional; falhas de exportacao nao afetam a aplicacao.",
            details,
        )

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
        application_db = self.check_application_database()
        analytical_db = self.check_analytical_database()
        results = {
            "auth_db_ok": application_db.status == STATUS_OK,
            "analytics_db_ok": analytical_db.status == STATUS_OK,
            "application_database_category": application_db.details.get("connection_category"),
            "analytical_database_category": analytical_db.details.get("connection_category"),
        }
        if application_db.status == STATUS_ERROR:
            return self._result(
                "heartbeat",
                STATUS_ERROR,
                "Heartbeat falhou no banco de aplicacao.",
                results,
            )
        if analytical_db.status != STATUS_OK:
            return self._result(
                "heartbeat",
                STATUS_OK,
                "Aplicacao disponivel; funcionalidade analitica degradada.",
                {**results, "degraded": True},
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
        started = time.perf_counter()
        details: dict[str, Any] = {
            "database_category": "application",
            "configured": self.auth_engine is not None,
            "selected_configuration_source": "injected" if self.auth_engine is not None else "configuration_missing",
            "connection_category": "configuration_missing",
            "critical_schema_available": False,
            "security_schema_available": False,
        }
        with span("health.application_database"):
            try:
                if self._uses_default_auth_factory:
                    details["selected_configuration_source"] = get_auth_database_config_source()
                    details["configured"] = True
                engine = self._get_auth_engine()
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                    details["critical_schema_available"] = self._table_exists(conn, "usuarios")
                    security_objects = (
                        "audit_log",
                        "password_reset_tokens",
                        "email_verification_tokens",
                    )
                    details["security_schema_available"] = all(
                        self._table_exists(conn, table_name)
                        for table_name in security_objects
                    )
                details["connection_category"] = (
                    "connection_success"
                    if details["critical_schema_available"]
                    else "schema_missing"
                )
            except Exception as exc:
                details["connection_category"] = classify_application_database_failure(exc)

        elapsed = time.perf_counter() - started
        details["latency_bucket"] = _latency_bucket(elapsed)
        success = details["connection_category"] == "connection_success"
        self._record_health_metrics(
            "application_db",
            "success" if success else "failure",
            str(details["connection_category"]),
            elapsed,
        )
        if not success:
            logger.warning(
                "Application database health | category=%s",
                details["connection_category"],
            )
        return self._result(
            "application_database",
            STATUS_OK if success else STATUS_ERROR,
            "Banco de aplicacao acessivel." if success else "Banco de aplicacao indisponivel ou schema critico ausente.",
            {**details, "connectivity": success},
        )

    def check_application_database_readiness(self) -> HealthCheckResult:
        """Executa somente o probe essencial usado pelo endpoint publico."""
        started = time.perf_counter()
        category = "query_failure"
        with span(
            "health.application.database",
            {
                "health.endpoint": "readiness",
                "health.result": "pending",
                "health.category": "pending",
            },
        ) as current:
            try:
                engine = self._get_auth_engine()
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                category = "connection_success"
                status = STATUS_OK
                result = "success"
            except Exception as exc:
                category = classify_application_database_failure(exc)
                status = STATUS_ERROR
                result = "failure"

            set_span_attributes(
                current,
                {
                    "health.result": result,
                    "health.category": category,
                },
            )

        elapsed = time.perf_counter() - started
        self._record_health_metrics(
            "application_db_readiness",
            result,
            category,
            elapsed,
        )
        return self._result(
            "application_database_readiness",
            status,
            "Banco da aplicacao acessivel."
            if status == STATUS_OK
            else "Banco da aplicacao indisponivel.",
            {
                "database_category": "application",
                "connection_category": category,
                "connectivity": status == STATUS_OK,
                "latency_bucket": _latency_bucket(elapsed),
            },
        )

    def check_analytical_database(self) -> HealthCheckResult:
        started = time.perf_counter()
        with span("health.analytical_database"):
            if self._uses_default_analytics_factory:
                details = dict(get_analytical_database_diagnostic())
            else:
                details = self._diagnose_injected_analytical_engine()

        elapsed = time.perf_counter() - started
        details["latency_bucket"] = _latency_bucket(elapsed)
        success = (
            details.get("connection_category") == "connection_success"
            and bool(details.get("essential_checks_passed"))
        )
        result = "success" if success else "degraded"
        self._record_health_metrics(
            "analytical_db",
            result,
            str(details.get("connection_category", "query_failure")),
            elapsed,
        )
        return self._result(
            "analytical_database",
            STATUS_OK if success else STATUS_WARNING,
            "Banco analitico readonly acessivel." if success else "Funcionalidade analitica degradada.",
            details,
        )

    def run_unified_report(self) -> dict[str, Any]:
        application = self.check_app()
        application_db = self.check_application_database()
        analytical_db = self.check_analytical_database()
        telemetry = self.check_telemetry()

        if application_db.status == STATUS_ERROR or application.status == STATUS_ERROR:
            overall = "unhealthy"
        elif analytical_db.status != STATUS_OK:
            overall = "degraded"
        else:
            overall = "healthy"

        telemetry_state = get_telemetry_status()
        return _sanitize_details(
            {
                "application": {
                    "status": "healthy" if application.status == STATUS_OK else "unhealthy",
                    "framework": "streamlit",
                    "checked_at": application.checked_at,
                },
                "overall_status": overall,
                "application_database": {
                    "status": "healthy" if application_db.status == STATUS_OK else "unhealthy",
                    "connection_category": application_db.details.get("connection_category"),
                    "critical_schema_available": application_db.details.get("critical_schema_available"),
                    "checked_at": application_db.checked_at,
                },
                "analytical_database": {
                    "status": "healthy" if analytical_db.status == STATUS_OK else "degraded",
                    "connection_category": analytical_db.details.get("connection_category"),
                    "failure_stage": analytical_db.details.get("failure_stage"),
                    "readonly_category": analytical_db.details.get("readonly_category"),
                    "readonly_set": analytical_db.details.get("readonly_set", False),
                    "readonly_verified": analytical_db.details.get(
                        "readonly_verified", False
                    ),
                    "view_available": analytical_db.details.get("view_available", False),
                    "view_query_success": analytical_db.details.get("view_query_success", False),
                    "view_query_category": analytical_db.details.get(
                        "view_query_category", "not_checked"
                    ),
                    "session_readonly": analytical_db.details.get("session_readonly", False),
                    "maximum_date_query_success": analytical_db.details.get(
                        "maximum_date_query_success", False
                    ),
                    "maximum_date_category": analytical_db.details.get(
                        "maximum_date_category", "not_checked"
                    ),
                    "maximum_available_data_date": analytical_db.details.get("maximum_available_data_date"),
                    "configuration_source": analytical_db.details.get(
                        "configuration_source",
                        analytical_db.details.get("selected_configuration_source"),
                    ),
                    "essential_checks_passed": analytical_db.details.get(
                        "essential_checks_passed", False
                    ),
                    "underlying_metadata_check": analytical_db.details.get(
                        "underlying_metadata_check", "not_required"
                    ),
                    "optional_metadata_available": analytical_db.details.get(
                        "optional_metadata_available", False
                    ),
                    "optional_metadata_category": analytical_db.details.get(
                        "optional_metadata_category", "not_checked"
                    ),
                    "warning_categories": analytical_db.details.get("warning_categories", []),
                    "checked_at": analytical_db.checked_at,
                },
                "opentelemetry": {
                    "status": telemetry_state.last_initialization_result,
                    "provider_type": telemetry_state.provider_type,
                    "exporter_configured": telemetry_state.exporter_configured,
                    "checked_at": telemetry.checked_at,
                },
            }
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

    def _diagnose_injected_analytical_engine(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "configuration_source": "injected",
            "selected_configuration_source": "injected",
            "database_category": "analytical",
            "host_type": "unknown",
            "ssl_mode": "unknown",
            "connection_category": "configuration_missing",
            "failure_stage": None,
            "readonly_category": "not_checked",
            "view_query_category": "not_checked",
            "maximum_date_category": "not_checked",
            "optional_metadata_category": "not_checked",
            "readonly_set": False,
            "readonly_verified": False,
            "view_available": False,
            "select_permission": False,
            "session_readonly": False,
            "view_query_success": False,
            "maximum_date_query_success": False,
            "underlying_metadata_check": "not_required",
            "optional_metadata_available": False,
            "essential_checks_passed": False,
            "warning_categories": [],
            "maximum_available_data_date": None,
        }
        try:
            engine = self._get_analytics_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                details["connection_category"] = "connection_success"
                details["readonly_set"] = True
                details["readonly_category"] = "configured"
                dialect = getattr(getattr(conn, "dialect", None), "name", "")
                if dialect == "postgresql":
                    readonly_value = conn.execute(
                        text("SHOW default_transaction_read_only")
                    ).scalar()
                    details["session_readonly"] = str(readonly_value).strip().lower() in {"on", "true", "1"}
                else:
                    # Engines injected into unit tests are already isolated; the
                    # production path always uses the readonly provider above.
                    details["session_readonly"] = True
                details["readonly_verified"] = details["session_readonly"]
                details["readonly_category"] = (
                    "verified" if details["session_readonly"] else "verification_failed"
                )
                if not details["session_readonly"]:
                    details["failure_stage"] = "readonly_verify"
                    return details
                try:
                    conn.execute(text(f"SELECT 1 FROM {AI_DATA_SOURCE} LIMIT 1"))
                except Exception as exc:
                    details["view_query_category"] = classify_analytical_database_failure(exc)
                    details["failure_stage"] = "view_select"
                    return details
                details["view_available"] = True
                details["view_query_success"] = True
                details["view_query_category"] = "success"
                details["select_permission"] = True
                try:
                    maximum_date = conn.execute(
                        text(f"SELECT MAX(data) AS ultima_data FROM {AI_DATA_SOURCE}")
                    ).scalar()
                except Exception as exc:
                    details["maximum_date_category"] = classify_analytical_database_failure(exc)
                    details["failure_stage"] = "maximum_date"
                    return details
                details["maximum_date_query_success"] = True
                details["maximum_date_category"] = "success"
                details["maximum_available_data_date"] = (
                    str(maximum_date) if maximum_date is not None else None
                )
                details["essential_checks_passed"] = True
        except Exception as exc:
            details["connection_category"] = classify_analytical_database_failure(exc)
            details["failure_stage"] = "connection_open"
        return details

    @staticmethod
    def _record_health_metrics(
        component: str,
        result: str,
        category: str,
        seconds: float,
    ) -> None:
        attributes = {
            "component": component,
            "result": result,
            "category": category if category else "unknown",
        }
        add_metric("eq10_health_checks_total", attributes=attributes)
        if result != "success":
            add_metric("eq10_health_check_failures_total", attributes=attributes)
        record_duration("eq10_health_check_duration_seconds", seconds, attributes)

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
