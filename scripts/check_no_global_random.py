"""Fail if source uses `random.*` or `np.random.*` globals.

Determinism in Project Ghost is built on injecting a `RandomSource` from
`SimClock`. Bare `random.random()` or `np.random.normal()` bypass that and
silently break replay. ADR-0002 forbids them; this script enforces it.

Allowed: importing the modules (some libs need it), submodule access via
attribute that is not a call, and use inside this script itself.
Use `# noqa: PG-RNG` on a line to suppress, but justify in code review.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = [ROOT / "src", ROOT / "tests"]
EXCLUDE = {ROOT / "scripts", ROOT / "tests" / "conftest.py"}

# Heuristics: flag calls like `random.something(`, `np.random.something(`,
# `numpy.random.something(`, plus seeding helpers.
PATTERNS = [
    re.compile(r"\brandom\.[A-Za-z_][A-Za-z_0-9]*\s*\("),
    re.compile(r"\bnp\.random\.[A-Za-z_][A-Za-z_0-9]*\s*\("),
    re.compile(r"\bnumpy\.random\.[A-Za-z_][A-Za-z_0-9]*\s*\("),
    re.compile(r"\bnp\.random\.seed\b"),
    re.compile(r"\brandom\.seed\b"),
]

SUPPRESS_TAG = "# noqa: PG-RNG"


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for src in SRC_DIRS:
        if not src.exists():
            continue
        for path in src.rglob("*.py"):
            if any(part.startswith(".") for part in path.parts):
                continue
            if any(path.is_relative_to(ex) for ex in EXCLUDE if ex.exists()):
                continue
            files.append(path)
    return files


def check_file(path: Path) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if SUPPRESS_TAG in line:
            continue
        for pat in PATTERNS:
            if pat.search(line):
                violations.append((lineno, line.rstrip()))
                break
    return violations


def main() -> int:
    bad = 0
    for path in iter_python_files():
        for lineno, line in check_file(path):
            rel = path.relative_to(ROOT)
            print(f"{rel}:{lineno}: forbidden global random use: {line}")
            bad += 1
    if bad:
        print(
            f"\n{bad} forbidden global random use(s). Use a RandomSource "
            f"from the clock; suppress per-line with `{SUPPRESS_TAG}` only "
            "when justified.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
