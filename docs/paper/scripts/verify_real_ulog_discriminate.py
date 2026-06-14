"""CLI driver: real PX4 ULog → discrimination experiment (paper §8.8).

Runs the same real PX4 ULog through (1) the reference policies and
(2) every ``RealULogBugCategory`` in turn, and prints the verdict
delta. Exit code 0 iff the verifier discriminates every buggy
category from nominal (i.e., every buggy category flips its
expected property); exit code 1 if any category fails to
discriminate; exit code 2 on argument errors.

Usage::

    pip install 'project-ghost[adapters]'
    python docs/paper/scripts/verify_real_ulog_discriminate.py \\
        --ulog docs/paper/data/sample.ulg \\
        --out-dir docs/paper/outputs/real_ulog_discrim
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from project_ghost.adapters.real_ulog_discrimination import (
    run_real_ulog_discrimination,
)


def _verdict(holds: bool) -> str:
    return "HOLDS   " if holds else "VIOLATED"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Real-data discrimination experiment: same real PX4 ULog, "
            "reference vs buggy policies, side-by-side verdicts. "
            "Implements paper §8.8."
        )
    )
    parser.add_argument("--ulog", type=Path, required=True, help="Path to .ulg file")
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Directory where the nominal and per-category MCAPs are written",
    )
    args = parser.parse_args()

    if not args.ulog.exists():
        print(f"error: ULog file not found: {args.ulog}", file=sys.stderr)
        return 2

    results = run_real_ulog_discrimination(args.ulog, args.out_dir)
    nom = results.nominal

    print(f"ULog input         : {args.ulog}")
    print(f"  SHA-256          : {results.ulog_sha256}")
    print(f"  pose samples     : {nom.n_pose_samples_in_ulog}")
    print(f"  cycles run       : {nom.n_cycles_run}")
    print()
    print(
        f"{'Run':38s} {'BAUD':9s} {'ERUR':9s} {'MD':9s} "
        f"{'RLB':9s} {'FPB':9s} {'MCAP SHA-256':16s}"
    )
    print("-" * 100)
    print(
        f"{'nominal (reference policies)':38s} "
        f"{_verdict(nom.baud_holds)} {_verdict(nom.erur_holds)} "
        f"{_verdict(nom.md_holds)} {_verdict(nom.rlb_holds)} "
        f"{_verdict(nom.fpb_holds)} {nom.mcap_sha256[:16]}..."
    )
    for cell in results.buggy_cells:
        s = cell.summary
        label = f"buggy: {cell.category.value} (exp {cell.expected_violator})"
        print(
            f"{label:38s} "
            f"{_verdict(s.baud_holds)} {_verdict(s.erur_holds)} "
            f"{_verdict(s.md_holds)} {_verdict(s.rlb_holds)} "
            f"{_verdict(s.fpb_holds)} {s.mcap_sha256[:16]}..."
        )
    print()
    print("Discrimination per category:")
    for cell in results.buggy_cells:
        flag = "OK" if cell.discriminates else "FAIL"
        print(
            f"  {cell.category.value:32s}  expected {cell.expected_violator} "
            f"VIOLATED  ->  {flag}"
        )
    print()
    if results.all_discriminate:
        print(
            "All buggy categories flipped their expected property on the\n"
            "real flight ULog. The verifier discriminates real telemetry\n"
            "against the same regressions caught on synthetic data in §8.2."
        )
        return 0
    missed = [
        c.category.value for c in results.buggy_cells if not c.discriminates
    ]
    print(
        "FAILURE: the following buggy categories did not flip their "
        f"expected property on the real ULog: {missed}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
