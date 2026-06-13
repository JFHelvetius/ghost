"""PX4 ULog → Ghost pose-samples launcher (paper §8.7, candidate ADR-0037).

Thin CLI wrapper around :mod:`project_ghost.adapters.px4_ulog`. Reads
a PX4 ULog file, parses the time-aligned pose samples, and prints
the first / last events as a sanity check. Useful for confirming
that a downloaded ULog file is the shape the Ghost pipeline can
ingest before investing in a full end-to-end conversion run.

The full ULog → MCAP → ``ghost verify-properties`` chain is the
v0.3.0 deliverable; see paper §8.7 for the explicit commitment and
the documented gap.

Usage:

    pip install 'project-ghost[adapters]'
    python docs/paper/scripts/px4_ulog_adapter_skeleton.py \\
        --ulog flight.ulg

Exit code 0 if the ULog parses cleanly; 1 on any
``ULogParseError``; 2 on argument or filesystem errors.

The module is also imported by paper §8.7 commentary, so its
docstring is kept narrative.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from project_ghost.adapters.px4_ulog import (
    ULogParseError,
    parse_ulog_pose_samples,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sanity-check launcher for the PX4 ULog adapter "
            "(project_ghost.adapters.px4_ulog). Parses a .ulg file "
            "and prints the first/last pose samples."
        )
    )
    parser.add_argument("--ulog", type=Path, required=True, help="Path to .ulg file")
    args = parser.parse_args()

    if not args.ulog.exists():
        print(f"error: ULog file not found: {args.ulog}", file=sys.stderr)
        return 2

    try:
        samples = parse_ulog_pose_samples(args.ulog)
    except ULogParseError as exc:
        print(f"error: ULog parse failed: {exc}", file=sys.stderr)
        return 1

    if not samples:
        print("warning: ULog produced 0 samples (empty trace?)")
        return 0

    print(f"Parsed {len(samples)} pose samples from {args.ulog}")
    print()
    print("First sample:")
    s0 = samples[0]
    print(f"  stamp_us:         {s0.stamp_us}")
    print(f"  position_m:       {s0.position_m}")
    print(f"  position_std_m:   {s0.position_std_m}")
    print(f"  quaternion_wxyz:  {s0.quaternion_wxyz}")
    print()
    print("Last sample:")
    s_last = samples[-1]
    print(f"  stamp_us:         {s_last.stamp_us}")
    print(f"  position_m:       {s_last.position_m}")
    print(f"  position_std_m:   {s_last.position_std_m}")
    print(f"  quaternion_wxyz:  {s_last.quaternion_wxyz}")
    print()
    print(
        "Next step (v0.3.0): pipe samples through the Ghost closed-loop\n"
        "pipeline with a ground-truth source (motion capture, RTK GPS,\n"
        "or the vacuous EKF2-self fallback) to materialise an MCAP, then\n"
        "run `ghost verify-properties --mcap <output>.mcap`. See paper\n"
        "§8.7 for the commitment."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
