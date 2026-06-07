"""Top-level ``ghost`` CLI dispatcher.

Subcommands:

- ``analyze-run``: derive a ``RunSummary`` report from an MCAP file +
  final state snapshot (T5, ADR-0013).
- ``trace-event``: reconstruct the observational pre-event message
  sequence around a target event (T6, ADR-0014). NOT explanation:
  reconstructs observed sequences, does not infer intent.
- ``analyze-belief``: align truth and belief ``VehicleState`` streams
  from two MCAP files and emit a deterministic JSON traceability
  report (ADR-0016). NOT evaluation: reconstructs paired observations,
  does not score the belief.

The CLI is intentionally tiny: argument parsing + thin glue around the
``analysis`` and ``traceability`` packages' pure functions. No
long-running processes, no network, no background threads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from project_ghost.analysis import (
    build_run_summary,
    build_traceability_report,
    encode_belief_report_to_bytes,
    generate_run_report,
)
from project_ghost.state.messages import VehicleState
from project_ghost.telemetry import MCAPReplayReader, from_json_dict
from project_ghost.traceability import (
    EventNotFoundError,
    build_behavior_trace,
    generate_trace_report,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


_NANOSECONDS_PER_SECOND: int = 1_000_000_000


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``ghost`` CLI.

    Returns process exit code:

    - ``0``: success.
    - ``1``: runtime error (e.g., event_id not found).
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

    _add_analyze_run_parser(subparsers)
    _add_trace_event_parser(subparsers)
    _add_analyze_belief_parser(subparsers)

    args = parser.parse_args(argv)

    if args.command == "analyze-run":
        return _cmd_analyze_run(args)
    if args.command == "trace-event":
        return _cmd_trace_event(args)
    if args.command == "analyze-belief":
        return _cmd_analyze_belief(args)

    # argparse with `required=True` on the subparsers prevents reaching
    # this point with an unknown command, but we keep the explicit
    # error for defensive symmetry. parser.error raises SystemExit(2).
    parser.error(f"unknown command: {args.command}")


# ---------------------------------------------------------------------------
# Subparser builders
# ---------------------------------------------------------------------------


def _add_analyze_run_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
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


def _add_trace_event_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    trace = subparsers.add_parser(
        "trace-event",
        help=(
            "Reconstruct the observational pre-event message sequence for "
            "a target event."
        ),
        description=(
            "Walks the MCAP, finds the event by sequence number, and "
            "writes a deterministic JSON trace of messages in the window "
            "before it. NOT explanation: this is observation, not "
            "inference."
        ),
    )
    trace.add_argument(
        "--mcap",
        type=Path,
        required=True,
        help="Path to the MCAP file (input; never modified).",
    )
    trace.add_argument(
        "--event-id",
        type=int,
        required=True,
        help="The target event's `sequence` field (integer).",
    )
    trace.add_argument(
        "--window-seconds",
        type=float,
        default=5.0,
        help=(
            "Window duration before the target event, in seconds. "
            "Converted to nanoseconds via int(window_seconds * 1e9). "
            "Default 5.0. Use 0 for an empty trace (the request is still "
            "valid and resolves the target event)."
        ),
    )


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


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


def _add_analyze_belief_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    analyze = subparsers.add_parser(
        "analyze-belief",
        help=(
            "Build a BeliefTraceabilityReport JSON from two MCAP files "
            "containing aligned truth and belief VehicleState streams."
        ),
        description=(
            "Reads VehicleState records from --truth-mcap and "
            "--belief-mcap, requires same length and same stamp_sim_ns "
            "per index, computes per-sample position/orientation error "
            "and covariance diagnostics, and writes a deterministic "
            "JSON report. JSON only — no text, no charts, no "
            "recommendations (ADR-0016)."
        ),
    )
    analyze.add_argument(
        "--truth-mcap",
        type=Path,
        required=True,
        help=(
            "Path to MCAP containing the truth VehicleState stream "
            "(input; never modified)."
        ),
    )
    analyze.add_argument(
        "--belief-mcap",
        type=Path,
        required=True,
        help=(
            "Path to MCAP containing the belief VehicleState stream "
            "(input; never modified)."
        ),
    )
    analyze.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path where the belief_report.json will be written. If "
            "omitted, the report is written to stdout."
        ),
    )


def _cmd_trace_event(args: argparse.Namespace) -> int:
    """Implementation of `ghost trace-event`.

    Writes the trace JSON to stdout. Returns 1 if event_id is not found.
    """
    if args.window_seconds < 0:
        sys.stderr.write(
            f"error: --window-seconds must be >= 0; got {args.window_seconds}\n"
        )
        return 1
    window_ns = int(args.window_seconds * _NANOSECONDS_PER_SECOND)

    try:
        with MCAPReplayReader(args.mcap) as reader:
            trace = build_behavior_trace(
                reader=reader,
                event_id=args.event_id,
                window_ns=window_ns,
            )
    except EventNotFoundError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    generate_trace_report(trace, output=None)
    return 0


def _read_vehicle_states_from_mcap(path: Path) -> list[VehicleState]:
    """Decode all ``VehicleState`` records from an MCAP file in order.

    Filters by schema name to avoid mis-decoding sibling channels
    that may carry other types. Records are returned in the MCAP's
    stored order (chronological by ``log_time``).
    """
    schema_name = f"{VehicleState.__module__}.{VehicleState.__name__}"
    states: list[VehicleState] = []
    with MCAPReplayReader(path) as reader:
        for msg in reader.iter_messages():
            if msg.schema_name != schema_name:
                continue
            state = from_json_dict(VehicleState, msg.payload_dict)
            states.append(state)
    return states


def _cmd_analyze_belief(args: argparse.Namespace) -> int:
    """Implementation of ``ghost analyze-belief``.

    Reads ``VehicleState`` records from both MCAPs, builds the
    traceability report, and writes the canonical JSON either to
    ``--output`` or to stdout.

    Returns ``1`` on alignment errors raised by
    ``build_traceability_report`` (length mismatch, stamp mismatch).
    """
    truth_states = _read_vehicle_states_from_mcap(args.truth_mcap)
    belief_states = _read_vehicle_states_from_mcap(args.belief_mcap)

    try:
        report = build_traceability_report(
            truth=truth_states, belief=belief_states
        )
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    encoded = encode_belief_report_to_bytes(report)
    if args.output is None:
        sys.stdout.write(encoded.decode("utf-8"))
    else:
        args.output.write_bytes(encoded)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["main"]
