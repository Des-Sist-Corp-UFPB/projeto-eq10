"""Diagnostico isolado da inicializacao do PySUS SIA."""

from __future__ import annotations

from datetime import datetime


RECOMMENDATION = (
    "Recomendacao: em Windows, rode a ETL via Docker ou WSL/Linux para "
    "evitar a recursao interna observada no PySUS/FTP."
)
WINDOWS_PATH_RECOMMENDATION = (
    r"Primeiro teste recomendado no Windows: mova o projeto para um caminho "
    r"simples, como C:\dev\DSC_SEC-MME, sem OneDrive, espacos ou acentos."
)


def _print_error(prefix: str, error: Exception) -> None:
    print(prefix)
    print(f"Tipo: {type(error).__name__}")
    print(f"Mensagem: {error}")


def _print_import_error(error: Exception) -> None:
    _print_error("Erro ao importar SIA", error)
    print("Etapa: import from pysus import SIA")
    if isinstance(error, RecursionError):
        print(
            "Diagnostico: o PySUS falhou durante o import, antes da criacao "
            "de SIA() e antes de SIA().load()."
        )
        print(
            "Contexto conhecido: em alguns ambientes Windows, o traceback "
            "aponta recursao interna em pysus/ftp/__init__.py, especialmente "
            "em chamadas Directory(parent_path)."
        )
        print(WINDOWS_PATH_RECOMMENDATION)
        print(RECOMMENDATION)


def main() -> int:
    try:
        from pysus import SIA
    except Exception as error:
        _print_import_error(error)
        return 1

    print("Import OK")

    try:
        sia = SIA()
    except Exception as error:
        _print_error("Erro ao criar instancia SIA", error)
        return 1

    print("Instância SIA OK")

    try:
        loaded_sia = sia.load()
    except Exception as error:
        _print_error("Erro ao carregar SIA", error)
        print(RECOMMENDATION)
        return 1

    print("Load SIA OK")

    try:
        year = datetime.now().year
        files = loaded_sia.get_files(group="PA", uf="PB", year=year)
    except Exception as error:
        _print_error("Erro ao listar arquivos PA/PB", error)
        return 1

    print(f"Listagem PA/PB OK | Ano: {year} | Arquivos encontrados: {len(files)}")
    if files:
        print(f"Primeiro arquivo: {files[0].name}")
        print(f"Ultimo arquivo: {files[-1].name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
