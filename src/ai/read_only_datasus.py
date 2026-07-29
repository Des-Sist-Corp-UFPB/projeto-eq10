"""Acesso somente leitura aos dados SIA/DATASUS para a camada de IA."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import quote_plus

from src.ai.config import AI_DATA_SOURCE

BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)

AI_DB_ENV_VARS = ["AI_DB_USER", "AI_DB_PASSWORD", "AI_DB_HOST", "AI_DB_PORT", "AI_DB_NAME"]
AI_CONFIG_ERROR_MESSAGE = (
    "Configuracao incompleta da camada de IA: informe AI_DATABASE_URL ou "
    "AI_DB_HOST, AI_DB_PORT, AI_DB_NAME, AI_DB_USER e AI_DB_PASSWORD."
)
AI_DB_POOL_RECYCLE_SECONDS = 1800
AI_DB_POOL_TIMEOUT_SECONDS = 10

# SSL: 'require' para Neon/cloud, 'prefer' ou 'disable' para PostgreSQL interno (Docker)
_DEFAULT_SSLMODE = "require"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", "db"}
_VALID_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def _build_db_url(user: str, password: str, host: str, port: str, dbname: str) -> str:
    """Monta a URL de conexão PostgreSQL respeitando AI_DB_SSLMODE.

    Variavel AI_DB_SSLMODE:
      - 'require'  (padrão) — exige SSL; compatível com Neon e RDS
      - 'prefer'   — usa SSL se disponível; compatível com PostgreSQL interno
      - 'disable'  — sem SSL; adequado para redes Docker internas sem TLS
    """
    encoded_password = quote_plus(password)
    sslmode = _normalized_sslmode(host=host)

    params = f"?sslmode={sslmode}"
    # channel_binding só funciona com sslmode=require e drivers compatíveis (Neon)
    if sslmode == "require":
        params += "&channel_binding=require"

    return (
        f"postgresql+psycopg2://{user}:{encoded_password}"
        f"@{host}:{port}/{dbname}{params}"
    )


def _normalized_sslmode(
    value: str | None = None,
    *,
    host: str | None = None,
) -> str:
    sslmode = (value or os.getenv("AI_DB_SSLMODE") or _DEFAULT_SSLMODE).strip().lower()
    if sslmode not in _VALID_SSLMODES:
        raise RuntimeError("Configuracao SSL invalida para a base analitica.")
    if _host_type(host) == "cloud" and sslmode in {"disable", "allow", "prefer"}:
        return "require"
    return sslmode


def _ensure_url_sslmode(database_url: str) -> str:
    """Aplica o SSL default tambem quando AI_DATABASE_URL e usada."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    query = dict(url.query)
    query["sslmode"] = _normalized_sslmode(query.get("sslmode"), host=url.host)
    return url.set(query=query).render_as_string(hide_password=False)


def _load_env_files() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() == "test":
        return

    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return

    load_dotenv(BASE_DIR / ".env")
    load_dotenv(BASE_DIR / "config" / ".env")


def _get_readonly_database_url() -> tuple[str, str]:
    if os.getenv("AI_DATABASE_URL"):
        return _ensure_url_sslmode(os.environ["AI_DATABASE_URL"]), "AI_DATABASE_URL"

    env = {name: os.getenv(name) for name in AI_DB_ENV_VARS}
    missing = [name for name, value in env.items() if not value]

    if missing:
        logger.error(
            "AI readonly database configuration incomplete | missing=%s",
            ",".join(missing),
        )
        raise RuntimeError(AI_CONFIG_ERROR_MESSAGE)

    database_url = _build_db_url(
        env["AI_DB_USER"],
        env["AI_DB_PASSWORD"],
        env["AI_DB_HOST"],
        env["AI_DB_PORT"],
        env["AI_DB_NAME"],
    )
    return database_url, "AI_DB_*"


def get_readonly_database_config_source() -> str:
    """Return only the selected AI database source name, never credentials."""
    _load_env_files()
    _, source = _get_readonly_database_url()
    return source


def _readonly_engine_options(database_url: str) -> dict:
    return {
        "pool_pre_ping": True,
        "pool_recycle": AI_DB_POOL_RECYCLE_SECONDS,
        "pool_timeout": AI_DB_POOL_TIMEOUT_SECONDS,
    }


def _set_session_read_only(dbapi_connection, _connection_record) -> None:
    """Ativa readonly depois do handshake, compativel com poolers Neon."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET default_transaction_read_only = on")
    finally:
        cursor.close()


def _create_readonly_engine(database_url: str):
    from sqlalchemy import create_engine, event

    engine = create_engine(database_url, **_readonly_engine_options(database_url))
    if database_url.strip().lower().startswith(("postgresql://", "postgresql+")):
        event.listen(engine, "connect", _set_session_read_only)
    return engine


def get_readonly_engine():
    """Cria um engine PostgreSQL separado usando variaveis AI_DB_*.

    Esta camada nao deve reutilizar a conexao principal da ETL. O usuario de banco
    previsto para a IA deve ter permissoes apenas de leitura.
    """
    _load_env_files()

    database_url, source = _get_readonly_database_url()

    logger.info("AI readonly database source selected | source=%s", source)
    return _create_readonly_engine(database_url)


def _host_type(host: str | None) -> str:
    normalized = (host or "").strip().lower()
    if not normalized:
        return "unknown"
    return "local" if normalized in _LOCAL_HOSTS or normalized.endswith(".local") else "cloud"


def classify_analytical_database_failure(exc: BaseException) -> str:
    """Classifica falhas sem devolver a mensagem potencialmente sensivel."""
    if str(exc) == AI_CONFIG_ERROR_MESSAGE:
        return "configuration_missing"
    original = getattr(exc, "orig", None)
    pgcode = getattr(original, "pgcode", None) or getattr(exc, "pgcode", None)
    if pgcode in {"28P01", "28000"}:
        return "authentication_failure"
    if pgcode == "42501":
        return "permission_denied"
    if pgcode == "42P01":
        return "view_missing"

    message = str(original or exc).casefold()
    if any(term in message for term in ("could not translate host", "name or service not known", "getaddrinfo")):
        return "dns_failure"
    if any(term in message for term in ("ssl", "certificate", "tls")):
        return "ssl_failure"
    if any(term in message for term in ("password authentication failed", "authentication failed")):
        return "authentication_failure"
    if "permission denied" in message and any(
        term in message for term in ("connection to server", "socket", "10013")
    ):
        return "connection_failure"
    if any(term in message for term in ("permission denied", "insufficient privilege")):
        return "permission_denied"
    if "does not exist" in message and ("relation" in message or AI_DATA_SOURCE in message):
        return "view_missing"
    if any(term in message for term in ("connection refused", "timeout", "could not connect", "network")):
        return "connection_failure"
    return "query_failure"


def get_analytical_database_diagnostic(
    connection_error: BaseException | None = None,
) -> dict[str, object]:
    """Executa diagnostico readonly e retorna somente metadados nao sensiveis."""
    diagnostic: dict[str, object] = {
        "configuration_source": "configuration_missing",
        "selected_configuration_source": "configuration_missing",
        "database_category": "analytical",
        "host_type": "unknown",
        "ssl_mode": "unknown",
        "connection_category": "configuration_missing",
        "view_available": False,
        "select_permission": False,
        "session_readonly": False,
        "view_query_success": False,
        "maximum_date_query_success": False,
        "underlying_metadata_check": "not_required",
        "essential_checks_passed": False,
        "warning_categories": [],
        "maximum_available_data_date": None,
    }

    try:
        _load_env_files()
        database_url, source = _get_readonly_database_url()
        from sqlalchemy import text
        from sqlalchemy.engine import make_url

        parsed = make_url(database_url)
        diagnostic["configuration_source"] = source
        diagnostic["selected_configuration_source"] = source
        diagnostic["host_type"] = _host_type(parsed.host)
        diagnostic["ssl_mode"] = parsed.query.get("sslmode", "unknown")
        engine = _create_readonly_engine(database_url)
    except Exception as exc:
        diagnostic["connection_category"] = (
            "configuration_missing"
            if str(exc) == AI_CONFIG_ERROR_MESSAGE
            else classify_analytical_database_failure(exc)
        )
        logger.warning("Analytical database diagnostic | details=%s", diagnostic)
        return diagnostic

    if connection_error is not None:
        diagnostic["connection_category"] = classify_analytical_database_failure(
            connection_error
        )
        logger.warning("Analytical database diagnostic | details=%s", diagnostic)
        return diagnostic

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            diagnostic["connection_category"] = "connection_success"

            readonly_value = conn.execute(
                text("SHOW transaction_read_only")
            ).scalar()
            diagnostic["session_readonly"] = str(readonly_value).strip().lower() in {
                "on",
                "true",
                "1",
            }
            if not diagnostic["session_readonly"]:
                diagnostic["connection_category"] = "permission_denied"
                logger.warning("Analytical database diagnostic | details=%s", diagnostic)
                return diagnostic

            # A consulta real e a verificacao autoritativa. Consultas de catalogo
            # podem ser negadas ao papel readonly mesmo quando a view e utilizavel.
            conn.execute(text(f"SELECT 1 FROM {AI_DATA_SOURCE} LIMIT 1"))
            diagnostic["view_available"] = True
            diagnostic["view_query_success"] = True
            diagnostic["select_permission"] = True

            maximum_date = conn.execute(
                text(f"SELECT MAX(data)::date FROM {AI_DATA_SOURCE}")
            ).scalar()
            diagnostic["maximum_date_query_success"] = True
            diagnostic["maximum_available_data_date"] = (
                str(maximum_date) if maximum_date is not None else None
            )
            diagnostic["essential_checks_passed"] = True
    except Exception as exc:
        diagnostic["connection_category"] = classify_analytical_database_failure(exc)

    logger.info("Analytical database diagnostic | details=%s", diagnostic)
    return diagnostic


def get_last_available_date(engine):
    """Retorna a ultima data disponivel na fonte da camada de IA ou None."""
    from sqlalchemy import text

    query = text(f"SELECT MAX(data)::date AS ultima_data FROM {AI_DATA_SOURCE}")

    with engine.connect() as conn:
        result = conn.execute(query).mappings().first()

    if not result:
        return None

    return result["ultima_data"]
