"""GET /auditoria — audit log page. can_view_audit_log guard. Filters applied server-side
after fetching (fetch cap 500), matching src/ui/admin_page.py.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.roles import is_super_admin
from app.middleware.guards import require_audit_access
from app.service import audit_service

router = APIRouter()


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.get("/auditoria", response_class=HTMLResponse)
def get_auditoria(
    request: Request,
    limit: int = audit_service.DEFAULT_AUDIT_LIMIT,
    event_type: str = "Todos",
    status: str = "Todos",
    user_search: str = "",
    start_date: str = "",
    end_date: str = "",
) -> HTMLResponse:
    guard = require_audit_access(request)
    if isinstance(guard, RedirectResponse):
        return guard
    user = guard

    templates: Jinja2Templates = request.app.state.templates

    entries = audit_service.get_recent_logs(audit_service.AUDIT_MAX_FETCH_LIMIT)
    summary = audit_service.build_summary(entries)

    safe_limit = limit if limit in audit_service.AUDIT_LIMIT_OPTIONS else audit_service.DEFAULT_AUDIT_LIMIT
    parsed_start = _parse_date(start_date)
    parsed_end = _parse_date(end_date)

    filtered = audit_service.filter_entries(
        entries,
        event_type=event_type,
        user_search=user_search,
        status=status,
        start_date=parsed_start,
        end_date=parsed_end,
    )
    visible = filtered[:safe_limit]
    rows = [audit_service.format_entry_for_display(entry) for entry in visible]

    return templates.TemplateResponse(
        request,
        "auditoria.html",
        {
            "active_page": "Auditoria",
            "summary": summary,
            "rows": rows,
            "total_filtered": len(filtered),
            "visible_count": len(visible),
            "filters": {
                "limit": safe_limit,
                "event_type": event_type,
                "status": status,
                "user_search": user_search,
                "start_date": start_date,
                "end_date": end_date,
            },
            "limit_options": audit_service.AUDIT_LIMIT_OPTIONS,
            "event_options": audit_service.EVENT_CATEGORY_OPTIONS,
            "status_options": audit_service.STATUS_FILTER_OPTIONS,
            "status_labels": audit_service.STATUS_FILTER_LABELS,
            "show_user_management_link": is_super_admin(user),
        },
    )
