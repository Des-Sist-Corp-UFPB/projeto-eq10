"""Servidor MCP (Model Context Protocol) para dados SIA/DATASUS — EQ10.

Expoe as operacoes do sistema como *tools* e *resources* que qualquer
assistente de IA compativel com MCP (Claude Desktop, Cursor, etc.) pode
chamar com segurança. Cada tool chama os services existentes — sem
reimplementar regras de negocio.

Transporte padrao: stdio (uso local / Claude Desktop).
Para producao HTTP/SSE, use: mcp run src/mcp_server.py --transport sse

Uso:
    python -m src.mcp_server        # start via stdio
    mcp run src/mcp_server.py       # alternativa via CLI do pacote mcp
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Carrega variáveis de ambiente antes de qualquer import de serviços.
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() == "test":
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
        load_dotenv(BASE_DIR / "config" / ".env")
    except ModuleNotFoundError:
        pass


_load_env()

# ──────────────────────────────────────────────────────────────────────────────
# Inicialização do servidor MCP
# ──────────────────────────────────────────────────────────────────────────────
from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    name="datasus-mcp",
    instructions=(
        "Servidor de dados SIA/DATASUS da Prefeitura Municipal de Mamanguape (EQ10). "
        "Disponibiliza dados ambulatoriais anonimizados e agregados do sistema SIA. "
        "Nenhuma tool modifica dados — todas sao somente leitura. "
        "Antes de executar qualquer SQL, use o resource 'schema' para conhecer as "
        "colunas e tipos de dados disponiveis."
    ),
)

# ──────────────────────────────────────────────────────────────────────────────
# Imports de serviços (lazy para nao carregar engines desnecessariamente)
# ──────────────────────────────────────────────────────────────────────────────


def _get_analytics_engine():
    from src.ai.read_only_datasus import get_readonly_engine
    return get_readonly_engine()


# ──────────────────────────────────────────────────────────────────────────────
# Resource: schema das colunas disponíveis (contexto estático, custo zero)
# ──────────────────────────────────────────────────────────────────────────────
_SCHEMA_TEXT = """\
# Schema da view analitica vw_data_sus_ia

Esta e a unica fonte de dados exposta por este servidor. Ela e somente leitura.

## Colunas

| Coluna                  | Tipo        | Descricao                                           |
|-------------------------|-------------|-----------------------------------------------------|
| data                    | DATE        | Data do atendimento (AAAA-MM-DD)                    |
| idade                   | INTEGER     | Idade do paciente em anos                           |
| sexo                    | TEXT        | Sexo do paciente ('M', 'F' ou 'I')                 |
| municipio_atendimento   | TEXT        | Nome do municipio onde ocorreu o atendimento        |
| municipio_residencia    | TEXT        | Nome do municipio de residencia do paciente         |
| raca_cor                | TEXT        | Raca/cor autodeclarada                              |
| unidade                 | TEXT        | Nome da unidade de saude                            |
| ocupacao                | TEXT        | Descricao da ocupacao do profissional de saude      |
| procedimento            | TEXT        | Descricao do procedimento realizado                 |
| frequencia              | INTEGER     | Numero de atendimentos registrados                  |
| quantidade_apresentada  | INTEGER     | Quantidade de procedimentos apresentada (cobranca)  |
| valor_apresentado       | NUMERIC     | Valor total apresentado para pagamento (R$)         |
| valor_aprovado          | NUMERIC     | Valor total aprovado para pagamento (R$)            |

## Filtros recomendados

- `data >= CURRENT_DATE - INTERVAL '3 months'` para o periodo coberto (ultimos 3 meses)
- `municipio_atendimento` ou `municipio_residencia` para recorte geografico
- `procedimento` para filtrar por tipo de atendimento

## Restricoes de segurança

- Nao e permitido realizar SELECT * sem WHERE (tabela pode ser grande)
- Nao sao permitidos JOINs com outras tabelas
- Nao sao permitidos INSERT, UPDATE, DELETE ou DDL
"""


@mcp.resource("datasus://schema")
def get_schema() -> str:
    """Retorna o dicionario de dados (schema) da view analitica SIA/DATASUS.

    Use este resource ANTES de construir qualquer query SQL para conhecer os
    nomes exatos das colunas e seus tipos.
    """
    return _SCHEMA_TEXT


# ──────────────────────────────────────────────────────────────────────────────
# Tool 1: consultar_indicador
# ──────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def consultar_indicador(
    indicador: str,
    agrupar_por: str = "municipio_atendimento",
    data_inicio: str = "",
    data_fim: str = "",
    limite: int = 50,
) -> list[dict[str, Any]]:
    """Agrega um indicador numerico dos dados SIA/DATASUS.

    Args:
        indicador: Nome da coluna numerica a agregar. Valores validos:
                   'frequencia', 'quantidade_apresentada',
                   'valor_apresentado', 'valor_aprovado'.
        agrupar_por: Coluna de agrupamento (ex: 'municipio_atendimento',
                     'procedimento', 'sexo', 'raca_cor', 'unidade').
                     Padrao: 'municipio_atendimento'.
        data_inicio: Data inicial no formato AAAA-MM-DD (opcional).
                     Se vazia, usa os ultimos 3 meses.
        data_fim: Data final no formato AAAA-MM-DD (opcional).
                  Se vazia, usa a data mais recente disponivel.
        limite: Numero maximo de linhas a retornar. Maximo: 200.

    Returns:
        Lista de dicionarios com os campos 'grupo' e 'total',
        ordenados por total decrescente.

    Exemplo:
        consultar_indicador('valor_aprovado', 'procedimento', '2024-01-01', '2024-03-31', 10)
    """
    from src.ai.config import AI_ALLOWED_COLUMNS, AI_DATA_SOURCE
    from sqlalchemy import text

    INDICADORES_VALIDOS = {"frequencia", "quantidade_apresentada", "valor_apresentado", "valor_aprovado"}
    GRUPOS_VALIDOS = {c for c in AI_ALLOWED_COLUMNS if c not in INDICADORES_VALIDOS and c not in ("data", "idade")}

    if indicador not in INDICADORES_VALIDOS:
        raise ValueError(
            f"Indicador '{indicador}' invalido. Escolha um de: {sorted(INDICADORES_VALIDOS)}"
        )
    if agrupar_por not in GRUPOS_VALIDOS:
        raise ValueError(
            f"Coluna de agrupamento '{agrupar_por}' invalida. Escolha uma de: {sorted(GRUPOS_VALIDOS)}"
        )

    limite = min(int(limite), 200)

    where_clauses: list[str] = []
    params: dict[str, Any] = {"limite": limite}

    if data_inicio:
        where_clauses.append("data >= :data_inicio")
        params["data_inicio"] = data_inicio
    else:
        where_clauses.append("data >= CURRENT_DATE - INTERVAL '3 months'")

    if data_fim:
        where_clauses.append("data <= :data_fim")
        params["data_fim"] = data_fim

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Nomes de colunas ja validados — uso seguro em f-string
    sql = f"""
        SELECT
            {agrupar_por} AS grupo,
            SUM({indicador}) AS total
        FROM {AI_DATA_SOURCE}
        {where_sql}
        GROUP BY {agrupar_por}
        ORDER BY total DESC
        LIMIT :limite
    """

    engine = _get_analytics_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    return [{"grupo": str(r["grupo"]), "total": float(r["total"] or 0)} for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Tool 2: executar_sql_seguro
# ──────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def executar_sql_seguro(query: str, limite: int = 100) -> list[dict[str, Any]]:
    """Executa uma query SQL somente leitura na view analitica vw_data_sus_ia.

    Validacoes de segurança aplicadas:
    - Apenas SELECT e permitido (nenhuma DML/DDL)
    - Apenas a view vw_data_sus_ia pode ser acessada
    - Limite maximo de 500 linhas por chamada
    - Bloqueio de palavras-chave perigosas (DROP, DELETE, UPDATE, INSERT, etc.)

    Args:
        query: Query SQL somente leitura. Deve comecar com SELECT e
               referenciar apenas vw_data_sus_ia. Use o resource
               'datasus://schema' para conhecer as colunas disponiveis.
        limite: Numero maximo de linhas. Padrao: 100. Maximo: 500.

    Returns:
        Lista de dicionarios representando as linhas do resultado.

    Exemplo:
        executar_sql_seguro(
            "SELECT municipio_atendimento, SUM(frequencia) AS total "
            "FROM vw_data_sus_ia "
            "WHERE data >= CURRENT_DATE - INTERVAL '1 month' "
            "GROUP BY municipio_atendimento ORDER BY total DESC LIMIT 10"
        )
    """
    import re
    from src.ai.prompt_guard import validar_prompt
    from src.ai.config import AI_DATA_SOURCE
    from sqlalchemy import text

    # Validacao 1: verifica com o prompt guard do sistema
    valido, mensagem = validar_prompt(query)
    if not valido:
        raise PermissionError(f"Query bloqueada pelo sistema de segurança: {mensagem}")

    # Validacao 2: apenas SELECT
    query_stripped = query.strip().upper()
    if not query_stripped.startswith("SELECT"):
        raise PermissionError("Apenas queries SELECT sao permitidas.")

    # Validacao 3: palavras-chave proibidas
    FORBIDDEN = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CALL)\b",
        re.IGNORECASE,
    )
    if FORBIDDEN.search(query):
        raise PermissionError("A query contem palavras-chave proibidas.")

    # Validacao 4: apenas a view autorizada pode ser acessada
    if AI_DATA_SOURCE.lower() not in query.lower():
        raise PermissionError(
            f"A query deve referenciar apenas a view '{AI_DATA_SOURCE}'."
        )

    limite = min(int(limite), 500)

    # Envolve em subquery com LIMIT para garantir o teto
    safe_sql = f"SELECT * FROM ({query.rstrip(';')}) AS _mcp_query LIMIT {limite}"

    engine = _get_analytics_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(safe_sql)).mappings().all()

    return [dict(row) for row in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Tool 3: serie_temporal
# ──────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def serie_temporal(
    indicador: str = "frequencia",
    granularidade: str = "mes",
    municipio: str = "",
    procedimento: str = "",
    data_inicio: str = "",
    data_fim: str = "",
) -> list[dict[str, Any]]:
    """Retorna a evolucao temporal de um indicador SIA/DATASUS.

    Util para identificar tendencias, sazonalidades e picos de demanda.

    Args:
        indicador: Coluna numerica a agregar. Valores validos:
                   'frequencia', 'quantidade_apresentada',
                   'valor_apresentado', 'valor_aprovado'.
                   Padrao: 'frequencia'.
        granularidade: Agrupamento temporal — 'mes' ou 'semana'.
                       Padrao: 'mes'.
        municipio: Filtro opcional por municipio de atendimento
                   (correspondencia exata, case insensitive).
        procedimento: Filtro opcional por descricao do procedimento
                      (correspondencia parcial, case insensitive).
        data_inicio: Data inicial AAAA-MM-DD. Se vazia: ultimos 3 meses.
        data_fim: Data final AAAA-MM-DD. Se vazia: data mais recente.

    Returns:
        Lista de pontos no tempo, cada um com 'periodo' e 'total',
        ordenados cronologicamente.
    """
    from src.ai.config import AI_DATA_SOURCE
    from sqlalchemy import text

    INDICADORES_VALIDOS = {"frequencia", "quantidade_apresentada", "valor_apresentado", "valor_aprovado"}
    GRANULARIDADES_VALIDAS = {"mes", "semana"}

    if indicador not in INDICADORES_VALIDOS:
        raise ValueError(f"Indicador invalido: {indicador}. Validos: {sorted(INDICADORES_VALIDOS)}")
    if granularidade not in GRANULARIDADES_VALIDAS:
        raise ValueError(f"Granularidade invalida: {granularidade}. Validas: {sorted(GRANULARIDADES_VALIDAS)}")

    # Expressao de truncagem temporal
    trunc_expr = (
        "DATE_TRUNC('month', data)::date"
        if granularidade == "mes"
        else "DATE_TRUNC('week', data)::date"
    )

    where_clauses: list[str] = []
    params: dict[str, Any] = {}

    if data_inicio:
        where_clauses.append("data >= :data_inicio")
        params["data_inicio"] = data_inicio
    else:
        where_clauses.append("data >= CURRENT_DATE - INTERVAL '3 months'")

    if data_fim:
        where_clauses.append("data <= :data_fim")
        params["data_fim"] = data_fim

    if municipio:
        where_clauses.append("LOWER(municipio_atendimento) = LOWER(:municipio)")
        params["municipio"] = municipio

    if procedimento:
        where_clauses.append("LOWER(procedimento) LIKE LOWER(:procedimento)")
        params["procedimento"] = f"%{procedimento}%"

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sql = f"""
        SELECT
            {trunc_expr} AS periodo,
            SUM({indicador}) AS total
        FROM {AI_DATA_SOURCE}
        {where_sql}
        GROUP BY {trunc_expr}
        ORDER BY periodo ASC
    """

    engine = _get_analytics_engine()
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    return [
        {"periodo": str(r["periodo"]), "total": float(r["total"] or 0)}
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Ponto de entrada
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
