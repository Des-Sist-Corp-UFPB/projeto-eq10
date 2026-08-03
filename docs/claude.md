# claude.md — System Map (token-efficient reference)

Monolithic Streamlit app (originated as a Municipal Secretariat of Mamanguape internship
project, now adapted to DSC/UFPB course standards). Two independent runtimes share one repo:

1. **ETL pipeline** (`main.py`, `Dockerfile`) — extracts DATASUS/SIA data via `pysus`, transforms,
   loads into the analytical Postgres (Neon). Runs standalone, not part of the web app request path.
2. **Streamlit chat/audit app** (`app_ai_chat.py`, `Dockerfile.chat`) — auth, chat UI, statistics
   page, admin/audit page. This is the production web app referenced below.

## Two databases — routing is the load-bearing fact of this system

| Concern | Engine getter | Env vars | Host |
|---|---|---|---|
| Auth/app data (users, sessions, chat history, audit_log) | `src/auth/user_service.py: get_auth_engine()` | `AUTH_DATABASE_URL` or `AUTH_DB_HOST/PORT/NAME/USER/PASSWORD` | Professor PostgreSQL |
| DATASUS analytics (AI layer, `vw_data_sus_ia` view) | `src/ai/read_only_datasus.py: get_readonly_engine()` | `AI_DATABASE_URL` or `AI_DB_USER/PASSWORD/HOST/PORT/NAME` (+`AI_DB_SSLMODE`, default `require`) | Neon (read-only) |

Never merge these. `AuditLogService.from_environment()` reuses the auth engine (`get_auth_engine()`).
`src/diagnostics/health_service.py` checks both engines separately and never logs credentials.
Analytics DB failure degrades only AI; auth DB failure makes app unhealthy.

## Roles and RBAC

```
ROLE_USER        = "user"        — authenticated, can use chat only
ROLE_ADMIN       = "admin"       — can view audit log
ROLE_SUPER_ADMIN = "super_admin" — can manage users (change roles, set_audit_access, soft_delete)

can_view_audit_log(user) — True if role in {admin, super_admin} OR can_view_audit=True flag
is_super_admin(user)     — True if role == "super_admin" (user management gate)
```

## Pages and navigation

| Page | Key | Access |
|---|---|---|
| Statistics (`render_statistics_page`) | `DEFAULT_PAGE = "Estatísticas"` | Public (no auth required) |
| Chat IA (`_render_chat_page`) | `CHAT_PAGE = "Chat IA"` | Authenticated + email verified (if `EMAIL_VERIFICATION_REQUIRED=true`) |
| Audit/Admin (`render_admin_page`) | `ADMIN_PAGE = "Auditoria"` | `can_view_audit_log()` = True |

Navigation state lives in `st.session_state.current_page`. Query param `?page=<slug>` also accepted.

## Session payload (stored in `st.session_state["auth_user"]`)

```python
{
  "id": int,
  "nome": str,
  "email": str,
  "role": str,           # "user" | "admin" | "super_admin"
  "can_view_audit": bool
}
```

`login_session()`, `logout_session()`, `get_authenticated_user()` in `src/auth/session.py`.
`can_access_chat(session_state)` = `get_authenticated_user() is not None`.

## Directory map

```
app_ai_chat.py            Entry point: routing, auth gates, chat rendering, response sanitization
src/ui/
  styles.py               GLOBAL_LIGHT_THEME_CSS + AUDIT_PAGE_CSS (centralized style helper)
  admin_page.py           Audit log page + user management (super_admin only) + observability
  sidebar.py              Sidebar nav shell (HTML injection + Streamlit click-target buttons)
  header.py               Top bar: session info + profile popover + logout
  auth_modal.py           Login/register/reset/profile modal panels
  statistics_page.py      Public stats page: hero card + Power BI embedded link
  protected_chat.py       Auth/email-verification gates for chat page
  notifications.py        Toast queue helpers
src/auth/                 user_service (engine, CRUD, soft_delete, set_role, set_audit_access),
                          session, roles, security (argon2), google_oauth_service,
                          email_* services, validation
src/audit/audit_log_service.py
                          AuditEntry dataclass, EVENT_* constants, VALID_EVENTS,
                          SUCCESS_/FAILURE_/BLOCKED_/INFO_EVENTS sets,
                          ensure_schema (auto-migrates), log_event, get_recent_logs,
                          get_logs_by_user, log_audit_event_safely
src/ai/                   Isolated AI layer (see below)
src/chat/chat_history_service.py
                          ChatSession, ChatMessage dataclasses; get_or_create_active_chat_session,
                          add_chat_message (persists to auth DB)
src/diagnostics/health_service.py
                          run_heartbeat, run_unified_report, check_application_database,
                          check_analytical_database — no secret leakage
src/analytics/umami.py   configure_umami, track_event, track_event_once, track_page_view
src/observability/        OpenTelemetry telemetry (OTEL_ENABLED=true to activate)
tests/                    unittest-based; UI tests use _FakeStreamlit stub (test_admin_page_ui.py)
```

## AI query engine — request flow (`src/ai/datasus_ai.py: perguntar_datasus`)

```
prompt
  -> prompt_guard / classify_prompt()        # allow/deny by keyword lists
  -> month_checker.validar_mes_solicitado_no_prompt()
  -> data_provider.load_controlled_datasus_dataframe()  # SELECT allowlisted cols from vw_data_sus_ia
  -> simple_stats_runner.executar_pergunta_simples()    # pure-pandas dispatcher (no LLM)
  -> [sentinel returned] pandasai_runner.executar_pergunta_com_pandasai()  # LLM fallback
```

`AI_ALLOWED_COLUMNS` / `AI_ALLOWED_TABLES` (`src/ai/config.py`) are the allowlist.
`AI_MAX_MONTHS=3`, `AI_MAX_ROWS=5_000_000`.
`app_ai_chat.py: _friendly_response()` sanitizes all rendered AI text (replaces tracebacks/secrets).

## User management (super_admin only, `src/auth/user_service.py`)

Key methods on `UserService`:
- `get_all_users()` → list of `UserProfile` (id, nome, email, role, criado_em, can_view_audit)
- `set_role(user_id, new_role, acting_admin_id, acting_admin_email)` → audit logged
- `set_audit_access(user_id, bool, acting_admin_id, acting_admin_email)` → audit logged
- `soft_delete_user(user_id)` → sets `ativo=False`, NEVER runs DELETE
- `authenticate(email, password)` → returns UserProfile or raises AuthValidationError

## Audit log columns (`audit_log` table)

```
id, evento, user_id, user_email, prompt_text, detalhe,
status (success|failure|blocked|info), source, action, criado_em
```

`AuditLogService.log_event(evento, user_id, user_email, prompt_text, detalhe, status, source, action)`
All text sanitized before persistence: strips passwords, tokens, connection strings.

## Audit page — filter/display logic (`src/ui/admin_page.py`)

- Event categories: Login, Conta, Prompt bloqueado, Administracao, Outros
- Status vocabulary: success | failure | blocked | info (colors green/red/orange/blue)
- Filters: limit (20/50/100), event_type, status, user_search (email), start_date, end_date
- `_filter_audit_entries()` applies all filters client-side (entries already fetched)
- `_render_audit_table()` renders `st.dataframe` + selectbox to pick event for detail dialog
- `_render_user_management()` visible only to super_admin

## Observability and health

- `?healthcheck=1` query param → runs `HealthService.run_heartbeat()` → returns JSON for Uptime Kuma
- Admin page expander "Saude e observabilidade" → `_render_observability_diagnostics()`
- `src/observability/telemetry.py` → OpenTelemetry spans (no-op if `OTEL_ENABLED` not set)
- `src/analytics/umami.py` → Umami web analytics (no-op if not configured)

## Auth services

- `GoogleOAuthService` — OAuth2 PKCE flow (env `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
- `EmailVerificationService` — token-based verification (env `EMAIL_VERIFICATION_REQUIRED`)
- `PasswordResetService` — token-based reset (SMTP via `email_service.py`)
- `EmailChangeService` — code-based email change (SMTP)
- `AccountReactivationService` — soft-deleted user reactivation via email code
- `PendingRegistrationService` — pending user registration with email confirmation

## Sanitization conventions

All modules: `_sanitize_text()` strips `password=`/`token=`/connection strings/tracebacks
before logging or displaying. `_sanitize_audit_text()` in `admin_page.py` also truncates to 90 chars.
Status vocabulary is fixed: `success | failure | blocked | info`.

## Tests

unittest-based, one module per source file. UI tests fake `st` via `_FakeStreamlit`
(see `tests/test_admin_page_ui.py`). `ENVIRONMENT=test` short-circuits all `_load_env_files()`.

## ETL pipeline (`main.py`)

Independent runtime. Uses `pysus.SIA`, `src/extract.py`, `src/transform.py`, `src/load.py`.
Connects to analytical Neon DB. Not part of the web app request path.
