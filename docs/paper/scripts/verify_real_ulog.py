"""CLI driver: real PX4 ULog → Ghost MCAP → property verdicts (paper §8.7).

The script that closes paper §8.7's standing critique. Drives
``project_ghost.adapters.real_ulog_smoke.run_real_ulog_smoke``
end-to-end on a real PX4 flight log, materialises a Ghost-schema
MCAP, runs the five property verifiers, and prints the verdict
bundle alongside the MCAP and ULog SHA-256s.

Usage::

    pip install 'project-ghost[adapters]'
    python docs/paper/scripts/verify_real_ulog.py \\
        --ulog docs/paper/data/sample.ulg \\
        --mcap-out docs/paper/outputs/real_ulog_smoke.mcap

Exit code 0 if all properties hold; 1 if any violates; 2 on
argument errors.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from project_ghost.adapters.real_ulog_smoke import run_real_ulog_smoke


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end driver: real PX4 ULog -> Ghost MCAP -> "
            "property verdicts. Implements the v0.2.3 delivery on "
            "paper §8.7."
        )
    )
    parser.add_argument("--ulog", type=Path, required=True, help="Path to .ulg file")
    parser.add_argument("--mcap-out", type=Path, required=True, help="Where to write the MCAP")
    args = parser.parse_args()

    if not args.ulog.exists():
        print(f"error: ULog file not found: {args.ulog}", file=sys.stderr)
        return 2
    args.mcap_out.parent.mkdir(parents=True, exist_ok=True)

    summary = run_real_ulog_smoke(args.ulog, args.mcap_out)

    print(f"ULog input         : {args.ulog}")
    print(f"  SHA-256          : {summary.ulog_sha256}")
    print(f"  pose samples     : {summary.n_pose_samples_in_ulog}")
    print(f"MCAP output        : {summary.mcap_path}")
    print(f"  SHA-256          : {summary.mcap_sha256}")
    print(f"  Ghost cycles run : {summary.n_cycles_run}")
    print()
    print("Property verdicts on real flight telemetry:")
    for label, holds in (
        ("BAUD-v1", summary.baud_holds),
        ("ERUR-v1", summary.erur_holds),
        ("MD-v1  ", summary.md_holds),
        ("RLB-v1 ", summary.rlb_holds),
        ("FPB-v1 ", summary.fpb_holds),
    ):
        verdict = "HOLDS" if holds else "VIOLATED"
        print(f"  {label}:  {verdict}")
    print(f"  FPB-v1 fire_fraction = {summary.fpb_fire_fraction:.4f}")
    print()
    print(
        "Honest scope: this run uses the ULog's EKF2 estimate as both\n"
        "belief and (vacuous) ground truth. All-HOLDS is therefore a\n"
        "vacuous verdict; what is non-vacuous is that the verifier ran\n"
        "unchanged on real flight telemetry. See paper §8.7."
    )

    all_hold = (
        summary.baud_holds
        and summary.erur_holds
        and summary.md_holds
        and summary.rlb_holds
        and summary.fpb_holds
    )
    return 0 if all_hold else 1


if __name__ == "__main__":
    raise SystemExit(main())
