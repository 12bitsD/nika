#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_TRACKED = re.compile(
    r"(msh\.team|kimi\.team|ou_2617|sk-[A-Za-z0-9_-]{12,})", re.IGNORECASE
)


def _names_in_node(root_node: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(root_node):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.split(".")[-1])
    return names


def _scan_stmt(
    stmt: ast.stmt, rel: str
) -> tuple[tuple[str, str] | None, set[str]]:
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    if isinstance(stmt, kinds) and not stmt.name.startswith("_"):
        return (rel, stmt.name), _names_in_node(stmt) - {stmt.name}
    return None, _names_in_node(stmt)


def _scan_file_defs_and_external_uses(
    py_file: Path, base: Path
) -> tuple[list[tuple[str, str]], set[str]]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), str(py_file))
    rel = str(py_file.relative_to(base))
    defs: list[tuple[str, str]] = []
    uses: set[str] = set()
    items = [_scan_stmt(stmt, rel) for stmt in tree.body]
    for found_def, stmt_uses in items:
        if found_def is not None:
            defs.append(found_def)
        uses.update(stmt_uses)
    return defs, uses


def _find_unused_public(
    src_root: Path, search_roots: tuple[Path, ...]
) -> list[str]:
    defined: list[tuple[str, str]] = []
    used: set[str] = set()
    src_files = set(src_root.rglob("*.py"))
    for py_file in sorted(src_files):
        if py_file.name == "__init__.py":
            continue
        file_defs, file_uses = _scan_file_defs_and_external_uses(
            py_file, src_root.parent
        )
        defined.extend(file_defs)
        used.update(file_uses)
    for root in search_roots:
        other_files = [
            f
            for f in sorted(root.rglob("*.py"))
            if f not in src_files and f.name != "__init__.py"
        ]
        for py_file in other_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), str(py_file))
            used.update(_names_in_node(tree))
    return [f"{rel}:{name}" for rel, name in defined if name not in used]


def _leak_in_file(repo_root: Path, rel: str) -> str | None:
    path = repo_root / rel
    if path.name == "check_hygiene.py" or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = FORBIDDEN_TRACKED.search(text)
    return f"{rel}:{match.group(0)}" if match is not None else None


def _check_workspace_secrets(repo_root: Path) -> list[str]:
    out = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        text=True,
    )
    found = [
        _leak_in_file(repo_root, rel) for rel in sorted(set(out.splitlines()))
    ]
    return [item for item in found if item is not None]


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    unused = _find_unused_public(
        repo / "src" / "nika",
        (repo / "src", repo / "tests", repo / "scripts"),
    )
    if unused:
        print("DEAD_CODE_DETECTED:", unused, file=sys.stderr)
        return 1
    leaks = _check_workspace_secrets(repo)
    if leaks:
        print("FORBIDDEN_TRACKED_STRINGS:", leaks, file=sys.stderr)
        return 1
    print("HYGIENE_OK: zero dead public symbols, zero secret/endpoint leaks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
