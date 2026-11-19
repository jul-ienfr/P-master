"""Garde-fou ADR-001 — `src/` ne doit jamais importer le laboratoire `poker/`.

Critère de sortie n°3 de l'ADR-001 : « Aucun import de production de `src/` vers
`poker/` ». Le constat du 19/11/2026 était une violation réelle
(`src/api/routes_history.py` importait `poker.decisionmaker.v2_contracts`) ;
les contrats V2 ont été déplacés vers `src/contracts/`. Ce test empêche la
régression, y compris par import dynamique.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SRC = ROOT / "src"

# Import statique `import poker` / `import poker.x` / `from poker.x import y`.
_DYNAMIC_IMPORT = re.compile(
    r"(import_module|__import__)\s*\(\s*['\"]poker(\.|['\"])",
)


def _iter_src_modules():
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _static_poker_imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "poker" or alias.name.startswith("poker."):
                    found.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0 and (module == "poker" or module.startswith("poker.")):
                found.append((node.lineno, f"from {module} import ..."))
    return found


def test_src_has_no_static_import_of_poker_package():
    offenders = []
    for path in _iter_src_modules():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for lineno, statement in _static_poker_imports(tree):
            offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {statement}")

    assert not offenders, (
        "ADR-001 : `src/` (production) ne doit pas importer `poker/` (laboratoire). "
        "Migrer le composant utile vers `src/` : " + " ; ".join(offenders)
    )


def test_src_has_no_dynamic_import_of_poker_package():
    offenders = []
    for path in _iter_src_modules():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _DYNAMIC_IMPORT.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")

    assert (
        not offenders
    ), "ADR-001 : import dynamique de `poker/` depuis `src/` détecté : " + " ; ".join(offenders)
