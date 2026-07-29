"""Pagina de administracao restrita: log de auditoria e gestao de usuarios.

Visivel apenas para admins, Super Admins e usuarios com can_view_audit=True.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import streamlit as st

from src.auth.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    can_view_audit_log,
    is_super_admin,
    role_display_name,
)
from src.auth.session import get_authenticated_user
from src.diagnostics.health_service import HealthService
from src.observability.telemetry import emit_verification_span
from src.ui.styles import AUDIT_PAGE_CSS as ADMIN_PAGE_CSS
from src.ui.styles import apply_audit_light_styles

logger = logging.getLogger(__name__)

ROLE_OPTIONS = [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]
AUDIT_LIMIT_OPTIONS = [20, 50, 100]
DEFAULT_AUDIT_LIMIT = 50
AUDIT_MAX_FETCH_LIMIT = 500
AUDIT_SELECTED_EVENT_KEY = "audit_selected_event"
AUDIT_SUMMARY_FILTER_KEY = "audit_summary_filter"
AUDIT_SUMMARY_FILTER_ALL = "all"
AUDIT_SUMMARY_FILTER_LOGINS = "logins"
AUDIT_SUMMARY_FILTER_FAILURES = "failures"
AUDIT_SUMMARY_FILTER_BLOCKED = "blocked_prompts"

EVENT_CATEGORY_OPTIONS = [
    "Todos",
    "Login",
    "Conta",
    "Prompt bloqueado",
    "Administracao",
    "Outros",
]

STATUS_FILTER_OPTIONS = ["Todos", "success", "failure", "blocked", "info"]
STATUS_FILTER_LABELS = {
    "Todos": "Todos",
    "success": "Sucesso",
    "failure": "Falha",
    "blocked": "Bloqueado",
    "info": "Informativo",
}

STATUS_ALIASES = {
    "success": "success",
    "sucesso": "success",
    "failure": "failure",
    "failed": "failure",
    "fail": "failure",
    "falha": "failure",
    "erro": "failure",
    "error": "failure",
    "invalid": "failure",
    "blocked": "blocked",
    "block": "blocked",
    "bloqueado": "blocked",
    "bloqueada": "blocked",
    "info": "info",
    "informativo": "info",
    "informativa": "info",
}

STATUS_BADGE_STYLES = {
    "success": {
        "background": "#DCFCE7",
        "text": "#166534",
        "border": "#86EFAC",
    },
    "failure": {
        "background": "#FEE2E2",
        "text": "#991B1B",
        "border": "#FCA5A5",
    },
    "blocked": {
        "background": "#FEF3C7",
        "text": "#92400E",
        "border": "#FCD34D",
    },
    "info": {
        "background": "#DBEAFE",
        "text": "#1E40AF",
        "border": "#93C5FD",
    },
}


def _safe_admin_error_summary(exc: BaseException) -> str:
    try:
        from src.auth.user_service import safe_auth_exception_summary

        return safe_auth_exception_summary(exc)
    except Exception:
        return type(exc).__name__


def _truncate_display(value: str | None, max_len: int = 90) -> str:
    clean_value = (value or "").strip()
    if len(clean_value) <= max_len:
        return clean_value
    return clean_value[: max_len - 1].rstrip() + "..."


def _sanitize_audit_text(value: str | None, *, max_len: int = 90) -> str:
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
    clean_value = re.sub(
        r"(?i)(postgresql(?:\+\w+)?|mysql|mariadb)://[^\s]+",
        "[conexao ocultada]",
        clean_value,
    )
    clean_value = re.sub(
        r"(?i)https?://[^\s]*(reset_password_token|verify_email_token|confirm_email_change_token|token|codigo|code)[^\s]*",
        "[link sensivel ocultado]",
        clean_value,
    )
    return _truncate_display(clean_value, max_len=max_len)


def _audit_status(evento: str, detalhe: str | None = None) -> str:
    text = f"{evento or ''} {detalhe or ''}".casefold()
    if "prompt_guard_block" in text or "blocked" in text or "bloque" in text or "denied" in text:
        return "blocked"
    if "fail" in text or "erro" in text or "error" in text or "invalid" in text:
        return "failure"
    if evento in {"login", "login_success", "account_created", "account_deleted", "account_reactivated", "access_granted"}:
        return "success"
    return "info"


def _normalize_status(status: Any) -> str:
    clean_status = str(status or "").strip().casefold()
    return STATUS_ALIASES.get(clean_status, "info")


def _entry_status(entry: Any) -> str:
    stored_status = str(getattr(entry, "status", "") or "").strip().casefold()
    if stored_status:
        normalized_status = _normalize_status(stored_status)
        if normalized_status != "info" or stored_status in STATUS_ALIASES:
            return normalized_status
    return _audit_status(getattr(entry, "evento", ""), getattr(entry, "detalhe", None))


def _audit_status_label(status: str) -> str:
    normalized_status = _normalize_status(status)
    return {
        "success": "Sucesso",
        "failure": "Falha",
        "blocked": "Bloqueado",
        "info": "Informativo",
    }.get(normalized_status, "Informativo")


def _get_status_badge_style(status: Any) -> str:
    style = STATUS_BADGE_STYLES.get(_normalize_status(status), STATUS_BADGE_STYLES["info"])
    return (
        f"background-color: {style['background']}; "
        f"color: {style['text']}; "
        f"border: 1px solid {style['border']}; "
        "font-weight: 700; "
        "text-align: center; "
        "border-radius: 999px;"
    )


def _audit_detail(entry: Any, *, max_len: int = 90) -> str:
    detail = getattr(entry, "detalhe", None) or getattr(entry, "prompt_text", None) or ""
    return _sanitize_audit_text(detail, max_len=max_len)


def _audit_summary(entries: list) -> dict[str, int]:
    statuses = [_entry_status(entry) for entry in entries]
    return {
        "total": len(entries),
        "logins": sum(1 for entry in entries if "login" in str(getattr(entry, "evento", "") or "").casefold()),
        "failures": sum(1 for status in statuses if status == "failure"),
        "blocked_prompts": sum(1 for entry in entries if _entry_status(entry) == "blocked"),
    }


def _coerce_entry_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _available_event_types(entries: list) -> list[str]:
    return sorted({str(getattr(entry, "evento", "") or "") for entry in entries if getattr(entry, "evento", None)})


def _event_category(value: Any) -> str:
    raw_event = getattr(value, "evento", value)
    event = str(raw_event or "").casefold()

    if "login" in event or "logout" in event:
        return "Login"
    if "prompt_blocked" in event or "prompt_guard_block" in event:
        return "Prompt bloqueado"
    if any(term in event for term in ("admin", "audit", "access", "role", "permission")):
        return "Administracao"
    if any(
        term in event
        for term in (
            "account",
            "password",
            "email",
            "registration",
            "reactivation",
            "verification",
        )
    ):
        return "Conta"
    return "Outros"


def _matches_event_filter(entry: Any, event_filter: str) -> bool:
    clean_filter = (event_filter or "Todos").strip()
    if clean_filter == "Todos":
        return True

    entry_event = str(getattr(entry, "evento", "") or "")
    if clean_filter in EVENT_CATEGORY_OPTIONS:
        return _event_category(entry) == clean_filter

    # Backwards-compatible path for older tests/helpers that still pass raw event names.
    return entry_event == clean_filter


def _apply_summary_filter(entries: list, summary_filter: str | None) -> list:
    clean_filter = summary_filter or AUDIT_SUMMARY_FILTER_ALL
    if clean_filter == AUDIT_SUMMARY_FILTER_LOGINS:
        return [entry for entry in entries if _event_category(entry) == "Login"]
    if clean_filter == AUDIT_SUMMARY_FILTER_FAILURES:
        return [entry for entry in entries if _entry_status(entry) == "failure"]
    if clean_filter == AUDIT_SUMMARY_FILTER_BLOCKED:
        return [entry for entry in entries if _entry_status(entry) == "blocked"]
    return entries


def _filter_audit_entries(
    entries: list,
    *,
    event_type: str = "Todos",
    user_search: str = "",
    status: str = "Todos",
    start_date: date | None = None,
    end_date: date | None = None,
    only_failures: bool = False,
    only_blocked: bool = False,
) -> list:
    clean_event_type = (event_type or "Todos").strip()
    clean_status = (status or "Todos").strip().casefold()
    clean_search = (user_search or "").strip().casefold()
    filtered = []

    for entry in entries:
        entry_status = _entry_status(entry)
        entry_email = str(getattr(entry, "user_email", "") or "").casefold()
        entry_user_id = str(getattr(entry, "user_id", "") or "").casefold()
        entry_date = _coerce_entry_date(getattr(entry, "criado_em", None))

        if not _matches_event_filter(entry, clean_event_type):
            continue
        if clean_search and clean_search not in entry_email and clean_search not in entry_user_id:
            continue
        if clean_status != "todos" and entry_status != clean_status:
            continue
        if only_failures and entry_status != "failure":
            continue
        if only_blocked and entry_status != "blocked":
            continue
        if start_date and (not entry_date or entry_date < start_date):
            continue
        if end_date and (not entry_date or entry_date > end_date):
            continue

        filtered.append(entry)

    return filtered


def _limit_audit_entries(entries: list, limit: int) -> list:
    safe_limit = limit if limit in AUDIT_LIMIT_OPTIONS else DEFAULT_AUDIT_LIMIT
    return entries[:safe_limit]


def _event_display(evento: str) -> str:
    labels = {
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
    return labels.get(evento, evento)


def _event_label(entry: Any) -> str:
    event_name = str(getattr(entry, "evento", "") or "")
    status = _entry_status(entry)
    if "login" in event_name and status == "failure":
        return "Falha no login"
    if "login" in event_name and status == "success":
        return "Login realizado"
    return _event_display(event_name)


def _format_dt(dt: Any) -> str:
    if dt is None:
        return "-"
    try:
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return str(dt)


def _user_value(user: dict[str, Any] | Any | None, key: str, default: Any = "") -> Any:
    if not user:
        return default
    if isinstance(user, dict):
        return user.get(key, default)
    return getattr(user, key, default)


def _user_initials(user: dict[str, Any] | Any | None) -> str:
    name = str(_user_value(user, "nome", "") or _user_value(user, "email", "") or "").strip()
    parts = [part for part in re.split(r"\s+", name) if part]
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[-1][0]}".upper()
    if parts:
        return parts[0][:2].upper()
    return "AD"


def _safe_button(label: str, **kwargs: Any) -> bool:
    try:
        return bool(st.button(label, **kwargs))
    except TypeError:
        kwargs.pop("icon", None)
        return bool(st.button(label, **kwargs))


@st.cache_resource(show_spinner=False)
def _get_user_service():
    from src.auth.user_service import UserService

    return UserService.from_environment()


@st.cache_resource(show_spinner=False)
def _get_audit_service():
    from src.audit.audit_log_service import AuditLogService

    return AuditLogService.from_environment()


def _render_audit_header(user: dict[str, Any] | Any) -> None:
    st.title("Painel de Auditoria")
    st.caption("Area restrita para administradores. Acompanhe eventos recentes do sistema.")
    name = str(_user_value(user, "nome", "") or "Administrador").strip()
    role = role_display_name(str(_user_value(user, "role", ROLE_USER) or ROLE_USER))
    st.caption(f"Logada como {name} · {role}")


def _render_audit_summary(entries: list) -> None:
    summary = _audit_summary(entries)
    cards = [
        ("Total de eventos", summary["total"]),
        ("Logins", summary["logins"]),
        ("Falhas", summary["failures"]),
        ("Prompts bloqueados", summary["blocked_prompts"]),
    ]
    columns = st.columns(4)
    for column, (label, value) in zip(columns, cards):
        with column:
            st.metric(label, value)


def _render_audit_filters(entries: list) -> dict[str, Any]:
    event_options = EVENT_CATEGORY_OPTIONS

    first_row = st.columns([1.1, 1.3, 1.15])
    with first_row[0]:
        limit = st.selectbox(
            "Quantidade",
            AUDIT_LIMIT_OPTIONS,
            index=AUDIT_LIMIT_OPTIONS.index(DEFAULT_AUDIT_LIMIT),
            key="audit-result-limit",
            help="Define quantos registros recentes serao exibidos.",
        )
    with first_row[1]:
        event_type = st.selectbox(
            "Tipo de evento",
            event_options,
            index=0,
            key="audit-filter-event-type",
            help="Filtre por categoria de evento.",
        )
    with first_row[2]:
        status = st.selectbox(
            "Status",
            STATUS_FILTER_OPTIONS,
            index=0,
            key="audit-filter-status",
            format_func=lambda value: STATUS_FILTER_LABELS.get(str(value), str(value)),
            help="Filtre por sucesso, falha, bloqueado ou informativo.",
        )

    second_row = st.columns([1.35, 1, 1])
    with second_row[0]:
        user_search = st.text_input(
            "Buscar por e-mail",
            value="",
            key="audit-filter-user-search",
            help="Digite parte do e-mail do usuario.",
        )
    with second_row[1]:
        start_date = st.date_input(
            "Data inicial",
            value=None,
            key="audit-filter-start-date",
            help="Filtre eventos a partir desta data.",
        )
    with second_row[2]:
        end_date = st.date_input(
            "Data final",
            value=None,
            key="audit-filter-end-date",
            help="Filtre eventos ate esta data.",
        )

    button_row = st.columns([1, 1, 1, 3])
    with button_row[0]:
        if _safe_button("Atualizar", use_container_width=True, key="audit-refresh"):
            st.rerun()
    with button_row[1]:
        if _safe_button("Limpar filtros", use_container_width=True, key="audit-clear-filters"):
            for key in (
                "audit-filter-event-type",
                "audit-filter-user-search",
                "audit-filter-status",
                "audit-filter-start-date",
                "audit-filter-end-date",
                "audit-result-limit",
                AUDIT_SUMMARY_FILTER_KEY,
            ):
                st.session_state.pop(key, None)
            st.rerun()
    with button_row[2]:
        if _safe_button("Aplicar filtros", type="primary", use_container_width=True, key="audit-apply-filters"):
            st.rerun()

    return {
        "limit": limit,
        "event_type": event_type,
        "user_search": user_search,
        "status": status,
        "start_date": start_date if isinstance(start_date, date) else None,
        "end_date": end_date if isinstance(end_date, date) else None,
        "only_failures": False,
        "only_blocked": False,
    }


def _render_status_badge(status: str) -> None:
    normalized_status = _normalize_status(status)
    label = _audit_status_label(status)
    badge = getattr(st, "badge", None)
    if callable(badge):
        color = {
            "success": "green",
            "failure": "red",
            "blocked": "orange",
            "info": "blue",
        }.get(normalized_status, "blue")
        try:
            badge(label, color=color)
            return
        except Exception:
            pass

    if normalized_status == "success":
        st.success(label)
    elif normalized_status == "failure":
        st.error(label)
    elif normalized_status == "blocked":
        st.warning(label)
    else:
        st.info(label)


def _render_event_badge(label: str) -> None:
    badge = getattr(st, "badge", None)
    if callable(badge):
        try:
            badge(label, color="blue")
            return
        except Exception:
            pass
    st.write(f"**{label}**")


def _audit_table_rows(entries: list) -> list[dict[str, str]]:
    return [
        {
            "Data/Hora": _format_dt(getattr(entry, "criado_em", None)),
            "Evento": _event_label(entry),
            "E-mail": _sanitize_audit_text(getattr(entry, "user_email", None), max_len=80),
            "Status": _audit_status_label(_entry_status(entry)),
            "Detalhe": _audit_detail(entry, max_len=110),
        }
        for entry in entries
    ]


def _audit_table_data(entries: list) -> Any:
    rows = _audit_table_rows(entries)
    try:
        import pandas as pd

        return pd.DataFrame(rows, columns=["Data/Hora", "Evento", "E-mail", "Status", "Detalhe"])
    except Exception:
        return rows


def _style_audit_table_data(table_data: Any) -> Any:
    if not hasattr(table_data, "style"):
        return table_data

    try:
        styler = table_data.style.set_properties(
            **{
                "background-color": "#FFFFFF",
                "color": "#111827",
                "border-color": "#E2E8F0",
            }
        ).set_table_styles(
            [
                {
                    "selector": "th",
                    "props": [
                        ("background-color", "#F8FAFC"),
                        ("color", "#334155"),
                        ("font-weight", "700"),
                        ("border-color", "#E2E8F0"),
                    ],
                },
                {
                    "selector": "td",
                    "props": [
                        ("background-color", "#FFFFFF"),
                        ("color", "#111827"),
                        ("border-color", "#E2E8F0"),
                    ],
                },
            ]
        )
        return styler.map(_get_status_badge_style, subset=["Status"])
    except AttributeError:
        try:
            return table_data.style.set_properties(
                **{
                    "background-color": "#FFFFFF",
                    "color": "#111827",
                    "border-color": "#E2E8F0",
                }
            ).applymap(_get_status_badge_style, subset=["Status"])
        except Exception:
            return table_data
    except Exception:
        return table_data


def _audit_event_key(entry: Any, index: int) -> str:
    raw_key = getattr(entry, "id", None) or f"{getattr(entry, 'evento', '')}-{getattr(entry, 'criado_em', '')}-{index}"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(raw_key))[:72] or str(index)


def _audit_event_option_label(entry: Any, index: int) -> str:
    timestamp = _format_dt(getattr(entry, "criado_em", None))
    email = _sanitize_audit_text(getattr(entry, "user_email", None), max_len=34)
    return f"{timestamp} · {_event_label(entry)} · {email}"


def _audit_entry_snapshot(entry: Any) -> dict[str, str]:
    metadata = {
        "ID do evento": getattr(entry, "id", "-"),
        "ID do usuario": getattr(entry, "user_id", None) or "-",
        "Evento interno": getattr(entry, "evento", None) or "-",
        "Origem": getattr(entry, "route", None) or getattr(entry, "source", None) or getattr(entry, "origem", None) or "-",
        "Acao": getattr(entry, "action", None) or "-",
    }
    metadata_text = " | ".join(
        f"{label}: {_sanitize_audit_text(str(value), max_len=180)}"
        for label, value in metadata.items()
        if str(value or "").strip() and str(value or "").strip() != "-"
    )

    return {
        "Evento": _event_label(entry),
        "Data/Hora": _format_dt(getattr(entry, "criado_em", None)),
        "E-mail": _sanitize_audit_text(getattr(entry, "user_email", None), max_len=220),
        "StatusKey": _entry_status(entry),
        "Status": _audit_status_label(_entry_status(entry)),
        "Prompt": _sanitize_audit_text(getattr(entry, "prompt_text", None), max_len=700),
        "Detalhe": _sanitize_audit_text(getattr(entry, "detalhe", None), max_len=700),
        "Metadados": metadata_text or "-",
    }


def _clear_selected_audit_event() -> None:
    st.session_state.pop(AUDIT_SELECTED_EVENT_KEY, None)


def _render_detail_field(label: str, value: str) -> None:
    st.caption(label)
    st.write(value or "-")


def _render_audit_event_dialog_body(snapshot: dict[str, str]) -> None:
    first_row = st.columns(2)
    with first_row[0]:
        _render_detail_field("Evento", snapshot.get("Evento", "-"))
    with first_row[1]:
        st.caption("Status")
        _render_status_badge(snapshot.get("StatusKey", snapshot.get("Status", "info")))

    second_row = st.columns(2)
    with second_row[0]:
        _render_detail_field("Data/Hora", snapshot.get("Data/Hora", "-"))
    with second_row[1]:
        _render_detail_field("E-mail", snapshot.get("E-mail", "-"))

    if snapshot.get("Prompt") and snapshot.get("Prompt") != "-":
        _render_detail_field("Prompt", snapshot.get("Prompt", "-"))
    _render_detail_field("Detalhe", snapshot.get("Detalhe", "-"))
    _render_detail_field("Metadados", snapshot.get("Metadados", "-"))

    if st.button("Fechar", key="audit-detail-close", use_container_width=True):
        _clear_selected_audit_event()
        st.rerun()


def _render_selected_audit_event_dialog() -> None:
    snapshot = st.session_state.get(AUDIT_SELECTED_EVENT_KEY)
    if not isinstance(snapshot, dict):
        return

    dialog_factory = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)
    if callable(dialog_factory):
        try:
            decorator = dialog_factory("Detalhes do evento", width="large", on_dismiss=_clear_selected_audit_event)
        except TypeError:
            decorator = dialog_factory("Detalhes do evento")

        @decorator
        def _audit_detail_dialog() -> None:
            _render_audit_event_dialog_body(snapshot)

        _audit_detail_dialog()
        return

    with st.container(border=True):
        st.subheader("Detalhes do evento")
        _render_audit_event_dialog_body(snapshot)


def _render_audit_table(entries: list) -> None:
    """Renderiza o log de auditoria em formato compacto e nativo."""
    if not entries:
        st.info("Nenhum evento encontrado com os filtros selecionados.")
        if _safe_button("Limpar filtros", key="audit-empty-clear-filters", use_container_width=False):
            for key in (
                "audit-filter-event-type",
                "audit-filter-user-search",
                "audit-filter-status",
                "audit-filter-start-date",
                "audit-filter-end-date",
                "audit-filter-only-failures",
                "audit-filter-only-blocked",
                "audit-result-limit",
                AUDIT_SUMMARY_FILTER_KEY,
            ):
                st.session_state.pop(key, None)
            st.rerun()
        return

    table_height = max(150, min(460, 38 * (len(entries) + 1)))
    table_data = _audit_table_data(entries)
    with st.container(key="audit-logs-dataframe"):
        st.dataframe(
            _style_audit_table_data(table_data),
            use_container_width=True,
            hide_index=True,
            height=table_height,
        )

    detail_cols = st.columns([3, 1])
    with detail_cols[0]:
        selected_index = st.selectbox(
            "Selecionar evento para ver detalhes",
            options=list(range(len(entries))),
            format_func=lambda index: _audit_event_option_label(entries[int(index)], int(index)),
            key="audit-detail-event-selector",
            help="Escolha um evento da lista para abrir os detalhes com seguranca.",
        )
    with detail_cols[1]:
        st.write("")
        if _safe_button("Ver detalhes", key="audit-open-selected-detail", use_container_width=True):
            selected_entry = entries[int(selected_index)]
            st.session_state[AUDIT_SELECTED_EVENT_KEY] = _audit_entry_snapshot(selected_entry)
            st.rerun()

    _render_selected_audit_event_dialog()


def _render_user_management(user: dict, service) -> None:
    """Renderiza a secao de gestao de usuarios (apenas Super Admin)."""
    st.subheader("Gestao de Usuarios")

    try:
        all_users = service.get_all_users()
    except Exception as exc:
        logger.warning(
            "admin_page: falha ao carregar usuarios | causa=%s | tipo=%s",
            _safe_admin_error_summary(exc),
            type(exc).__name__,
        )
        st.error("Nao foi possivel carregar os usuarios agora.")
        return

    if not all_users:
        st.info("Nenhum usuario encontrado.")
        return

    admin_id = int(user["id"])
    admin_email = user.get("email", "")

    for u in all_users:
        if u.id == admin_id:
            with st.expander(f"**{u.nome}** - {u.email} - *{role_display_name(u.role)}* (voce)"):
                st.caption("Este e seu proprio perfil. Nao e possivel alterar seu papel aqui.")
            continue

        with st.expander(f"**{u.nome}** - {u.email} - *{role_display_name(u.role)}*"):
            col1, col2, col3 = st.columns([2, 2, 2])

            with col1:
                new_role = st.selectbox(
                    "Papel",
                    options=ROLE_OPTIONS,
                    index=ROLE_OPTIONS.index(u.role) if u.role in ROLE_OPTIONS else 0,
                    format_func=role_display_name,
                    key=f"role_select_{u.id}",
                )
                if st.button("Salvar papel", key=f"save_role_{u.id}", use_container_width=True):
                    if new_role != u.role:
                        try:
                            service.set_role(u.id, new_role, acting_admin_id=admin_id, acting_admin_email=admin_email)
                            st.success(f"Papel de {u.nome} alterado para {role_display_name(new_role)}.")
                            st.cache_resource.clear()
                            st.rerun()
                        except Exception as exc:
                            logger.warning(
                                "admin_page: falha ao alterar papel | causa=%s | tipo=%s",
                                _safe_admin_error_summary(exc),
                                type(exc).__name__,
                            )
                            st.error("Nao foi possivel salvar a alteracao agora.")
                    else:
                        st.info("Nenhuma alteracao.")

            with col2:
                audit_label = "Tem acesso ao log" if u.can_view_audit else "Sem acesso ao log"
                st.caption(f"Log de auditoria: {audit_label}")
                if u.can_view_audit:
                    if st.button("Revogar acesso ao log", key=f"revoke_audit_{u.id}", use_container_width=True):
                        try:
                            service.set_audit_access(u.id, False, acting_admin_id=admin_id, acting_admin_email=admin_email)
                            st.success(f"Acesso ao log revogado para {u.nome}.")
                            st.rerun()
                        except Exception as exc:
                            logger.warning(
                                "admin_page: falha ao revogar auditoria | causa=%s | tipo=%s",
                                _safe_admin_error_summary(exc),
                                type(exc).__name__,
                            )
                            st.error("Nao foi possivel salvar a alteracao agora.")
                else:
                    if st.button("Conceder acesso ao log", key=f"grant_audit_{u.id}", use_container_width=True):
                        try:
                            service.set_audit_access(u.id, True, acting_admin_id=admin_id, acting_admin_email=admin_email)
                            st.success(f"Acesso ao log concedido para {u.nome}.")
                            st.rerun()
                        except Exception as exc:
                            logger.warning(
                                "admin_page: falha ao conceder auditoria | causa=%s | tipo=%s",
                                _safe_admin_error_summary(exc),
                                type(exc).__name__,
                            )
                            st.error("Nao foi possivel salvar a alteracao agora.")

            with col3:
                st.caption("Zona de perigo")
                confirm_key = f"confirm_delete_{u.id}"
                if not st.session_state.get(confirm_key):
                    if st.button("Excluir conta", key=f"delete_user_{u.id}", use_container_width=True):
                        st.session_state[confirm_key] = True
                        st.rerun()
                else:
                    st.warning(f"Confirmar exclusao de **{u.nome}**?")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Confirmar", key=f"confirm_yes_{u.id}", use_container_width=True):
                            try:
                                service.soft_delete_user(u.id)
                                st.success(f"Conta de {u.nome} excluida.")
                                st.session_state.pop(confirm_key, None)
                                st.rerun()
                            except Exception as exc:
                                logger.warning(
                                    "admin_page: falha ao excluir usuario | causa=%s | tipo=%s",
                                    _safe_admin_error_summary(exc),
                                    type(exc).__name__,
                                )
                                st.error("Nao foi possivel concluir a acao agora.")
                    with c2:
                        if st.button("Cancelar", key=f"confirm_no_{u.id}", use_container_width=True):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()


def render_admin_page() -> None:
    """Renderiza a pagina de administracao restrita."""
    apply_audit_light_styles(st)
    try:
        audit_container = st.container(key="audit-page-shell")
    except TypeError:
        audit_container = st.container()

    with audit_container:
        _render_admin_page_body()


def _render_observability_diagnostics() -> None:
    st.subheader("Diagnosticos de saude e observabilidade")
    try:
        report = HealthService().run_unified_report()
        application = report["application"]
        app_db = report["application_database"]
        analytical_db = report["analytical_database"]
        telemetry = report["opentelemetry"]

        columns = st.columns(4)
        columns[0].metric("Streamlit", application["status"])
        columns[1].metric("Banco da aplicacao", app_db["status"])
        columns[2].metric("Banco analitico", analytical_db["status"])
        columns[3].metric("OpenTelemetry", telemetry["status"])

        st.caption(
            "View analitica: "
            f"{'disponivel' if analytical_db.get('view_available') else 'indisponivel'} | "
            f"Ultima data: {analytical_db.get('maximum_available_data_date') or 'nao informada'} | "
            f"Provider: {telemetry.get('provider_type', 'noop')} | "
            f"Verificado em: {application.get('checked_at', 'nao informado')}"
        )
    except Exception as exc:
        logger.warning(
            "admin_page: diagnostico interno indisponivel | tipo=%s",
            type(exc).__name__,
        )
        st.warning("Diagnosticos internos indisponiveis no momento.")

    if _safe_button(
        "Emitir trace de verificacao",
        key="emit-observability-verification",
        use_container_width=False,
    ):
        attempted = emit_verification_span()
        if attempted:
            st.success("Criacao local do trace foi solicitada.")
        else:
            st.warning("OpenTelemetry nao esta configurado para emitir o trace.")


def _render_admin_page_body() -> None:
    user = get_authenticated_user(st.session_state)

    if not user or not can_view_audit_log(user):
        st.error("Acesso restrito. Esta area e exclusiva para administradores autorizados.")
        st.stop()
        return

    _render_audit_header(user)
    st.divider()

    if is_super_admin(user):
        try:
            svc = _get_user_service()
            _render_user_management(user, svc)
        except Exception as exc:
            logger.warning(
                "admin_page: falha ao carregar gestao de usuarios | causa=%s | tipo=%s",
                _safe_admin_error_summary(exc),
                type(exc).__name__,
            )
            st.error("Nao foi possivel carregar a gestao de usuarios agora.")
        st.divider()

    st.subheader("Eventos recentes")

    try:
        audit_svc = _get_audit_service()
        entries = audit_svc.get_recent_logs(limit=AUDIT_MAX_FETCH_LIMIT)
        _render_audit_summary(entries)

        with st.expander("Filtros", expanded=True):
            st.caption("Use os filtros para localizar eventos por tipo, status, e-mail ou periodo.")
            filters = _render_audit_filters(entries)
        limit = int(filters.pop("limit"))
        filtered_entries = _filter_audit_entries(entries, **filters)
        visible_entries = _limit_audit_entries(filtered_entries, limit)
        st.caption(f"Mostrando {len(visible_entries)} de {len(filtered_entries)} eventos.")
        _render_audit_table(visible_entries)
    except Exception as exc:
        logger.warning(
            "admin_page: falha ao carregar log de auditoria | causa=%s | tipo=%s",
            _safe_admin_error_summary(exc),
            type(exc).__name__,
        )
        st.error("Nao foi possivel carregar os logs agora. Tente novamente mais tarde.")

    st.divider()
    with st.expander("Saude e observabilidade", expanded=False):
        _render_observability_diagnostics()
