# Ideia de Servidor MCP — EQ10

**Domínio:** Análise de dados SIA/DATASUS (ETL + Postgres + PandasAI)  
**Data:** 2026-07-01

## O que é

Um **servidor MCP (Model Context Protocol)** expõe as operações do seu sistema como *tools* e *resources* que qualquer assistente de IA (Claude Desktop, Cursor, etc.) pode chamar com segurança. Na prática, é uma camada fina sobre a **API que vocês já têm** — cada tool chama um endpoint/service existente. Assim o projeto deixa de ser só uma tela e passa a ser operável por um agente de IA.

## Servidor proposto: `datasus-mcp`

### Tools sugeridas

- `consultar_indicador(filtros)` — agrega um indicador
- `executar_sql_seguro(query)` — SQL somente-leitura no schema
- `serie_temporal(indicador, periodo)` — evolução no tempo

### Resources (somente leitura)

- schema das tabelas + dicionário de dados como resource (essencial p/ text-to-SQL)

### Exemplos de uso com um LLM

- "Quantos atendimentos ambulatoriais por município em 2024, top 10?"
- "Mostre a série mensal de procedimentos da especialidade X."

## Esqueleto para começar (Python / FastMCP)

```python
# pip install mcp httpx
from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("datasus-mcp")
API = "http://localhost:8000"   # sua API local (ajuste a porta)

@mcp.tool()
def consultar_indicador(filtros):
    """agrega um indicador"""
    r = httpx.get(f"{API}/seu/endpoint")   # reaproveite sua API existente
    return r.json()

if __name__ == "__main__":
    mcp.run()   # transporte stdio; registre no Claude Desktop / Cursor
```

## Boas práticas

- **Segurança:** cada tool que altera dados deve exigir autenticação e registrar no **log de auditoria** (o mesmo do requisito da disciplina).
- **Escopo mínimo:** exponha só o necessário; separe tools de leitura das de escrita.
- **Reaproveite:** as tools devem chamar seus *services*/*controllers* existentes, não reimplementar regra de negócio.

## Referências
- Documentação MCP: https://modelcontextprotocol.io
- SDKs: Python (`mcp`), TypeScript (`@modelcontextprotocol/sdk`), Java (Spring AI MCP Server).

*Sugestão gerada em 2026-07-01 para orientar a integração de LLMs ao projeto.*