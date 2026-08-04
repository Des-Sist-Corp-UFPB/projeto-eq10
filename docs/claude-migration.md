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
| H | Runtime fix (login 500) + Docker deployment layer | Done — see below. |
| I | CI/CD cutover prep (deploy.yml → Dockerfile.fastapi, rewritten smoke test) | Done — cutover completed and verified live at https://eq10.dsc.rodrigor.com/. |
| J | Observability, `/health`, Umami, test coverage ≥85%, README evaluation sections | Done — see below. |

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

## Task H — Runtime fix (login 500) + Docker deployment layer

Triggered by a report that `POST /auth/login` returned 500 in "the professor's environment."
**This sandbox has no route to that Postgres** (no docker daemon, no local postgres binary, no
sudo to install one, `.env`'s `AUTH_DB_HOST=postgres` is a Docker-internal hostname) — same
limitation noted for Tasks C–F. Everything below is either evidence-based static diagnosis or a
verified-in-this-sandbox fix; nothing was rubber-stamped from the six hypotheses in the fix
request without checking it first.

### What the six hypothesized causes actually turned out to be

| # | Hypothesis | Verdict |
|---|---|---|
| 1 | `psycopg2` not installed in the venv running uvicorn | Not reproducible here — `import psycopg2` works in this sandbox's `.venv`, and every earlier Task C–F smoke test that reached `get_auth_connection()` got a real `psycopg2.OperationalError` (proves psycopg2 imports and attempts a real connection). If this is the real cause in their environment, it means uvicorn is being run outside `uv run`/the project venv — an operational mistake, not a code bug. No code fix applies; `Dockerfile.fastapi` sidesteps it entirely since `uv sync --frozen` guarantees psycopg2-binary is present in the image. |
| 2 | `argon2-cffi` not installed | Same as #1 — verified working in this sandbox (`import argon2` + a full hash/verify roundtrip both succeed, see the Task C smoke test). Not a code bug. |
| 3 | DB connection fails at import time | Confirmed **not** an issue by design — `get_auth_connection()` only connects when called, never at module import. Verified: `app.main` imports cleanly with zero DB access even when Postgres is completely unreachable. |
| 4 | `auth_provider` column doesn't exist | **Real risk, acted on.** Neither `auth_provider` nor `google_sub` is read anywhere in `app/` (`grep -rn "google_sub\|auth_provider" app/` matched only the `SELECT` itself) — both were only in `USER_COLUMNS` pre-emptively for OAuth, which is still deferred. Removed both rather than guess whether they exist in the real schema; they'll come back with the OAuth callback route. This directly shrinks the blast radius of exactly the class of bug being worried about. |
| 5 | `ACTIVE_CONDITION`'s three soft-delete columns might not all exist | **Investigated, not simplified.** `src/auth/user_service.py:_usuarios_create_table_sql()` + `_add_usuario_column_if_missing()` add `deleted_at`, `deletado`, AND `deletado_em` unconditionally every time the legacy app's `UserService.ensure_schema()` runs (confirmed by reading that function, and by `PRAGMA table_info(usuarios)` against the local `data/auth.sqlite3` dev DB, which the identical code path built). Since "the professor's environment" is the same Postgres the still-running legacy Streamlit app writes to, `ensure_schema()` has almost certainly already added all three there too. Simplifying `ACTIVE_CONDITION` based on a guess would risk trading a real bug for an invented one. Instead: `app/database/schema_check.py` now checks the actual live columns at startup and logs exactly which are missing, if any — so if this genuinely is the cause, it's a one-line startup log message away from being confirmed, not another round of guessing. |
| 6 | `https_only=True` + missing `X-Forwarded-Proto` loses the cookie | **Hypothesis was wrong about the mechanism, right that it's worth fixing.** Read Starlette's actual `SessionMiddleware.__call__` source: `https_only` is a **static** flag baked into the `Secure` cookie attribute at middleware-construction time — it is never re-evaluated per-request against `request.url.scheme`, and `X-Forwarded-Proto` is never consulted for this decision at all. The real risk is simpler and starker: if `ENVIRONMENT=production` is set, **every** session cookie gets `Secure` unconditionally, and any real browser (or curl's cookie jar) will silently refuse to send it back over a plain-HTTP connection — regardless of proxy headers. Fixed the *actual* gap this exposed: `nginx.fastapi.conf` was forwarding `X-Forwarded-Proto: $scheme`, which is always `"http"` from this container's nginx's own point of view (it never terminates TLS itself) — silently overwriting whatever an outer TLS-terminating proxy had already set, which matters for `request.url_for()` generating correct absolute URLs later, even though it turned out not to matter for the cookie's `Secure` flag specifically. Changed to `$http_x_forwarded_proto` (pass through, don't overwrite) and added `--proxy-headers --forwarded-allow-ips=127.0.0.1` to uvicorn in `start_fastapi.sh` so it actually honors that header. Documented the real, verified mechanism in a startup log line in `app/main.py` instead of quietly implementing a fix for a mechanism that doesn't exist. |

### Fixes applied

- **`app/database/auth_db.py`** — `USER_COLUMNS` no longer selects `google_sub`/`auth_provider`
  (see #4 above). Added `EXPECTED_USER_COLUMNS`, a plain tuple (not a SQL string) the new
  startup check verifies against `information_schema.columns`.
- **`app/database/schema_check.py`** (new) — `run_startup_checks()`, wired into `app/main.py`
  via a `lifespan` context manager: on startup, opens one connection, logs exactly which
  `EXPECTED_USER_COLUMNS` are missing from the real `usuarios` table (if any — never crashes
  the app either way, matches `src/diagnostics/health_service.py`'s degrade-loud-don't-crash
  philosophy), and runs a non-destructive `CREATE TABLE IF NOT EXISTS password_reset_tokens`
  (same shape as `PasswordResetService.ensure_schema()`) — the one narrow schema-bootstrap
  accommodation the fix request asked for. It does **not** attempt to create `usuarios`,
  `audit_log`, or `chat_*` — those stay owned by the legacy app's `ensure_schema()` calls,
  consistent with every other database module in `app/`.
- **A previously-unnoticed, unrelated bug found while implementing this**: `app/main.py` had
  `logger.info(...)` calls scattered through Tasks A–G that were **silently dropped** —
  Python's root logger has no handler by default, so anything below WARNING vanishes into
  `logging.lastResort`. `uvicorn --log-level info` does **not** fix this; it only configures
  uvicorn's own loggers (`uvicorn`, `uvicorn.error`, `uvicorn.access`), never the root logger
  the rest of `app/` propagates to. Added one `logging.basicConfig(level=logging.INFO, ...)`
  call at the top of `app/main.py`. Verified before/after: the new `https_only` log line and
  the schema-check warning were both invisible before this, both visible after, over real
  `uvicorn app.main:app` runs in this sandbox.
- **`app/main.py`** — logs `SessionMiddleware https_only=<bool>` on startup with the accurate
  mechanism explained inline (see #6 above), and wires up `_lifespan()` → `run_startup_checks()`.

### Docker deployment layer (new files, additive only)

| File | Purpose |
|---|---|
| `Dockerfile.fastapi` | **Base image is `ghcr.io/osgeo/gdal:ubuntu-small-3.8.4` (same as `Dockerfile`), not `python:3.11-slim`.** `pyproject.toml` pins `gdal==3.8.4` as an unconditional dependency; PyPI ships it source-only (confirmed: `pypi.org/pypi/gdal/3.8.4/json` lists only an `sdist`, no wheel), so building it needs `libgdal`/`gdal-config`, which a plain slim image doesn't have — `uv sync --frozen` against this repo's actual `pyproject.toml` would fail on `python:3.11-slim` before a single FastAPI dependency installed. Splitting `gdal`/`pysus`/`streamlit`/`pandasai` into an optional dependency group so a slim image could skip them isn't safe here: the ETL `Dockerfile` (which must not be touched) runs plain `uv sync --frozen --no-dev --no-install-project` with no `--extra` flag, so it would silently stop installing gdal/pysus the moment those became optional-only. Reusing the GDAL image is the only fix available without touching a forbidden file — heavier than ideal (carries GDAL/pysus/streamlit/pandasai binaries this app never uses), and worth revisiting later alongside an ETL Dockerfile update, but it actually builds. |
| `nginx.fastapi.conf` | Serves `/static/` from disk, proxies everything else + `/healthcheck` to uvicorn on 8811. `X-Forwarded-Proto` is passed through (`$http_x_forwarded_proto`) rather than overwritten (`$scheme`) — see #6 above. |
| `start_fastapi.sh` | Same supervisor pattern as the legacy `start.sh`: starts uvicorn (2 workers, `--proxy-headers`, port 8811), polls until it accepts connections, starts nginx, polls again, then supervises both and exits if either dies. |
| `docker-compose.migration.yml` | Local dev: FastAPI + a fresh local Postgres, doesn't touch `docker-compose.yml`. **Read the in-file comment before using it** — a fresh `postgres:16-alpine` container has no `usuarios`/`audit_log`/`chat_*` tables; only `password_reset_tokens` gets bootstrapped by this app's own startup check. Point it at an already-migrated Postgres, or run the legacy Streamlit app against the same container once first. |
| `docker-compose.prod.yml` | Added a `fastapi` service, additive only, gated behind `profiles: [fastapi]` so a bare `docker compose -f docker-compose.prod.yml up` still behaves exactly as it does on `main` (Streamlit `app` + `etl`, nothing else starts). Runs on a different external port (`8112`, vs. Streamlit's `8110`) so both can run side by side during the migration window. |

### What was and wasn't verified

Verified over real `uvicorn app.main:app` runs in this sandbox: app still starts cleanly with
the new lifespan hook; the schema check degrades gracefully (logs a `WARNING` and continues)
when Postgres is unreachable rather than crashing startup; both new log lines are now actually
visible after the `logging.basicConfig` fix; `docker-compose.migration.yml` and the updated
`docker-compose.prod.yml` both parse as valid YAML.

**Not verified** — no docker daemon is reachable in this sandbox (`docker info` fails with
"cannot connect to the Docker daemon"), so none of the following ran here: `docker build -f
Dockerfile.fastapi .`, `docker compose -f docker-compose.migration.yml up`, or an actual
login against a real Postgres, at the time this task was done — **since superseded**: Task I
below got Docker working end to end (the user fixed the daemon/group setup on the host, which
this environment turned out to share) and everything was actually built, run, and verified,
including one real bug the local-only static analysis in this task couldn't have caught (the
`nginx $host`-strips-the-port issue — see Task I). Login against the professor's real
production Postgres specifically is still unverified; that only happens after Task I's actual
cutover, which has not happened yet.

## Task I — CI/CD cutover prep (deploy.yml → Dockerfile.fastapi)

Goal: make `https://eq10.dsc.rodrigor.com/` serve the FastAPI app instead of Streamlit, by
changing what the existing GitHub Actions pipeline (`.github/workflows/deploy.yml`) builds and
deploys — same image tag, same SSH mechanism, no server-side changes. **This task prepared
everything on `branch-migration` and validated it locally. It deliberately stopped short of
merging to `main` and pushing** — that's the one step in this whole migration that immediately
triggers a real, unattended deploy to a server neither this environment nor the assistant has
any visibility into (the deploy step SSHs in and hands `github.actor:token` to a forced-command
script that lives entirely on that server, outside this repo). Given several auth subsystems
are still deferred (Google OAuth, email verification, email-change confirmation, account
reactivation — see Task C), cutting over silently drops those for whoever's using the live site
today. The user explicitly chose "prep only, not yet" when asked.

### What changed

- **`.github/workflows/deploy.yml`** — one line: `file: Dockerfile.chat` → `file:
  Dockerfile.fastapi`. Image tag, GHCR push, SSH deploy mechanism, and the health-check step
  are all untouched, exactly as scoped.
- **`docker-compose.prod.yml`, `Dockerfile.fastapi` HEALTHCHECK** — turned out to need **no
  changes**. Checked first rather than assumed: the `app` service in
  `docker-compose.prod.yml` has no `healthcheck:` block to update, and `Dockerfile.fastapi`'s
  own `HEALTHCHECK` already called `/healthcheck` from Task H.
- **`scripts/smoke_test_startup_container.py` — fully rewritten, not edited.** The original
  request assumed this was a URL-poller that needed a one-line swap. Reading it end to end
  showed otherwise: it's a structural test of the *Streamlit* container's specific 3-process
  supervisor (`readiness_server` + `streamlit` + `nginx`) — exact-byte-match JSON bodies from
  `/ping`/`/health` (endpoints that don't exist in the FastAPI image), internal-port checks
  against `8501`/`8502` (Streamlit's ports, not our `8811`), PID files at
  `/tmp/eq10-{readiness,streamlit,nginx}.pid` (files `start_fastapi.sh` never wrote), and
  `AUTH_DATABASE_URL=sqlite+pysqlite:...` (a DSN format `app/database/connection.py`'s
  psycopg2-only `get_auth_connection()` can't parse at all). None of it applies to a 2-process
  uvicorn+nginx stack with a single `/healthcheck` endpoint. Surfaced this to the user with the
  actual evidence rather than force-fitting a 2-line edit that couldn't have worked, and they
  chose the rewrite option. New version keeps the same shape/rigor as the original (start the
  real image, validate nginx config, poll the real health endpoint, verify both internal ports,
  kill the core process via its real PID file, verify the whole container goes down and exits
  non-zero) rather than a token check — same guarantee, correct process model.
- **`start_fastapi.sh`** — gained PID-file writing (`/tmp/eq10-uvicorn.pid`,
  `/tmp/eq10-nginx.pid`) matching `start.sh`'s `write_pid_file`/`report_exit` pattern exactly,
  since the rewritten smoke test needs a real PID to signal — Task H's version never wrote
  these because nothing consumed them yet.

### Verified — for real, not just locally-reasoned this time

Partway through this task, `docker info` started working in this environment (previously
failed identically to the user's own terminal). Turned out to be expected, not a fluke: this
sandbox and the user's WSL terminal are the same machine/user, and the daemon-group fix the
user applied earlier (`sudo systemctl start/enable snap.docker.dockerd.service`, `sudo
groupadd docker` + `usermod -aG docker` + `newgrp docker`) is a persistent OS-level change, not
a per-shell one. This let every claim below actually run, not just get reasoned about:

- `docker build -f Dockerfile.fastapi .` — succeeds.
- The rewritten `scripts/smoke_test_startup_container.py` — **passes end to end** against the
  real built image: nginx config valid, `/healthcheck` returns 200 with a `status` key,
  `/estatisticas` returns 200 containing "Mamanguape", both internal ports (8811, 8080) accept
  connections, killing uvicorn by its real PID file brings the whole container down within the
  timeout, exit code is non-zero. This is the strongest verification any part of this
  migration has had — a real container, really started, really killed, really supervised.
- Standalone container run (`docker run` + curl), matching the user's own manual steps:
  `/healthcheck` → 200 with `status: "error"` (no DB reachable, exactly as expected — proves
  the graceful-degradation path holds under a real container, not just a mocked one);
  `/estatisticas` → 200, contains "Mamanguape".
- `docker compose -f docker-compose.prod.yml --env-file .env.prod config --quiet` — passes
  with an empty `.env.prod`.

### Not done — deliberately

- **No merge to `main`, no push to `main`.** `.github/workflows/deploy.yml` only triggers on
  `push: branches: [main]` or manual `workflow_dispatch` — confirmed by reading the trigger
  block before doing anything else, specifically to establish that committing/pushing this work
  to `branch-migration` alone could not accidentally kick off a production deploy. Everything
  above is real local verification; nothing has touched the professor's server.
- **`APP_HEALTH_URL` GitHub repository variable not changed.** It currently defaults (in
  `scripts/verify_deploy_health.py`) to `https://eq10.dsc.rodrigor.com/ping` if unset — a
  Streamlit-only endpoint. Before an actual cutover, this needs to become
  `https://eq10.dsc.rodrigor.com/healthcheck` via the GitHub web UI (Settings → Variables →
  Actions) — not something achievable from a terminal in this repo.
- **`docker-compose.prod.yml`'s separate `fastapi` service (added in Task H, port 8112,
  different image tag `projeto-eq10-fastapi:latest`) is now redundant with this cutover
  approach** — the cutover reuses the *same* tag the `app` service already pulls
  (`projeto-eq10:latest`), so `app` becomes the FastAPI app directly and the `fastapi` service
  block just sits there pointing at an image nothing ever pushes. Left it in place rather than
  removing it unasked — it's inert, not broken — but it's worth deleting once the cutover is
  confirmed, to avoid the two-services-two-mental-models confusion.

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

**Superseded by Task J below**: a full `tests/test_app_*.py` suite now exists (214 tests,
93.64% coverage of `app/`), and this entire migration has since been cut over to production
and verified against the real professor's Postgres.

## Task J — Observability, /health, Umami, test coverage ≥85%, README evaluation sections

Triggered by the professor's evaluation requirements
(`docs/ORIENTACOES-AVALIACAO-2026-06-29.md`): OTel wiring, Umami in Jinja2, a real `/health`
readiness endpoint, ≥85% test coverage with a committed HTML report, and two README sections
cross-referenced against actual code by an automated evaluator
(`docs/AVALIACAO-2026-07-01.md` shows exactly how — it counts file-path evidence per claim).

### What the task's own snippets got wrong (verified against the real code before writing anything)

| # | Claim in the task | Reality |
|---|---|---|
| 1 | `configure_telemetry(service_name=..., enabled=...)` | **Takes zero arguments.** Reads `OTEL_ENABLED`/`OTEL_SERVICE_NAME`/`OTEL_EXPORTER_OTLP_*` directly from the environment itself (`src/observability/telemetry.py`). Called as `configure_telemetry()`. |
| 2 | Span attributes `auth.method`, `audit.filter`, `audit.limit` | **Not in `SAFE_ATTRIBUTE_KEYS`.** `safe_attributes()` silently drops any key not on that allow-list — using them wouldn't error, just silently do nothing, which is worse than not writing them (misleads whoever reads the code later into thinking they show up in traces). Used only accepted keys: `auth.provider`, `auth.result_status`, `audit.operation`, `audit.result_status`. |
| 3 | Manually emit `app.startup` span in `_lifespan()` | **`configure_telemetry()` already auto-emits one internally** via `_emit_startup_span_once()` when successfully configured — but that internal one hardcodes `app.framework="streamlit"` (legacy code, not touched). Added the manual span anyway (correctly labeled `fastapi`) since the task explicitly wants it and the attributes are legitimate — documented that this means two `app.startup` spans per process start, one mislabeled, rather than silently "fixing" it by omitting the manual one. |
| 4 | Point `Dockerfile.fastapi`'s `HEALTHCHECK` at `/health` | **Contradicts `docs/READINESS.md`**, which the task itself said to read first: *"O HEALTHCHECK do Docker permanece em /ping [the liveness endpoint]... A readiness do banco principal deve ser monitorada externamente por /health."* Switching would make Docker flap/restart the container on transient DB blips even though the process is fine — exactly what that design avoids. Left `HEALTHCHECK` on `/healthcheck` (always 200); added `/health` as a separate endpoint for external readiness monitoring only. |
| 5 | Healthcheck `CMD` snippet: `r = urlopen(...); assert r.status in (200, 503)` | `urlopen()` **raises `HTTPError` on a 503**, so `r.status` is never reached for the "acceptable" 503 case — the snippet would treat a deliberate, well-formed 503 as a crash. Moot given #4 (not using this endpoint for `HEALTHCHECK` at all), but worth flagging since it'd resurface if anyone tries this later. |

### J.1 — OpenTelemetry

- `app/main.py`'s `_lifespan()` now calls `configure_telemetry()` (no args), then
  `run_startup_checks()` (Task H), then emits the manual `app.startup` span (see #3 above).
  Verified over a real `uvicorn` run: the exact documented log line appears —
  `OpenTelemetry status | enabled=false | service_name=dsc-eq10 | ... | initialization=disabled`
  (disabled because `OTEL_ENABLED` isn't set in this sandbox; the code path that produces
  `initialization=configured` is the same either way, untouched legacy logic).
- `app/routes/auth.py:post_login()` wraps `auth_service.authenticate()` in
  `span("auth.login", {"auth.provider": "password"})`, sets `auth.result_status` on
  success/failure, and calls `add_metric()` with the **real** registered instrument names
  (`eq10_auth_login_total`, `eq10_auth_login_failures_total` — confirmed against
  `_create_instruments()`), not the task's invented `"auth.login.success"`/`"auth.login.failure"`.
- `app/routes/audit.py:get_auditoria()` wraps the fetch/filter block in
  `span("audit.list", {"audit.operation": "list"})` — deliberately does NOT put
  `user_search` (a free-text email search) into a span attribute even though the task's
  draft attribute name (`audit.filter`) wasn't accepted anyway; avoids leaking user input
  into traces on two independent grounds.
- `app/config/settings.py` was **not** given a new `otel_service_name` field — the task's own
  final caveat ("don't add otel_* fields for values configure_telemetry() already reads
  directly from env") applies, since it does read `OTEL_SERVICE_NAME` itself (see #1).
- **Found and fixed an unrelated, previously-invisible bug while testing this**: none, this
  time — Task H already fixed the silently-dropped-INFO-logs issue that would otherwise have
  hidden the OTel status line too.

### J.2 — Umami in Jinja2

- `app/config/settings.py` gained `umami_enabled`/`umami_script_url`/`umami_website_id`/
  `umami_host_url`/`umami_allowed_domain`, validated by **importing the pure validator
  functions directly from `src/analytics/umami.py`** (`_safe_https_url`, `_safe_website_id`,
  `_safe_domain`) rather than re-deriving the same HTTPS-only/valid-UUID/bare-domain rules.
  This is a legitimate "read-only import" from `src/` — those three functions have zero
  Streamlit dependency (only `configure_umami()`/`track_event()`/etc. in that file touch
  `st.session_state`); only the framework-coupled parts are actually off-limits per the
  "don't touch src/" rule.
- `app/main.py` exposes the five as Jinja2 template globals exactly as specified.
- `app/templates/sidebar.html` injects the tracker `<script>` + manual page-tracking script
  in `<head>`, gated by `{% if umami_enabled %}`, `data-auto-track="false"`, using the exact
  `PAGE_SLUGS` mapping given (verified it matches `src/analytics/umami.py:ALLOWED_PAGES`'s
  keys one-to-one).

### J.3 — `GET /health`

- Added to `app/routes/healthcheck.py` alongside the existing `/healthcheck`, matching
  `docs/READINESS.md`'s contract exactly: `SELECT 1` via `get_auth_connection()`, HTTP 200
  `{"status":"healthy","database":"connected"}` or HTTP 503
  `{"status":"unhealthy","database":"unavailable"}`, `Cache-Control: no-store`, never leaks
  exception text (verified with a test asserting a secret-laden exception message never
  appears in the response body).
- `nginx.fastapi.conf` proxies `/health` to uvicorn with short timeouts (5s connect, 6s
  read), matching the legacy `/health` nginx block's timeouts exactly.
- `Dockerfile.fastapi`'s `HEALTHCHECK` **intentionally left unchanged** — see #4 above.
- Verified over a real `uvicorn` run: 503 with the exact contract body when the (sandbox's
  unreachable) auth DB can't connect; `/healthcheck` unaffected.

### J.4 — Test suite, ≥85% coverage

`tests/conftest.py` + ten `tests/test_app_*.py` files, 214 tests, all passing, mocking at the
`app/database`/service boundary (patched at the *importing* module's namespace, not the
defining one — e.g. `app.service.auth_service.get_auth_connection`, not
`app.database.connection.get_auth_connection`, since `from x import y` binds a new name into
the importer's namespace; this tripped up three tests on the first run, same class of mistake
made and fixed during Tasks C/F earlier in this migration). No live Postgres involved anywhere
in the suite.

```
uv run pytest tests/test_app_*.py --cov=app --cov-report=html --cov-report=term -q
```

**Result: 93.64% line coverage of `app/`** (1542 statements, 98 missed), comfortably over the
85% requirement. Per-file breakdown: every `app/database/*.py` file and `app/routes/healthcheck.py`
hit 100%; `app/auth/roles.py` and `app/auth/session.py` 100%; `app/middleware/guards.py` 100%;
the five service files 90–97%; routes 88–94%; `app/main.py` 90% (the uncovered lines are
`create_app()`'s router-registration boilerplate, not meaningfully testable in isolation).

Report copied to `cobertura/backend/` (raw `htmlcov/` added to `.gitignore` — it wasn't there
before, so a stray `htmlcov/` could have been committed by accident on a future run).
`cobertura/coverage-report.txt` (the pre-existing Streamlit-era report, 85.5%) is untouched —
now two separate, independently-passing coverage reports for the two stacks in this repo,
matching `docs/ORIENTACOES-AVALIACAO-2026-06-29.md`'s explicit guidance for projects with more
than one module (`cobertura/backend/` + the existing legacy report).

### J.5 — README sections

**Did not add the two sections as new content** — both already existed
(`## Log de Auditoria`, `## Integracoes Externas`) and had already passed evaluation per
`docs/AVALIACAO-2026-07-01.md` (file-path-evidence-based automated check). Adding a second,
differently-named copy of each would have fragmented the evidence trail for that same
automated evaluator rather than helping it. Instead, updated both **in place** to describe the
FastAPI implementation as the current one (with its own file paths) while keeping the legacy
`src/` references as explicitly-labeled prior-implementation context — plus added
OpenTelemetry and Umami as two new subsections under "Integracoes Externas" (they're bona fide
external services per the task's framing, distinct from the narrative treatment they already
had under "Observabilidade"/"Analytics de uso"). Also updated "Observabilidade", "Liveness e
readiness", and "Analytics de uso" to reference the FastAPI files, and added a FastAPI
subsection to "Cobertura de Testes" alongside the pre-existing Streamlit one.

### Verified

Over a real `uvicorn app.main:app` run in this sandbox: OTel startup log line (both the
`https_only` line from Task H and the new OTel status line — confirms the Task H logging fix
still works), `/health` 503-with-exact-body when DB unreachable, `/healthcheck` unaffected,
full test suite green with coverage computed for real (not estimated). **Not verified**: OTel
span export against a real collector, Umami script actually loading in a browser against the
real institutional endpoint, and — same standing caveat as every prior task — this sandbox has
no route to the professor's real Postgres, so `/health` returning 200 there specifically is
unverified from here (though `/healthcheck` already proved `auth_db_ok: true` against it after
the Task I cutover, which exercises the same connection path).
