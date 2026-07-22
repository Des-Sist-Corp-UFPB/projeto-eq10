"""Servico de usuarios com persistencia na tabela usuarios."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)

from src.auth.security import MIN_PASSWORD_LENGTH, hash_password, verify_password
from src.auth.validation import EMAIL_RE

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_AUTH_SQLITE_PATH = BASE_DIR / "data" / "auth.sqlite3"

AUTH_CONFIG_ERROR_MESSAGE = (
    "Configuracao incompleta da autenticacao: informe AUTH_DATABASE_URL, "
    "ou AUTH_DB_HOST, AUTH_DB_PORT, AUTH_DB_NAME, AUTH_DB_USER e AUTH_DB_PASSWORD."
)

logger = logging.getLogger(__name__)
T = TypeVar("T")

AUTH_DB_POOL_RECYCLE_SECONDS = 1800
AUTH_DB_POOL_TIMEOUT_SECONDS = 10
AUTH_DB_RETRY_ATTEMPTS = 3
AUTH_DB_RETRY_BASE_DELAY_SECONDS = 0.2
PRODUCTION_ENVIRONMENT_VALUES = {"prod", "production"}
AUTH_DB_REQUIRED_ENV_VARS = (
    "AUTH_DB_HOST",
    "AUTH_DB_PORT",
    "AUTH_DB_NAME",
    "AUTH_DB_USER",
    "AUTH_DB_PASSWORD",
)

TRANSIENT_DB_ERROR_MARKERS = (
    "connection reset",
    "connection refused",
    "connection timed out",
    "could not connect",
    "server closed the connection",
    "terminating connection",
    "connection already closed",
    "closed connection",
    "ssl syscall error",
    "ssl connection has been closed",
    "broken pipe",
    "network is unreachable",
    "timeout expired",
    "timeout",
)

NON_TRANSIENT_DB_ERROR_MARKERS = (
    "does not exist",
    "no such table",
    "syntax error",
    "permission denied",
    "insufficient privilege",
    "duplicate key",
    "unique constraint",
    "foreign key constraint",
)


class AuthValidationError(ValueError):
    """Erro seguro para exibicao na interface."""

    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


@dataclass(frozen=True)
class UserProfile:
    id: int
    nome: str
    email: str
    role: str
    criado_em: Any = None
    atualizado_em: Any = None
    ultimo_login_em: Any = None
    can_view_audit: bool = False


GOOGLE_EMAIL_NOT_VERIFIED_MESSAGE = "Nao foi possivel confirmar o e-mail da conta Google."
GOOGLE_ACCOUNT_UNAVAILABLE_MESSAGE = (
    "Nao foi possivel entrar com Google para esta conta. Use a recuperacao da conta."
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_env_files() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() == "test":
        return

    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return

    load_dotenv(BASE_DIR / ".env")
    load_dotenv(BASE_DIR / "config" / ".env")


def _current_environment() -> str:
    for name in ("ENVIRONMENT", "APP_ENV", "ENV", "DEPLOY_ENV"):
        value = os.getenv(name)
        if value and value.strip():
            return value.strip().lower()
    return ""


def is_production_environment() -> bool:
    return _current_environment() in PRODUCTION_ENVIRONMENT_VALUES


def _auth_db_env_values() -> dict[str, str | None]:
    return {
        "AUTH_DB_HOST": os.getenv("AUTH_DB_HOST"),
        "AUTH_DB_PORT": os.getenv("AUTH_DB_PORT"),
        "AUTH_DB_NAME": os.getenv("AUTH_DB_NAME") or os.getenv("AUTH_DB_DATABASE"),
        "AUTH_DB_USER": os.getenv("AUTH_DB_USER"),
        "AUTH_DB_PASSWORD": os.getenv("AUTH_DB_PASSWORD"),
    }


def _missing_auth_db_env_vars() -> list[str]:
    values = _auth_db_env_values()
    return [name for name in AUTH_DB_REQUIRED_ENV_VARS if not values.get(name)]


def _has_any_auth_db_env_var() -> bool:
    names = (*AUTH_DB_REQUIRED_ENV_VARS, "AUTH_DB_DATABASE", "AUTH_DB_SSLMODE")
    return any(bool(os.getenv(name)) for name in names)


def _log_legacy_auth_fallback(source: str) -> None:
    logger.warning(
        "Auth database using legacy fallback outside production | source=%s | environment=%s",
        source,
        _current_environment() or "unset",
    )


def _build_database_url(prefix: str, *, require_port: bool = True) -> str | None:
    user = os.getenv(f"{prefix}_USER")
    password = os.getenv(f"{prefix}_PASSWORD")
    host = os.getenv(f"{prefix}_HOST")
    database = os.getenv(f"{prefix}_NAME") or os.getenv(f"{prefix}_DATABASE")
    port = os.getenv(f"{prefix}_PORT")

    required_values = [user, password, host, database]
    if require_port:
        required_values.append(port)
    if not all(required_values):
        return None

    netloc = f"{host}:{port}" if port else str(host)
    safe_password = quote_plus(password or "")
    return (
        f"postgresql+psycopg2://{user}:{safe_password}@{netloc}/{database}"
        f"{_postgres_query_suffix(str(host), prefix)}"
    )


def _build_lowercase_database_url() -> str | None:
    user = os.getenv("user")
    password = os.getenv("password")
    host = os.getenv("host")
    database = os.getenv("database")
    port = os.getenv("port")

    if not all([user, password, host, database]):
        return None

    netloc = f"{host}:{port}" if port else str(host)
    safe_password = quote_plus(password or "")
    return (
        f"postgresql+psycopg2://{user}:{safe_password}@{netloc}/{database}"
        f"{_postgres_query_suffix(str(host), 'DB')}"
    )


def _is_local_host(host: str) -> bool:
    return host.strip().lower() in {"localhost", "127.0.0.1", "::1", "db", "postgres"}


def _postgres_query_suffix(host: str, prefix: str) -> str:
    sslmode = (
        os.getenv(f"{prefix}_SSLMODE")
        or os.getenv("AUTH_DB_SSLMODE")
        or os.getenv("DB_SSLMODE")
        or ("disable" if _is_local_host(host) else "require")
    )
    params = [f"sslmode={sslmode}"]
    if sslmode == "require" and not _is_local_host(host):
        params.append("channel_binding=require")
    return "?" + "&".join(params)


def _build_sqlite_database_url() -> str:
    configured_path = os.getenv("AUTH_SQLITE_PATH")
    sqlite_path = Path(configured_path).expanduser() if configured_path else DEFAULT_AUTH_SQLITE_PATH
    if not sqlite_path.is_absolute():
        sqlite_path = BASE_DIR / sqlite_path

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{sqlite_path.as_posix()}"


def _get_auth_database_url() -> tuple[str, str]:
    if os.getenv("AUTH_DATABASE_URL"):
        return os.environ["AUTH_DATABASE_URL"], "AUTH_DATABASE_URL"

    auth_db_url = _build_database_url("AUTH_DB", require_port=True)
    if auth_db_url:
        return auth_db_url, "AUTH_DB_*"

    if is_production_environment():
        if _has_any_auth_db_env_var():
            logger.error(
                "Auth database configuration incomplete in production | missing=%s",
                ",".join(_missing_auth_db_env_vars()),
            )
        else:
            logger.error("Auth database configuration missing in production")
        raise RuntimeError(AUTH_CONFIG_ERROR_MESSAGE)

    if _has_any_auth_db_env_var():
        logger.warning(
            "Incomplete AUTH_DB_* ignored outside production | missing=%s",
            ",".join(_missing_auth_db_env_vars()),
        )

    if os.getenv("DATABASE_URL"):
        _log_legacy_auth_fallback("DATABASE_URL")
        return os.environ["DATABASE_URL"], "DATABASE_URL"

    legacy_db_url = _build_lowercase_database_url()
    if legacy_db_url:
        _log_legacy_auth_fallback("lowercase database env")
        return legacy_db_url, "lowercase database env"

    logger.warning(
        "Auth database env not configured outside production; using local SQLite auth store. "
        "AI_DB_* is readonly and is not used for authentication writes."
    )
    return _build_sqlite_database_url(), "local SQLite"


def get_auth_database_config_source() -> str:
    """Return only the selected auth database source name, never credentials."""
    _load_env_files()
    _, source = _get_auth_database_url()
    return source


def get_auth_engine():
    """Cria engine para persistencia de autenticacao."""
    _load_env_files()

    database_url, source = _get_auth_database_url()

    if not database_url:
        raise RuntimeError(AUTH_CONFIG_ERROR_MESSAGE)

    from sqlalchemy import create_engine

    logger.info("Auth database source selected | source=%s", source)
    return create_engine(database_url, **_auth_engine_options(database_url))


def get_application_engine():
    """Alias for application-owned writable data (auth, audit, tokens, chat)."""
    return get_auth_engine()


def _auth_engine_options(database_url: str) -> dict[str, Any]:
    """Pool options safe for auth/audit engines without breaking SQLite tests."""
    options: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_recycle": AUTH_DB_POOL_RECYCLE_SECONDS,
    }
    if not database_url.strip().lower().startswith("sqlite"):
        options["pool_timeout"] = AUTH_DB_POOL_TIMEOUT_SECONDS
    return options


def normalize_email(email: str) -> str:
    """Regra unica de normalizacao de e-mail para autenticacao."""
    return (email or "").strip().casefold()


def _normalize_email(email: str) -> str:
    return normalize_email(email)


def _validate_name(nome: str) -> str:
    clean_name = (nome or "").strip()
    if not clean_name:
        raise AuthValidationError("Informe seu nome.")

    return clean_name


def _validate_email(email: str) -> str:
    clean_email = _normalize_email(email)
    if not clean_email:
        raise AuthValidationError("Informe seu e-mail.")
    if not EMAIL_RE.match(clean_email):
        raise AuthValidationError("Informe um e-mail válido.")

    return clean_email


def _validate_new_password(password: str, confirmation: str | None = None) -> str:
    if not password:
        raise AuthValidationError("Informe uma senha.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthValidationError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if confirmation is not None and not confirmation:
        raise AuthValidationError("Confirme sua senha.")
    if confirmation is not None and password != confirmation:
        raise AuthValidationError("As senhas não coincidem.")

    return password


def _row_to_user(row: Any) -> UserProfile:
    return UserProfile(
        id=int(row["id"]),
        nome=row["nome"],
        email=row["email"],
        role=row["role"],
        criado_em=row["criado_em"],
        atualizado_em=row["atualizado_em"],
        ultimo_login_em=row["ultimo_login_em"],
        can_view_audit=bool(row["can_view_audit"]) if "can_view_audit" in row.keys() else False,
    )


def _get_usuario_columns(conn: Any) -> set[str]:
    if conn.dialect.name == "sqlite":
        return {
            row["name"]
            for row in conn.execute(text("PRAGMA table_info(usuarios)")).mappings()
        }

    return {
        row["column_name"]
        for row in conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'usuarios'
                  AND table_schema = current_schema()
                """
            )
        ).mappings()
    }


def _usuarios_create_table_sql(dialect: str) -> str:
    id_column = "id SERIAL PRIMARY KEY"
    if dialect == "sqlite":
        id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

    return f"""
        CREATE TABLE IF NOT EXISTS usuarios (
            {id_column},
            nome TEXT NOT NULL,
            email TEXT NOT NULL,
            senha_hash TEXT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            criado_em TIMESTAMP NOT NULL,
            atualizado_em TIMESTAMP NOT NULL,
            ultimo_login_em TIMESTAMP NULL,
            email_verificado BOOLEAN NOT NULL DEFAULT false,
            email_verificado_em TIMESTAMP NULL,
            deleted_at TIMESTAMP NULL,
            deletado BOOLEAN NOT NULL DEFAULT false,
            deletado_em TIMESTAMP NULL,
            google_sub TEXT NULL,
            google_picture TEXT NULL,
            auth_provider TEXT NOT NULL DEFAULT 'password',
            can_view_audit BOOLEAN NOT NULL DEFAULT false
        )
    """


def _drop_password_hash_not_null_if_needed(conn: Any) -> None:
    if conn.dialect.name == "postgresql":
        conn.execute(text("ALTER TABLE usuarios ALTER COLUMN senha_hash DROP NOT NULL"))
        return

    if conn.dialect.name != "sqlite":
        return

    table_info = list(conn.execute(text("PRAGMA table_info(usuarios)")).mappings())
    senha_hash_info = next((row for row in table_info if row["name"] == "senha_hash"), None)
    if not senha_hash_info or not bool(senha_hash_info["notnull"]):
        return

    old_columns = {str(row["name"]) for row in table_info}
    backup_table = "usuarios_password_not_null_backup"
    target_columns = [
        "id",
        "nome",
        "email",
        "senha_hash",
        "role",
        "criado_em",
        "atualizado_em",
        "ultimo_login_em",
        "email_verificado",
        "email_verificado_em",
        "deleted_at",
        "deletado",
        "deletado_em",
        "google_sub",
        "google_picture",
        "auth_provider",
        "can_view_audit",
    ]
    defaults = {
        "role": "'user'",
        "criado_em": "CURRENT_TIMESTAMP",
        "atualizado_em": "CURRENT_TIMESTAMP",
        "ultimo_login_em": "NULL",
        "email_verificado": "false",
        "email_verificado_em": "NULL",
        "deleted_at": "NULL",
        "deletado": "false",
        "deletado_em": "NULL",
        "google_sub": "NULL",
        "google_picture": "NULL",
        "auth_provider": "'password'",
        "can_view_audit": "false",
    }
    select_expressions = [
        column if column in old_columns else defaults.get(column, "NULL")
        for column in target_columns
    ]

    conn.execute(text(f"DROP TABLE IF EXISTS {backup_table}"))
    conn.execute(text(f"ALTER TABLE usuarios RENAME TO {backup_table}"))
    conn.execute(text(_usuarios_create_table_sql("sqlite")))
    conn.execute(
        text(
            f"""
            INSERT INTO usuarios ({", ".join(target_columns)})
            SELECT {", ".join(select_expressions)}
            FROM {backup_table}
            """
        )
    )
    conn.execute(text(f"DROP TABLE {backup_table}"))


def _add_usuario_column_if_missing(
    conn: Any,
    columns: set[str],
    column_name: str,
    definition: str,
) -> None:
    if column_name in columns:
        return

    if conn.dialect.name == "postgresql":
        conn.execute(text(f"ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS {column_name} {definition}"))
    else:
        conn.execute(text(f"ALTER TABLE usuarios ADD COLUMN {column_name} {definition}"))

    columns.add(column_name)


def _active_user_condition(columns: set[str]) -> str:
    conditions: list[str] = []
    if "deleted_at" in columns:
        conditions.append("deleted_at IS NULL")
    if "deletado" in columns:
        conditions.append("deletado IS NOT TRUE")
    if "deletado_em" in columns:
        conditions.append("deletado_em IS NULL")

    return " AND ".join(conditions) if conditions else "1 = 1"


def _active_user_sort_expression(columns: set[str]) -> str:
    return f"CASE WHEN {_active_user_condition(columns)} THEN 1 ELSE 0 END"


def _soft_delete_select_columns(columns: set[str]) -> str:
    deleted_at_column = "deleted_at" if "deleted_at" in columns else "NULL AS deleted_at"
    deletado_column = "deletado" if "deletado" in columns else "FALSE AS deletado"
    deletado_em_column = "deletado_em" if "deletado_em" in columns else "NULL AS deletado_em"
    return f"{deleted_at_column}, {deletado_column}, {deletado_em_column}"


def _is_soft_deleted(row: Any) -> bool:
    return row["deleted_at"] is not None or bool(row["deletado"]) or row["deletado_em"] is not None


def _safe_database_error_reason(exc: BaseException) -> str:
    original = getattr(exc, "orig", exc)
    message = str(original).casefold()

    if isinstance(exc, IntegrityError):
        return "duplicate or constraint violation"
    if "permission denied" in message or "insufficient privilege" in message:
        return "database permission denied"
    if "usuarios" in message and ("does not exist" in message or "no such table" in message):
        return "users table does not exist"
    if (
        isinstance(exc, OperationalError)
        or "connection refused" in message
        or "could not connect" in message
        or "could not translate host" in message
        or "timeout" in message
    ):
        return "database connection failed"
    if isinstance(exc, ProgrammingError):
        return "database schema or SQL error"
    if isinstance(exc, DBAPIError):
        return "database operation failed"

    return type(exc).__name__


def is_transient_database_error(exc: BaseException) -> bool:
    """Return True only for retryable connection/pool/network database failures."""
    if not isinstance(exc, SQLAlchemyError):
        return False
    if isinstance(exc, (IntegrityError, ProgrammingError)):
        return False

    original = getattr(exc, "orig", exc)
    message = str(original).casefold()
    if any(marker in message for marker in NON_TRANSIENT_DB_ERROR_MARKERS):
        return False

    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    if isinstance(exc, OperationalError):
        return any(marker in message for marker in TRANSIENT_DB_ERROR_MARKERS) or not message

    return any(marker in message for marker in TRANSIENT_DB_ERROR_MARKERS)


def run_transient_db_operation(
    action: str,
    operation: Callable[[], T],
    *,
    attempts: int = AUTH_DB_RETRY_ATTEMPTS,
    base_delay_seconds: float = AUTH_DB_RETRY_BASE_DELAY_SECONDS,
    sleep_func: Callable[[float], None] = time.sleep,
) -> T:
    """Run a DB operation with short retry only for transient connection errors."""
    max_attempts = max(1, int(attempts or 1))
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except SQLAlchemyError as exc:
            if not is_transient_database_error(exc) or attempt >= max_attempts:
                raise
            delay = min(base_delay_seconds * attempt, 1.0)
            logger.warning(
                "Erro transitorio autenticacao | acao=%s | tentativa=%s/%s | causa=%s | tipo=%s",
                action,
                attempt,
                max_attempts,
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            sleep_func(delay)

    raise RuntimeError("unreachable database retry state")


def safe_auth_exception_summary(exc: BaseException) -> str:
    """Resumo tecnico seguro para logs de autenticacao."""
    if isinstance(exc, SQLAlchemyError):
        return _safe_database_error_reason(exc)

    message = str(exc).casefold()
    dependency_names = ("sqlalchemy", "psycopg2", "pymysql", "passlib", "bcrypt")
    if isinstance(exc, ModuleNotFoundError) or (
        isinstance(exc, ImportError)
        and any(name in message for name in dependency_names)
    ):
        return "auth dependency missing"

    return type(exc).__name__


def _log_database_error(action: str, exc: BaseException) -> None:
    logger.warning(
        "Erro seguro autenticacao | acao=%s | causa=%s | tipo=%s",
        action,
        safe_auth_exception_summary(exc),
        type(exc).__name__,
    )


def _is_duplicate_index_creation_error(exc: BaseException) -> bool:
    reason = safe_auth_exception_summary(exc)
    message = str(getattr(exc, "orig", exc)).casefold()
    return (
        isinstance(exc, IntegrityError)
        or reason == "duplicate or constraint violation"
        or "could not create unique index" in message
        or "unique constraint" in message
        or "duplicate key" in message
    )


def _create_unique_index_safely(conn: Any, sql: str, index_name: str) -> None:
    """Cria indice unico sem derrubar auth quando ha duplicatas antigas."""
    if conn.dialect.name == "postgresql":
        transaction = conn.begin_nested()
        try:
            conn.execute(text(sql))
        except SQLAlchemyError as exc:
            transaction.rollback()
            if _is_duplicate_index_creation_error(exc):
                logger.warning(
                    "Aviso seguro autenticacao | acao=ensure_schema_index | index=%s | causa=%s | tipo=%s",
                    index_name,
                    safe_auth_exception_summary(exc),
                    type(exc).__name__,
                )
                return
            raise
        else:
            transaction.commit()
            return

    try:
        conn.execute(text(sql))
    except SQLAlchemyError as exc:
        if _is_duplicate_index_creation_error(exc):
            logger.warning(
                "Aviso seguro autenticacao | acao=ensure_schema_index | index=%s | causa=%s | tipo=%s",
                index_name,
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            return
        raise


class UserService:
    """Casos de uso de cadastro, login e perfil."""

    def __init__(self, engine, initialize_schema: bool = True):
        self.engine = engine
        if initialize_schema:
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "UserService":
        return cls(get_auth_engine())

    def ensure_schema(self) -> None:
        dialect = self.engine.dialect.name
        create_table_sql = _usuarios_create_table_sql(dialect)

        def operation() -> None:
            with self.engine.begin() as conn:
                conn.execute(text(create_table_sql))
                _drop_password_hash_not_null_if_needed(conn)

                columns = _get_usuario_columns(conn)
                _add_usuario_column_if_missing(conn, columns, "email_verificado", "BOOLEAN NOT NULL DEFAULT false")
                _add_usuario_column_if_missing(conn, columns, "email_verificado_em", "TIMESTAMP NULL")
                _add_usuario_column_if_missing(conn, columns, "deleted_at", "TIMESTAMP NULL")
                _add_usuario_column_if_missing(conn, columns, "deletado", "BOOLEAN NOT NULL DEFAULT false")
                _add_usuario_column_if_missing(conn, columns, "deletado_em", "TIMESTAMP NULL")
                _add_usuario_column_if_missing(conn, columns, "google_sub", "TEXT NULL")
                _add_usuario_column_if_missing(conn, columns, "google_picture", "TEXT NULL")
                _add_usuario_column_if_missing(conn, columns, "auth_provider", "TEXT NOT NULL DEFAULT 'password'")
                _add_usuario_column_if_missing(conn, columns, "can_view_audit", "BOOLEAN NOT NULL DEFAULT false")

                conn.execute(text("UPDATE usuarios SET email_verificado = false WHERE email_verificado IS NULL"))
                conn.execute(text("UPDATE usuarios SET deletado = false WHERE deletado IS NULL"))
                conn.execute(text("UPDATE usuarios SET auth_provider = 'password' WHERE auth_provider IS NULL"))
                conn.execute(text("UPDATE usuarios SET can_view_audit = false WHERE can_view_audit IS NULL"))

                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                create_index_sql = f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_email_ativo
                    ON usuarios (lower(email))
                    WHERE {active_condition}
                """
                _create_unique_index_safely(conn, create_index_sql, "ux_usuarios_email_ativo")

                _create_unique_index_safely(
                    conn,
                    """
                        CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_google_sub
                        ON usuarios (google_sub)
                        WHERE google_sub IS NOT NULL
                    """,
                    "ux_usuarios_google_sub",
                )

        try:
            run_transient_db_operation("ensure_schema", operation)
        except SQLAlchemyError as exc:
            _log_database_error("ensure_schema", exc)
            raise

    def active_email_exists(self, email: str) -> bool:
        clean_email = _validate_email(email)

        def operation() -> bool:
            with self.engine.connect() as conn:
                active_condition = _active_user_condition(_get_usuario_columns(conn))
                row = conn.execute(
                    text(
                        f"""
                        SELECT id
                        FROM usuarios
                        WHERE lower(email) = :email
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"email": clean_email},
                ).mappings().first()
            return row is not None

        try:
            return run_transient_db_operation("active_email_exists", operation)
        except SQLAlchemyError as exc:
            _log_database_error("active_email_exists", exc)
            raise

    def _log_audit_event(
        self,
        evento: str,
        *,
        user_id: int | None = None,
        user_email: str | None = None,
        detalhe: str | None = None,
        status: str | None = None,
        source: str | None = None,
        action: str | None = None,
    ) -> None:
        try:
            from src.audit.audit_log_service import log_audit_event_safely

            log_audit_event_safely(
                self.engine,
                evento,
                user_id=user_id,
                user_email=user_email,
                detalhe=detalhe,
                status=status,
                source=source,
                action=action,
            )
        except Exception:
            logger.debug("audit_log nao disponivel ainda - ignorado em %s", evento)

    def create_user(
        self,
        nome: str,
        email: str,
        senha: str,
        confirmar_senha: str,
        role: str = "user",
    ) -> UserProfile:
        clean_name = _validate_name(nome)
        clean_email = _validate_email(email)
        clean_password = _validate_new_password(senha, confirmar_senha)
        clean_role = (role or "user").strip() or "user"

        def operation() -> Any:
            with self.engine.begin() as conn:
                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                existing_user = conn.execute(
                    text(
                        f"""
                        SELECT id
                        FROM usuarios
                        WHERE lower(email) = :email
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"email": clean_email},
                ).mappings().first()
                if existing_user:
                    raise AuthValidationError("Já existe uma conta ativa com este e-mail.")

                now = _now()
                conn.execute(
                    text(
                        """
                        INSERT INTO usuarios (
                            nome,
                            email,
                            senha_hash,
                            role,
                            criado_em,
                            atualizado_em
                        )
                        VALUES (
                            :nome,
                            :email,
                            :senha_hash,
                            :role,
                            :criado_em,
                            :atualizado_em
                        )
                        """
                    ),
                    {
                        "nome": clean_name,
                        "email": clean_email,
                        "senha_hash": hash_password(clean_password),
                        "role": clean_role,
                        "criado_em": now,
                        "atualizado_em": now,
                    },
                )
                row = conn.execute(
                    text(
                        f"""
                        SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                               COALESCE(can_view_audit, false) AS can_view_audit
                        FROM usuarios
                        WHERE lower(email) = :email
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"email": clean_email},
                ).mappings().first()
            return row

        try:
            row = run_transient_db_operation("create_user", operation)
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            _log_database_error("create_user", exc)
            raise

        user = _row_to_user(row)

        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_ACCOUNT_CREATED

            AuditLogService(self.engine, initialize_schema=False).log_event(
                EVENT_ACCOUNT_CREATED,
                user_id=user.id,
                user_email=user.email,
                detalhe=f"role={user.role}; provider=password",
                status="success",
                source="auth",
                action="account_created",
            )
        except Exception:
            logger.debug("audit_log nao disponivel ainda — ignorado em create_user")

        return user

    def authenticate(self, email: str, senha: str) -> UserProfile:
        clean_email = _validate_email(email)
        if not senha:
            self._log_audit_event(
                "login_failure",
                user_email=clean_email,
                detalhe="motivo=senha_ausente",
                status="failure",
                source="auth",
                action="login",
            )
            raise AuthValidationError("Informe sua senha.")

        failure_user_id: int | None = None

        def operation() -> Any:
            nonlocal failure_user_id
            with self.engine.begin() as conn:
                columns = _get_usuario_columns(conn)
                soft_delete_columns = _soft_delete_select_columns(columns)
                active_sort_expression = _active_user_sort_expression(columns)
                row = conn.execute(
                    text(
                        f"""
                        SELECT id, nome, email, senha_hash, role, criado_em, atualizado_em,
                               ultimo_login_em, {soft_delete_columns}
                        FROM usuarios
                        WHERE lower(email) = :email
                        ORDER BY {active_sort_expression} DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"email": clean_email},
                ).mappings().first()

                if not row:
                    raise AuthValidationError("E-mail ou senha inválidos.")
                failure_user_id = int(row["id"])
                if _is_soft_deleted(row):
                    raise AuthValidationError("E-mail ou senha inválidos.")
                if not row["senha_hash"]:
                    raise AuthValidationError("E-mail ou senha inválidos.")
                if not verify_password(senha, row["senha_hash"]):
                    raise AuthValidationError("E-mail ou senha inválidos.")

                now = _now()
                conn.execute(
                    text(
                        """
                        UPDATE usuarios
                        SET ultimo_login_em = :ultimo_login_em,
                            atualizado_em = :atualizado_em
                        WHERE id = :id
                        """
                    ),
                    {"id": row["id"], "ultimo_login_em": now, "atualizado_em": now},
                )
                active_row = conn.execute(
                    text(
                        """
                        SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                               COALESCE(can_view_audit, false) AS can_view_audit
                        FROM usuarios
                        WHERE id = :id
                        LIMIT 1
                        """
                    ),
                    {"id": row["id"]},
                ).mappings().first()
            return active_row

        try:
            active_row = run_transient_db_operation("authenticate", operation)
        except AuthValidationError:
            self._log_audit_event(
                "login_failure",
                user_id=failure_user_id,
                user_email=clean_email,
                detalhe="motivo=credenciais_invalidas",
                status="failure",
                source="auth",
                action="login",
            )
            raise
        except SQLAlchemyError as exc:
            self._log_audit_event(
                "database_connection_failure",
                user_email=clean_email,
                detalhe="operacao=login",
                status="failure",
                source="auth",
                action="database",
            )
            _log_database_error("authenticate", exc)
            raise

        user = _row_to_user(active_row)

        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_LOGIN

            AuditLogService(self.engine, initialize_schema=False).log_event(
                EVENT_LOGIN,
                user_id=user.id,
                user_email=user.email,
                detalhe="provider=password",
                status="success",
                source="auth",
                action="login",
            )
        except Exception:
            logger.debug("audit_log nao disponivel ainda — ignorado em authenticate")

        return user

    def authenticate_google_identity(
        self,
        *,
        google_sub: str,
        email: str,
        email_verified: bool,
        name: str | None = None,
        picture: str | None = None,
    ) -> UserProfile:
        """Entra, vincula ou cria usuario a partir de uma identidade Google verificada."""
        clean_sub = (google_sub or "").strip()
        if not clean_sub:
            self._log_audit_event(
                "login_failure",
                detalhe="provider=google; motivo=google_sub_ausente",
                status="failure",
                source="google_oauth",
                action="login",
            )
            raise AuthValidationError(GOOGLE_ACCOUNT_UNAVAILABLE_MESSAGE)

        clean_email = _validate_email(email)
        if not email_verified:
            self._log_audit_event(
                "login_failure",
                user_email=clean_email,
                detalhe="provider=google; motivo=email_nao_verificado",
                status="failure",
                source="google_oauth",
                action="login",
            )
            raise AuthValidationError(GOOGLE_EMAIL_NOT_VERIFIED_MESSAGE)

        clean_name = (name or "").strip() or clean_email.split("@", 1)[0] or "Usuario"
        clean_picture = (picture or "").strip() or None

        def operation() -> UserProfile:
            authenticated_user: UserProfile | None = None
            with self.engine.begin() as conn:
                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                soft_delete_columns = _soft_delete_select_columns(columns)
                active_sort_expression = _active_user_sort_expression(columns)
                now = _now()

                google_row = conn.execute(
                    text(
                        f"""
                        SELECT id, nome, email, role, criado_em, atualizado_em,
                               ultimo_login_em, google_sub, {soft_delete_columns}
                        FROM usuarios
                        WHERE google_sub = :google_sub
                        ORDER BY {active_sort_expression} DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"google_sub": clean_sub},
                ).mappings().first()

                if google_row:
                    if _is_soft_deleted(google_row):
                        raise AuthValidationError(GOOGLE_ACCOUNT_UNAVAILABLE_MESSAGE)
                    self._touch_google_login(conn, int(google_row["id"]), clean_picture, now)
                    authenticated_user = self._get_user_by_id_in_connection(conn, int(google_row["id"]))

                if authenticated_user is None:
                    email_row = conn.execute(
                    text(
                        f"""
                        SELECT id, google_sub, {soft_delete_columns}
                        FROM usuarios
                        WHERE lower(email) = :email
                        ORDER BY {active_sort_expression} DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"email": clean_email},
                    ).mappings().first()

                    if email_row:
                        if _is_soft_deleted(email_row):
                            raise AuthValidationError(GOOGLE_ACCOUNT_UNAVAILABLE_MESSAGE)
                        existing_sub = str(email_row["google_sub"] or "").strip()
                        if existing_sub and existing_sub != clean_sub:
                            raise AuthValidationError(GOOGLE_ACCOUNT_UNAVAILABLE_MESSAGE)
                        self._link_google_identity(conn, int(email_row["id"]), clean_sub, clean_picture, now)
                        authenticated_user = self._get_user_by_id_in_connection(conn, int(email_row["id"]))

                if authenticated_user is None:
                    user_id = self._create_google_user(conn, clean_name, clean_email, clean_sub, clean_picture, now)
                    authenticated_user = self._get_user_by_id_in_connection(conn, user_id)
            return authenticated_user

        try:
            authenticated_user = run_transient_db_operation("authenticate_google_identity", operation)
        except AuthValidationError:
            self._log_audit_event(
                "login_failure",
                user_email=clean_email,
                detalhe="provider=google; motivo=credenciais_invalidas",
                status="failure",
                source="google_oauth",
                action="login",
            )
            raise
        except SQLAlchemyError as exc:
            self._log_audit_event(
                "database_connection_failure",
                user_email=clean_email,
                detalhe="operacao=google_login",
                status="failure",
                source="google_oauth",
                action="database",
            )
            _log_database_error("authenticate_google_identity", exc)
            raise

        self._log_audit_event(
            "login",
            user_id=authenticated_user.id if authenticated_user else None,
            user_email=authenticated_user.email if authenticated_user else clean_email,
            detalhe="provider=google",
            status="success",
            source="google_oauth",
            action="login",
        )
        return authenticated_user

    def get_user_by_google_sub(self, google_sub: str) -> UserProfile | None:
        clean_sub = (google_sub or "").strip()
        if not clean_sub:
            return None

        def operation() -> UserProfile | None:
            with self.engine.connect() as conn:
                columns = _get_usuario_columns(conn)
                if "google_sub" not in columns:
                    return None
                active_condition = _active_user_condition(columns)
                row = conn.execute(
                    text(
                        f"""
                        SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                               COALESCE(can_view_audit, false) AS can_view_audit
                        FROM usuarios
                        WHERE google_sub = :google_sub
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"google_sub": clean_sub},
                ).mappings().first()
            return _row_to_user(row) if row else None

        try:
            return run_transient_db_operation("get_user_by_google_sub", operation)
        except SQLAlchemyError as exc:
            _log_database_error("get_user_by_google_sub", exc)
            raise

    def get_active_user_by_email(self, email: str) -> UserProfile | None:
        clean_email = _validate_email(email)

        def operation() -> UserProfile | None:
            with self.engine.connect() as conn:
                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                row = conn.execute(
                    text(
                        f"""
                        SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                               COALESCE(can_view_audit, false) AS can_view_audit
                        FROM usuarios
                        WHERE lower(email) = :email
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"email": clean_email},
                ).mappings().first()
            return _row_to_user(row) if row else None

        try:
            return run_transient_db_operation("get_active_user_by_email", operation)
        except SQLAlchemyError as exc:
            _log_database_error("get_active_user_by_email", exc)
            raise

    def get_user_by_id(self, user_id: int) -> UserProfile | None:
        def operation() -> UserProfile | None:
            with self.engine.connect() as conn:
                active_condition = _active_user_condition(_get_usuario_columns(conn))
                row = conn.execute(
                    text(
                        f"""
                        SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                               COALESCE(can_view_audit, false) AS can_view_audit
                        FROM usuarios
                        WHERE id = :id
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"id": user_id},
                ).mappings().first()
            return _row_to_user(row) if row else None

        try:
            return run_transient_db_operation("get_user_by_id", operation)
        except SQLAlchemyError as exc:
            _log_database_error("get_user_by_id", exc)
            raise

    def _get_user_by_id_in_connection(self, conn: Any, user_id: int) -> UserProfile:
        row = conn.execute(
            text(
                """
                SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                       COALESCE(can_view_audit, false) AS can_view_audit
                FROM usuarios
                WHERE id = :id
                LIMIT 1
                """
            ),
            {"id": user_id},
        ).mappings().first()
        if row is None:
            raise AuthValidationError("Usuario ativo nao encontrado.")
        return _row_to_user(row)

    def _touch_google_login(
        self,
        conn: Any,
        user_id: int,
        picture: str | None,
        now: datetime,
    ) -> None:
        columns = _get_usuario_columns(conn)
        assignments = [
            "ultimo_login_em = :ultimo_login_em",
            "atualizado_em = :atualizado_em",
        ]
        params: dict[str, Any] = {
            "id": user_id,
            "ultimo_login_em": now,
            "atualizado_em": now,
        }
        if "google_picture" in columns:
            assignments.append("google_picture = :google_picture")
            params["google_picture"] = picture
        if "email_verificado" in columns:
            assignments.append("email_verificado = :email_verificado")
            params["email_verificado"] = True
        if "email_verificado_em" in columns:
            assignments.append("email_verificado_em = COALESCE(email_verificado_em, :email_verificado_em)")
            params["email_verificado_em"] = now

        conn.execute(
            text(
                f"""
                UPDATE usuarios
                SET {", ".join(assignments)}
                WHERE id = :id
                """
            ),
            params,
        )

    def _link_google_identity(
        self,
        conn: Any,
        user_id: int,
        google_sub: str,
        picture: str | None,
        now: datetime,
    ) -> None:
        columns = _get_usuario_columns(conn)
        assignments = [
            "ultimo_login_em = :ultimo_login_em",
            "atualizado_em = :atualizado_em",
        ]
        params: dict[str, Any] = {
            "id": user_id,
            "google_sub": google_sub,
            "google_picture": picture,
            "ultimo_login_em": now,
            "atualizado_em": now,
        }
        if "google_sub" in columns:
            assignments.append("google_sub = :google_sub")
        if "google_picture" in columns:
            assignments.append("google_picture = :google_picture")
        if "auth_provider" in columns:
            assignments.append("auth_provider = :auth_provider")
            params["auth_provider"] = "password_google"
        if "email_verificado" in columns:
            assignments.append("email_verificado = :email_verificado")
            params["email_verificado"] = True
        if "email_verificado_em" in columns:
            assignments.append("email_verificado_em = COALESCE(email_verificado_em, :email_verificado_em)")
            params["email_verificado_em"] = now

        conn.execute(
            text(
                f"""
                UPDATE usuarios
                SET {", ".join(assignments)}
                WHERE id = :id
                """
            ),
            params,
        )

    def _create_google_user(
        self,
        conn: Any,
        name: str,
        email: str,
        google_sub: str,
        picture: str | None,
        now: datetime,
    ) -> int:
        conn.execute(
            text(
                """
                INSERT INTO usuarios (
                    nome,
                    email,
                    senha_hash,
                    role,
                    criado_em,
                    atualizado_em,
                    ultimo_login_em,
                    email_verificado,
                    email_verificado_em,
                    deletado,
                    deletado_em,
                    google_sub,
                    google_picture,
                    auth_provider
                )
                VALUES (
                    :nome,
                    :email,
                    NULL,
                    'user',
                    :criado_em,
                    :atualizado_em,
                    :ultimo_login_em,
                    :email_verificado,
                    :email_verificado_em,
                    :deletado,
                    :deletado_em,
                    :google_sub,
                    :google_picture,
                    :auth_provider
                )
                """
            ),
            {
                "nome": name,
                "email": email,
                "criado_em": now,
                "atualizado_em": now,
                "ultimo_login_em": now,
                "email_verificado": True,
                "email_verificado_em": now,
                "deletado": False,
                "deletado_em": None,
                "google_sub": google_sub,
                "google_picture": picture,
                "auth_provider": "google",
            },
        )
        row = conn.execute(
            text(
                """
                SELECT id
                FROM usuarios
                WHERE google_sub = :google_sub
                LIMIT 1
                """
            ),
            {"google_sub": google_sub},
        ).mappings().first()
        return int(row["id"])

    def get_all_users(self) -> list[UserProfile]:
        """Retorna todos os usuarios ativos. Uso exclusivo de Super Admins."""
        try:
            with self.engine.connect() as conn:
                active_condition = _active_user_condition(_get_usuario_columns(conn))
                rows = conn.execute(
                    text(
                        f"""
                        SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                               COALESCE(can_view_audit, false) AS can_view_audit
                        FROM usuarios
                        WHERE {active_condition}
                        ORDER BY criado_em DESC
                        """
                    )
                ).mappings().all()
        except SQLAlchemyError as exc:
            _log_database_error("get_all_users", exc)
            raise

        return [_row_to_user(row) for row in rows]

    def set_role(
        self,
        target_user_id: int,
        new_role: str,
        acting_admin_id: int | None = None,
        acting_admin_email: str | None = None,
    ) -> UserProfile:
        """Atualiza o papel (role) de um usuario. Registra evento de auditoria."""
        from src.auth.roles import VALID_ROLES

        if new_role not in VALID_ROLES:
            raise AuthValidationError(f"Papel invalido: {new_role}")

        try:
            with self.engine.begin() as conn:
                active_condition = _active_user_condition(_get_usuario_columns(conn))
                conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET role = :role,
                            atualizado_em = :atualizado_em
                        WHERE id = :id
                          AND {active_condition}
                        """
                    ),
                    {"id": target_user_id, "role": new_role, "atualizado_em": _now()},
                )
        except SQLAlchemyError as exc:
            _log_database_error("set_role", exc)
            raise

        user = self.get_user_by_id(target_user_id)
        if user is None:
            raise AuthValidationError("Usuario ativo nao encontrado.")

        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_ROLE_CHANGED

            AuditLogService(self.engine, initialize_schema=False).log_event(
                EVENT_ROLE_CHANGED,
                user_id=target_user_id,
                user_email=user.email,
                detalhe=f"novo_role={new_role} | admin_id={acting_admin_id} | admin={acting_admin_email}",
                status="info",
                source="admin",
                action="role_changed",
            )
        except Exception:
            logger.debug("audit_log nao disponivel — ignorado em set_role")

        return user

    def set_audit_access(
        self,
        target_user_id: int,
        grant: bool,
        acting_admin_id: int | None = None,
        acting_admin_email: str | None = None,
    ) -> None:
        """Concede ou revoga acesso de visualizacao do log de auditoria."""
        try:
            with self.engine.begin() as conn:
                active_condition = _active_user_condition(_get_usuario_columns(conn))
                conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET can_view_audit = :val,
                            atualizado_em = :atualizado_em
                        WHERE id = :id
                          AND {active_condition}
                        """
                    ),
                    {"id": target_user_id, "val": grant, "atualizado_em": _now()},
                )
        except SQLAlchemyError as exc:
            _log_database_error("set_audit_access", exc)
            raise

        try:
            from src.audit.audit_log_service import (
                AuditLogService,
                EVENT_ACCESS_GRANTED,
                EVENT_ACCESS_REVOKED,
            )

            evento = EVENT_ACCESS_GRANTED if grant else EVENT_ACCESS_REVOKED
            AuditLogService(self.engine, initialize_schema=False).log_event(
                evento,
                user_id=target_user_id,
                detalhe=f"admin_id={acting_admin_id} | admin={acting_admin_email}",
                status="success" if grant else "info",
                source="admin",
                action="audit_access",
            )
        except Exception:
            logger.debug("audit_log nao disponivel — ignorado em set_audit_access")

    def update_name(self, user_id: int, nome: str) -> UserProfile:
        clean_name = _validate_name(nome)
        try:
            with self.engine.begin() as conn:
                active_condition = _active_user_condition(_get_usuario_columns(conn))
                now = _now()
                conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET nome = :nome,
                            atualizado_em = :atualizado_em
                        WHERE id = :id
                          AND {active_condition}
                        """
                    ),
                    {"id": user_id, "nome": clean_name, "atualizado_em": now},
                )
        except SQLAlchemyError as exc:
            _log_database_error("update_name", exc)
            raise

        user = self.get_user_by_id(user_id)
        if user is None:
            raise AuthValidationError("Usuario ativo nao encontrado.")

        return user

    def update_email(self, user_id: int, email: str) -> UserProfile:
        clean_email = _validate_email(email)
        try:
            with self.engine.begin() as conn:
                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                active_user = conn.execute(
                    text(
                        f"""
                        SELECT id
                        FROM usuarios
                        WHERE id = :id
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"id": user_id},
                ).mappings().first()

                if not active_user:
                    raise AuthValidationError("Usuario ativo nao encontrado.")

                duplicate_user = conn.execute(
                    text(
                        f"""
                        SELECT id
                        FROM usuarios
                        WHERE lower(email) = :email
                          AND id <> :id
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"id": user_id, "email": clean_email},
                ).mappings().first()
                if duplicate_user:
                    raise AuthValidationError("Já existe uma conta ativa com este e-mail.")

                assignments = ["email = :email", "atualizado_em = :atualizado_em"]
                params: dict[str, Any] = {
                    "id": user_id,
                    "email": clean_email,
                    "atualizado_em": _now(),
                }
                if "email_verificado" in columns:
                    assignments.append("email_verificado = :email_verificado")
                    params["email_verificado"] = False
                if "email_verificado_em" in columns:
                    assignments.append("email_verificado_em = :email_verificado_em")
                    params["email_verificado_em"] = None

                conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET {", ".join(assignments)}
                        WHERE id = :id
                          AND {active_condition}
                        """
                    ),
                    params,
                )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            _log_database_error("update_email", exc)
            raise

        user = self.get_user_by_id(user_id)
        if user is None:
            raise AuthValidationError("Usuario ativo nao encontrado.")

        return user

    def change_password(
        self,
        user_id: int,
        senha_atual: str,
        nova_senha: str,
        confirmar_senha: str,
    ) -> None:
        clean_new_password = _validate_new_password(nova_senha, confirmar_senha)

        try:
            with self.engine.begin() as conn:
                active_condition = _active_user_condition(_get_usuario_columns(conn))
                row = conn.execute(
                    text(
                        f"""
                        SELECT id, senha_hash
                        FROM usuarios
                        WHERE id = :id
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"id": user_id},
                ).mappings().first()

                if not row:
                    raise AuthValidationError("Usuario ativo nao encontrado.")
                if not row["senha_hash"]:
                    raise AuthValidationError("Senha atual invalida.")
                if not verify_password(senha_atual, row["senha_hash"]):
                    raise AuthValidationError("Senha atual invalida.")

                conn.execute(
                    text(
                        """
                        UPDATE usuarios
                        SET senha_hash = :senha_hash,
                            atualizado_em = :atualizado_em
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": user_id,
                        "senha_hash": hash_password(clean_new_password),
                        "atualizado_em": _now(),
                    },
                )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            _log_database_error("change_password", exc)
            raise

    def soft_delete_user(self, user_id: int) -> None:
        try:
            with self.engine.begin() as conn:
                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                assignments = ["atualizado_em = :atualizado_em"]
                params: dict[str, Any] = {"id": user_id, "atualizado_em": _now()}

                if "deleted_at" in columns:
                    assignments.insert(0, "deleted_at = :deleted_at")
                    params["deleted_at"] = params["atualizado_em"]
                if "deletado" in columns:
                    assignments.insert(0, "deletado = :deletado")
                    params["deletado"] = True
                if "deletado_em" in columns:
                    assignments.insert(0, "deletado_em = :deletado_em")
                    params["deletado_em"] = params["atualizado_em"]
                if len(assignments) == 1:
                    raise AuthValidationError("Tabela de usuarios nao possui soft delete configurado.")

                user_row = conn.execute(
                    text("SELECT email FROM usuarios WHERE id = :id LIMIT 1"),
                    {"id": user_id},
                ).mappings().first()
                user_email_for_audit = user_row["email"] if user_row else None

                conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET {", ".join(assignments)}
                        WHERE id = :id
                          AND {active_condition}
                        """
                    ),
                    params,
                )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            _log_database_error("soft_delete_user", exc)
            raise

        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_ACCOUNT_DELETED

            AuditLogService(self.engine, initialize_schema=False).log_event(
                EVENT_ACCOUNT_DELETED,
                user_id=user_id,
                user_email=user_email_for_audit,
                status="success",
                source="auth",
                action="account_deactivated",
            )
        except Exception:
            logger.debug("audit_log nao disponivel — ignorado em soft_delete_user")

