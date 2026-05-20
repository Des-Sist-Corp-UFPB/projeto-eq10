"""Acesso somente leitura aos dados SIA/DATASUS para a camada de IA."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

BASE_DIR = Path(__file__).resolve().parents[2]

AI_DB_ENV_VARS = ["AI_DB_USER", "AI_DB_PASSWORD", "AI_DB_HOST", "AI_DB_NAME"]
AI_CONFIG_ERROR_MESSAGE = "Configuração incompleta da camada de IA: variáveis AI_DB_* ausentes."


def _load_env_files() -> None:
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
    database_url = (
        f"postgresql://{env['AI_DB_USER']}:{encoded_password}"
        f"@{env['AI_DB_HOST']}/{env['AI_DB_NAME']}"
        "?sslmode=require&channel_binding=require"
    )

    from sqlalchemy import create_engine

    return create_engine(database_url)


def get_last_available_date(engine):
    """Retorna a ultima data disponivel na tabela data_sus ou None."""
    from sqlalchemy import text

    query = text("SELECT MAX(data)::date AS ultima_data FROM data_sus")

    with engine.connect() as conn:
        result = conn.execute(query).mappings().first()

    if not result:
        return None

    return result["ultima_data"]
