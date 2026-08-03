"""/chat — Chat IA. GET renders the page (with persisted message history), POST /chat/ask
answers a question via the isolated AI layer (src/ai/datasus_ai.py) and returns JSON for
chat.js to append to the DOM.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.session import get_authenticated_user
from app.database import auth_db
from app.database.connection import get_auth_connection
from app.middleware.guards import require_authenticated
from app.service import chat_service

router = APIRouter()

SUGGESTION_PROMPTS = (
    "Valor aprovado por município de atendimento",
    "Frequência total por sexo",
    "Procedimentos com maior valor aprovado",
    "Média de idade dos atendimentos",
    "Unidades com maior quantidade apresentada",
    "Valor aprovado por raça/cor",
)


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _email_verified(user: dict[str, Any]) -> bool:
    conn = get_auth_connection()
    try:
        row = auth_db.get_user_by_id(conn, user["id"])
    finally:
        conn.close()
    return bool(row and row["email_verificado"])


@router.get("/chat", response_class=HTMLResponse)
def get_chat(request: Request) -> HTMLResponse:
    guard = require_authenticated(request)
    if isinstance(guard, RedirectResponse):
        return guard
    user = guard

    settings = request.app.state.settings
    if settings.email_verification_required and not _email_verified(user):
        return _templates(request).TemplateResponse(
            request, "chat.html", {"active_page": "Chat IA", "email_verification_gate": True}
        )

    conn = get_auth_connection()
    try:
        history = chat_service.load_message_history(conn, user["id"])
    finally:
        conn.close()

    messages = [
        {
            "role": "user" if m["role"] == "user" else "assistant",
            "html": chat_service.render_user_content(m["conteudo"])
            if m["role"] == "user"
            else chat_service.render_assistant_content(m["conteudo"]),
        }
        for m in history
    ]

    return _templates(request).TemplateResponse(
        request,
        "chat.html",
        {
            "active_page": "Chat IA",
            "email_verification_gate": False,
            "suggestions": SUGGESTION_PROMPTS,
            "messages": messages,
        },
    )


@router.post("/chat/ask")
def post_chat_ask(request: Request, prompt: str = Form(...)) -> JSONResponse:
    user = get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "auth_required"}, status_code=401)

    settings = request.app.state.settings
    if settings.email_verification_required and not _email_verified(user):
        return JSONResponse({"error": "email_verification_required"}, status_code=403)

    clean_prompt = chat_service.sanitize_text(prompt)
    if not clean_prompt:
        return JSONResponse({"error": "empty_prompt"}, status_code=400)

    conn = get_auth_connection()
    try:
        session_id = chat_service.get_or_create_active_session(conn, user["id"], title=clean_prompt)
        chat_service.save_message(conn, session_id, user["id"], "user", clean_prompt, "ok")
    finally:
        conn.close()

    resposta, status = chat_service.process_question(clean_prompt, user)

    conn = get_auth_connection()
    try:
        chat_service.save_message(conn, session_id, user["id"], "assistant", resposta, status)
    finally:
        conn.close()

    return JSONResponse(
        {
            "user_html": chat_service.render_user_content(clean_prompt),
            "assistant_html": chat_service.render_assistant_content(resposta),
            "status": status,
        }
    )
