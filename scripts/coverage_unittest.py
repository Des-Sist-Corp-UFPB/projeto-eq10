"""Run unittest discovery with a small stdlib-only line coverage report.

This project intentionally avoids requiring network access during tests. The
preferred coverage tool is still ``coverage.py`` when available, but this script
provides a deterministic fallback for local/evaluation environments where extra
packages are not installed.
"""

from __future__ import annotations

import argparse
import ast
import os
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_ROOTS = [PROJECT_ROOT / "app_ai_chat.py", PROJECT_ROOT / "src"]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _source_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in SOURCE_ROOTS:
        if root.is_file():
            files.append(root.resolve())
        elif root.is_dir():
            files.extend(path.resolve() for path in root.rglob("*.py"))
    return sorted(files)


def _executable_lines(path: pathlib.Path) -> set[int]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return set()

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not body or not isinstance(body, list):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstring_lines.add(first.lineno)

    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno not in docstring_lines:
            lines.add(node.lineno)
    return lines


def _missing_ranges(lines: list[int]) -> str:
    if not lines:
        return ""

    ranges: list[str] = []
    start = previous = lines[0]
    for line in lines[1:]:
        if line == previous + 1:
            previous = line
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = line
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def _filename_key(filename: str) -> str:
    return os.path.normcase(os.path.abspath(filename))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run unittest with stdlib-only line coverage.")
    parser.add_argument("--tests", default="tests", help="Test discovery directory.")
    parser.add_argument("--fail-under", type=float, default=None, help="Fail if total coverage is below this percentage.")
    parser.add_argument("--show-missing", action="store_true", help="Show missing line ranges for every measured file.")
    args = parser.parse_args()

    source_files = _source_files()
    measured = {path: _executable_lines(path) for path in source_files}
    source_by_name = {_filename_key(str(path)): path for path in source_files}
    executed: dict[pathlib.Path, set[int]] = {path: set() for path in source_files}

    def tracer(frame, event, arg):
        if event != "call":
            return None

        path = source_by_name.get(_filename_key(frame.f_code.co_filename))
        if path is None:
            return None

        def line_tracer(frame, event, arg, source_path=path):
            if event == "line":
                executed.setdefault(source_path, set()).add(frame.f_lineno)
            return line_tracer

        return line_tracer

    sys.settrace(tracer)
    try:
        loader = unittest.defaultTestLoader
        suite = loader.discover(args.tests)
        runner = unittest.TextTestRunner(verbosity=1)
        result = runner.run(suite)
    finally:
        sys.settrace(None)

    print()
    print("Coverage summary")
    print("Name                                           Stmts   Miss  Cover")
    print("------------------------------------------------------------------")

    total_lines = 0
    total_missed = 0
    rows: list[tuple[float, pathlib.Path, int, int, str]] = []
    for path in source_files:
        statements = measured.get(path, set())
        if not statements:
            continue
        hit = executed.get(path, set()) & statements
        missed_lines = sorted(statements - hit)
        missed = len(missed_lines)
        total = len(statements)
        coverage = 100.0 if total == 0 else (total - missed) * 100.0 / total
        rows.append((coverage, path, total, missed, _missing_ranges(missed_lines)))
        total_lines += total
        total_missed += missed

    for coverage, path, total, missed, missing in sorted(rows, key=lambda row: _relative(row[1])):
        suffix = f"   {missing}" if args.show_missing and missing else ""
        print(f"{_relative(path):46} {total:5d} {missed:6d} {coverage:5.1f}%{suffix}")

    total_coverage = 100.0 if total_lines == 0 else (total_lines - total_missed) * 100.0 / total_lines
    print("------------------------------------------------------------------")
    print(f"TOTAL                                          {total_lines:5d} {total_missed:6d} {total_coverage:5.1f}%")

    if args.fail_under is not None and total_coverage < args.fail_under:
        print(f"Coverage failure: total {total_coverage:.1f}% is below {args.fail_under:.1f}%.")
        return 2 if result.wasSuccessful() else 1

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
