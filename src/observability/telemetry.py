"""Configuracao central e segura de OpenTelemetry.

Este modulo nunca inclui argumentos de negocio em spans. Os chamadores devem usar
somente atributos de baixa cardinalidade definidos em ``SAFE_ATTRIBUTE_KEYS``.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import threading
import time
from urllib.parse import unquote
from functools import wraps
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

logger = logging.getLogger(__name__)

SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "ai.execution_mode", "ai.operation", "ai.metric", "ai.dimension",
        "ai.result_status", "ai.fallback_used", "auth.operation",
        "auth.provider", "auth.result_status", "audit.operation",
        "audit.result_status", "db.system", "db.category", "db.operation",
        "db.view", "db.result_status", "db.row_count", "error.category",
        "result", "app.framework", "deployment.environment",
        "telemetry.verification", "component", "category",
    }
)

_lock = threading.RLock()
_initialized = False
_shutdown_registered = False
_startup_span_emitted = False
_log_filter_installed = False
_tracer_provider: Any = None
_meter_provider: Any = None
_logger_provider: Any = None
_instruments: dict[str, Any] = {}
_status: dict[str, Any] = {
    "enabled": False,
    "service_name": "dsc-eq10",
    "exporter_configured": False,
    "headers_configured": False,
    "provider_type": "noop",
    "processor_configured": False,
    "protocol": "http/protobuf",
    "endpoint_category": "not_configured",
    "last_initialization_result": "disabled",
    "exporter_failure_category": None,
}


@dataclass(frozen=True)
class TelemetryStatus:
    enabled: bool
    service_name: str
    exporter_configured: bool
    headers_configured: bool
    provider_type: str
    processor_configured: bool
    protocol: str
    endpoint_category: str
    last_initialization_result: str
    exporter_failure_category: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "service_name": self.service_name,
            "exporter_configured": self.exporter_configured,
            "headers_configured": self.headers_configured,
            "provider_type": self.provider_type,
            "processor_configured": self.processor_configured,
            "protocol": self.protocol,
            "endpoint_category": self.endpoint_category,
            "last_initialization_result": self.last_initialization_result,
            "exporter_failure_category": self.exporter_failure_category,
        }


class _CorrelationFilter(logging.Filter):
    """Adiciona IDs de correlacao; nao altera a mensagem do log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.otelTraceID = "0"
        record.otelSpanID = "0"
        record.otelServiceName = os.getenv("OTEL_SERVICE_NAME", "dsc-eq10")
        try:
            from opentelemetry import trace

            context = trace.get_current_span().get_span_context()
            if context.is_valid:
                record.otelTraceID = format(context.trace_id, "032x")
                record.otelSpanID = format(context.span_id, "016x")
        except Exception:
            pass
        return True


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().strip("\"'").lower() in {"1", "true", "yes", "on"}


def _endpoint_category(endpoint: str | None) -> str:
    value = (endpoint or "").lower()
    if not value:
        return "not_configured"
    if "alloy" in value or "collector" in value:
        return "internal_collector"
    if "localhost" in value or "127.0.0.1" in value:
        return "local"
    return "remote"


def _safe_service_name(value: str | None) -> str:
    candidate = (value or "dsc-eq10").strip()
    if re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", candidate):
        return candidate
    return "invalid"


def _safe_protocol(value: str | None) -> str:
    candidate = (value or "http/protobuf").strip().lower()
    if candidate in {"http/protobuf", "grpc"}:
        return candidate
    return "unsupported"


def _headers_are_configured(value: str | None) -> bool:
    """Valida apenas a estrutura key=value sem registrar nomes ou valores."""
    for item in (value or "").split(","):
        key, separator, header_value = item.partition("=")
        if separator and unquote(key).strip() and unquote(header_value).strip():
            return True
    return False


def _signal_endpoint(base_endpoint: str, signal: str) -> str:
    """Aplica o caminho OTLP uma vez, inclusive quando a base termina em /otlp."""
    normalized = base_endpoint.rstrip("/")
    suffix = f"/v1/{signal}"
    if normalized.endswith(suffix):
        return normalized
    return f"{normalized}{suffix}"


def _classify_exporter_failure(exc: BaseException) -> str:
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    if "timeout" in name or "timeout" in message:
        return "timeout"
    if any(term in message for term in ("401", "unauthenticated", "authentication")):
        return "authentication"
    if any(term in message for term in ("403", "forbidden", "authorization")):
        return "authorization"
    if any(term in message for term in ("404", "not found")):
        return "endpoint_not_found"
    if any(term in message for term in ("protocol", "protobuf", "grpc")):
        return "protocol_error"
    if any(term in name or term in message for term in ("connection", "dns", "resolve")):
        return "connection"
    if any(term in message for term in ("503", "unavailable")):
        return "unavailable"
    return "unknown"


def _log_safe_status(status: TelemetryStatus) -> None:
    # WARNING e intencional: este log ocorre antes de o Streamlit configurar o
    # logging e deve aparecer exatamente uma vez mesmo com root level WARNING.
    logger.warning(
        "OpenTelemetry status | enabled=%s | service_name=%s | "
        "endpoint_configured=%s | headers_configured=%s | provider_type=%s | "
        "processor_configured=%s | protocol=%s | initialization=%s",
        str(status.enabled).lower(),
        status.service_name,
        str(status.exporter_configured).lower(),
        str(status.headers_configured).lower(),
        status.provider_type,
        str(status.processor_configured).lower(),
        status.protocol,
        status.last_initialization_result,
    )


def _install_log_filter() -> None:
    global _log_filter_installed
    if _log_filter_installed:
        return
    root = logging.getLogger()
    if not any(isinstance(item, _CorrelationFilter) for item in root.filters):
        root.addFilter(_CorrelationFilter())
    for handler in root.handlers:
        if not any(isinstance(item, _CorrelationFilter) for item in handler.filters):
            handler.addFilter(_CorrelationFilter())
    _log_filter_installed = True


class _SafeTelemetryLogFilter(_CorrelationFilter):
    _secret = re.compile(
        r"(?i)(password|senha|token|authorization|api[_-]?key|secret|database_url|smtp_password)"
        r"\s*[:=]\s*[^\s,;]+"
    )
    _email = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("opentelemetry"):
            return False
        super().filter(record)
        message = self._secret.sub(r"\1=[REDACTED]", record.getMessage())
        record.msg = self._email.sub("[EMAIL_REDACTED]", message)
        record.args = ()
        if record.exc_info:
            record.exc_info = None
            record.exc_text = None
        return True


class _SafeSpanExporterProxy:
    """Observa apenas o resultado do exporter, sem acessar payload ou destino."""

    def __init__(self, delegate: Any):
        self._delegate = delegate

    def export(self, spans: Any) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            result = self._delegate.export(spans)
        except Exception as exc:
            _status["exporter_failure_category"] = _classify_exporter_failure(exc)
            logger.warning(
                "OpenTelemetry export failure | category=%s",
                _status["exporter_failure_category"],
            )
            return SpanExportResult.FAILURE
        if result is not SpanExportResult.SUCCESS:
            _status["exporter_failure_category"] = "unknown"
            logger.warning("OpenTelemetry export failure | category=unknown")
        return result

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        force_flush = getattr(self._delegate, "force_flush", None)
        if callable(force_flush):
            return bool(force_flush(timeout_millis=timeout_millis))
        return True


def configure_telemetry() -> TelemetryStatus:
    """Inicializa traces e metricas OTLP uma unica vez por processo."""
    global _initialized, _tracer_provider, _meter_provider, _logger_provider, _shutdown_registered
    with _lock:
        if _initialized:
            return get_telemetry_status()

        enabled = _flag("OTEL_ENABLED", False)
        endpoint = (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
        headers_configured = _headers_are_configured(
            os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
        )
        service_name = _safe_service_name(os.getenv("OTEL_SERVICE_NAME"))
        protocol = _safe_protocol(os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL"))
        _status.update(
            enabled=enabled,
            service_name=service_name,
            exporter_configured=bool(endpoint),
            headers_configured=headers_configured,
            provider_type="noop",
            processor_configured=False,
            protocol=protocol,
            endpoint_category=_endpoint_category(endpoint),
            exporter_failure_category=None,
        )
        _install_log_filter()

        if not enabled:
            _status["last_initialization_result"] = "disabled"
            _initialized = True
            status = get_telemetry_status()
            _log_safe_status(status)
            return status
        if not endpoint:
            logger.warning("OpenTelemetry desativado | causa=endpoint_nao_configurado")
            _status["last_initialization_result"] = "configuration_missing"
            _initialized = True
            status = get_telemetry_status()
            _log_safe_status(status)
            return status
        if protocol != "http/protobuf":
            _status["last_initialization_result"] = "failed"
            _status["exporter_failure_category"] = "protocol_error"
            _initialized = True
            status = get_telemetry_status()
            _log_safe_status(status)
            return status

        try:
            from opentelemetry import metrics, trace
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create(
                {"service.name": service_name}
            )
            if os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower() != "none":
                _tracer_provider = TracerProvider(resource=resource)
                trace_exporter = OTLPSpanExporter(
                    endpoint=_signal_endpoint(endpoint, "traces")
                )
                _tracer_provider.add_span_processor(
                    BatchSpanProcessor(
                        _SafeSpanExporterProxy(trace_exporter)
                    )
                )
                trace.set_tracer_provider(_tracer_provider)
                if trace.get_tracer_provider() is not _tracer_provider:
                    raise RuntimeError("tracer_provider_not_installed")
                _status["provider_type"] = "sdk"
                _status["processor_configured"] = True
            if os.getenv("OTEL_METRICS_EXPORTER", "otlp").lower() != "none":
                reader = PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=_signal_endpoint(endpoint, "metrics"))
                )
                _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
                metrics.set_meter_provider(_meter_provider)
                _create_instruments(metrics.get_meter("eq10.application"))
            if os.getenv("OTEL_LOGS_EXPORTER", "none").lower() == "otlp":
                from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
                from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
                from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

                _logger_provider = LoggerProvider(resource=resource)
                _logger_provider.add_log_record_processor(
                    BatchLogRecordProcessor(
                        OTLPLogExporter(endpoint=_signal_endpoint(endpoint, "logs"))
                    )
                )
                handler = LoggingHandler(level=logging.INFO, logger_provider=_logger_provider)
                handler.name = "eq10-opentelemetry"
                handler.addFilter(_SafeTelemetryLogFilter())
                if not any(item.name == handler.name for item in logging.getLogger().handlers):
                    logging.getLogger().addHandler(handler)

            _status["last_initialization_result"] = "configured"
            if not _shutdown_registered:
                atexit.register(shutdown_telemetry)
                _shutdown_registered = True
        except Exception as exc:
            _status["last_initialization_result"] = "failed"
            _status["exporter_failure_category"] = _classify_exporter_failure(exc)
            logger.warning(
                "OpenTelemetry indisponivel | causa=%s",
                _status["exporter_failure_category"],
            )
        _initialized = True
        status = get_telemetry_status()
        _log_safe_status(status)
        if status.last_initialization_result == "configured":
            _emit_startup_span_once()
        return status


def _create_instruments(meter: Any) -> None:
    counters = (
        "eq10_ai_requests_total", "eq10_ai_requests_blocked_total",
        "eq10_ai_requests_failed_total", "eq10_ai_fallback_total",
        "eq10_analytical_query_errors_total", "eq10_auth_login_total",
        "eq10_auth_login_failures_total", "eq10_email_send_failures_total",
        "eq10_health_checks_total", "eq10_health_check_failures_total",
    )
    for name in counters:
        _instruments[name] = meter.create_counter(name)
    for name in (
        "eq10_ai_request_duration_seconds",
        "eq10_analytical_query_duration_seconds",
        "eq10_health_check_duration_seconds",
    ):
        _instruments[name] = meter.create_histogram(name, unit="s")


def get_telemetry_status() -> TelemetryStatus:
    return TelemetryStatus(**_status)


def _emit_startup_span_once() -> bool:
    global _startup_span_emitted
    if _startup_span_emitted:
        return False
    _startup_span_emitted = True
    return emit_verification_span(
        span_name="app.startup",
        verification="startup",
        flush=False,
    )


def emit_verification_span(
    *,
    span_name: str = "observability.test",
    verification: str = "manual",
    flush: bool = True,
) -> bool:
    """Emite um span sem dados de usuario; sucesso significa tentativa local."""
    status = get_telemetry_status()
    if status.provider_type != "sdk" or status.last_initialization_result != "configured":
        return False
    try:
        from opentelemetry import trace

        with trace.get_tracer("eq10.verification").start_as_current_span(
            span_name,
            attributes={
                "app.framework": "streamlit",
                "deployment.environment": os.getenv("ENVIRONMENT", "unknown")[:32],
                "telemetry.verification": verification[:32],
            },
        ):
            pass
        if flush and _tracer_provider is not None:
            _tracer_provider.force_flush(timeout_millis=5000)
        return True
    except Exception:
        return False


def safe_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Remove chaves inesperadas e valores inadequados antes da exportacao."""
    safe: dict[str, Any] = {}
    for key, value in (attributes or {}).items():
        if key not in SAFE_ATTRIBUTE_KEYS or value is None:
            continue
        if isinstance(value, (bool, int, float)):
            safe[key] = value
        elif isinstance(value, str) and len(value) <= 80:
            safe[key] = value
    return safe


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Cria span seguro; falhas da telemetria nunca escapam para o negocio."""
    configure_telemetry()
    try:
        from opentelemetry import trace
        context = trace.get_tracer("eq10.application").start_as_current_span(
            name, attributes=safe_attributes(attributes)
        )
    except Exception:
        yield None
        return
    with context as current:
        yield current


def set_span_attributes(current: Any, attributes: dict[str, Any]) -> None:
    if current is None:
        return
    for key, value in safe_attributes(attributes).items():
        try:
            current.set_attribute(key, value)
        except Exception:
            pass


def record_error(current: Any, category: str) -> None:
    """Registra apenas categoria, nunca mensagem ou stack com dados."""
    set_span_attributes(current, {"error.category": category})
    try:
        from opentelemetry.trace import Status, StatusCode

        if current is not None:
            current.set_status(Status(StatusCode.ERROR))
    except Exception:
        pass


def add_metric(name: str, value: int = 1, attributes: dict[str, Any] | None = None) -> None:
    try:
        instrument = _instruments.get(name)
        if instrument is not None:
            instrument.add(value, safe_attributes(attributes))
    except Exception:
        pass


def record_duration(name: str, seconds: float, attributes: dict[str, Any] | None = None) -> None:
    try:
        instrument = _instruments.get(name)
        if instrument is not None:
            instrument.record(max(0.0, seconds), safe_attributes(attributes))
    except Exception:
        pass


def trace_ai_request(function: Any) -> Any:
    """Decora o pipeline sem ler ou exportar o prompt recebido."""
    @wraps(function)
    def wrapped(prompt_usuario: str, *args: Any, **kwargs: Any) -> Any:
        from src.ai.prompt_policy import classify_prompt

        decision = classify_prompt(prompt_usuario)
        dimensions = {
            "ai.operation": decision.operation or "unknown",
            "ai.metric": decision.metric or "rows",
            "ai.dimension": decision.dimension or "none",
        }
        started = time.perf_counter()
        with span("ai.request", dimensions) as current:
            try:
                result = function(prompt_usuario, *args, **kwargs)
                with span("ai.response.format"):
                    result_text = str(result)
                    blocked = not decision.allowed or "ainda não está disponível" in result_text.casefold()
                    failed = result_text.startswith(("Ocorreu um erro", "Não foi possível", "O motor"))
                    fallback = "modo estatístico simples" in result_text.casefold() and "modelo de ia" in result_text.casefold()
                mode = "blocked" if blocked else ("llm" if not fallback else "simple")
                status = "blocked" if blocked else ("error" if failed else "success")
                attrs = {
                    **dimensions,
                    "ai.execution_mode": mode,
                    "ai.result_status": status,
                    "ai.fallback_used": fallback,
                }
                set_span_attributes(current, attrs)
                add_metric("eq10_ai_requests_total", attributes={"ai.result_status": status, "ai.execution_mode": mode})
                if blocked:
                    add_metric("eq10_ai_requests_blocked_total", attributes={"ai.result_status": "blocked"})
                if failed:
                    add_metric("eq10_ai_requests_failed_total", attributes={"error.category": "pipeline_error"})
                if fallback:
                    add_metric("eq10_ai_fallback_total", attributes={"ai.execution_mode": "simple"})
                return result
            except Exception:
                record_error(current, "unexpected")
                add_metric("eq10_ai_requests_total", attributes={"ai.result_status": "error"})
                add_metric("eq10_ai_requests_failed_total", attributes={"error.category": "unexpected"})
                raise
            finally:
                record_duration(
                    "eq10_ai_request_duration_seconds",
                    time.perf_counter() - started,
                    dimensions,
                )
    return wrapped


def traced_operation(
    span_name: str,
    attributes: dict[str, Any],
    *,
    success_metric: str | None = None,
    failure_metric: str | None = None,
) -> Any:
    """Instrumenta uma operacao sem inspecionar argumentos ou retornos."""
    def decorate(function: Any) -> Any:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with span(span_name, attributes) as current:
                try:
                    result = function(*args, **kwargs)
                    status_key = "auth.result_status" if span_name.startswith("auth.") else "audit.result_status"
                    result_status = "failure" if getattr(result, "success", True) is False else "success"
                    set_span_attributes(current, {status_key: result_status})
                    if result_status == "success" and success_metric:
                        add_metric(success_metric, attributes={status_key: "success"})
                    if result_status == "failure" and failure_metric:
                        add_metric(failure_metric, attributes={"error.category": "operation_failed"})
                    return result
                except Exception as exc:
                    status_key = "auth.result_status" if span_name.startswith("auth.") else "audit.result_status"
                    set_span_attributes(current, {status_key: "failure"})
                    record_error(current, type(exc).__name__)
                    if failure_metric:
                        add_metric(failure_metric, attributes={"error.category": type(exc).__name__})
                    raise
        return wrapped
    return decorate


def shutdown_telemetry() -> None:
    for provider in (_logger_provider, _meter_provider, _tracer_provider):
        try:
            if provider is not None:
                provider.shutdown()
        except Exception:
            pass


def _reset_for_tests() -> None:
    """Reinicia somente estado local; API reservada aos testes."""
    global _initialized, _tracer_provider, _meter_provider, _logger_provider, _shutdown_registered, _startup_span_emitted
    with _lock:
        _initialized = False
        _tracer_provider = None
        _meter_provider = None
        _logger_provider = None
        _shutdown_registered = False
        _startup_span_emitted = False
        _instruments.clear()
        _status.update(
            enabled=False,
            service_name="dsc-eq10",
            exporter_configured=False,
            headers_configured=False,
            provider_type="noop",
            processor_configured=False,
            protocol="http/protobuf",
            endpoint_category="not_configured",
            last_initialization_result="disabled",
            exporter_failure_category=None,
        )
