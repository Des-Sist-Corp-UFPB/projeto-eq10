"""Integracao client-side, opcional e privacy-safe com o Umami.

Um componente Streamlit oculto executa somente o bootstrap necessario para
inserir o tracker no ``parent.document.head``. O iframe do componente, por si
so, nao representaria a pagina principal e por isso nao e usado como alvo do
tracker. A integracao pode ser bloqueada por CSP ou por uma futura mudanca de
isolamento entre o componente e a pagina pai; nesses casos o app continua
funcionando normalmente.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

_SCRIPT_SESSION_KEY = "_eq10_umami_script_injected"
_LAST_PAGE_SESSION_KEY = "_eq10_umami_last_page"
_ONCE_SESSION_PREFIX = "_eq10_umami_event_once_"
_TRACKER_ELEMENT_ID = "eq10-umami-tracker"

ALLOWED_PAGES = {
    "/estatisticas": "statistics",
    "/login": "login",
    "/cadastro": "registration",
    "/recuperar-senha": "password-reset",
    "/chat-ia": "chat",
    "/auditoria": "audit",
    "/administracao": "admin",
}

ALLOWED_EVENTS = {
    "login_submitted",
    "login_succeeded",
    "login_failed",
    "registration_submitted",
    "registration_succeeded",
    "password_reset_requested",
    "ai_chat_opened",
    "ai_question_submitted",
    "ai_question_succeeded",
    "ai_question_blocked",
    "ai_question_failed",
    "ai_fallback_used",
    "statistics_viewed",
    "audit_page_viewed",
    "health_diagnostics_viewed",
    "observability_trace_requested",
}

ALLOWED_PROPERTIES = {
    "result": {"success", "blocked", "failure"},
    "execution_mode": {"simple", "llm", "fallback"},
    "page": {"statistics", "chat", "audit", "admin"},
    "category": {"authentication", "analytical_database", "telemetry"},
}


@dataclass(frozen=True)
class UmamiStatus:
    enabled: bool
    script_configured: bool
    website_id_configured: bool
    production_domain_configured: bool
    initialization_attempted: bool
    tracking_mode: str
    masked_website_id: str
    last_local_event_attempt_category: str


_status_lock = threading.Lock()
_status = UmamiStatus(
    enabled=False,
    script_configured=False,
    website_id_configured=False,
    production_domain_configured=False,
    initialization_attempted=False,
    tracking_mode="disabled",
    masked_website_id="",
    last_local_event_attempt_category="none",
)


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_https_url(value: str | None) -> str:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return candidate.rstrip("/")


def _safe_domain(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    if re.fullmatch(r"[a-z0-9.-]+", candidate) and "." in candidate:
        return candidate
    return ""


def _safe_website_id(value: str | None) -> str:
    candidate = str(value or "").strip()
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError, TypeError):
        return ""


def _masked_website_id(value: str) -> str:
    if not value:
        return ""
    parts = value.split("-")
    return f"{parts[0]}-****-****-****-{parts[-1]}"


def _configuration() -> dict[str, Any]:
    script_url = _safe_https_url(os.getenv("UMAMI_SCRIPT_URL"))
    website_id = _safe_website_id(os.getenv("UMAMI_WEBSITE_ID"))
    host_url = _safe_https_url(os.getenv("UMAMI_HOST_URL"))
    domain = _safe_domain(os.getenv("UMAMI_ALLOWED_DOMAIN"))
    requested = _enabled(os.getenv("UMAMI_ENABLED"))
    return {
        "enabled": bool(requested and script_url and website_id),
        "requested": requested,
        "script_url": script_url,
        "website_id": website_id,
        "host_url": host_url,
        "domain": domain,
    }


def _default_renderer(markup: str) -> None:
    import streamlit.components.v1 as components

    components.html(markup, height=0, width=0)


def _session_state(st_module: Any | None) -> Any:
    if st_module is not None:
        return st_module.session_state
    import streamlit as st

    return st.session_state


def _render(markup: str, renderer: Callable[[str], Any] | None) -> None:
    (renderer or _default_renderer)(markup)


def _bootstrap_markup(config: Mapping[str, Any]) -> str:
    values = json.dumps(
        {
            "scriptUrl": config["script_url"],
            "websiteId": config["website_id"],
            "hostUrl": config["host_url"],
            "domain": config["domain"],
            "elementId": _TRACKER_ELEMENT_ID,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return f"""<script>
(() => {{
  try {{
    const p = window.parent;
    const c = {values};
    p.__eq10UmamiQueue = p.__eq10UmamiQueue || [];
    p.__eq10UmamiTrack = p.__eq10UmamiTrack || function() {{
      const args = Array.from(arguments);
      if (p.umami && typeof p.umami.track === "function") p.umami.track.apply(p.umami, args);
      else p.__eq10UmamiQueue.push(args);
    }};
    let tracker = p.document.getElementById(c.elementId);
    if (!tracker) {{
      tracker = p.document.createElement("script");
      tracker.id = c.elementId;
      tracker.defer = true;
      tracker.src = c.scriptUrl;
      tracker.setAttribute("data-website-id", c.websiteId);
      tracker.setAttribute("data-auto-track", "false");
      if (c.domain) tracker.setAttribute("data-domains", c.domain);
      if (c.hostUrl) tracker.setAttribute("data-host-url", c.hostUrl);
      p.document.head.appendChild(tracker);
    }}
    const flush = () => {{
      if (!(p.umami && typeof p.umami.track === "function")) return;
      const pending = p.__eq10UmamiQueue.splice(0);
      pending.forEach(args => p.umami.track.apply(p.umami, args));
    }};
    tracker.addEventListener("load", flush, {{ once: true }});
    flush();
  }} catch (_) {{}}
}})();
</script>"""


def _tracking_markup(*arguments: Any) -> str:
    args = json.dumps(arguments, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    return f"""<script>
(() => {{
  try {{
    const p = window.parent;
    if (typeof p.__eq10UmamiTrack === "function") p.__eq10UmamiTrack.apply(p, {args});
  }} catch (_) {{}}
}})();
</script>"""


def configure_umami(
    *,
    st_module: Any | None = None,
    renderer: Callable[[str], Any] | None = None,
) -> UmamiStatus:
    """Configura o tracker uma vez por sessao de navegador."""
    global _status
    config = _configuration()
    state = _session_state(st_module)
    attempted = True
    mode = "parent_script_injection" if config["enabled"] else "disabled"
    configured_status = UmamiStatus(
        enabled=config["enabled"],
        script_configured=bool(config["script_url"]),
        website_id_configured=bool(config["website_id"]),
        production_domain_configured=bool(config["domain"]),
        initialization_attempted=attempted,
        tracking_mode=mode,
        masked_website_id=_masked_website_id(config["website_id"]),
        last_local_event_attempt_category=_status.last_local_event_attempt_category,
    )
    with _status_lock:
        _status = configured_status

    if not config["enabled"] or state.get(_SCRIPT_SESSION_KEY):
        return configured_status
    try:
        _render(_bootstrap_markup(config), renderer)
        state[_SCRIPT_SESSION_KEY] = True
    except Exception:
        pass
    return configured_status


def _record_attempt(category: str) -> None:
    global _status
    with _status_lock:
        _status = replace(_status, last_local_event_attempt_category=category)


def _safe_event_data(event_data: Mapping[str, str] | None) -> dict[str, str] | None:
    if event_data is None:
        return {}
    if not isinstance(event_data, Mapping):
        return None
    safe: dict[str, str] = {}
    for key, value in event_data.items():
        if key not in ALLOWED_PROPERTIES or not isinstance(value, str):
            return None
        if value not in ALLOWED_PROPERTIES[key]:
            return None
        safe[key] = value
    return safe


def track_event(
    event_name: str,
    event_data: Mapping[str, str] | None = None,
    *,
    st_module: Any | None = None,
    renderer: Callable[[str], Any] | None = None,
) -> bool:
    """Solicita um evento somente se nome e propriedades forem permitidos."""
    if event_name not in ALLOWED_EVENTS:
        return False
    safe_data = _safe_event_data(event_data)
    if safe_data is None:
        return False
    if not configure_umami(st_module=st_module, renderer=renderer).enabled:
        return False
    try:
        _render(_tracking_markup(event_name, safe_data), renderer)
        _record_attempt("custom_event")
        return True
    except Exception:
        return False


def track_event_once(
    event_name: str,
    event_data: Mapping[str, str] | None = None,
    *,
    st_module: Any | None = None,
    renderer: Callable[[str], Any] | None = None,
) -> bool:
    """Deduplica um evento declarativo durante a sessao Streamlit."""
    state = _session_state(st_module)
    key = f"{_ONCE_SESSION_PREFIX}{event_name}"
    if state.get(key):
        return False
    emitted = track_event(event_name, event_data, st_module=st_module, renderer=renderer)
    if emitted:
        state[key] = True
    return emitted


def track_page_view(
    page_name: str,
    *,
    st_module: Any | None = None,
    renderer: Callable[[str], Any] | None = None,
) -> bool:
    """Registra uma pagina logica somente quando ela muda na sessao."""
    if page_name not in ALLOWED_PAGES:
        return False
    state = _session_state(st_module)
    if state.get(_LAST_PAGE_SESSION_KEY) == page_name:
        return False
    if not configure_umami(st_module=st_module, renderer=renderer).enabled:
        return False
    try:
        _render(
            _tracking_markup({"url": page_name, "title": ALLOWED_PAGES[page_name]}),
            renderer,
        )
        state[_LAST_PAGE_SESSION_KEY] = page_name
        _record_attempt("page_view")
        return True
    except Exception:
        return False


def get_umami_status() -> dict[str, Any]:
    """Retorna somente diagnostico local seguro; nao confirma ingestao remota."""
    config = _configuration()
    with _status_lock:
        current = _status
    if not current.initialization_attempted and config["requested"]:
        current = replace(
            current,
            enabled=config["enabled"],
            script_configured=bool(config["script_url"]),
            website_id_configured=bool(config["website_id"]),
            production_domain_configured=bool(config["domain"]),
            masked_website_id=_masked_website_id(config["website_id"]),
        )
    return asdict(current)
