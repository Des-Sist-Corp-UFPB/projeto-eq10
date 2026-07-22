# Database routing and ownership

The project intentionally uses two PostgreSQL databases:

| Variable group | Purpose | Access |
| --- | --- | --- |
| `AUTH_DATABASE_URL` or complete `AUTH_DB_HOST`, `AUTH_DB_PORT`, `AUTH_DB_NAME`, `AUTH_DB_USER`, `AUTH_DB_PASSWORD` | Writable application database for `usuarios`, audit logs, `pending_registrations`, password reset tokens, e-mail verification/change tokens, account reactivation tokens, `chat_sessions`, `chat_messages`, and other app-owned tables | Read/write; schema initialization is allowed for application tables |
| `AI_DATABASE_URL` or complete `AI_DB_HOST`, `AI_DB_PORT`, `AI_DB_NAME`, `AI_DB_USER`, `AI_DB_PASSWORD` | Read-only DATASUS analytical database for `vw_data_sus_ia`, `data_sus`, and `dim_*` tables | Read-only; the application must only run analytical `SELECT` queries |

Having two databases is intentional and is not a conflict. The risk is ambiguous routing, for example when application writes silently use the DATASUS/Neon database or when analytical queries use the application database.

## Application database

Preferred configuration:

```env
AUTH_DB_HOST=auth-db.example.com
AUTH_DB_PORT=5432
AUTH_DB_NAME=app_db
AUTH_DB_USER=app_user
AUTH_DB_PASSWORD=replace-with-secret
AUTH_DB_SSLMODE=require
```

Alternative single URL:

```env
AUTH_DATABASE_URL=postgresql+psycopg2://app_user:replace-with-secret@auth-db.example.com:5432/app_db?sslmode=require
```

Production must use `AUTH_DATABASE_URL` or the complete `AUTH_DB_*` group. In production, the application does not fall back to `DATABASE_URL`, lowercase legacy variables, `AI_DB_*`, or local SQLite for auth/application writes.

## DATASUS analytical database

Preferred configuration:

```env
AI_DB_HOST=analytics-db.example.com
AI_DB_PORT=5432
AI_DB_NAME=analytics
AI_DB_USER=ia_readonly
AI_DB_PASSWORD=replace-with-secret
AI_DB_SSLMODE=require
```

Alternative single URL:

```env
AI_DATABASE_URL=postgresql+psycopg2://ia_readonly:replace-with-secret@analytics-db.example.com:5432/analytics?sslmode=require
```

The AI/DATASUS engine sets PostgreSQL sessions to read-only and is used by `src.ai.read_only_datasus`, `src.ai.data_provider`, `src.ai.month_checker`, and the MCP analytical tools. Application schema initialization, auth writes, audit writes, token writes, and chat history writes must not use this engine.

## Local compatibility

For development and tests only, the auth layer can still use legacy `DATABASE_URL`, lowercase `user/password/host/database`, or local SQLite fallback. These fallbacks log only the selected source name and are disabled when `ENVIRONMENT=production`, `APP_ENV=production`, `ENV=production`, or `DEPLOY_ENV=production`.

The lowercase `user/password/host/database` variables remain for the legacy ETL path in `src/load.py`; they are not production application/auth configuration.
