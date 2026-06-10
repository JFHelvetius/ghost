"""Tests del linter `scripts/check_no_unstable_collections.py` (U1.b).

Verifica que el linter:

- detecta literales/comprensiones set, llamadas a `set`/`frozenset`/`Counter`
  y `.keys()` no envuelto en `sorted(...)`.
- pasa código limpio (incluido `sorted(d.keys())`).
- respeta el tag `# noqa: stable-collection`.
- como CLI, retorna 1 ante violaciones y 0 ante código limpio.

El script no es un paquete instalado: se carga vía `importlib` por path para
mantener el linter aislado en `scripts/` (ver `check_no_global_random.py`,
mismo patrón).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest


def _load_linter() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "scripts" / "check_no_unstable_collections.py"
    spec = importlib.util.spec_from_file_location("check_no_unstable_collections", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se pudo cargar linter desde {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_linter: ModuleType = _load_linter()


# ---------------------------------------------------------------------------
# Detección — un test por categoría para facilitar el diagnóstico
# ---------------------------------------------------------------------------


def test_unstable_collection_linter_detects_violation() -> None:
    """Smoke test global per spec U1.b: detecta al menos un caso de cada clase."""
    cases: list[tuple[str, str]] = [
        ("x = {1, 2, 3}\n", "set literal"),
        ("x = {i for i in range(5)}\n", "set comprehension"),
        ("x = set([1, 2])\n", "set(...)"),
        ("x = frozenset([1, 2])\n", "frozenset(...)"),
        ("import collections\nx = collections.Counter([1])\n", "Counter(...)"),
        ("for k in d.keys():\n    pass\n", ".keys()"),
    ]
    for src, fragment in cases:
        violations = _linter.check_text(src, f"<{fragment}>")
        assert violations, f"esperaba violación en: {src!r}"
        msgs = [m for _, m in violations]
        assert any(fragment in m for m in msgs), (
            f"esperaba {fragment!r} en {msgs!r} para fuente {src!r}"
        )


def test_linter_detects_set_literal() -> None:
    violations = _linter.check_text("x = {1, 2}\n", "<t>")
    assert violations
    assert "set literal" in violations[0][1]


def test_linter_detects_set_comprehension() -> None:
    violations = _linter.check_text("x = {i for i in range(3)}\n", "<t>")
    assert violations
    assert "set comprehension" in violations[0][1]


def test_linter_detects_set_call() -> None:
    violations = _linter.check_text("x = set()\n", "<t>")
    assert violations
    assert "set(...)" in violations[0][1]


def test_linter_detects_frozenset_call() -> None:
    violations = _linter.check_text("x = frozenset()\n", "<t>")
    assert violations
    assert "frozenset(...)" in violations[0][1]


def test_linter_detects_counter_call_qualified() -> None:
    violations = _linter.check_text("import collections\nx = collections.Counter([1, 2])\n", "<t>")
    assert violations
    assert any("Counter(...)" in m for _, m in violations)


def test_linter_detects_counter_call_bare() -> None:
    violations = _linter.check_text("x = Counter([1, 2])\n", "<t>")
    assert violations
    assert "Counter(...)" in violations[0][1]


def test_linter_detects_unwrapped_keys() -> None:
    violations = _linter.check_text("for k in d.keys():\n    pass\n", "<t>")
    assert violations
    assert ".keys()" in violations[0][1]


# ---------------------------------------------------------------------------
# Aprobación de código limpio
# ---------------------------------------------------------------------------


def test_unstable_collection_linter_passes_clean_fixture() -> None:
    """Smoke positivo per spec U1.b: código que respeta §10 no produce violaciones."""
    clean = (
        "from typing import Any\n"
        "\n"
        "def process(d: dict[str, int]) -> list[int]:\n"
        "    out: list[int] = []\n"
        "    for k in sorted(d.keys()):\n"
        "        out.append(d[k])\n"
        "    return sorted(out)\n"
        "\n"
        "RANGES: tuple[int, ...] = (1, 2, 3)\n"
        "MAP: dict[str, int] = {'a': 1, 'b': 2}\n"
    )
    assert _linter.check_text(clean, "<clean>") == []


def test_linter_sorted_keys_call_is_allowed() -> None:
    """`sorted(d.keys())` es el patrón canónico y NO debe flaggearse."""
    assert _linter.check_text("x = sorted(d.keys())\n", "<t>") == []


def test_linter_dict_literal_is_allowed() -> None:
    """Diccionarios literales (orden estable en 3.7+) no son violación."""
    assert _linter.check_text("x = {'a': 1, 'b': 2}\n", "<t>") == []


def test_linter_dict_comprehension_is_allowed() -> None:
    """Diccionarios por comprensión están explícitamente fuera del scope §10."""
    assert _linter.check_text("x = {k: v for k, v in items}\n", "<t>") == []


def test_linter_list_comprehension_is_allowed() -> None:
    assert _linter.check_text("x = [i for i in range(3)]\n", "<t>") == []


def test_linter_tuple_literal_is_allowed() -> None:
    assert _linter.check_text("x = (1, 2, 3)\n", "<t>") == []


def test_linter_import_set_module_is_allowed() -> None:
    """Importar módulos cuyo nombre coincide no es una llamada al constructor."""
    assert _linter.check_text("import collections\n", "<t>") == []


# ---------------------------------------------------------------------------
# Supresión por tag (ver `SUPPRESS_TAG` en el linter)
# ---------------------------------------------------------------------------


def test_linter_suppress_tag_silences_violation() -> None:
    # El tag se compone desde la constante del linter para que ruff no
    # malinterprete el literal como su propia directiva de supresión.
    src = f"x = {{1, 2, 3}}  {_linter.SUPPRESS_TAG}\n"
    assert _linter.check_text(src, "<suppressed>") == []


def test_linter_suppress_only_affects_tagged_line() -> None:
    src = (
        f"x = {{1, 2, 3}}  {_linter.SUPPRESS_TAG}\n"
        "y = {4, 5, 6}\n"  # esta segunda línea NO está suprimida
    )
    violations = _linter.check_text(src, "<mixed>")
    assert len(violations) == 1
    lineno, _ = violations[0]
    assert lineno == 2


# ---------------------------------------------------------------------------
# Errores de sintaxis se reportan, no crashean
# ---------------------------------------------------------------------------


def test_linter_reports_syntax_error_gracefully() -> None:
    violations = _linter.check_text("def broken(:\n", "<broken>")
    assert violations
    _, msg = violations[0]
    assert "syntax error" in msg


# ---------------------------------------------------------------------------
# CLI — `main(argv)`
# ---------------------------------------------------------------------------


def test_linter_cli_returns_zero_for_clean_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_file = tmp_path / "clean.py"
    clean_file.write_text("x = sorted(d.keys())\n", encoding="utf-8")
    rc = _linter.main([str(clean_file)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_linter_cli_returns_one_for_dirty_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dirty_file = tmp_path / "dirty.py"
    dirty_file.write_text("x = {1, 2, 3}\n", encoding="utf-8")
    rc = _linter.main([str(dirty_file)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "forbidden unstable collection" in captured.out
    assert "set literal" in captured.out


def test_linter_cli_warns_on_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does_not_exist.py"
    rc = _linter.main([str(missing)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "no existe" in captured.err


def test_linter_cli_default_scans_in_scope_dirs() -> None:
    """Sin argv, el linter recorre `perception/`, `state/`, `mission/`.

    Esos subpaquetes pueden o no existir aún (Fase 3 los crea); el linter
    debe ser tolerante y devolver 0 cuando no hay nada que escanear.
    """
    rc = _linter.main([])
    assert rc in (0, 1)  # 0 si no hay nada o todo limpio; 1 si hay violaciones reales
