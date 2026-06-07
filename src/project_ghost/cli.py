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
- ``summarize-belief``: aggregate descriptive statistics over a
  ``BeliefTraceabilityReport`` and emit a deterministic JSON
  consistency summary (ADR-0017). NOT evaluation: descriptive
  statistics only.
- ``build-manifest``: hash declared inputs and outputs of a run and
  emit a deterministic ``RunManifest`` JSON (ADR-0018). Provenance,
  not interpretation.
- ``compare-belief``: aggregate N labeled
  ``BeliefConsistencySummary`` instances into a deterministic
  ``ComparativeBeliefReport`` JSON (ADR-0018). Description is not
  evaluation; comparison is not judgment.

The CLI is intentionally tiny: argument parsing + thin glue around the
``analysis`` and ``traceability`` packages' pure functions. No
long-running processes, no network, no background threads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_ghost.analysis import (
    LabeledSummary,
    build_comparative_report,
    build_run_manifest,
    build_run_summary,
    build_traceability_report,
    decode_belief_report_from_json,
    decode_consistency_summary_from_json,
    decode_run_manifest_from_json,
    encode_belief_report_to_bytes,
    encode_comparative_report_to_bytes,
    encode_consistency_summary_to_bytes,
    encode_run_manifest_to_bytes,
    generate_run_report,
    summarize_belief_consistency,
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
    _add_summarize_belief_parser(subparsers)
    _add_build_manifest_parser(subparsers)
    _add_compare_belief_parser(subparsers)

    args = parser.parse_args(argv)

    if args.command == "analyze-run":
        return _cmd_analyze_run(args)
    if args.command == "trace-event":
        return _cmd_trace_event(args)
    if args.command == "analyze-belief":
        return _cmd_analyze_belief(args)
    if args.command == "summarize-belief":
        return _cmd_summarize_belief(args)
    if args.command == "build-manifest":
        return _cmd_build_manifest(args)
    if args.command == "compare-belief":
        return _cmd_compare_belief(args)

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


def _add_summarize_belief_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    summarize = subparsers.add_parser(
        "summarize-belief",
        help=(
            "Aggregate descriptive statistics over a "
            "BeliefTraceabilityReport JSON (ADR-0017)."
        ),
        description=(
            "Reads the canonical JSON produced by `ghost analyze-belief`, "
            "computes min / max / mean over per-sample errors and "
            "covariance diagnostics, and writes a deterministic JSON "
            "summary. JSON only — no text, no charts, no recommendations. "
            "Description is not evaluation (ADR-0017)."
        ),
    )
    summarize.add_argument(
        "--report",
        type=Path,
        required=True,
        help=(
            "Path to the BeliefTraceabilityReport JSON file "
            "(input; never modified)."
        ),
    )
    summarize.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path where the consistency_summary.json will be written. "
            "If omitted, the summary is written to stdout."
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


def _add_build_manifest_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    bm = subparsers.add_parser(
        "build-manifest",
        help=(
            "Hash declared inputs and outputs of a run, attach an opaque "
            "config descriptor, and emit a deterministic RunManifest JSON "
            "(ADR-0018)."
        ),
        description=(
            "Computes SHA-256 of every --input and --output-artifact file, "
            "merges --config-json (if any) with --config-kv overrides, and "
            "writes a canonical JSON manifest. Provenance only — no "
            "interpretation, no signing, no path canonicalization."
        ),
    )
    bm.add_argument(
        "--run-id",
        type=str,
        required=True,
        help="Caller-chosen run identifier (e.g., 'ablation_sigma_0p05').",
    )
    bm.add_argument(
        "--config-json",
        type=Path,
        default=None,
        help=(
            "Path to a JSON object whose contents become the initial "
            "config_descriptor (input; never modified)."
        ),
    )
    bm.add_argument(
        "--config-kv",
        type=str,
        action="append",
        default=None,
        help=(
            "Override pair KEY=VALUE merged into config_descriptor "
            "after --config-json (repeatable). VALUE is stored as string."
        ),
    )
    bm.add_argument(
        "--input",
        type=str,
        action="append",
        default=None,
        help=(
            "Declared input artifact as PATH=KIND (repeatable). KIND is a "
            "free-form taxonomy hint, e.g. 'mcap_truth', 'mcap_belief'."
        ),
    )
    bm.add_argument(
        "--output-artifact",
        type=str,
        action="append",
        default=None,
        help=(
            "Declared output artifact as PATH=KIND (repeatable). KIND is "
            "a free-form taxonomy hint, e.g. 'belief_report', "
            "'consistency_summary'."
        ),
    )
    bm.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path where the manifest JSON is written. If omitted, the "
            "manifest is written to stdout."
        ),
    )


def _add_compare_belief_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    cb = subparsers.add_parser(
        "compare-belief",
        help=(
            "Aggregate N labeled BeliefConsistencySummary instances into a "
            "deterministic ComparativeBeliefReport JSON (ADR-0018)."
        ),
        description=(
            "Reads each --summary file, optionally pairs with a --manifest "
            "file of the same label, and emits a comparison whose first "
            "label is the baseline. Description is not evaluation, "
            "comparison is not judgment."
        ),
    )
    cb.add_argument(
        "--summary",
        type=str,
        action="append",
        required=True,
        help=(
            "Summary as LABEL=PATH (repeatable; >=1). The first entry is "
            "the baseline. Each path must point to a "
            "BeliefConsistencySummary JSON produced by `ghost "
            "summarize-belief`."
        ),
    )
    cb.add_argument(
        "--manifest",
        type=str,
        action="append",
        default=None,
        help=(
            "Optional manifest as LABEL=PATH (repeatable). Each label "
            "must match one of --summary; labels without a manifest "
            "appear with null in the report."
        ),
    )
    cb.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path where the comparative report JSON is written. If "
            "omitted, the report is written to stdout."
        ),
    )


def _cmd_summarize_belief(args: argparse.Namespace) -> int:
    """Implementation of ``ghost summarize-belief``.

    Reads the report JSON, decodes via
    ``decode_belief_report_from_json``, summarizes, and writes the
    canonical JSON to ``--output`` or to stdout.

    Returns ``1`` on any of:

    - missing input file (``FileNotFoundError``),
    - malformed JSON (``json.JSONDecodeError``),
    - schema mismatch or decoder failure (``ValueError`` / ``TypeError``
      / ``KeyError`` raised by ``decode_belief_report_from_json`` or
      the dataclass constructors it invokes).
    """
    try:
        raw = args.report.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"error: invalid JSON in {args.report}: {e}\n")
        return 1

    try:
        report = decode_belief_report_from_json(data)
    except (TypeError, ValueError, KeyError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    summary = summarize_belief_consistency(report)
    encoded = encode_consistency_summary_to_bytes(summary)
    if args.output is None:
        sys.stdout.write(encoded.decode("utf-8"))
    else:
        args.output.write_bytes(encoded)
    return 0


# ---------------------------------------------------------------------------
# ADR-0018: build-manifest and compare-belief helpers + implementations
# ---------------------------------------------------------------------------


def _split_key_value(s: str) -> tuple[str, str]:
    """Parse ``KEY=VALUE``. Splits on the first ``=`` so VALUE may
    contain further ``=`` characters; KEY must be non-empty."""
    if "=" not in s:
        raise ValueError(f"expected KEY=VALUE; got {s!r}")
    key, value = s.split("=", 1)
    if not key:
        raise ValueError(f"KEY must be non-empty; got {s!r}")
    return key, value


def _split_label_path(s: str) -> tuple[str, str]:
    """Parse ``LABEL=PATH``. Splits on the first ``=``; both halves
    must be non-empty."""
    if "=" not in s:
        raise ValueError(f"expected LABEL=PATH; got {s!r}")
    label, path = s.split("=", 1)
    if not label or not path:
        raise ValueError(
            f"LABEL and PATH must both be non-empty; got {s!r}"
        )
    return label, path


def _split_path_kind(s: str) -> tuple[str, str]:
    """Parse ``PATH=KIND``. Splits on the LAST ``=`` so PATH may
    contain ``=`` characters; both halves must be non-empty."""
    if "=" not in s:
        raise ValueError(f"expected PATH=KIND; got {s!r}")
    path, kind = s.rsplit("=", 1)
    if not path or not kind:
        raise ValueError(
            f"PATH and KIND must both be non-empty; got {s!r}"
        )
    return path, kind


def _cmd_build_manifest(args: argparse.Namespace) -> int:  # noqa: PLR0911
    """Implementation of ``ghost build-manifest``.

    Returns ``1`` on: missing input file, malformed --config-json,
    invalid --config-kv / --input / --output-artifact format,
    or validation failure inside ``build_run_manifest``.

    PLR0911 is silenced because each early return is a distinct
    error path with a distinct stderr message; collapsing them
    behind a sentinel would reduce clarity.
    """
    config: dict[str, Any] = {}
    if args.config_json is not None:
        try:
            raw = args.config_json.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as e:
            sys.stderr.write(f"error: {e}\n")
            return 1
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.stderr.write(
                f"error: invalid JSON in --config-json: {e}\n"
            )
            return 1
        if not isinstance(loaded, dict):
            sys.stderr.write(
                "error: --config-json must contain a JSON object; got "
                f"{type(loaded).__name__}\n"
            )
            return 1
        config.update(loaded)

    if args.config_kv is not None:
        for kv in args.config_kv:
            try:
                key, value = _split_key_value(kv)
            except ValueError as e:
                sys.stderr.write(f"error: --config-kv {e}\n")
                return 1
            config[key] = value

    try:
        inputs = [
            _split_path_kind(s) for s in (args.input or [])
        ]
        outputs = [
            _split_path_kind(s) for s in (args.output_artifact or [])
        ]
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    try:
        manifest = build_run_manifest(
            run_id=args.run_id,
            config_descriptor=config,
            inputs=[(Path(p), k) for p, k in inputs],
            outputs=[(Path(p), k) for p, k in outputs],
        )
    except (FileNotFoundError, OSError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    except (TypeError, ValueError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    encoded = encode_run_manifest_to_bytes(manifest)
    if args.output is None:
        sys.stdout.write(encoded.decode("utf-8"))
    else:
        args.output.write_bytes(encoded)
    return 0


def _read_json_file(path: Path) -> dict[str, Any] | None:
    """Read and parse a JSON object from ``path``. Returns ``None`` and
    writes to stderr on any failure (so the caller just returns 1)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        sys.stderr.write(f"error: {e}\n")
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"error: invalid JSON in {path}: {e}\n")
        return None
    if not isinstance(loaded, dict):
        sys.stderr.write(
            f"error: expected JSON object in {path}; got "
            f"{type(loaded).__name__}\n"
        )
        return None
    return loaded


def _cmd_compare_belief(  # noqa: PLR0911, PLR0912
    args: argparse.Namespace,
) -> int:
    """Implementation of ``ghost compare-belief``.

    Returns ``1`` on: invalid --summary / --manifest format, duplicate
    label, missing or malformed input file, schema_version mismatch,
    or a --manifest label without a matching --summary.

    PLR0911 / PLR0912 silenced: each early return / branch is a
    distinct error path with distinct stderr messaging.
    """
    summary_paths: dict[str, Path] = {}
    label_order: list[str] = []
    for entry in args.summary:
        try:
            label, path_str = _split_label_path(entry)
        except ValueError as e:
            sys.stderr.write(f"error: --summary {e}\n")
            return 1
        if label in summary_paths:
            sys.stderr.write(
                f"error: duplicate --summary label {label!r}\n"
            )
            return 1
        summary_paths[label] = Path(path_str)
        label_order.append(label)

    manifest_paths: dict[str, Path] = {}
    if args.manifest is not None:
        for entry in args.manifest:
            try:
                label, path_str = _split_label_path(entry)
            except ValueError as e:
                sys.stderr.write(f"error: --manifest {e}\n")
                return 1
            if label not in summary_paths:
                sys.stderr.write(
                    f"error: --manifest label {label!r} has no matching "
                    "--summary\n"
                )
                return 1
            if label in manifest_paths:
                sys.stderr.write(
                    f"error: duplicate --manifest label {label!r}\n"
                )
                return 1
            manifest_paths[label] = Path(path_str)

    labeled: list[LabeledSummary] = []
    for label in label_order:
        summary_data = _read_json_file(summary_paths[label])
        if summary_data is None:
            return 1
        try:
            summary = decode_consistency_summary_from_json(summary_data)
        except (TypeError, ValueError, KeyError) as e:
            sys.stderr.write(f"error: {e}\n")
            return 1

        manifest = None
        if label in manifest_paths:
            manifest_data = _read_json_file(manifest_paths[label])
            if manifest_data is None:
                return 1
            try:
                manifest = decode_run_manifest_from_json(manifest_data)
            except (TypeError, ValueError, KeyError) as e:
                sys.stderr.write(f"error: {e}\n")
                return 1

        labeled.append(
            LabeledSummary(label=label, summary=summary, manifest=manifest)
        )

    try:
        report = build_comparative_report(labeled)
    except ValueError as e:  # pragma: no cover
        # Defensive: duplicate labels and empty input are validated above,
        # so build_comparative_report cannot raise from this site under
        # current CLI flow. Kept for forward-compatibility with future
        # invariants added to build_comparative_report.
        sys.stderr.write(f"error: {e}\n")
        return 1

    encoded = encode_comparative_report_to_bytes(report)
    if args.output is None:
        sys.stdout.write(encoded.decode("utf-8"))
    else:
        args.output.write_bytes(encoded)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["main"]
