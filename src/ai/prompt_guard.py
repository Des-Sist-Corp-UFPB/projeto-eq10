"""Validacoes de seguranca para prompts da camada de IA."""

from __future__ import annotations

import re
import unicodedata


MENSAGEM_BLOQUEIO = (
    "Não posso atender esse pedido. A IA só pode visualizar dados estatísticos "
    "dos últimos 3 meses disponíveis e não pode modificar código, banco de dados, "
    "arquivos ou estrutura do sistema."
)

DANGEROUS_TERMS = [
    "delete",
    "drop",
    "truncate",
    "insert",
    "update",
    "alter",
    "create table",
    "schema",
    "banco de dados",
    "estrutura do banco",
    "modifique",
    "altere",
    "apague",
    "exclua",
    "deletar",
    "crie tabela",
    "mude o codigo",
    "editar codigo",
    "sql",
    "script",
    "python",
    "arquivo",
    "terminal",
    "sistema operacional",
    "env",
    ".env",
    "senha",
    "credenciais",
    "chave",
    "token",
    "secret",
    "api key",
]

STATISTICAL_TERMS = [
    "total",
    "contagem",
    "registro",
    "registros",
    "media",
    "mediana",
    "maximo",
    "minimo",
    "frequencia",
    "quantidade",
    "valor",
    "percentual",
    "porcentagem",
    "comparacao",
    "variacao",
    "ranking",
    "distribuicao",
    "sexo",
    "idade",
    "municipio",
    "unidade",
    "procedimento",
    "procedimentos",
    "atendimento",
    "atendimentos",
    "ocupacao",
    "raca",
    "cor",
    "mes",
    "ano",
    "periodo",
]


def _normalizar_texto(texto: str) -> str:
    texto_normalizado = unicodedata.normalize("NFKD", texto.casefold())
    texto_sem_acentos = "".join(
        caractere
        for caractere in texto_normalizado
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"\s+", " ", texto_sem_acentos).strip()


def _contem_termo(texto: str, termo: str) -> bool:
    termo_normalizado = _normalizar_texto(termo)

    if re.search(r"^\w", termo_normalizado) and re.search(r"\w$", termo_normalizado):
        return re.search(rf"\b{re.escape(termo_normalizado)}\b", texto) is not None

    return termo_normalizado in texto


def validar_prompt(prompt: str) -> tuple[bool, str]:
    """Bloqueia prompts fora do escopo estatistico e pedidos de modificacao.

    A camada de IA deve apenas visualizar dados estatisticos ja existentes nos
    ultimos 3 meses disponiveis. Esta funcao impede pedidos de escrita,
    alteracao de codigo/arquivos/sistema, acesso a credenciais e comandos
    livres de SQL, scripts, Python, terminal ou sistema operacional.
    """
    if not prompt or not prompt.strip():
        return False, MENSAGEM_BLOQUEIO

    prompt_normalizado = _normalizar_texto(prompt)

    if any(_contem_termo(prompt_normalizado, termo) for termo in DANGEROUS_TERMS):
        return False, MENSAGEM_BLOQUEIO

    if not any(_contem_termo(prompt_normalizado, termo) for termo in STATISTICAL_TERMS):
        return False, MENSAGEM_BLOQUEIO

    return True, ""
