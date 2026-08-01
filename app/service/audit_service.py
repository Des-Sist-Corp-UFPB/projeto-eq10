"""Audit logging — ported from src/audit/audit_log_service.py. Raw-SQL persistence
lives in app/database/audit_db.py; this module owns event vocabulary, status
inference and text sanitization.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from app.database.audit_db import get_recent_audit_logs, insert_audit_log
from app.database.connection import get_auth_connection

logger = logging.getLogger(__name__)

EVENT_LOGIN = "login"
EVENT_LOGIN_FAILURE = "login_failure"
EVENT_LOGOUT = "logout"
EVENT_ACCOUNT_CREATED = "account_created"
EVENT_ACCOUNT_DELETED = "account_deleted"
EVENT_ACCOUNT_REACTIVATED = "account_reactivated"
EVENT_PASSWORD_RESET_REQUESTED = "password_reset_requested"
EVENT_PASSWORD_RESET_COMPLETED = "password_reset_completed"
EVENT_EMAIL_CHANGE_REQUESTED = "email_change_requested"
EVENT_EMAIL_CHANGE_CONFIRMED = "email_change_confirmed"
EVENT_EMAIL_VERIFICATION_COMPLETED = "email_verification_completed"
EVENT_CHAT_PROMPT = "chat_prompt"
EVENT_PROMPT_GUARD_BLOCK = "prompt_guard_block"
EVENT_CHAT_PROCESSING_ERROR = "chat_processing_error"
EVENT_ACCESS_GRANTED = "access_granted"
EVENT_ACCESS_REVOKED = "access_revoked"
EVENT_ROLE_CHANGED = "role_changed"
EVENT_ADMIN_ACCESS_DENIED = "admin_access_denied"
EVENT_DATABASE_CONNECTION_FAILURE = "database_connection_failure"
EVENT_EMAIL_SENDING_FAILURE = "email_sending_failure"

VALID_EVENTS = {
    EVENT_LOGIN,
    EVENT_LOGIN_FAILURE,
    EVENT_LOGOUT,
    EVENT_ACCOUNT_CREATED,
    EVENT_ACCOUNT_DELETED,
    EVENT_ACCOUNT_REACTIVATED,
    EVENT_PASSWORD_RESET_REQUESTED,
    EVENT_PASSWORD_RESET_COMPLETED,
    EVENT_EMAIL_CHANGE_REQUESTED,
    EVENT_EMAIL_CHANGE_CONFIRMED,
    EVENT_EMAIL_VERIFICATION_COMPLETED,
    EVENT_CHAT_PROMPT,
    EVENT_PROMPT_GUARD_BLOCK,
    EVENT_CHAT_PROCESSING_ERROR,
    EVENT_ACCESS_GRANTED,
    EVENT_ACCESS_REVOKED,
    EVENT_ROLE_CHANGED,
    EVENT_ADMIN_ACCESS_DENIED,
    EVENT_DATABASE_CONNECTION_FAILURE,
    EVENT_EMAIL_SENDING_FAILURE,
}

SUCCESS_EVENTS = {
    EVENT_LOGIN,
    EVENT_ACCOUNT_CREATED,
    EVENT_ACCOUNT_DELETED,
    EVENT_ACCOUNT_REACTIVATED,
    EVENT_PASSWORD_RESET_COMPLETED,
    EVENT_EMAIL_CHANGE_CONFIRMED,
    EVENT_EMAIL_VERIFICATION_COMPLETED,
    EVENT_ACCESS_GRANTED,
}

FAILURE_EVENTS = {
    EVENT_LOGIN_FAILURE,
    EVENT_CHAT_PROCESSING_ERROR,
    EVENT_DATABASE_CONNECTION_FAILURE,
    EVENT_EMAIL_SENDING_FAILURE,
}

BLOCKED_EVENTS = {
    EVENT_PROMPT_GUARD_BLOCK,
    EVENT_ADMIN_ACCESS_DENIED,
}

INFO_EVENTS = {
    EVENT_LOGOUT,
    EVENT_PASSWORD_RESET_REQUESTED,
    EVENT_EMAIL_CHANGE_REQUESTED,
    EVENT_ACCESS_REVOKED,
    EVENT_ROLE_CHANGED,
    EVENT_CHAT_PROMPT,
}

PROMPT_PREVIEW_MAX_LEN = 160
DETAIL_MAX_LEN = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate(value: str | None, max_len: int = DETAIL_MAX_LEN) -> str | None:
    if value is None:
        return None
    return value[:max_len] if len(value) > max_len else value


def sanitize_text(value: str | None, *, max_len: int = DETAIL_MAX_LEN) -> str | None:
    """Remove valores sensiveis antes de persistir/exibir auditoria."""
    if value is None:
        return None

    clean = str(value).strip()
    if not clean:
        return None

    clean = re.sub(
        r"(?i)\b(password|senha|token|api[_-]?key|secret|client_secret|smtp_password|db_password)\s*[:=]\s*[^\s,;]+",
        r"\1=[oculto]",
        clean,
    )
    clean = re.sub(
        r"(?i)(reset_password_token|verify_email_token|confirm_email_change_token)=([^&\s]+)",
        r"\1=[oculto]",
        clean,
    )
    clean = re.sub(
        r"(?i)\b(postgresql(?:\+\w+)?|mysql|mssql|oracle)://[^\s,;]+",
        "[db-url-oculta]",
        clean,
    )
    clean = re.sub(
        r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[oculto]",
        clean,
    )
    return _truncate(clean, max_len=max_len)


def _sanitize_prompt_preview(value: str | None) -> str | None:
    return sanitize_text(value, max_len=PROMPT_PREVIEW_MAX_LEN)


def _infer_status(evento: str) -> str:
    if evento in SUCCESS_EVENTS:
        return "success"
    if evento in FAILURE_EVENTS:
        return "failure"
    if evento in BLOCKED_EVENTS:
        return "blocked"
    return "info"


def log_event(
    conn: Any,
    evento: str,
    *,
    user_id: int | None = None,
    user_email: str | None = None,
    prompt_text: str | None = None,
    detalhe: str | None = None,
    status: str | None = None,
    source: str | None = None,
    action: str | None = None,
) -> None:
    """Registra um evento de auditoria na conexao fornecida. Nao propaga excecoes."""
    if evento not in VALID_EVENTS:
        logger.warning("audit_log: evento desconhecido ignorado | evento=%s", evento)
        return

    safe_status = (status or _infer_status(evento)).strip().lower()
    if safe_status not in {"success", "failure", "blocked", "info"}:
        safe_status = _infer_status(evento)

    insert_audit_log(
        conn,
        evento,
        user_id,
        sanitize_text(user_email, max_len=320),
        _sanitize_prompt_preview(prompt_text),
        sanitize_text(detalhe),
        safe_status,
        sanitize_text(source, max_len=120),
        sanitize_text(action, max_len=120),
        _now(),
    )


def log_event_safely(evento: str, **kwargs: Any) -> None:
    """Abre sua propria conexao e registra o evento sem jamais propagar excecoes."""
    try:
        conn = get_auth_connection()
    except Exception as exc:
        logger.warning("audit_log: falha ao conectar | evento=%s | tipo=%s", evento, type(exc).__name__)
        return

    try:
        log_event(conn, evento, **kwargs)
    except Exception as exc:
        logger.warning(
            "audit_log: falha ao registrar evento | evento=%s | tipo=%s",
            evento,
            type(exc).__name__,
        )
    finally:
        conn.close()


# ── Audit page — ported from src/ui/admin_page.py ─────────────────────────────────

AUDIT_LIMIT_OPTIONS = (20, 50, 100)
DEFAULT_AUDIT_LIMIT = 50
AUDIT_MAX_FETCH_LIMIT = 500

EVENT_CATEGORY_OPTIONS = ["Todos", "Login", "Conta", "Prompt bloqueado", "Administracao", "Outros"]
STATUS_FILTER_OPTIONS = ["Todos", "success", "failure", "blocked", "info"]
STATUS_FILTER_LABELS = {
    "Todos": "Todos",
    "success": "Sucesso",
    "failure": "Falha",
    "blocked": "Bloqueado",
    "info": "Informativo",
}

STATUS_ALIASES = {
    "success": "success", "sucesso": "success",
    "failure": "failure", "failed": "failure", "fail": "failure", "falha": "failure",
    "erro": "failure", "error": "failure", "invalid": "failure",
    "blocked": "blocked", "block": "blocked", "bloqueado": "blocked", "bloqueada": "blocked",
    "info": "info", "informativo": "info", "informativa": "info",
}

STATUS_BADGE_STYLES = {
    "success": {"background": "#DCFCE7", "text": "#166534", "border": "#86EFAC"},
    "failure": {"background": "#FEE2E2", "text": "#991B1B", "border": "#FCA5A5"},
    "blocked": {"background": "#FEF3C7", "text": "#92400E", "border": "#FCD34D"},
    "info": {"background": "#DBEAFE", "text": "#1E40AF", "border": "#93C5FD"},
}

_EVENT_DISPLAY_LABELS = {
    "login": "Login",
    "login_success": "Login realizado",
    "login_failure": "Falha no login",
    "account_created": "Conta criada",
    "account_deleted": "Conta desativada",
    "account_deactivated": "Conta desativada",
    "account_reactivated": "Conta reativada",
    "chat_prompt": "Pergunta IA",
    "prompt_blocked": "Prompt bloqueado",
    "prompt_guard_block": "Prompt bloqueado",
    "chat_processing_error": "Erro no Chat IA",
    "password_reset_requested": "Recuperacao de senha solicitada",
    "password_reset_completed": "Senha redefinida",
    "email_change_requested": "Alteracao de e-mail solicitada",
    "email_change_confirmed": "E-mail alterado",
    "email_verification_completed": "E-mail verificado",
    "admin_access_denied": "Acesso negado",
    "access_denied": "Acesso negado",
    "access_granted": "Acesso concedido",
    "access_revoked": "Acesso revogado",
    "role_changed": "Papel alterado",
}


def get_recent_logs(limit: int = AUDIT_MAX_FETCH_LIMIT) -> list[dict[str, Any]]:
    conn = get_auth_connection()
    try:
        return get_recent_audit_logs(conn, limit)
    finally:
        conn.close()


def sanitize_display_text(value: str | None, *, max_len: int = 90) -> str:
    """Display-time sanitizer (separate from log-time sanitize_text): also truncates."""
    clean_value = (value or "").strip()
    if not clean_value:
        return "-"

    lowered = clean_value.casefold()
    if any(term in lowered for term in ("traceback", "operationalerror", "sqlalchemy", "psycopg2")):
        return "Erro tecnico registrado com seguranca."

    clean_value = re.sub(
        r"(?i)\b(password|senha|token|api[_-]?key|secret|client_secret|smtp_password|db_password)\s*[:=]\s*[^\s,;]+",
        r"\1=[oculto]",
        clean_value,
    )
    clean_value = re.sub(r"(?i)(postgresql(?:\+\w+)?|mysql|mariadb)://[^\s]+", "[conexao ocultada]", clean_value)
    clean_value = re.sub(
        r"(?i)https?://[^\s]*(reset_password_token|verify_email_token|confirm_email_change_token|token|codigo|code)[^\s]*",
        "[link sensivel ocultado]",
        clean_value,
    )
    if len(clean_value) > max_len:
        clean_value = clean_value[: max_len - 1].rstrip() + "..."
    return clean_value


def _audit_status_from_event(evento: str, detalhe: str | None = None) -> str:
    text = f"{evento or ''} {detalhe or ''}".casefold()
    if "prompt_guard_block" in text or "blocked" in text or "bloque" in text or "denied" in text:
        return "blocked"
    if "fail" in text or "erro" in text or "error" in text or "invalid" in text:
        return "failure"
    if evento in {"login", "login_success", "account_created", "account_deleted", "account_reactivated", "access_granted"}:
        return "success"
    return "info"


def entry_status(entry: dict[str, Any]) -> str:
    stored_status = str(entry.get("status") or "").strip().casefold()
    if stored_status:
        normalized_status = STATUS_ALIASES.get(stored_status, "info")
        if normalized_status != "info" or stored_status in STATUS_ALIASES:
            return normalized_status
    return _audit_status_from_event(entry.get("evento", ""), entry.get("detalhe"))


def status_label(status: str) -> str:
    normalized = STATUS_ALIASES.get(str(status or "").strip().casefold(), "info")
    return {"success": "Sucesso", "failure": "Falha", "blocked": "Bloqueado", "info": "Informativo"}.get(normalized, "Informativo")


def event_category(entry: dict[str, Any]) -> str:
    event = str(entry.get("evento") or "").casefold()
    if "login" in event or "logout" in event:
        return "Login"
    if "prompt_blocked" in event or "prompt_guard_block" in event:
        return "Prompt bloqueado"
    if any(term in event for term in ("admin", "audit", "access", "role", "permission")):
        return "Administracao"
    if any(term in event for term in ("account", "password", "email", "registration", "reactivation", "verification")):
        return "Conta"
    return "Outros"


def event_label(entry: dict[str, Any]) -> str:
    event_name = str(entry.get("evento") or "")
    status = entry_status(entry)
    if "login" in event_name and status == "failure":
        return "Falha no login"
    if "login" in event_name and status == "success":
        return "Login realizado"
    return _EVENT_DISPLAY_LABELS.get(event_name, event_name)


def format_dt(dt: Any) -> str:
    if dt is None:
        return "-"
    try:
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(dt)


def _coerce_entry_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def build_summary(entries: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [entry_status(entry) for entry in entries]
    return {
        "total": len(entries),
        "logins": sum(1 for entry in entries if "login" in str(entry.get("evento") or "").casefold()),
        "failures": sum(1 for status in statuses if status == "failure"),
        "blocked_prompts": sum(1 for status in statuses if status == "blocked"),
    }


def filter_entries(
    entries: list[dict[str, Any]],
    *,
    event_type: str = "Todos",
    user_search: str = "",
    status: str = "Todos",
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    clean_event_type = (event_type or "Todos").strip()
    clean_status = (status or "Todos").strip().casefold()
    clean_search = (user_search or "").strip().casefold()
    filtered = []

    for entry in entries:
        current_status = entry_status(entry)
        entry_email = str(entry.get("user_email") or "").casefold()
        entry_user_id = str(entry.get("user_id") or "").casefold()
        entry_date = _coerce_entry_date(entry.get("criado_em"))

        if clean_event_type != "Todos" and event_category(entry) != clean_event_type:
            continue
        if clean_search and clean_search not in entry_email and clean_search not in entry_user_id:
            continue
        if clean_status != "todos" and current_status != clean_status:
            continue
        if start_date and (not entry_date or entry_date < start_date):
            continue
        if end_date and (not entry_date or entry_date > end_date):
            continue

        filtered.append(entry)

    return filtered


def format_entry_for_display(entry: dict[str, Any]) -> dict[str, str]:
    """Sanitized/formatted fields for both the table row and the detail view."""
    status = entry_status(entry)
    metadata_parts = []
    for label, value in (
        ("ID do evento", entry.get("id")),
        ("ID do usuario", entry.get("user_id")),
        ("Evento interno", entry.get("evento")),
        ("Origem", entry.get("source")),
        ("Acao", entry.get("action")),
    ):
        clean_value = str(value if value is not None else "").strip()
        if clean_value and clean_value != "-":
            metadata_parts.append(f"{label}: {sanitize_display_text(clean_value, max_len=180)}")

    return {
        "evento": event_label(entry),
        "data_hora": format_dt(entry.get("criado_em")),
        "email": sanitize_display_text(entry.get("user_email"), max_len=80),
        "status_key": status,
        "status_label": status_label(status),
        "prompt": sanitize_display_text(entry.get("prompt_text"), max_len=700),
        "detalhe": sanitize_display_text(entry.get("detalhe") or entry.get("prompt_text"), max_len=110),
        "detalhe_full": sanitize_display_text(entry.get("detalhe"), max_len=700),
        "metadados": " | ".join(metadata_parts) or "-",
    }
