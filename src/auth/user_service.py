"""Servico de usuarios com persistencia na tabela usuarios."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError, SQLAlchemyError

from src.auth.security import MIN_PASSWORD_LENGTH, hash_password, verify_password
from src.auth.validation import EMAIL_RE

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_AUTH_SQLITE_PATH = BASE_DIR / "data" / "auth.sqlite3"

AUTH_CONFIG_ERROR_MESSAGE = (
    "Configuracao incompleta da autenticacao: informe AUTH_DATABASE_URL, "
    "DATABASE_URL, AUTH_DB_* ou use o fallback local em data/auth.sqlite3."
)

logger = logging.getLogger(__name__)


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


def _build_database_url(prefix: str) -> str | None:
    user = os.getenv(f"{prefix}_USER")
    password = os.getenv(f"{prefix}_PASSWORD")
    host = os.getenv(f"{prefix}_HOST")
    database = os.getenv(f"{prefix}_NAME") or os.getenv(f"{prefix}_DATABASE")
    port = os.getenv(f"{prefix}_PORT")

    if not all([user, password, host, database]):
        return None

    netloc = f"{host}:{port}" if port else str(host)
    safe_password = quote_plus(password or "")
    return f"postgresql+psycopg2://{user}:{safe_password}@{netloc}/{database}{_postgres_query_suffix(str(host), prefix)}"


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
    return f"postgresql+psycopg2://{user}:{safe_password}@{netloc}/{database}{_postgres_query_suffix(str(host), 'DB')}"


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

    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"], "DATABASE_URL"

    auth_db_url = _build_database_url("AUTH_DB")
    if auth_db_url:
        return auth_db_url, "AUTH_DB_*"

    legacy_db_url = _build_lowercase_database_url()
    if legacy_db_url:
        return legacy_db_url, "lowercase database env"

    logger.warning(
        "Auth database env not configured; using local SQLite auth store. "
        "AI_DB_* is readonly and is not used for authentication writes."
    )
    return _build_sqlite_database_url(), "local SQLite"


def get_auth_engine():
    """Cria engine para persistencia de autenticacao."""
    _load_env_files()

    database_url, source = _get_auth_database_url()

    if not database_url:
        raise RuntimeError(AUTH_CONFIG_ERROR_MESSAGE)

    from sqlalchemy import create_engine

    logger.info("Auth database source selected | source=%s", source)
    return create_engine(database_url)


def _normalize_email(email: str) -> str:
    return (email or "").strip().casefold()


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
        id_column = "id SERIAL PRIMARY KEY"
        if dialect == "sqlite":
            id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS usuarios (
                {id_column},
                nome TEXT NOT NULL,
                email TEXT NOT NULL,
                senha_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                criado_em TIMESTAMP NOT NULL,
                atualizado_em TIMESTAMP NOT NULL,
                ultimo_login_em TIMESTAMP NULL,
                email_verificado BOOLEAN NOT NULL DEFAULT false,
                email_verificado_em TIMESTAMP NULL,
                deleted_at TIMESTAMP NULL,
                deletado BOOLEAN NOT NULL DEFAULT false,
                deletado_em TIMESTAMP NULL,
                can_view_audit BOOLEAN NOT NULL DEFAULT false
            )
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text(create_table_sql))
                columns = _get_usuario_columns(conn)
                _add_usuario_column_if_missing(conn, columns, "email_verificado", "BOOLEAN NOT NULL DEFAULT false")
                _add_usuario_column_if_missing(conn, columns, "email_verificado_em", "TIMESTAMP NULL")
                _add_usuario_column_if_missing(conn, columns, "deletado", "BOOLEAN NOT NULL DEFAULT false")
                _add_usuario_column_if_missing(conn, columns, "deletado_em", "TIMESTAMP NULL")
                _add_usuario_column_if_missing(conn, columns, "can_view_audit", "BOOLEAN NOT NULL DEFAULT false")
                conn.execute(text("UPDATE usuarios SET email_verificado = false WHERE email_verificado IS NULL"))
                conn.execute(text("UPDATE usuarios SET deletado = false WHERE deletado IS NULL"))
                conn.execute(text("UPDATE usuarios SET can_view_audit = false WHERE can_view_audit IS NULL"))
                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                create_index_sql = f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_usuarios_email_ativo
                    ON usuarios (lower(email))
                    WHERE {active_condition}
                """
                conn.execute(text(create_index_sql))
        except SQLAlchemyError as exc:
            _log_database_error("ensure_schema", exc)
            raise

    def active_email_exists(self, email: str) -> bool:
        clean_email = _validate_email(email)
        try:
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
        except SQLAlchemyError as exc:
            _log_database_error("active_email_exists", exc)
            raise

        return row is not None

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

        try:
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
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            _log_database_error("create_user", exc)
            raise

        user = _row_to_user(row)
        # Auditoria: conta criada
        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_ACCOUNT_CREATED
            AuditLogService(self.engine, initialize_schema=False).log_event(
                EVENT_ACCOUNT_CREATED,
                user_id=user.id,
                user_email=user.email,
                detalhe=f"role={user.role}",
            )
        except Exception:
            logger.debug("audit_log nao disponivel ainda — ignorado em create_user")
        return user

    def authenticate(self, email: str, senha: str) -> UserProfile:
        clean_email = _validate_email(email)
        if not senha:
            raise AuthValidationError("Informe sua senha.")

        try:
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
                if _is_soft_deleted(row):
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
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            _log_database_error("authenticate", exc)
            raise

        user = _row_to_user(active_row)
        # Auditoria: login realizado
        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_LOGIN
            AuditLogService(self.engine, initialize_schema=False).log_event(
                EVENT_LOGIN,
                user_id=user.id,
                user_email=user.email,
            )
        except Exception:
            logger.debug("audit_log nao disponivel ainda — ignorado em authenticate")
        return user

    def get_user_by_id(self, user_id: int) -> UserProfile | None:
        try:
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
        except SQLAlchemyError as exc:
            _log_database_error("get_user_by_id", exc)
            raise

        return _row_to_user(row) if row else None

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

        return [_row_to_user(r) for r in rows]

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
                        SET role = :role, atualizado_em = :atualizado_em
                        WHERE id = :id AND {active_condition}
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
                        SET can_view_audit = :val, atualizado_em = :atualizado_em
                        WHERE id = :id AND {active_condition}
                        """
                    ),
                    {"id": target_user_id, "val": grant, "atualizado_em": _now()},
                )
        except SQLAlchemyError as exc:
            _log_database_error("set_audit_access", exc)
            raise

        try:
            from src.audit.audit_log_service import AuditLogService, EVENT_ACCESS_GRANTED, EVENT_ACCESS_REVOKED
            evento = EVENT_ACCESS_GRANTED if grant else EVENT_ACCESS_REVOKED
            AuditLogService(self.engine, initialize_schema=False).log_event(
                evento,
                user_id=target_user_id,
                detalhe=f"admin_id={acting_admin_id} | admin={acting_admin_email}",
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
                    raise AuthValidationError("JÃ¡ existe uma conta ativa com este e-mail.")

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

                # Captura email antes de deletar para o log de auditoria
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
            )
        except Exception:
            logger.debug("audit_log nao disponivel — ignorado em soft_delete_user")
