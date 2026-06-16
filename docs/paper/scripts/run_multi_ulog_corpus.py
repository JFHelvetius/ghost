"""CLI driver: 3-ULog x 6-category discrimination corpus (paper §8.8.1).

Runs the full six-category discrimination matrix on the three
bundled PX4 SITL ULogs and emits the reproducible JSON artefact
that §8.8.1 cites. Exit code 0 if the matrix matches the paper's
honest baseline (all six categories discriminate on every ULog
with ``fire_fraction > 0.9``); exit code 1 if that active-ULog
invariant regresses; exit code 2 on argument or fixture errors.

Usage::

    pip install 'project-ghost[adapters]'
    python docs/paper/scripts/run_multi_ulog_corpus.py \\
        --out-dir docs/paper/outputs/multi_ulog_discrimination
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from project_ghost.adapters.real_ulog_corpus import run_multi_ulog_discrimination


def _default_corpus() -> list[Path]:
    base = Path("docs/paper/data")
    return [
        base / "sample.ulg",
        base / "corpus" / "sample_appended.ulg",
        base / "corpus" / "sample_logging_tagged.ulg",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Multi-ULog discrimination corpus: 3 PX4 SITL ULogs x 6 "
            "buggy categories. Implements paper §8.8.1."
        )
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("docs/paper/outputs/multi_ulog_discrimination"),
        help="Directory where per-ULog MCAPs and matrix.json are written.",
    )
    parser.add_argument(
        "--ulog",
        type=Path,
        action="append",
        help=(
            "Override the bundled corpus. May be passed multiple times. "
            "If omitted, the three bundled ULogs in docs/paper/data/ are used."
        ),
    )
    args = parser.parse_args()

    ulogs = args.ulog if args.ulog else _default_corpus()
    missing = [p for p in ulogs if not p.exists()]
    if missing:
        for m in missing:
            print(f"ERROR: ULog not found: {m}", file=sys.stderr)
        return 2

    results = run_multi_ulog_discrimination(ulogs, args.out_dir, emit_json=True)

    print()
    print(f"Corpus              : {len(ulogs)} ULogs")
    print(f"Detection matrix    : 6 categories x {len(ulogs)} ULogs")
    print(f"all_discriminate    : {results.all_discriminate}")
    print(f"all_isolated        : {results.all_isolated}")
    print(f"JSON artefact       : {args.out_dir / 'matrix.json'}")

    # The paper's load-bearing invariant: every "active" ULog
    # (fire_fraction > 0.9) discriminates every category.
    regressions: list[str] = []
    for cat, row in results.matrix.items():
        for ulog in ulogs:
            ff = results.per_ulog[ulog.name].nominal.fpb_fire_fraction
            if ff > 0.9 and row.get(ulog.name) is not True:
                regressions.append(f"{cat} on {ulog.name} (fire_fraction={ff:.3f})")

    if regressions:
        print()
        print("REGRESSION: active-ULog discrimination invariant broken:")
        for r in regressions:
            print(f"  - {r}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
