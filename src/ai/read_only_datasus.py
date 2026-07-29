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
DIAGNOSTIC_FAILURE_STAGES = {
    "connection_open",
    "readonly_set",
    "readonly_verify",
    "view_select",
    "maximum_date",
    "optional_catalog",
    "optional_underlying_metadata",
}


class ReadonlyInitializationError(RuntimeError):
    """Falha segura do listener readonly, sem propagar detalhes do driver."""

    def __init__(self, category: str):
        self.category = category
        super().__init__("readonly_initialization_failed")


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
        try:
            cursor.execute("SET default_transaction_read_only = on")
        except Exception as exc:
            raise ReadonlyInitializationError(
                classify_analytical_database_failure(exc)
            ) from None
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
    if isinstance(exc, ReadonlyInitializationError):
        return exc.category
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
        "failure_stage": None,
        "readonly_category": "not_checked",
        "view_query_category": "not_checked",
        "maximum_date_category": "not_checked",
        "optional_metadata_category": "not_checked",
        "readonly_set": False,
        "readonly_verified": False,
        "view_available": False,
        "select_permission": False,
        "session_readonly": False,
        "view_query_success": False,
        "maximum_date_query_success": False,
        "optional_metadata_available": False,
        "underlying_metadata_check": "not_checked",
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
        configuration_missing = str(exc) == AI_CONFIG_ERROR_MESSAGE
        diagnostic["connection_category"] = (
            "configuration_missing"
            if configuration_missing
            else classify_analytical_database_failure(exc)
        )
        if not configuration_missing:
            diagnostic["failure_stage"] = "connection_open"
        logger.warning("Analytical database diagnostic | details=%s", diagnostic)
        return diagnostic

    if connection_error is not None:
        diagnostic["connection_category"] = classify_analytical_database_failure(
            connection_error
        )
        diagnostic["failure_stage"] = "connection_open"
        logger.warning("Analytical database diagnostic | details=%s", diagnostic)
        return diagnostic

    try:
        connection_context = engine.connect()
    except ReadonlyInitializationError as exc:
        diagnostic["connection_category"] = "connection_success"
        diagnostic["readonly_category"] = classify_analytical_database_failure(exc)
        diagnostic["failure_stage"] = "readonly_set"
        logger.warning("Analytical database diagnostic | details=%s", diagnostic)
        return diagnostic
    except Exception as exc:
        diagnostic["connection_category"] = classify_analytical_database_failure(exc)
        diagnostic["failure_stage"] = "connection_open"
        logger.warning("Analytical database diagnostic | details=%s", diagnostic)
        return diagnostic

    diagnostic["connection_category"] = "connection_success"
    diagnostic["readonly_set"] = True
    diagnostic["readonly_category"] = "configured"

    with connection_context as conn:
        try:
            readonly_value = conn.execute(
                text("SHOW default_transaction_read_only")
            ).scalar()
            readonly_verified = str(readonly_value).strip().lower() in {
                "on",
                "true",
                "1",
            }
            diagnostic["readonly_verified"] = readonly_verified
            diagnostic["session_readonly"] = readonly_verified
            diagnostic["readonly_category"] = (
                "verified" if readonly_verified else "verification_failed"
            )
            if not readonly_verified:
                diagnostic["failure_stage"] = "readonly_verify"
                logger.warning("Analytical database diagnostic | details=%s", diagnostic)
                return diagnostic
        except Exception as exc:
            category = classify_analytical_database_failure(exc)
            diagnostic["readonly_category"] = category
            diagnostic["failure_stage"] = "readonly_verify"
            diagnostic["warning_categories"].append(
                f"readonly_verification_{category}"
            )

        try:
            conn.execute(text(f"SELECT 1 FROM {AI_DATA_SOURCE} LIMIT 1"))
            diagnostic["view_available"] = True
            diagnostic["view_query_success"] = True
            diagnostic["select_permission"] = True
            diagnostic["view_query_category"] = "success"
        except Exception as exc:
            diagnostic["view_query_category"] = classify_analytical_database_failure(exc)
            diagnostic["failure_stage"] = "view_select"
            logger.warning("Analytical database diagnostic | details=%s", diagnostic)
            return diagnostic

        try:
            maximum_date = conn.execute(
                text(f"SELECT MAX(data)::date FROM {AI_DATA_SOURCE}")
            ).scalar()
            diagnostic["maximum_date_query_success"] = True
            diagnostic["maximum_date_category"] = "success"
            diagnostic["maximum_available_data_date"] = (
                str(maximum_date) if maximum_date is not None else None
            )
        except Exception as exc:
            diagnostic["maximum_date_category"] = classify_analytical_database_failure(exc)
            diagnostic["failure_stage"] = "maximum_date"
            logger.warning("Analytical database diagnostic | details=%s", diagnostic)
            return diagnostic

        diagnostic["essential_checks_passed"] = True

        try:
            metadata_name = conn.execute(
                text("SELECT to_regclass(:source)"),
                {"source": AI_DATA_SOURCE},
            ).scalar()
            diagnostic["optional_metadata_available"] = metadata_name is not None
            diagnostic["optional_metadata_category"] = (
                "available" if metadata_name is not None else "unavailable"
            )
            diagnostic["underlying_metadata_check"] = diagnostic[
                "optional_metadata_category"
            ]
        except Exception as exc:
            category = classify_analytical_database_failure(exc)
            diagnostic["optional_metadata_category"] = category
            diagnostic["underlying_metadata_check"] = category
            diagnostic["failure_stage"] = "optional_catalog"
            diagnostic["warning_categories"].append(
                f"optional_catalog_{category}"
            )

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
