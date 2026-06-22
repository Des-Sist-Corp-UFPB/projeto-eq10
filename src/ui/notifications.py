"""Notificacoes leves da interface Streamlit."""

from __future__ import annotations

import html
from collections.abc import MutableMapping
from typing import Any

import streamlit as st

PENDING_TOAST_KEY = "pending_toast"
PENDING_TOAST_KIND_KEY = "pending_toast_kind"

SUCCESS_FEEDBACK_CSS = (
    "<style>"
    ".success-feedback-stack{"
    "position:fixed;top:1rem;right:1.15rem;z-index:2147483000;"
    "width:min(25rem,calc(100vw - 2rem));pointer-events:none;"
    "}"
    ".success-feedback-card{"
    "display:flex;align-items:center;gap:.72rem;"
    "padding:.86rem .95rem;border:1px solid #bbf7d0;"
    "border-radius:1rem;background:#f0fdf4;color:#166534;"
    "box-shadow:0 18px 38px rgba(15,23,42,.14);"
    "font-size:.94rem;font-weight:760;line-height:1.38;"
    "}"
    ".success-feedback-icon{"
    "display:grid;place-items:center;width:1.35rem;height:1.35rem;"
    "flex:0 0 1.35rem;border-radius:999px;background:#22c55e;"
    "color:#fff;font-size:.9rem;font-weight:900;line-height:1;"
    "}"
    ".success-feedback-message{color:#166534;}"
    "@media(max-width:700px){"
    ".success-feedback-stack{top:.75rem;right:.75rem;left:.75rem;width:auto;}"
    "}"
    "</style>"
)


def queue_toast(
    session_state: MutableMapping[str, object],
    message: str,
    kind: str = "success",
) -> None:
    session_state[PENDING_TOAST_KEY] = message
    session_state[PENDING_TOAST_KIND_KEY] = kind if kind in {"success"} else "success"


def build_success_feedback_html(message: Any) -> str:
    safe_message = html.escape(str(message), quote=False)
    return (
        SUCCESS_FEEDBACK_CSS
        + '<div class="success-feedback-stack" aria-live="polite" aria-atomic="true">'
        + '<section class="success-feedback-card" role="status">'
        + '<span class="success-feedback-icon" aria-hidden="true">&#10003;</span>'
        + f'<span class="success-feedback-message">{safe_message}</span>'
        + "</section></div>"
    )


def show_success_feedback(message: Any) -> None:
    html_renderer = getattr(st, "html", None)
    if callable(html_renderer):
        html_renderer(build_success_feedback_html(message))
    else:
        st.success(str(message))


def render_pending_toast() -> None:
    message = st.session_state.pop(PENDING_TOAST_KEY, None)
    kind = st.session_state.pop(PENDING_TOAST_KIND_KEY, "success")
    if not message:
        return

    if kind == "success":
        show_success_feedback(message)
    else:
        st.success(str(message))
