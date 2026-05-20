"""CLI simples para testar a camada isolada de IA do SIA/DATASUS."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path[:0] = [str(PROJECT_ROOT)]

from src.ai.datasus_ai import perguntar_datasus

GENERIC_ERROR_MESSAGE = (
    "Não foi possível processar a pergunta. Verifique a configuração da camada de IA."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Faça uma pergunta estatística para a camada de IA do SIA/DATASUS.",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Pergunta estatística sobre a tabela data_sus.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    prompt = " ".join(args.prompt).strip()

    if not prompt:
        print(
            'Informe uma pergunta. Exemplo: python scripts/ask_datasus_ai.py '
            '"qual o total de valor aprovado por município?"',
            file=sys.stderr,
        )
        return 1

    try:
        resposta = perguntar_datasus(prompt)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print(GENERIC_ERROR_MESSAGE, file=sys.stderr)
        return 1

    print(resposta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
