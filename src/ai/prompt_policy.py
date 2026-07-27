"""Politica unica de seguranca e classificacao para perguntas estatisticas."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

BLOCK_MESSAGE = (
    "Não posso atender esse pedido. A IA só pode consultar estatísticas dos dados "
    "SIA/DATASUS autorizados e não pode executar SQL livre, alterar dados, acessar "
    "credenciais, arquivos ou informações do sistema."
)

_UNSAFE_PATTERNS = (
    r"\b(delete|drop|truncate|insert|update|alter|create)\b",
    r"\b(select|with)\b",
    r"\b(sql|script|python|terminal|shell|powershell|cmd)\b",
    r"\b(schema|database|banco de dados|estrutura do banco|tabela)\b",
    r"\b(senha|credencia(?:l|is)|token|secret|api key|chave de api)\b",
    r"(?:^|\s)\.env\b",
    r"\b(arquivo|arquivos|diretorio|servidor|sistema operacional)\b",
    r"\b(apague|exclua|deletar|modifique|altere|edite|execute|rode)\b",
)
_DIMENSIONS = (
    ("municipio_residencia", ("municipios de residencia", "municipio de residencia")),
    ("municipio_atendimento", ("municipios", "municipio")),
    ("raca_cor", ("raca cor", "raca")),
    ("procedimento", ("procedimentos", "procedimento")),
    ("unidade", ("unidades", "unidade")),
    ("ocupacao", ("ocupacoes", "ocupacao")),
    ("sexo", ("sexo",)),
)
_METRICS = (
    ("valor_aprovado", ("valor aprovado",)),
    ("valor_apresentado", ("valor apresentado",)),
    ("quantidade_apresentada", ("quantidade apresentada",)),
    ("frequencia", ("frequencia",)),
    ("idade", ("idade",)),
)
_HEALTHCARE_TERMS = (
    "atendimento", "atendimentos", "registro", "registros", "datasus", "sia",
    "paciente", "pacientes",
)
_UNSUPPORTED_STATISTICAL_TERMS = (
    "comparacao", "compare", "variacao", "evolucao", "distribuicao",
    "percentual", "porcentagem", "mediana", "tendencia", "cresceu", "crescimento",
)
_DIMENSION_DISPLAY = {
    "municipio_atendimento": "município de atendimento",
    "municipio_residencia": "município de residência",
    "raca_cor": "raça/cor",
    "procedimento": "procedimento",
    "unidade": "unidade de atendimento",
    "ocupacao": "ocupação",
    "sexo": "sexo",
}
_METRIC_DISPLAY = {
    "valor_aprovado": "valor aprovado",
    "valor_apresentado": "valor apresentado",
    "quantidade_apresentada": "quantidade apresentada",
    "frequencia": "frequência",
    "idade": "idade",
    "rows": "atendimentos",
    "records": "registros",
}


def dimension_display(dimension: str) -> str:
    return _DIMENSION_DISPLAY[dimension]


def metric_display(metric: str) -> str:
    return _METRIC_DISPLAY[metric]


def normalize_prompt(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9_]+", " ", text).strip()


def _contains(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _match(text: str, choices: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for value, aliases in choices:
        if any(_contains(text, alias) for alias in aliases):
            return value
    return None


@dataclass(frozen=True)
class PromptDecision:
    allowed: bool
    reason: str
    intent: str
    operation: str | None = None
    metric: str | None = None
    dimension: str | None = None
    limit: int = 10
    normalized_prompt: str = ""

    @property
    def query_plan(self) -> str:
        if not self.allowed:
            return "none"
        parts = [
            "source=vw_data_sus_ia",
            f"operation={self.operation}",
            f"metric={self.metric or 'rows'}",
            f"dimension={self.dimension or 'none'}",
        ]
        if self.operation == "ranking":
            parts.append(f"limit={self.limit}")
        return ";".join(parts)


def classify_prompt(prompt: str) -> PromptDecision:
    """Retorna a decisao autoritativa usada por guard, runners e orquestrador."""
    normalized = normalize_prompt(prompt)
    if not normalized:
        return PromptDecision(False, "empty_prompt", "blocked", normalized_prompt=normalized)
    if any(re.search(pattern, normalized) for pattern in _UNSAFE_PATTERNS):
        return PromptDecision(False, "unsafe_request", "blocked", normalized_prompt=normalized)

    dimension = _match(normalized, _DIMENSIONS)
    metric = _match(normalized, _METRICS)
    if metric is None and _contains(normalized, "valor"):
        metric = "valor_aprovado"
    is_latest = any(
        phrase in normalized
        for phrase in ("ultima data", "data mais recente", "ultimo mes", "mes mais recente")
    )
    in_scope = bool(
        dimension or metric or any(_contains(normalized, term) for term in _HEALTHCARE_TERMS)
        or is_latest
    )
    match = re.search(r"\btop\s+(\d{1,3})\b", normalized)
    limit = min(max(int(match.group(1)), 1), 100) if match else 10

    if any(_contains(normalized, term) for term in ("ranking", "rankings", "top", "maior", "maiores")):
        operation = "ranking"
    elif _contains(normalized, "media"):
        operation = "mean"
    elif in_scope and any(_contains(normalized, term) for term in _UNSUPPORTED_STATISTICAL_TERMS):
        operation = "unsupported"
    elif any(_contains(normalized, term) for term in ("quantidade", "contagem", "quantos", "numero")):
        operation = "sum" if metric in {"quantidade_apresentada", "frequencia"} else "count"
    elif any(_contains(normalized, term) for term in ("total", "soma", "valor")):
        operation = "sum" if metric and metric != "idade" else "count"
    elif is_latest:
        operation = "latest"
    elif dimension and metric:
        operation = "sum"
    else:
        operation = None

    if not in_scope or operation is None:
        return PromptDecision(False, "outside_statistical_scope", "blocked", normalized_prompt=normalized)

    if (
        operation == "count"
        and dimension == "procedimento"
        and not _contains(normalized, "por")
        and "atendimento" not in normalized
    ):
        operation = "count_distinct"
        dimension = None
        metric = "procedimento"
    elif operation == "ranking" and metric is None:
        metric = "valor_aprovado"

    if metric is None and any(_contains(normalized, term) for term in ("registro", "registros")):
        metric = "records"

    return PromptDecision(
        True,
        "allowed_statistical_query",
        f"statistical_{operation}",
        operation,
        metric or "rows",
        dimension,
        limit,
        normalized,
    )
