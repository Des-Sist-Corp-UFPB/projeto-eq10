"""/admin/users — super_admin-only user management. Reachable only via the link on
/auditoria, not from the sidebar, matching the legacy admin page's discoverability.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.roles import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER, role_display_name
from app.middleware.guards import require_super_admin
from app.service import user_management_service
from app.service.auth_service import AuthValidationError

router = APIRouter(prefix="/admin")

ROLE_OPTIONS = [ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN]


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/users", response_class=HTMLResponse)
def get_users(request: Request, error: str | None = None, success: str | None = None) -> HTMLResponse:
    guard = require_super_admin(request)
    if isinstance(guard, RedirectResponse):
        return guard
    admin_user = guard

    users = user_management_service.get_all_users()

    return _templates(request).TemplateResponse(
        request,
        "users.html",
        {
            "active_page": None,
            "admin_user": admin_user,
            "users": users,
            "role_options": ROLE_OPTIONS,
            "role_display_name": role_display_name,
            "error": error,
            "success": success,
        },
    )


@router.post("/users/{user_id}/role")
def post_user_role(request: Request, user_id: int, new_role: str = Form(...)) -> RedirectResponse:
    guard = require_super_admin(request)
    if isinstance(guard, RedirectResponse):
        return guard
    admin_user = guard

    try:
        user_management_service.set_role(user_id, new_role, admin_user["id"], admin_user["email"])
    except AuthValidationError as exc:
        return RedirectResponse(url=f"/admin/users?error={quote(exc.public_message)}", status_code=303)

    return RedirectResponse(url="/admin/users?success=Papel+atualizado.", status_code=303)


@router.post("/users/{user_id}/audit-access")
def post_user_audit_access(request: Request, user_id: int, grant: str = Form(...)) -> RedirectResponse:
    guard = require_super_admin(request)
    if isinstance(guard, RedirectResponse):
        return guard
    admin_user = guard

    user_management_service.set_audit_access(user_id, grant == "1", admin_user["id"], admin_user["email"])
    return RedirectResponse(url="/admin/users?success=Acesso+ao+log+atualizado.", status_code=303)


@router.post("/users/{user_id}/deactivate")
def post_user_deactivate(request: Request, user_id: int) -> RedirectResponse:
    guard = require_super_admin(request)
    if isinstance(guard, RedirectResponse):
        return guard

    user_management_service.soft_delete_user(user_id)
    return RedirectResponse(url="/admin/users?success=Conta+desativada.", status_code=303)
