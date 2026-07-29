# claude.md — System Map (token-efficient reference)

Monolithic Streamlit app (originated as a Municipal Secretariat of Mamanguape internship
project, now adapted to DSC/UFPB course standards). Two independent runtimes share one repo:

1. **ETL pipeline** (`main.py`, `Dockerfile`) — extracts DATASUS/SIA data via `pysus`, transforms,
   loads into the analytical Postgres (Neon). Runs standalone, not part of the web app request path.
2. **Streamlit chat/audit app** (`app_ai_chat.py`, `Dockerfile.chat`) — auth, chat UI, statistics
   page, admin/audit page. This is the production web app referenced in Parts A/B below.

## Two databases — routing is the load-bearing fact of this system

| Concern | Engine getter | Env vars | Host |
|---|---|---|---|
| Auth/app data (users, sessions, chat history, **audit_log**) | `src/auth/user_service.py: get_auth_engine()` | `AUTH_DB_*` / `DATABASE_URL`-style (see `user_service.py`) | Professor PostgreSQL |
| DATASUS analytics (AI layer, `vw_data_sus_ia` view) | `src/ai/read_only_datasus.py: get_readonly_engine()` | `AI_DATABASE_URL` or `AI_DB_USER/PASSWORD/HOST/PORT/NAME` (+`AI_DB_SSLMODE`, default `require`) | Neon (read-only) |

Never merge these. `AuditLogService.from_environment()` reuses the **auth** engine
(`get_auth_engine()`), not the analytics one — audit data lives with app/auth data by design.
`src/diagnostics/health_service.py` pings both engines separately (`check_application_database`,
`check_datasus_view`, `run_heartbeat`) and never logs credentials (see `_redact_text`,
`SENSITIVE_KEY_RE`).

## Directory map

```
app_ai_chat.py            Entry point: routing, auth gates, chat rendering, response sanitization
src/ui/
  styles.py                GLOBAL_LIGHT_THEME_CSS + AUDIT_PAGE_CSS (centralized style helper)
  admin_page.py             Audit page: filters, table, event-detail dialog (render_admin_page)
  sidebar.py, header.py     Nav shell, auth header
  auth_modal.py             Login/register/reset modal
  statistics_page.py        Public statistics dashboard
  protected_chat.py         Auth/email-verification gates for chat page
  notifications.py          Toast queue helpers
src/auth/                  user_service (auth engine + CRUD), session, roles, security,
                            google_oauth_service, email_* services, validation
src/audit/audit_log_service.py   AuditEntry, EVENT_* constants, ensure_schema (auto-migrates
                            audit_log table), log_event, get_recent_logs — status inferred
                            into success/failure/blocked/info (see SUCCESS_/FAILURE_/BLOCKED_/
                            INFO_EVENTS sets)
src/ai/                     Isolated AI layer (see "AI query engine" below)
src/diagnostics/health_service.py   Safe health checks, no secret leakage, used by
                            `?healthcheck=1` query param (Uptime Kuma) and admin diagnostics
src/chat/chat_history_service.py    Persists chat sessions/messages (auth DB)
tests/                      unittest-style; one file per service/module; UI tests use a
                            `_FakeStreamlit` stub (see test_admin_page_ui.py) rather than real Streamlit
```

## AI query engine — request flow (`src/ai/datasus_ai.py: perguntar_datasus`)

```
prompt
  -> prompt_guard.validar_prompt()          # allow/deny by keyword lists (DANGEROUS_TERMS blocks
  |                                          # write/schema/secret intents; STATISTICAL_TERMS must
  |                                          # match at least one, else blocked). Blocks logged as
  |                                          # EVENT_PROMPT_GUARD_BLOCK.
  -> month_checker.validar_mes_solicitado_no_prompt()   # only checks IF prompt names an explicit
  |                                          # PT month+4-digit-year; queries analytics DB to see if
  |                                          # that month has data. No date mentioned => always passes.
  -> data_provider.load_controlled_datasus_dataframe()  # SELECT allowlisted columns from
  |                                          # vw_data_sus_ia, last AI_MAX_MONTHS (3) months only,
  |                                          # LIMIT AI_MAX_ROWS. Any exception here (incl. DB auth
  |                                          # config errors) is caught by a bare `except Exception`
  |                                          # in perguntar_datasus and converted to
  |                                          # GENERIC_AI_ERROR_MESSAGE — this is a single point of
  |                                          # failure for ALL prompts, not prompt-specific.
  -> simple_stats_runner.executar_pergunta_estatistica_simples()   # pure-pandas keyword-pattern
  |                                          # dispatcher (no LLM, no cost). Returns
  |                                          # SIMPLE_STATS_UNAVAILABLE_MESSAGE sentinel when no
  |                                          # pattern matches -> caller falls through to LLM.
  -> [only if simple mode returned the sentinel] pandasai_runner.executar_pergunta_com_pandasai()
                                             # PandasAI + LiteLLM over the *same* already-filtered
                                             # DataFrame (never raw SQL from the model). Raises
                                             # LLMRateLimitError (recoverable, triggers simple-mode
                                             # fallback notice) or RuntimeError (config/import errors,
                                             # returned verbatim as the chat message).
```

`AI_ALLOWED_COLUMNS` / `AI_ALLOWED_TABLES` (`src/ai/config.py`) are the single allowlist — the
data provider raises if `AI_DATA_SOURCE` (`vw_data_sus_ia`) isn't in `AI_ALLOWED_TABLES`, and only
allowlisted columns are ever selected. `AI_MAX_MONTHS=3`, `AI_MAX_ROWS=5_000_000`.

`app_ai_chat.py: _friendly_response()` is a second safety net on the **rendered** text: it replaces
any response containing traceback/connection-string/secret-like substrings with
`GENERIC_ERROR_MESSAGE`, and maps a few known backend sentinel substrings (e.g. "não foi possível
processar a pergunta") to friendlier messages. Because the data-provider exception path always
returns the literal string containing "não foi possível processar a pergunta", **any** analytics-DB
hiccup for **any** prompt surfaces as the same generic refusal shown to users — this is why
valid/invalid prompts look the same when they fail.

`simple_stats_runner.py` dispatch is **ordered keyword matching** on a normalized (accent-stripped,
lowercased) prompt — not a general grouper. It currently only recognizes: total/soma of a single
numeric column, ranking/top-N by one dimension + one metric, mean of `idade` (ungrouped only),
frequency-by-sexo, count of distinct `procedimento`, count of rows, latest available date. It has
**no branch for a plain COUNT grouped by a dimension** (e.g. "total de atendimentos por sexo") and
`_media_idade` ignores any "por <dimensão>" suffix in the prompt. Any prompt matching none of the
branches returns `SIMPLE_STATS_UNAVAILABLE_MESSAGE` and falls through to the LLM path.

`EXAMPLE_PROMPTS` (`app_ai_chat.py`) is the literal suggestion list rendered as buttons — every
entry must have a matching `simple_stats_runner` branch (or working LLM) or the UI teaches users a
question the backend can't answer.

## Audit page styling — where light theme lives

- `.streamlit/config.toml` — `base="light"` + explicit palette (source of truth for Streamlit's own
  theme; without it Streamlit falls back to a theme that can render native widgets dark regardless
  of custom CSS, since native controls like selects/dataframes/dialogs are BaseWeb components
  themed by Streamlit's internal CSS variables, not by page CSS).
- `src/ui/styles.py` — `apply_global_light_styles()` (page background, called once) and
  `apply_audit_light_styles()` / `AUDIT_PAGE_CSS` (scoped to `.st-key-audit-page-shell`: metrics,
  expander, selectbox/text/date inputs, dataframe grid + header, buttons, `stDialog`).
- `src/ui/admin_page.py: render_admin_page()` wraps everything in
  `st.container(key="audit-page-shell")` so the scoped CSS above applies. The event-detail modal
  (`_render_selected_audit_event_dialog`) uses `st.dialog` + native `st.caption`/`st.write`/
  `st.button` only — **no raw HTML** is rendered inside it.
- **`Dockerfile.chat` does not `COPY .streamlit`** into the image — this is the actual root cause of
  dark native widgets in production (page background looks light via forced CSS, but Streamlit's
  own theme, absent config.toml, does not).

## Conventions worth knowing

- All AI/audit-adjacent modules sanitize before logging or displaying: strip `password=`/`token=`/
  connection strings/tracebacks (see `_sanitize_text` in both `admin_page.py` and
  `audit_log_service.py`, and `_redact_text` in `health_service.py`). Follow the same pattern for
  any new user-facing or logged string.
- Status vocabulary is fixed: `success | failure | blocked | info`, colors green/red/yellow-orange/
  blue respectively (`STATUS_BADGE_STYLES` in `admin_page.py`).
- Tests are unittest-based, one module per source file, and UI tests fake `st` rather than run a
  real Streamlit server (`_FakeStreamlit` in `tests/test_admin_page_ui.py`).
- `ENVIRONMENT=test` short-circuits all `_load_env_files()` dotenv loading across `src/ai/*` — tests
  rely on `patch.dict(os.environ, ..., clear=True)` instead.
