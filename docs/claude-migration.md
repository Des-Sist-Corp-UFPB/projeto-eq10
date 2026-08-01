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
| C | Authentication `/auth/*` | Core done (login/register/logout/profile/password-reset). Google OAuth, email verification, email-change confirmation, account reactivation NOT started (user decision: move on to D–G first). |
| D | Chat IA `/chat` | Done. |
| E | Audit/Admin `/auditoria` | Done. |
| F | User Management `/admin/users` | Done. |
| G | Healthcheck `/healthcheck` | Done. |
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
  database/             One psycopg2 module per domain. Raw SQL only.
    connection.py         get_auth_connection() — opens a new psycopg2 connection per call
                        (AUTH_DATABASE_URL or AUTH_DB_HOST/PORT/NAME/USER/PASSWORD +
                        AUTH_DB_SSLMODE). Caller owns commit/rollback/close.
    auth_db.py            usuarios + password_reset_tokens queries. Does NOT create either
                        table — both are migrated by the legacy app's own ensure_schema()
                        calls (UserService, PasswordResetService), which keep running since
                        app_ai_chat.py is untouched. This module only reads/writes rows.
    audit_db.py           audit_log insert/select. Same non-migrating stance.
    chat_db.py / users_db.py   Not started yet (Tasks D / F).
  service/              Business logic per domain.
    audit_service.py      EVENT_* constants, VALID/SUCCESS/FAILURE/BLOCKED/INFO_EVENTS,
                        sanitize_text() (regex-for-regex port of audit_log_service.py's
                        sanitizer), log_event_safely(). Built ahead of Task E because Task C
                        depends on it for login/logout/register audit entries.
    email_service.py      EmailConfig/EmailService/EmailSendResult, ported from
                        src/auth/email_service.py. Fake/local mode by default; only sends
                        real SMTP when EMAIL_ENABLED=true and EMAIL_PROVIDER=smtp.
    auth_service.py       register/authenticate/logout, profile self-service
                        (update_profile_name/update_profile_email/change_password/
                        deactivate_account), and the full password-reset flow
                        (request_password_reset/validate_reset_token/
                        reset_password_with_token), ported from UserService +
                        PasswordResetService. Verified with an in-memory smoke test
                        (mocked auth_db + connection) since no live Postgres is reachable
                        in this sandbox — see "Testing this app" below.
  routes/
    estatisticas.py      GET /estatisticas — public, no DB, renders estatisticas.html.
    auth.py               GET/POST /auth/login, POST /auth/logout, GET/POST /auth/register,
                        GET /auth/profile, POST /auth/profile/{name,email,password,deactivate},
                        GET/POST /auth/forgot-password, GET/POST /auth/reset-password.
                        NOT implemented: Google OAuth callback, email verification, email-change
                        confirmation, account reactivation (see "Deferred" below).
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
    css/auth.css           Page-specific: narrow centered .auth-card, .profile-section,
                        .profile-danger-zone.
    login.html / register.html / profile.html / forgot_password.html / reset_password.html
                          All extend sidebar.html.
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
- **register() is a direct create — not the legacy double opt-in.** The real
  `src/ui/auth_modal.py` register flow goes through `PendingRegistrationService`
  (a separate `pending_registrations` table + confirmation-code step before a real `usuarios`
  row ever exists — ~600 lines). The migration prompt's own Task C spec (Section 8) instead
  gives `register(nome, email, password) → triggers email verification flow if required`, and
  Section 3.6 confirms the verification gate only blocks **/chat**, not login — so a verified
  account isn't required to sign in. `app/service/auth_service.register()` therefore creates
  the `usuarios` row immediately (via the same validation/audit path as
  `UserService.create_user()`) and logs the user in right away. `EMAIL_VERIFICATION_REQUIRED`
  is wired into `sidebar.html`'s template globals but the actual "send a verification email or
  show the chat gate" behavior isn't implemented yet — see Deferred below.

## Task D — Chat IA notes

- `app/database/chat_db.py` / `app/service/chat_service.py` port `src/chat/chat_history_service.py`
  (session/message persistence, `redact_sensitive_content`) and the response-handling half of
  `app_ai_chat.py` (`_friendly_response`, `_render_assistant_content` and its table/list/pair-line
  parsers, sanitization). The AI layer itself is untouched — `chat_service.process_question()`
  imports and calls `src.ai.datasus_ai.perguntar_datasus()` exactly as the legacy app does.
- **GET /chat loads message history from the DB**, unlike the legacy page, which only ever shows
  messages accumulated in `st.session_state.messages` during the current browser session (DB
  writes there are fire-and-forget, never read back into the UI). This is a deliberate adaptation,
  not an oversight: the migration prompt's own Task D route table says `GET /chat → ... renders
  chat template with message history`, and there's no FastAPI equivalent of Streamlit's persistent
  per-tab script-rerun state to source that history from otherwise — the DB is the only place it
  can come from.
- `POST /chat/ask` returns JSON (`user_html`, `assistant_html`, `status`) for `chat.js` to append
  via `fetch`, rather than a redirect — matches the prompt's own "JSON or redirect" option in
  Section 8 and the "fetch/HTMX, append message to DOM" instruction for `chat.js`.
- Email-verification gating (`EMAIL_VERIFICATION_REQUIRED=true` + unverified) checks
  `usuarios.email_verificado` directly via `auth_db.get_user_by_id()` — there's no verification
  *action* wired up yet (that subsystem is still deferred, see Task C above), so a user who ends
  up gated here currently has no self-service way to clear it beyond an admin/DB fix.
- Verified with an in-memory smoke test (mocked `chat_db`) covering session reuse, message
  persistence, and `redact_sensitive_content()` catching `token=`/`senha:` patterns, plus a
  standalone check of every `render_assistant_content()` branch (number card, JSON list, markdown
  table, colon-pair table, plain paragraph, and unsafe-pattern-triggers-friendly-message) against
  real sample inputs — all correct. Guard behavior (`/chat` redirects to login, `/chat/ask` returns
  401) was verified over real HTTP. `perguntar_datasus()` itself was not exercised (needs the full
  `AI_DB_*`/LLM stack, out of reach in this sandbox).

## Task E — Audit/Admin notes

- `app/service/audit_service.py` gained the display half ported from `src/ui/admin_page.py`:
  `EVENT_CATEGORY_OPTIONS`/`STATUS_FILTER_OPTIONS`/`STATUS_BADGE_STYLES`, `event_category()`,
  `event_label()`, `entry_status()` (stored status wins, falls back to inferring from event
  name), `sanitize_display_text()` (a *different*, more aggressive truncate-and-redact than
  `sanitize_text()` used at log-write time — legacy keeps these as two separate functions too,
  `_sanitize_text` vs `_sanitize_audit_text`), `build_summary()`, `filter_entries()`,
  `format_entry_for_display()`.
  `_render_observability_diagnostics()` (the health/OTEL/Umami expander on the legacy admin
  page) was intentionally **not** ported — it's outside the migration prompt's Task E scope
  (Section 3.5 only specifies filters/summary/table/detail), and healthcheck itself is Task G.
- Filters are plain `GET` query params (`limit`, `event_type`, `status`, `user_search`,
  `start_date`, `end_date`) — a normal server-rendered form submit, no JS/fetch needed for
  filtering itself. `auditoria.js` only handles the event-detail modal (row click → populate
  from `data-*` attributes already rendered server-side → show; no second request).
- **User management is a link, not embedded content.** Legacy's `_render_user_management()`
  renders inline inside the admin page for `super_admin`. The migration prompt puts user
  management on its own route (`/admin/users`, Task F) instead, so `auditoria.html` shows a
  "Gestão de usuários" card linking there when `is_super_admin(user)`, preserving the "not a
  sidebar item, only discoverable from Auditoria" property without duplicating Task F's route.
- Verified over real HTTP with `TestClient`, mocking `require_audit_access` (to inject a fake
  super_admin without a real session) and `audit_service.get_recent_logs` (to avoid needing
  Postgres): the page renders with correct summary counts, status badge classes, the
  super_admin-only management link, and a filtered request (`?event_type=Login`) returns 200.
  Separately, `build_summary`/`event_category`/`filter_entries` (by category, status, email
  substring, date range) /`format_entry_for_display` (including sensitive-detail redaction)
  were checked against 6+ hand-built entries — all correct. This TestClient-plus-guard-mock
  pattern is a better fit for route-level checks than the raw in-memory service mocks used for
  Tasks C/D and is worth reusing for Task F.

## Task F — User Management notes

- `app/database/users_db.py` / `app/service/user_management_service.py` port
  `UserService.get_all_users/set_role/set_audit_access/soft_delete_user` directly — same
  validation (`new_role` must be in `VALID_ROLES`), same audit events
  (`role_changed`/`access_granted`/`access_revoked`/`account_deleted`) with the same
  `detalhe` format (`novo_role=... | admin_id=... | admin=...`).
  `soft_delete_user()` never runs `DELETE`, same soft-delete columns as Task C's
  self-service path.
- Per the prompt's own instruction ("not a sidebar item... reachable only from within the
  Auditoria page"), `/admin/users` has no nav entry — only the link added to `auditoria.html`
  in Task E.
- Delete confirmation uses a JS `confirm()` on the form (same pattern as
  `/auth/profile/deactivate` in Task C) instead of legacy's two-step
  button-reveals-confirm/cancel session-state dance — same safety property (can't delete
  with a single accidental click), simpler mechanism now that there's a real browser dialog
  API to use instead of faking one out of Streamlit widgets.
- Verified via `TestClient` + mocked `require_super_admin`/`users_db`/`auth_db`: page render
  (including the "você" tag on the admin's own row and the self-row skipping edit controls),
  role change, invalid-role rejection (redirects with a URL-encoded `?error=` — checked the
  encoding is actually applied, not just that it redirects), audit-access grant, and
  deactivate-then-gone-from-list — all correct, all three audit events fired. Guard redirect
  for unauthenticated requests checked over real HTTP.

## Task G — Healthcheck notes

- `app/routes/healthcheck.py` calls `src.diagnostics.health_service.HealthService().run_heartbeat()`
  as-is (untouched legacy module — no port needed, it's already framework-agnostic) and returns
  `result.as_dict()` as JSON with **HTTP 200 always**, even when `status: "error"` — matching
  the legacy `?healthcheck=1` handler and the Uptime Kuma contract in Section 3.8 (keyword
  match on `"status": "ok"` in the body, not on HTTP status code).
- Verified over real HTTP in this sandbox (no reachable Postgres): returns 200 with
  `status: "error"`, `auth_db_ok: false`, a `dns_failure` category, and no leaked connection
  string/credentials — confirming the graceful-degradation path actually works, not just the
  happy path.

## Corrections to the prompt's schema/env-var sketch (verified against real code + live sqlite dev DB)

The migration prompt's Section 4 (`usuarios` columns) and Section 5 (env vars) are
approximations. Where they disagree with `src/auth/user_service.py`,
`src/auth/email_service.py` and the actual `data/auth.sqlite3` dev DB, **the code wins** —
this migration must not invent columns/env vars that don't exist, and must not rename the
real ones:

- **No `ativo` column exists.** Soft-delete uses `deletado BOOLEAN`, `deleted_at TIMESTAMP`,
  `deletado_em TIMESTAMP` (all three, redundantly — that's how the legacy schema evolved).
  `app/database/auth_db.py:ACTIVE_CONDITION` and `deactivate_own_account()` /
  `update_active_user_password()` use the real columns. Confirmed via
  `PRAGMA table_info(usuarios)` against `data/auth.sqlite3`.
- **No `avatar_url` or `google_email_verified` columns.** The real columns are `google_picture`
  and `email_verificado` (+ `email_verificado_em`). `google_sub` and `auth_provider` do exist
  as named.
- **Email env vars are `EMAIL_ENABLED` / `EMAIL_PROVIDER` / `EMAIL_FROM` /
  `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` / `EMAIL_SMTP_USERNAME` / `EMAIL_SMTP_PASSWORD` /
  `EMAIL_USE_TLS`** (confirmed in `.env.example` and `src/auth/email_service.py`) — not the
  `SMTP_HOST/PORT/USER/PASSWORD/FROM` names sketched in the prompt's Section 5.
  `app/service/email_service.py` uses the real names.
- `APP_PUBLIC_BASE_URL` (used to build password-reset/verification links) is real
  (`.env.example`, `src/auth/password_reset_service.py`) but isn't listed in the prompt's env
  table at all. `app/service/auth_service.py:_resolve_public_base_url()` reads it, falling
  back to `EMAIL_PUBLIC_BASE_URL`, then `APP_PUBLIC_URL`, then `http://localhost:8080`
  (matching `.env.example`'s documented default), same precedence as the legacy service.

## Deferred (not yet built) — scope note

Task C's remaining panels from Section 3.3 are each an independent subsystem in the legacy
code, all substantially larger than core login/register/profile: `GoogleOAuthService` (OAuth2
PKCE, ~225 lines), `EmailVerificationService` (~570 lines), `EmailChangeService` (code-based,
~715 lines), `AccountReactivationService` (~565 lines), and the `PendingRegistrationService`
double opt-in (~605 lines) that the simplified `register()` above intentionally bypasses.
None are wired into `app/routes/auth.py` yet:

- `GET /auth/google/callback` — not started.
- `GET /auth/verify-email` — not started. `login.html`/`register.html` don't yet show a
  verification gate; `EMAIL_VERIFICATION_REQUIRED` is exposed as a template global but unused.
- `GET/POST /auth/confirm-email-change` — not started. `POST /auth/profile/email` updates the
  email immediately (matching `UserService.update_email()`) rather than requiring a
  confirmation code first, which is what `EmailChangeService` actually does in production.
- `POST /auth/reactivate` — not started. A deactivated account currently has no self-service
  path back in.

Each needs its own database/service/routes/template pass per Section 6, plus (for OAuth)
Google API client credentials to test against. Flagging here rather than rushing a port,
since these are security-sensitive flows this session couldn't verify against a live
Postgres or real SMTP/Google credentials (see "Testing this app" below).

## Conventions carried forward unchanged from `docs/claude.md`

- Two-database routing (`AUTH_DB_*` vs `AI_DB_*`) — `app/database/auth_db.py` /
  `connection.py` cover the auth side; `AI_DB_*` lands with Task D (AI layer stays in
  `src/ai/`, called from `app/service/chat_service.py`, not ported/rewritten).
- Audit event vocabulary, status vocabulary (`success|failure|blocked|info`), and the
  sanitization rules in Section 3.11 of the migration prompt are ported as-is
  (`app/service/audit_service.py`, built ahead of Task E — see above) — do not invent new
  event types or statuses.
- Soft delete never runs `DELETE` SQL — flips `deletado`/`deleted_at`/`deletado_em`, not an
  `ativo` flag (see schema correction above). `app/database/auth_db.py:deactivate_own_account()`
  covers Task C's self-service path; Task F's admin-initiated `users_db.py:soft_delete_user()`
  will do the same update from the admin side.

## Testing this app during migration

```bash
uv run uvicorn app.main:app --reload --port 8811
```

No live Postgres or Docker daemon is reachable in this sandbox, so DB-touching routes
couldn't be hit end-to-end over HTTP. What was actually verified:

- Every GET route that doesn't need a DB (`/estatisticas`, `/auth/login`, `/auth/register`,
  `/auth/forgot-password`) was hit over real HTTP with `uvicorn` running and rendered
  correctly, including the `require_authenticated` guard's redirect-to-login behavior on
  `/auth/profile`.
- `app/service/auth_service.py`'s full control flow — register, duplicate-email rejection,
  authenticate (success + wrong-password), profile name/email update, change-password
  (success + wrong-current-password), the complete password-reset cycle (request → validate →
  complete → reuse-rejected), and deactivate-then-login-rejected — was exercised end-to-end
  against an in-memory fake standing in for `app/database/auth_db.py` +
  `get_auth_connection()`, with real password hashing/verification and real audit-event
  emission (asserted by event name and status, 10/10 fired as expected). No test file was
  committed for this — it was a one-off sandbox script, not a permanent suite.
- What this does **not** prove: actual SQL syntax against a real Postgres server (parameter
  binding, `RETURNING id`, the partial unique index on `usuarios(lower(email))`, timestamp
  timezone handling). Run the queries in `app/database/auth_db.py` against a real `AUTH_DB_*`
  before trusting this in production.

No test suite exists yet for `app/` — the `tests/` directory at the repo root is entirely
legacy-Streamlit-focused (`_FakeStreamlit` stub etc.) and out of scope to extend until a task
explicitly calls for FastAPI test coverage.
