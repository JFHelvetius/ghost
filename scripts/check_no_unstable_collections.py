"""Fail if perception/, state/, or mission/ use unstable collections.

`docs/specs/uncertainty.md` §10 forbids `set`, `frozenset`,
`collections.Counter`, and `dict.keys()` not wrapped in `sorted(...)` inside
producers (`perception/`), fusers (`state/`), and planners (`mission/`).
Iteration order over these is implementation-dependent enough to break
the determinism guarantee of ADR-0002 across CPython versions or with
non-trivial keys.

Use `# noqa: stable-collection` on a line to suppress, with a justification
in code review. The linter mirrors the CLI shape of
`scripts/check_no_global_random.py` so both can run in the same CI step.

Public entry points (for tests):

- ``check_text(text, filename)`` — pure detection.
- ``main(argv)`` — CLI. With ``argv``, treats args as explicit file paths
  to scan; without, walks the three in-scope subpackages.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
SCAN_DIRS: tuple[Path, ...] = (
    ROOT / "src" / "project_ghost" / "perception",
    ROOT / "src" / "project_ghost" / "state",
    ROOT / "src" / "project_ghost" / "mission",
)

SUPPRESS_TAG: str = "# noqa: stable-collection"

# Constructores prohibidos cuando aparecen como `Foo(...)`.
_FORBIDDEN_CALL_NAMES: tuple[str, ...] = ("set", "frozenset", "Counter")


def _is_keys_call(node: ast.Call) -> bool:
    """obj.keys() pattern."""
    return isinstance(node.func, ast.Attribute) and node.func.attr == "keys"


def _is_forbidden_constructor(node: ast.Call) -> tuple[bool, str]:
    """(True, name) if this Call is a forbidden constructor invocation."""
    func = node.func
    if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALL_NAMES:
        return True, func.id
    # `collections.Counter(...)`, `mycollections.Counter(...)`, etc.
    if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_CALL_NAMES:
        return True, func.attr
    return False, ""


def _is_sorted_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "sorted"


def check_text(text: str, filename: str = "<text>") -> list[tuple[int, str]]:  # noqa: PLR0912
    """Detecta violaciones de §10 en `text`. Devuelve (lineno, mensaje)."""
    try:
        tree = ast.parse(text, filename=filename)
    except SyntaxError as e:
        return [(e.lineno or 0, f"syntax error: {e.msg}")]

    source_lines = text.splitlines()

    # Primera pasada: marcar los `.keys()` que están directamente como argumento
    # posicional de `sorted(...)`. Esos son legítimos y NO se flaggean.
    allowed_keys_ids: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_sorted_call(node):
            for arg in node.args:
                if isinstance(arg, ast.Call) and _is_keys_call(arg):
                    allowed_keys_ids.append(id(arg))

    # Segunda pasada: recoger violaciones.
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Set):
            violations.append((node.lineno, "set literal { ... }"))
            continue
        if isinstance(node, ast.SetComp):
            violations.append((node.lineno, "set comprehension { ... for ... }"))
            continue
        if isinstance(node, ast.DictComp):
            # Diccionario por comprensión: orden estable en CPython 3.7+, pero
            # los iteradores intermedios pueden no serlo. No lo flaggeamos por
            # default; reservado para U1.c si se observan problemas.
            continue
        if isinstance(node, ast.Call):
            forbidden, name = _is_forbidden_constructor(node)
            if forbidden:
                violations.append((node.lineno, f"{name}(...) call"))
                continue
            if _is_keys_call(node) and id(node) not in allowed_keys_ids:
                violations.append(
                    (node.lineno, "dict .keys() not wrapped in sorted(...)")
                )

    # Filtrar líneas suprimidas explícitamente.
    kept: list[tuple[int, str]] = []
    for lineno, msg in violations:
        idx = lineno - 1
        if 0 <= idx < len(source_lines) and SUPPRESS_TAG in source_lines[idx]:
            continue
        kept.append((lineno, msg))
    return kept


def iter_python_files() -> list[Path]:
    """Devuelve todos los .py dentro de los subpaquetes en alcance."""
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for path in scan_dir.rglob("*.py"):
            if any(part.startswith(".") for part in path.parts):
                continue
            files.append(path)
    # Orden estable: sorted por path para reproducibilidad de output.
    return sorted(files)


def main(argv: list[str] | None = None) -> int:
    paths = [Path(a).resolve() for a in argv] if argv else iter_python_files()

    bad = 0
    for path in paths:
        if not path.exists():
            print(f"warning: {path} no existe; saltado", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, msg in check_text(text, str(path)):
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                rel = path
            print(f"{rel}:{lineno}: forbidden unstable collection: {msg}")
            bad += 1

    if bad:
        print(
            f"\n{bad} unstable collection use(s) in perception/state/mission. "
            f"Use sorted iteration; suppress per-line with "
            f"`{SUPPRESS_TAG}` only when justified.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
