"""Self-assessment analysis (ADR-0020 offline path).

Pure, deterministic, stdlib-only. Reads ``BeliefSelfAssessment`` records
from a captured MCAP (channel ``/self_assessment``) and emits a
descriptive summary: counts per level per block, temporal coverage
fractions, timestamp range. Observational only — no verdict, no
classification beyond the levels the agent itself declared.

Encoding posture (frozen): ``sort_keys=True``, ``indent=2``,
``ensure_ascii=False``, trailing newline, UTF-8 — same as ADR-0013 /
0016 / 0017 / 0018 / 0019.

The CLI ``ghost analyze-self-assessment --mcap PATH [--output PATH]``
wraps this module.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from project_ghost.core.uncertainty.self_assessment import (
    BeliefSelfAssessment,
    SelfAssessmentLevel,
)
from project_ghost.telemetry import (
    CHANNEL_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

SELF_ASSESSMENT_SUMMARY_ANALYSIS_VERSION: int = 1
SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION: str = "1"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelCounts:
    """Per-level record count for one block (or overall).

    Sum equals the count of records used to build the parent summary
    (since every record contributes exactly one level per block).
    """

    known: int
    uncertain: int
    unknown: int

    def __post_init__(self) -> None:
        for name, v in (
            ("known", self.known),
            ("uncertain", self.uncertain),
            ("unknown", self.unknown),
        ):
            if v < 0:
                raise ValueError(f"LevelCounts: {name} must be >= 0; got {v}")

    def total(self) -> int:
        return self.known + self.uncertain + self.unknown


@dataclass(frozen=True)
class SelfAssessmentSummary:
    """Aggregate over a sequence of ``BeliefSelfAssessment`` records.

    Counts per level for each block's ``*_overall_level`` field and for
    the global ``overall_level``. Timestamp coverage (first / last /
    span) derived from ``belief_stamp_sim_ns``. Empty input → zero
    counts, ``None`` for timestamps.
    """

    total_records: int

    position_counts: LevelCounts
    velocity_counts: LevelCounts
    orientation_counts: LevelCounts
    overall_counts: LevelCounts

    timestamp_first_ns: int | None
    timestamp_last_ns: int | None
    timestamp_span_ns: int | None

    # Distinct thresholds_sha256 observed (tuple alphabetically sorted).
    # If the agent ran with a single configuration, this has length 1.
    # Length > 1 signals heterogeneity in the run's threshold set —
    # purely observational signal for the operator.
    distinct_thresholds_sha256: tuple[str, ...]

    analysis_version: int = SELF_ASSESSMENT_SUMMARY_ANALYSIS_VERSION

    def __post_init__(self) -> None:
        if self.total_records < 0:
            raise ValueError(f"total_records must be >= 0; got {self.total_records}")
        if not isinstance(self.distinct_thresholds_sha256, tuple):
            raise TypeError(
                "distinct_thresholds_sha256 must be a tuple; got "
                f"{type(self.distinct_thresholds_sha256).__name__}"
            )
        # Per-block counts must sum to total_records.
        for name, counts in (
            ("position_counts", self.position_counts),
            ("velocity_counts", self.velocity_counts),
            ("orientation_counts", self.orientation_counts),
            ("overall_counts", self.overall_counts),
        ):
            if counts.total() != self.total_records:
                raise ValueError(
                    f"{name}.total() ({counts.total()}) must equal "
                    f"total_records ({self.total_records})"
                )


# ---------------------------------------------------------------------------
# summarize_self_assessments
# ---------------------------------------------------------------------------


def _bump(counts: dict[SelfAssessmentLevel, int], level: SelfAssessmentLevel) -> None:
    counts[level] += 1


def _to_level_counts(counts: dict[SelfAssessmentLevel, int]) -> LevelCounts:
    return LevelCounts(
        known=counts[SelfAssessmentLevel.KNOWN],
        uncertain=counts[SelfAssessmentLevel.UNCERTAIN],
        unknown=counts[SelfAssessmentLevel.UNKNOWN],
    )


def summarize_self_assessments(
    records: tuple[BeliefSelfAssessment, ...],
) -> SelfAssessmentSummary:
    """Aggregate descriptive counts + timestamp coverage.

    Pure function — single forward pass, no clock, no random, no I/O.
    Preserves input order: timestamp_first/last are min/max, NOT
    ``records[0]`` / ``records[-1]``.
    """
    pos_counts: dict[SelfAssessmentLevel, int] = {
        SelfAssessmentLevel.KNOWN: 0,
        SelfAssessmentLevel.UNCERTAIN: 0,
        SelfAssessmentLevel.UNKNOWN: 0,
    }
    vel_counts = dict(pos_counts)
    ori_counts = dict(pos_counts)
    overall_counts = dict(pos_counts)

    distinct_hashes: set[str] = set()

    if records:
        timestamps = [r.belief_stamp_sim_ns for r in records]
        first_ns: int | None = min(timestamps)
        last_ns: int | None = max(timestamps)
        # last_ns and first_ns are int when records is non-empty.
        assert first_ns is not None  # for type narrowing
        assert last_ns is not None
        span_ns: int | None = last_ns - first_ns
    else:
        first_ns = None
        last_ns = None
        span_ns = None

    for r in records:
        _bump(pos_counts, r.position_overall_level)
        _bump(vel_counts, r.velocity_overall_level)
        _bump(ori_counts, r.orientation_overall_level)
        _bump(overall_counts, r.overall_level)
        distinct_hashes.add(r.thresholds_sha256)

    return SelfAssessmentSummary(
        total_records=len(records),
        position_counts=_to_level_counts(pos_counts),
        velocity_counts=_to_level_counts(vel_counts),
        orientation_counts=_to_level_counts(ori_counts),
        overall_counts=_to_level_counts(overall_counts),
        timestamp_first_ns=first_ns,
        timestamp_last_ns=last_ns,
        timestamp_span_ns=span_ns,
        distinct_thresholds_sha256=tuple(sorted(distinct_hashes)),
    )


# ---------------------------------------------------------------------------
# MCAP reader
# ---------------------------------------------------------------------------


def read_self_assessments_from_mcap(
    mcap_path: Path,
) -> tuple[BeliefSelfAssessment, ...]:
    """Read every ``BeliefSelfAssessment`` from the ``/self_assessment``
    channel of ``mcap_path``, in stored order.

    Filters by channel (not by schema name) so a stream that uses a
    non-default channel name is intentionally skipped. The decoder
    catalogue handles type reconstruction.
    """
    records: list[BeliefSelfAssessment] = []
    with MCAPReplayReader(mcap_path) as reader:
        for msg in reader.iter_messages():
            if msg.channel != CHANNEL_SELF_ASSESSMENT:
                continue
            decoded = decode_message(msg)
            if isinstance(decoded, BeliefSelfAssessment):
                records.append(decoded)
    return tuple(records)


# ---------------------------------------------------------------------------
# Encoder + writer
# ---------------------------------------------------------------------------


def encode_self_assessment_summary_to_bytes(
    summary: SelfAssessmentSummary,
) -> bytes:
    """Encode ``summary`` as canonical UTF-8 JSON bytes."""
    document = {
        "schema_version": SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION,
        "summary": dataclasses.asdict(summary),
    }
    serialized = json.dumps(
        document,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


def generate_self_assessment_summary(summary: SelfAssessmentSummary, output_path: Path) -> None:
    """Write ``summary`` as canonical JSON to ``output_path``."""
    output_path.write_bytes(encode_self_assessment_summary_to_bytes(summary))


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def _validate_envelope(
    data: object,
    *,
    schema_version: str,
    inner_key: str,
) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(f"expected JSON mapping; got {type(data).__name__}")
    if "schema_version" not in data:
        raise ValueError("missing 'schema_version' in JSON envelope")
    if data["schema_version"] != schema_version:
        raise ValueError(
            f"incompatible schema_version {data['schema_version']!r}; expected {schema_version!r}"
        )
    if inner_key not in data:
        raise ValueError(f"missing {inner_key!r} in JSON envelope")
    inner = data[inner_key]
    if not isinstance(inner, Mapping):
        raise TypeError(f"{inner_key!r} must be a mapping; got {type(inner).__name__}")
    return inner


def _decode_level_counts(raw: Mapping[str, Any]) -> LevelCounts:
    return LevelCounts(
        known=raw["known"],
        uncertain=raw["uncertain"],
        unknown=raw["unknown"],
    )


def decode_self_assessment_summary_from_json(
    data: Mapping[str, Any],
) -> SelfAssessmentSummary:
    """Reconstruct a ``SelfAssessmentSummary`` from canonical JSON.

    Validates ``schema_version`` and ``analysis_version``.
    """
    inner = _validate_envelope(
        data,
        schema_version=SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION,
        inner_key="summary",
    )
    analysis_version = inner.get("analysis_version", SELF_ASSESSMENT_SUMMARY_ANALYSIS_VERSION)
    if analysis_version != SELF_ASSESSMENT_SUMMARY_ANALYSIS_VERSION:
        raise ValueError(
            f"incompatible analysis_version {analysis_version!r}; "
            f"expected {SELF_ASSESSMENT_SUMMARY_ANALYSIS_VERSION!r}"
        )
    return SelfAssessmentSummary(
        total_records=inner["total_records"],
        position_counts=_decode_level_counts(inner["position_counts"]),
        velocity_counts=_decode_level_counts(inner["velocity_counts"]),
        orientation_counts=_decode_level_counts(inner["orientation_counts"]),
        overall_counts=_decode_level_counts(inner["overall_counts"]),
        timestamp_first_ns=inner["timestamp_first_ns"],
        timestamp_last_ns=inner["timestamp_last_ns"],
        timestamp_span_ns=inner["timestamp_span_ns"],
        distinct_thresholds_sha256=tuple(inner["distinct_thresholds_sha256"]),
        analysis_version=analysis_version,
    )


__all__ = [
    "SELF_ASSESSMENT_SUMMARY_ANALYSIS_VERSION",
    "SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION",
    "LevelCounts",
    "SelfAssessmentSummary",
    "decode_self_assessment_summary_from_json",
    "encode_self_assessment_summary_to_bytes",
    "generate_self_assessment_summary",
    "read_self_assessments_from_mcap",
    "summarize_self_assessments",
]
