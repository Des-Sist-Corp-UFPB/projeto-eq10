# claude-migration.md — branch-migration reference

Companion to `docs/claude.md` (legacy Streamlit system map). This file documents the **new**
FastAPI app being built on `branch-migration` under `app/`. The legacy `app_ai_chat.py` +
`src/` tree stays in place, untouched, as the reference implementation until the migration is
complete and cut over. The ETL pipeline (`main.py`, `Dockerfile`, `src/extract.py`,
`src/transform.py`, `src/load.py`) is out of scope for this migration entirely.

## Status

| Task | Area | Status |
|---|---|---|
| A | Architecture bootstrap (`main.py`, `sidebar.html`, `base.css`, `base.js`) | Done |
| B | Statistics page `/estatisticas` | Done |
| C | Authentication `/auth/*` | Not started |
| D | Chat IA `/chat` | Not started |
| E | Audit/Admin `/auditoria` | Not started |
| F | User Management `/admin/users` | Not started |
| G | Healthcheck `/healthcheck` | Not started |

## Stack

Python 3.12 target (dev venv currently pinned to 3.11 via `.python-version` / `pyproject.toml`
`requires-python`, shared with the ETL pipeline — not changed by this migration). FastAPI +
Jinja2 + vanilla CSS/JS + raw `psycopg2` (no SQLAlchemy, no ORM). New deps added via `uv add`:
`fastapi`, `uvicorn[standard]`, `jinja2`, `itsdangerous` (required by
`starlette.middleware.sessions.SessionMiddleware`), `python-multipart` (required for HTML form
parsing in POST routes).

## Directory map (`app/`)

```
app/
  main.py              App factory create_app(): SessionMiddleware, StaticFiles mount,
                        Jinja2Templates, router includes, safe startup log.
  config/settings.py    get_settings() reads env (no new vars except SESSION_SECRET_KEY,
                        which falls back to an insecure dev default with a warning-worthy
                        default if unset — set it explicitly in every real environment).
                        get_configured_logo_url() ported 1:1 from src/ui/styles.py.
  auth/
    session.py          login_session/logout_session/get_authenticated_user/can_access_chat,
                        ported from src/auth/session.py but operate on Starlette
                        `request.session` (a plain dict) instead of st.session_state.
                        Session payload is flat, not nested under one "auth_user" key:
                        request.session = {user_id, email, role, nome, can_view_audit}.
    roles.py             ROLE_USER/ROLE_ADMIN/ROLE_SUPER_ADMIN, is_super_admin, is_admin,
                        can_view_audit_log, role_display_name — ported 1:1 from
                        src/auth/roles.py.
  middleware/guards.py   require_authenticated / require_audit_access / require_super_admin.
                        Each returns either the user dict or a RedirectResponse. Routes call
                        the guard first and return the RedirectResponse as-is when auth fails:

                            guard = require_authenticated(request)
                            if isinstance(guard, RedirectResponse):
                                return guard
                            user = guard  # dict from here on

                        This keeps redirect targets (e.g. back to /auth/login?next=...)
                        decided in one place without a generic 401 JSON handler getting in
                        the way of a browser-facing app.
  database/             One psycopg2 module per domain. Raw SQL only. Not started yet
                        (auth_db.py / chat_db.py / audit_db.py / users_db.py land with
                        Tasks C–F).
  service/              Business logic per domain. Not started yet.
  routes/
    estatisticas.py      GET /estatisticas — public, no DB, renders estatisticas.html.
  templates/
    sidebar.html          Base layout. No components/ folder, no base.html — this IS the
                        base. Every page template extends it and fills {% block title %} /
                        {% block content %} (+ optional extra_css / extra_js blocks).
                        Exposes template globals set in main.py:
                          get_authenticated_user(request), can_view_audit_log(user),
                          is_super_admin(user), logo_url, email_verification_required.
    estatisticas.html     Hero card + Power BI link card, copy ported verbatim from
                        src/ui/statistics_page.py.
  static/
    css/base.css          Global design tokens + sidebar + top header + profile popover +
                        buttons + forms + chat bubbles + responsive breakpoints. Ported from
                        app_ai_chat.py:_apply_style() and src/ui/styles.py. Streamlit-specific
                        selectors ([data-testid=...], .st-key-*) were translated to plain
                        HTML/CSS classes; the palette, spacing and component shapes are kept
                        exact.
    css/estatisticas.css  Page-specific: .app-hero, .public-dashboard-card, .powerbi-link.
    js/base.js            Two vanilla handlers: mobile sidebar toggle (off-canvas below
                        560px, matches the sidebar-toggle/backdrop markup in sidebar.html)
                        and the profile popover (click-to-open, outside-click/Escape to
                        close). Neither exists in the legacy Streamlit app since Streamlit
                        owns its own widget chrome — these are the vanilla-JS equivalents of
                        the `st.popover` and CSS-only mobile breakpoint the legacy app relied
                        on.
```

## Deviations from the legacy implementation (intentional, spec-mandated)

- **Session shape is flat**, not a nested `auth_user` dict — see `app/auth/session.py`
  docstring. Matches Section 2 of the migration prompt exactly:
  `user_id, email, role, nome, can_view_audit`.
- **Navigation is real `<a href>` routing**, not `st.session_state.current_page` +
  `st.rerun()`. `PAGE_SLUGS` / `?page=` query-param handling from `src/ui/sidebar.py` has no
  equivalent here — the URL path *is* the page.
- **Auth guards return-or-redirect** instead of raising. Chosen so every protected route stays
  a plain function that either proceeds with a `user` dict or bounces the request, with no
  custom exception-handler indirection to trace through.
- Sidebar shows/hides the "Auditoria" link based on `can_view_audit_log()` exactly like
  `src/ui/sidebar.py:_sidebar_nav_markup()`; user management (`/admin/users`, Task F) is
  **not** a sidebar item, same as legacy — it is reachable only from within the Auditoria page
  for `super_admin` users, mirroring `src/ui/admin_page.py:_render_user_management()`.

## Conventions carried forward unchanged from `docs/claude.md`

- Two-database routing (`AUTH_DB_*` vs `AI_DB_*`) — not touched yet; lands with Task C
  (`app/database/auth_db.py`) and Task D (AI layer stays in `src/ai/`, called from
  `app/service/chat_service.py`, not ported/rewritten).
- Audit event vocabulary, status vocabulary (`success|failure|blocked|info`), and the
  sanitization rules in Section 3.11 of the migration prompt are ported as-is when Task E
  lands — do not invent new event types or statuses.
- `soft_delete_user()` never runs `DELETE` SQL — flips `ativo=False` only (Task F).

## Testing this app during migration

```bash
uv run uvicorn app.main:app --reload --port 8811
```

No test suite exists yet for `app/` — the `tests/` directory at the repo root is entirely
legacy-Streamlit-focused (`_FakeStreamlit` stub etc.) and out of scope to extend until a task
explicitly calls for FastAPI test coverage.
