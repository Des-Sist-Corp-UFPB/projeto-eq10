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


def _build_db_url(user: str, password: str, host: str, port: str, dbname: str) -> str:
    """Monta a URL de conexão PostgreSQL respeitando AI_DB_SSLMODE.

    Variavel AI_DB_SSLMODE:
      - 'require'  (padrão) — exige SSL; compatível com Neon e RDS
      - 'prefer'   — usa SSL se disponível; compatível com PostgreSQL interno
      - 'disable'  — sem SSL; adequado para redes Docker internas sem TLS
    """
    encoded_password = quote_plus(password)
    sslmode = (os.getenv("AI_DB_SSLMODE") or _DEFAULT_SSLMODE).strip().lower()

    params = f"?sslmode={sslmode}"
    # channel_binding só funciona com sslmode=require e drivers compatíveis (Neon)
    if sslmode == "require":
        params += "&channel_binding=require"

    return (
        f"postgresql+psycopg2://{user}:{encoded_password}"
        f"@{host}:{port}/{dbname}{params}"
    )


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
        return os.environ["AI_DATABASE_URL"], "AI_DATABASE_URL"

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
    options = {
        "pool_pre_ping": True,
        "pool_recycle": AI_DB_POOL_RECYCLE_SECONDS,
        "pool_timeout": AI_DB_POOL_TIMEOUT_SECONDS,
    }
    if database_url.strip().lower().startswith(("postgresql://", "postgresql+")):
        options["connect_args"] = {"options": "-c default_transaction_read_only=on"}
    return options


def get_readonly_engine():
    """Cria um engine PostgreSQL separado usando variaveis AI_DB_*.

    Esta camada nao deve reutilizar a conexao principal da ETL. O usuario de banco
    previsto para a IA deve ter permissoes apenas de leitura.
    """
    _load_env_files()

    database_url, source = _get_readonly_database_url()

    from sqlalchemy import create_engine

    logger.info("AI readonly database source selected | source=%s", source)
    return create_engine(database_url, **_readonly_engine_options(database_url))


def get_last_available_date(engine):
    """Retorna a ultima data disponivel na fonte da camada de IA ou None."""
    from sqlalchemy import text

    query = text(f"SELECT MAX(data)::date AS ultima_data FROM {AI_DATA_SOURCE}")

    with engine.connect() as conn:
        result = conn.execute(query).mappings().first()

    if not result:
        return None

    return result["ultima_data"]
