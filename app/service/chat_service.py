"""Chat IA business logic — ported from app_ai_chat.py (prompt processing, response
formatting/sanitization) and src/chat/chat_history_service.py (persistence, redaction).
The AI layer itself (src/ai/datasus_ai.py:perguntar_datasus) is NOT ported — it stays in
src/ai/ and is called as-is, per docs/claude-migration.md.
"""

from __future__ import annotations

import ast
import html
import json
import logging
import re
from typing import Any

import pandas as pd

from app.database import chat_db
from app.service import audit_service

logger = logging.getLogger(__name__)

DEFAULT_CHAT_TITLE = "Conversa do Chat IA"
ALLOWED_ROLES = {"user", "assistant", "system"}
ALLOWED_STATUSES = {"ok", "blocked", "error", "fallback"}

GENERIC_ERROR_MESSAGE = (
    "O motor estatístico não conseguiu concluir esta consulta agora. "
    "A pergunta foi aceita pela validação; tente novamente em alguns instantes."
)
DATA_ACCESS_ERROR_MESSAGE = "Não consegui acessar os dados no momento. Tente novamente em alguns instantes."
UNEXPECTED_FORMAT_ERROR_MESSAGE = (
    "A camada de IA respondeu com um formato inesperado. Tente uma pergunta mais específica."
)

_UNSAFE_RESPONSE_PATTERNS = (
    "traceback",
    "postgresql://",
    "postgresql+" + "psyco" + "pg2://",
    "sqlite://",
    "sql" + "alchemy",
    "psyco" + "pg2",
    "operationalerror",
    "programmingerror",
    "integrityerror",
    "connection string",
    "api key",
    "apikey",
    "token",
    "client_secret",
    "api_secret",
    "secret_key",
    ".env",
)

_SPECIAL_CHAR_TRANSLATION = str.maketrans(
    {
        " ": " ", "​": "", "‐": "-", "‑": "-", "‒": "-",
        "–": "-", "—": "-", "―": "-", "‘": "'", "’": "'",
        "“": '"', "”": '"', "•": "-", "…": "...", " ": " ",
        "−": "-", "﻿": "",
    }
)
_NUMBER_RE = re.compile(r"^\s*(?:R\$\s*)?-?\d{1,3}(?:\.\d{3})*(?:,\d+)?\s*$|^\s*-?\d+(?:[.,]\d+)?\s*$")
_PAIR_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*(.+?):\s*(.+?)\s*$")
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$")

_TOKEN_QUERY_RE = re.compile(r"\b(reset_password_token|verify_email_token)=([^\s&]+)", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(password|senha|api[_-]?key|token|secret|smtp[_-]?password)\s*[:=]\s*([^\s]+)",
    re.IGNORECASE,
)
_LONG_HEX_RE = re.compile(r"\b[a-f0-9]{48,}\b", re.IGNORECASE)


def redact_sensitive_content(content: str) -> str:
    clean_content = str(content or "")
    clean_content = _TOKEN_QUERY_RE.sub(r"\1=[REDACTED]", clean_content)
    clean_content = _SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", clean_content)
    clean_content = _LONG_HEX_RE.sub("[REDACTED_HASH]", clean_content)
    return clean_content


def _clean_title(title: str | None) -> str:
    clean_title = " ".join(str(title or "").split())
    return clean_title[:90] if clean_title else DEFAULT_CHAT_TITLE


# ── Persistence orchestration — ported from src/chat/chat_history_service.py ─────


def get_or_create_active_session(conn: Any, user_id: int, title: str | None = None) -> int:
    session = chat_db.get_active_chat_session(conn, user_id)
    if session:
        return session["id"]
    return chat_db.create_chat_session(conn, user_id, _clean_title(title))


def save_message(conn: Any, session_id: int, user_id: int, role: str, content: str, status: str = "ok") -> None:
    clean_role = (role or "").strip().lower()
    if clean_role not in ALLOWED_ROLES:
        raise ValueError("role invalido")
    clean_status = (status or "ok").strip().lower()
    if clean_status not in ALLOWED_STATUSES:
        clean_status = "ok"

    chat_db.add_chat_message(conn, session_id, user_id, clean_role, redact_sensitive_content(content), clean_status)


def load_message_history(conn: Any, user_id: int) -> list[dict[str, Any]]:
    session = chat_db.get_active_chat_session(conn, user_id)
    if not session:
        return []
    return chat_db.get_chat_messages(conn, session["id"], user_id)


# ── Prompt processing — ported from app_ai_chat.py:_process_pending_prompt ───────


def process_question(prompt: str, user_context: dict[str, Any] | None) -> tuple[str, str]:
    """Calls the isolated AI layer and returns (response_text, status)."""
    from src.ai.datasus_ai import perguntar_datasus

    try:
        resposta = perguntar_datasus(prompt, user_context=user_context)
        return resposta, "ok"
    except Exception as exc:
        logger.warning(
            "Erro seguro chat_service | operacao=processar_prompt | tipo=%s | fallback=mensagem_amigavel",
            type(exc).__name__,
        )
        audit_service.log_event_safely(
            audit_service.EVENT_CHAT_PROCESSING_ERROR,
            user_id=int(user_context["id"]) if user_context and user_context.get("id") else None,
            user_email=user_context.get("email") if user_context else None,
            prompt_text=prompt,
            detalhe=f"tipo={type(exc).__name__}",
            status="failure",
            source="chat_ia",
            action="process_prompt",
        )
        return GENERIC_ERROR_MESSAGE, "error"


# ── Response sanitization/formatting — ported from app_ai_chat.py ────────────────


def _escape_text(value: Any) -> str:
    return html.escape(str(value), quote=False)


def sanitize_text(value: Any) -> str:
    text = str(value if value is not None else "").translate(_SPECIAL_CHAR_TRANSLATION)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def friendly_response(value: Any) -> str:
    """Blocks tracebacks/connection strings/tokens and maps known AI error sentinels."""
    text = sanitize_text(value)
    normalized = text.casefold()

    if not text:
        return UNEXPECTED_FORMAT_ERROR_MESSAGE

    if any(pattern in normalized for pattern in _UNSAFE_RESPONSE_PATTERNS):
        logger.warning("Resposta tecnica da IA substituida por mensagem amigavel.")
        return GENERIC_ERROR_MESSAGE

    if "não foi possível processar a pergunta" in normalized:
        return GENERIC_ERROR_MESSAGE

    if "configuração incompleta da camada de ia" in normalized:
        return DATA_ACCESS_ERROR_MESSAGE

    if "formato esperado" in normalized or "não retornou o resultado" in normalized:
        return UNEXPECTED_FORMAT_ERROR_MESSAGE

    if (
        "dependências da ia" in normalized
        or "erro ao executar" in normalized
        or "configuração inválida da ia" in normalized
        or "provedor de ia" in normalized
    ):
        return GENERIC_ERROR_MESSAGE

    return text


def _is_number_like(value: str) -> bool:
    return bool(_NUMBER_RE.match(value.strip()))


def _try_parse_structured(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None

    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(stripped)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
    return None


def _structured_to_frame(value: Any) -> pd.DataFrame | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]

    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return pd.DataFrame(value)

    if isinstance(value, dict) and all(not isinstance(item, (dict, list, tuple, set)) for item in value.values()):
        return pd.DataFrame([value])

    return None


def _structured_to_list(value: Any) -> list[str] | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]

    if isinstance(value, list) and all(not isinstance(item, (dict, list, tuple, set)) for item in value):
        return [sanitize_text(item) for item in value]

    return None


def _dataframe_to_html(df: pd.DataFrame) -> str:
    display_df = df.head(50).copy()
    table_html = display_df.to_html(index=False, border=0, classes="assistant-table", escape=True)
    note = ""
    if len(df) > len(display_df):
        note = f'<p class="assistant-muted">Mostrando 50 de {len(df)} linhas.</p>'
    return f'<div class="assistant-table-wrap">{table_html}</div>{note}'


def _markdown_table_to_frame(value: str) -> pd.DataFrame | None:
    lines = [line.strip() for line in value.splitlines() if "|" in line]
    if len(lines) < 2 or not any(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", line) for line in lines):
        return None

    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)

    if len(rows) < 2:
        return None

    header = rows[0]
    body = [row for row in rows[1:] if len(row) == len(header)]
    if not body:
        return None

    return pd.DataFrame(body, columns=header)


def _pair_lines_to_frame(value: str) -> tuple[list[str], pd.DataFrame | None]:
    intro_lines: list[str] = []
    rows: list[dict[str, str]] = []

    for line in value.splitlines():
        clean_line = line.strip()
        if not clean_line:
            continue

        match = _PAIR_LINE_RE.match(clean_line)
        if match:
            rows.append({"Categoria": match.group(1).strip(), "Resultado": match.group(2).strip()})
        else:
            intro_lines.append(clean_line)

    if len(rows) < 2:
        return intro_lines, None
    return intro_lines, pd.DataFrame(rows)


def _plain_list_to_html(value: str) -> str | None:
    items = []
    ordered = False
    for line in value.splitlines():
        clean_line = line.strip()
        match = _LIST_LINE_RE.match(clean_line)
        if not match:
            continue
        if re.match(r"^\d+[.)]", clean_line):
            ordered = True
        items.append(match.group(1).strip())

    if len(items) < 2:
        return None

    tag = "ol" if ordered else "ul"
    rendered_items = "".join(f"<li>{_escape_text(item)}</li>" for item in items)
    return f'<{tag} class="assistant-list">{rendered_items}</{tag}>'


def _paragraphs_to_html(value: str) -> str:
    blocks = []
    for block in re.split(r"\n\s*\n", value):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        blocks.append(f"<p>{_escape_text(' '.join(lines))}</p>")
    return "".join(blocks) or f"<p>{_escape_text(value)}</p>"


def render_assistant_content(content: str) -> str:
    """Number-like -> result card; list -> <ul>; table (dict/markdown) -> <table>; text -> <p>."""
    text = friendly_response(content)

    if _is_number_like(text):
        return f'<div class="assistant-result"><span>Resultado</span>{_escape_text(text)}</div>'

    parsed = _try_parse_structured(text)
    if parsed is not None:
        parsed_frame = _structured_to_frame(parsed)
        if parsed_frame is not None:
            return _dataframe_to_html(parsed_frame)

        parsed_list = _structured_to_list(parsed)
        if parsed_list is not None and parsed_list:
            items = "".join(f"<li>{_escape_text(item)}</li>" for item in parsed_list)
            return f'<ul class="assistant-list">{items}</ul>'

    markdown_frame = _markdown_table_to_frame(text)
    if markdown_frame is not None:
        return _dataframe_to_html(markdown_frame)

    intro_lines, pair_frame = _pair_lines_to_frame(text)
    if pair_frame is not None:
        intro_html = _paragraphs_to_html("\n".join(intro_lines)) if intro_lines else ""
        return f"{intro_html}{_dataframe_to_html(pair_frame)}"

    list_html = _plain_list_to_html(text)
    if list_html is not None:
        return list_html

    return _paragraphs_to_html(text)


def render_user_content(content: str) -> str:
    return f"<p>{_escape_text(sanitize_text(content))}</p>"
