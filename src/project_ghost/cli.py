"""Top-level ``ghost`` CLI dispatcher.

Subcommands:

- ``analyze-run``: derive a ``RunSummary`` report from an MCAP file +
  final state snapshot.

The CLI is intentionally tiny: argument parsing + thin glue around the
``analysis`` package's pure functions. No long-running processes, no
network, no background threads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from project_ghost.analysis import build_run_summary, generate_run_report
from project_ghost.state.messages import VehicleState
from project_ghost.telemetry import MCAPReplayReader, from_json_dict

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``ghost`` CLI.

    Returns process exit code:

    - ``0``: success.
    - ``2``: argument parsing failure (argparse default).
    """
    parser = argparse.ArgumentParser(
        prog="ghost",
        description=(
            "Project Ghost CLI. Subcommands operate on captured runs offline; "
            "no long-running processes or network access."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze-run",
        help=(
            "Build a RunSummary JSON report from an MCAP file plus a final "
            "state snapshot."
        ),
        description=(
            "Walks the MCAP, derives run-level counts and histograms, "
            "hashes the final state, and writes a deterministic JSON report."
        ),
    )
    analyze.add_argument(
        "--mcap",
        type=Path,
        required=True,
        help="Path to the MCAP file (input; never modified).",
    )
    analyze.add_argument(
        "--state",
        type=Path,
        required=True,
        help=(
            "Path to a JSON-encoded final VehicleState snapshot. Must be "
            "decodable by `telemetry.from_json_dict(VehicleState, ...)`."
        ),
    )
    analyze.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path where the run_report.json will be written.",
    )
    analyze.add_argument(
        "--run-id",
        type=str,
        default=None,
        help=(
            "Run identifier; defaults to the MCAP filename without "
            "extension (e.g., 'empty_room_run' for 'empty_room_run.mcap')."
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "analyze-run":
        return _cmd_analyze_run(args)

    # argparse with `required=True` on the subparsers prevents reaching
    # this point with an unknown command, but we keep the explicit
    # error for defensive symmetry. parser.error raises SystemExit(2).
    parser.error(f"unknown command: {args.command}")


def _cmd_analyze_run(args: argparse.Namespace) -> int:
    """Implementation of `ghost analyze-run`."""
    state_data = json.loads(args.state.read_text(encoding="utf-8"))
    final_state = from_json_dict(VehicleState, state_data)

    run_id = args.run_id if args.run_id is not None else args.mcap.stem

    with MCAPReplayReader(args.mcap) as reader:
        summary = build_run_summary(
            run_id=run_id,
            reader=reader,
            final_state=final_state,
        )

    generate_run_report(summary, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["main"]
