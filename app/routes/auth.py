"""/auth/* — login, logout, register, profile. Google OAuth, password reset, email
verification, email-change confirmation and account reactivation are not wired up
yet (see docs/claude-migration.md status table).
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.session import get_authenticated_user, login_session, logout_session
from app.middleware.guards import require_authenticated
from app.service import auth_service
from app.service.auth_service import AuthValidationError

router = APIRouter(prefix="/auth")


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/login", response_class=HTMLResponse)
def get_login(request: Request, next: str = "/estatisticas") -> HTMLResponse:
    if get_authenticated_user(request):
        return RedirectResponse(url=next or "/estatisticas", status_code=303)

    return _templates(request).TemplateResponse(
        request, "login.html", {"active_page": None, "next": next, "error": None, "email": ""}
    )


@router.post("/login", response_class=HTMLResponse)
def post_login(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    next: str = Form("/estatisticas"),
) -> HTMLResponse:
    try:
        user = auth_service.authenticate(email, senha)
    except AuthValidationError as exc:
        return _templates(request).TemplateResponse(
            request,
            "login.html",
            {"active_page": None, "next": next, "error": exc.public_message, "email": email},
            status_code=400,
        )

    login_session(request, user)
    return RedirectResponse(url=next or "/estatisticas", status_code=303)


@router.post("/logout")
def post_logout(request: Request) -> RedirectResponse:
    user = get_authenticated_user(request)
    auth_service.logout(user)
    logout_session(request)
    return RedirectResponse(url="/estatisticas", status_code=303)


@router.get("/register", response_class=HTMLResponse)
def get_register(request: Request) -> HTMLResponse:
    if get_authenticated_user(request):
        return RedirectResponse(url="/estatisticas", status_code=303)

    return _templates(request).TemplateResponse(
        request,
        "register.html",
        {"active_page": None, "error": None, "nome": "", "email": ""},
    )


@router.post("/register", response_class=HTMLResponse)
def post_register(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
) -> HTMLResponse:
    try:
        user = auth_service.register(nome, email, senha, confirmar_senha)
    except AuthValidationError as exc:
        return _templates(request).TemplateResponse(
            request,
            "register.html",
            {"active_page": None, "error": exc.public_message, "nome": nome, "email": email},
            status_code=400,
        )

    login_session(request, user)
    return RedirectResponse(url="/estatisticas", status_code=303)


@router.get("/profile", response_class=HTMLResponse)
def get_profile(request: Request) -> HTMLResponse:
    guard = require_authenticated(request)
    if isinstance(guard, RedirectResponse):
        return guard

    return _templates(request).TemplateResponse(
        request,
        "profile.html",
        {"active_page": None, "profile_user": guard, "error": None, "success": None},
    )


@router.post("/profile/name", response_class=HTMLResponse)
def post_profile_name(request: Request, nome: str = Form(...)) -> HTMLResponse:
    guard = require_authenticated(request)
    if isinstance(guard, RedirectResponse):
        return guard
    user = guard

    try:
        updated = auth_service.update_profile_name(user["id"], nome)
    except AuthValidationError as exc:
        return _templates(request).TemplateResponse(
            request,
            "profile.html",
            {"active_page": None, "profile_user": user, "error": exc.public_message, "success": None},
            status_code=400,
        )

    login_session(request, updated)
    return RedirectResponse(url="/auth/profile", status_code=303)


@router.post("/profile/email", response_class=HTMLResponse)
def post_profile_email(request: Request, email: str = Form(...)) -> HTMLResponse:
    guard = require_authenticated(request)
    if isinstance(guard, RedirectResponse):
        return guard
    user = guard

    try:
        updated = auth_service.update_profile_email(user["id"], email)
    except AuthValidationError as exc:
        return _templates(request).TemplateResponse(
            request,
            "profile.html",
            {"active_page": None, "profile_user": user, "error": exc.public_message, "success": None},
            status_code=400,
        )

    login_session(request, updated)
    return RedirectResponse(url="/auth/profile", status_code=303)


@router.post("/profile/password", response_class=HTMLResponse)
def post_profile_password(
    request: Request,
    senha_atual: str = Form(...),
    nova_senha: str = Form(...),
    confirmar_senha: str = Form(...),
) -> HTMLResponse:
    guard = require_authenticated(request)
    if isinstance(guard, RedirectResponse):
        return guard
    user = guard

    try:
        auth_service.change_password(user["id"], senha_atual, nova_senha, confirmar_senha)
    except AuthValidationError as exc:
        return _templates(request).TemplateResponse(
            request,
            "profile.html",
            {"active_page": None, "profile_user": user, "error": exc.public_message, "success": None},
            status_code=400,
        )

    return _templates(request).TemplateResponse(
        request,
        "profile.html",
        {"active_page": None, "profile_user": user, "error": None, "success": "Senha atualizada com sucesso."},
    )


@router.post("/profile/deactivate")
def post_profile_deactivate(request: Request) -> RedirectResponse:
    guard = require_authenticated(request)
    if isinstance(guard, RedirectResponse):
        return guard
    user = guard

    auth_service.deactivate_account(user)
    logout_session(request)
    return RedirectResponse(url="/estatisticas", status_code=303)


@router.get("/forgot-password", response_class=HTMLResponse)
def get_forgot_password(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(
        request, "forgot_password.html", {"active_page": None, "message": None}
    )


@router.post("/forgot-password", response_class=HTMLResponse)
def post_forgot_password(request: Request, email: str = Form(...)) -> HTMLResponse:
    result = auth_service.request_password_reset(email)
    return _templates(request).TemplateResponse(
        request, "forgot_password.html", {"active_page": None, "message": result.message}
    )


@router.get("/reset-password", response_class=HTMLResponse)
def get_reset_password(request: Request, reset_password_token: str = "") -> HTMLResponse:
    validation = auth_service.validate_reset_token(reset_password_token)
    return _templates(request).TemplateResponse(
        request,
        "reset_password.html",
        {
            "active_page": None,
            "token": reset_password_token,
            "token_valid": validation.success,
            "error": None if validation.success else validation.message,
            "success": None,
        },
    )


@router.post("/reset-password", response_class=HTMLResponse)
def post_reset_password(
    request: Request,
    reset_password_token: str = Form(...),
    nova_senha: str = Form(...),
    confirmar_senha: str = Form(...),
) -> HTMLResponse:
    try:
        result = auth_service.reset_password_with_token(reset_password_token, nova_senha, confirmar_senha)
    except auth_service.AuthValidationError as exc:
        return _templates(request).TemplateResponse(
            request,
            "reset_password.html",
            {"active_page": None, "token": reset_password_token, "token_valid": True, "error": exc.public_message, "success": None},
            status_code=400,
        )

    if not result.success:
        return _templates(request).TemplateResponse(
            request,
            "reset_password.html",
            {"active_page": None, "token": reset_password_token, "token_valid": False, "error": result.message, "success": None},
            status_code=400,
        )

    return _templates(request).TemplateResponse(
        request,
        "reset_password.html",
        {"active_page": None, "token": reset_password_token, "token_valid": False, "error": None, "success": result.message},
    )
