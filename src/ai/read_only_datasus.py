"""Acesso somente leitura aos dados SIA/DATASUS para a camada de IA."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

from src.ai.config import AI_DATA_SOURCE

BASE_DIR = Path(__file__).resolve().parents[2]

AI_DB_ENV_VARS = ["AI_DB_USER", "AI_DB_PASSWORD", "AI_DB_HOST", "AI_DB_NAME"]
AI_CONFIG_ERROR_MESSAGE = "Configuração incompleta da camada de IA: variáveis AI_DB_* ausentes."

# SSL: 'require' para Neon/cloud, 'prefer' ou 'disable' para PostgreSQL interno (Docker)
_DEFAULT_SSLMODE = "require"


def _build_db_url(user: str, password: str, host: str, dbname: str) -> str:
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
        f"@{host}/{dbname}{params}"
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

def get_readonly_engine():
    """Cria um engine PostgreSQL separado usando variaveis AI_DB_*.

    Esta camada nao deve reutilizar a conexao principal da ETL. O usuario de banco
    previsto para a IA deve ter permissoes apenas de leitura.
    """
    _load_env_files()

    env = {name: os.getenv(name) for name in AI_DB_ENV_VARS}
    missing = [name for name, value in env.items() if not value]

    if missing:
        raise RuntimeError(AI_CONFIG_ERROR_MESSAGE)

    encoded_password = quote_plus(env["AI_DB_PASSWORD"])
    database_url = _build_db_url(
        env["AI_DB_USER"], env["AI_DB_PASSWORD"], env["AI_DB_HOST"], env["AI_DB_NAME"]
    )

    from sqlalchemy import create_engine

    return create_engine(database_url)


def get_last_available_date(engine):
    """Retorna a ultima data disponivel na fonte da camada de IA ou None."""
    from sqlalchemy import text

    query = text(f"SELECT MAX(data)::date AS ultima_data FROM {AI_DATA_SOURCE}")

    with engine.connect() as conn:
        result = conn.execute(query).mappings().first()

    if not result:
        return None

    return result["ultima_data"]
