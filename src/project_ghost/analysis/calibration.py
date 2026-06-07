"""Belief calibration honesty check (ADR-0019 core).

Stdlib-only. Pure. Deterministic. Observational.

For each record where the source ``BeliefTraceabilityReport`` carries a
non-degenerate ``covariance_trace``, this module exposes the **ratio**
between empirical error magnitude and the declared uncertainty scale:

- ``position_error_to_uncertainty_ratio =
    position_error_norm_m / sqrt(covariance_trace)``
- ``orientation_error_to_uncertainty_ratio =
    orientation_error_rad  / sqrt(covariance_trace)``

These are observational ratios, not statistical tests. There is no
"calibrated / uncalibrated" verdict. No threshold-based classification.
No NEES / NIS / Mahalanobis claim. The system exposes the numbers; the
operator interprets.

**Dimensional honesty.** ``covariance_trace`` mixes m², (m/s)², rad²,
(m/s²)², (rad/s)². ``sqrt(trace)`` is therefore not a per-axis position
standard deviation — it is an **upper bound on any single per-axis
standard deviation** for a PSD covariance. The ratios above are
**lower bounds on "error magnitude / per-axis declared std"**:

- A ratio much greater than 1 is robust evidence that the declared
  covariance cannot support the observed error at any per-axis
  scaling. Strong overconfidence signal.
- A ratio small relative to 1 is **inconclusive** under V1 (could
  mean well-scaled covariance or other state dimensions absorbing
  the trace). The operator interprets.

A future ADR may extend ``BeliefTraceabilityReport`` to expose
per-block covariance traces (position-only, orientation-only, etc.),
enabling per-axis-scaled ratios. That extension is out of v1 scope.

**Provenance.** Every report carries the SHA-256 hex of the bytes of
its source ``belief_report.json``. The CLI computes it; library callers
provide it explicitly. Same auditing model as ADR-0018 / 0019 manifests.

Encoding posture (frozen): ``sort_keys=True``, ``indent=2``,
``ensure_ascii=False``, trailing newline, UTF-8. Byte determinism
within fixed CPython.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from .belief_traceability import BeliefTraceabilityReport


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

BELIEF_CALIBRATION_ANALYSIS_VERSION: int = 1
BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION: str = "1"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_SHA256_HEX_LEN: int = 64
_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdef")


def _validate_sha256(s: object, *, name: str) -> None:
    if not isinstance(s, str):
        raise TypeError(f"{name} must be str; got {type(s).__name__}")
    if len(s) != _SHA256_HEX_LEN:
        raise ValueError(
            f"{name} must be {_SHA256_HEX_LEN} hex chars; got len={len(s)}"
        )
    for c in s:
        if c not in _HEX_CHARS:
            raise ValueError(
                f"{name} must be lowercase hex; got {s!r}"
            )


def _validate_envelope(
    data: object,
    *,
    schema_version: str,
    inner_key: str,
) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError(
            f"expected JSON mapping; got {type(data).__name__}"
        )
    if "schema_version" not in data:
        raise ValueError("missing 'schema_version' in JSON envelope")
    if data["schema_version"] != schema_version:
        raise ValueError(
            f"incompatible schema_version {data['schema_version']!r}; "
            f"expected {schema_version!r}"
        )
    if inner_key not in data:
        raise ValueError(f"missing {inner_key!r} in JSON envelope")
    inner = data[inner_key]
    if not isinstance(inner, Mapping):
        raise TypeError(
            f"{inner_key!r} must be a mapping; got {type(inner).__name__}"
        )
    return inner


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeliefCalibrationRecord:
    """Per-record honesty audit of declared uncertainty.

    A record is **usable for calibration** iff the source
    ``BeliefTraceRecord`` had ``covariance_available=True``,
    ``covariance_trace is not None`` and ``covariance_trace > 0``. When
    usable, the four derived fields carry the observable ratios; when
    not usable, they are ``None``.

    ``position_error_norm_m`` and ``orientation_error_rad`` are
    pass-throughs from the source record; ``covariance_trace`` is the
    pass-through total trace (mixed units — see module docstring).
    """

    timestamp_ns: int
    position_error_norm_m: float
    orientation_error_rad: float
    covariance_trace: float | None
    covariance_sqrt_trace: float | None
    position_error_to_uncertainty_ratio: float | None
    orientation_error_to_uncertainty_ratio: float | None
    usable_for_calibration: bool
    analysis_version: int = BELIEF_CALIBRATION_ANALYSIS_VERSION


@dataclass(frozen=True)
class BeliefCalibrationReport:
    """Per-record + aggregate calibration audit derived from a
    ``BeliefTraceabilityReport``.

    ``source_belief_report_sha256`` is the SHA-256 hex of the bytes of
    the belief_report file that produced this report. Required.

    Aggregate ratio fields are min / max / mean over the records where
    ``usable_for_calibration`` is ``True``. When no record is usable,
    all aggregate ratio fields are ``None``.

    There is no verdict field. No "calibrated" boolean. No score.
    Operators read the ratios and decide.
    """

    source_belief_report_sha256: str
    total_records: int
    records_usable_for_calibration: int
    records_not_usable: int
    records: tuple[BeliefCalibrationRecord, ...]

    position_error_to_uncertainty_ratio_min: float | None
    position_error_to_uncertainty_ratio_max: float | None
    position_error_to_uncertainty_ratio_mean: float | None
    orientation_error_to_uncertainty_ratio_min: float | None
    orientation_error_to_uncertainty_ratio_max: float | None
    orientation_error_to_uncertainty_ratio_mean: float | None

    analysis_version: int = BELIEF_CALIBRATION_ANALYSIS_VERSION

    def __post_init__(self) -> None:
        _validate_sha256(
            self.source_belief_report_sha256,
            name="source_belief_report_sha256",
        )
        if not isinstance(self.records, tuple):
            raise TypeError(
                f"records must be a tuple; got {type(self.records).__name__}"
            )
        if self.total_records != len(self.records):
            raise ValueError(
                f"total_records {self.total_records} != len(records) "
                f"{len(self.records)}"
            )
        if (
            self.records_usable_for_calibration + self.records_not_usable
            != self.total_records
        ):
            raise ValueError(
                "records_usable_for_calibration + records_not_usable must "
                f"equal total_records; got "
                f"{self.records_usable_for_calibration} + "
                f"{self.records_not_usable} != {self.total_records}"
            )


# ---------------------------------------------------------------------------
# analyze_belief_calibration
# ---------------------------------------------------------------------------


def analyze_belief_calibration(
    report: BeliefTraceabilityReport,
    *,
    source_belief_report_sha256: str,
) -> BeliefCalibrationReport:
    """Audit each record of ``report`` for declared-vs-empirical ratios.

    Pure function: single forward pass, no clock, no random, no I/O.

    ``source_belief_report_sha256`` is the SHA-256 hex of the source
    belief_report bytes; validated as 64 lowercase hex chars.
    """
    _validate_sha256(
        source_belief_report_sha256, name="source_belief_report_sha256"
    )

    records: list[BeliefCalibrationRecord] = []
    pos_ratios: list[float] = []
    ori_ratios: list[float] = []
    records_usable = 0

    for source_record in report.records:
        cov_trace = source_record.covariance_trace
        sqrt_trace: float | None = None
        pos_ratio: float | None = None
        ori_ratio: float | None = None
        usable = False
        if (
            source_record.covariance_available
            and cov_trace is not None
            and cov_trace > 0.0
        ):
            sqrt_trace_v = math.sqrt(cov_trace)
            pos_ratio_v = (
                source_record.position_error_norm_m / sqrt_trace_v
            )
            ori_ratio_v = (
                source_record.orientation_error_rad / sqrt_trace_v
            )
            sqrt_trace = sqrt_trace_v
            pos_ratio = pos_ratio_v
            ori_ratio = ori_ratio_v
            pos_ratios.append(pos_ratio_v)
            ori_ratios.append(ori_ratio_v)
            records_usable += 1
            usable = True

        records.append(
            BeliefCalibrationRecord(
                timestamp_ns=source_record.timestamp_ns,
                position_error_norm_m=source_record.position_error_norm_m,
                orientation_error_rad=source_record.orientation_error_rad,
                covariance_trace=cov_trace,
                covariance_sqrt_trace=sqrt_trace,
                position_error_to_uncertainty_ratio=pos_ratio,
                orientation_error_to_uncertainty_ratio=ori_ratio,
                usable_for_calibration=usable,
            )
        )

    total_records = len(records)
    records_not_usable = total_records - records_usable

    if pos_ratios:
        pos_min: float | None = min(pos_ratios)
        pos_max: float | None = max(pos_ratios)
        pos_mean: float | None = sum(pos_ratios) / len(pos_ratios)
        ori_min: float | None = min(ori_ratios)
        ori_max: float | None = max(ori_ratios)
        ori_mean: float | None = sum(ori_ratios) / len(ori_ratios)
    else:
        pos_min = None
        pos_max = None
        pos_mean = None
        ori_min = None
        ori_max = None
        ori_mean = None

    return BeliefCalibrationReport(
        source_belief_report_sha256=source_belief_report_sha256,
        total_records=total_records,
        records_usable_for_calibration=records_usable,
        records_not_usable=records_not_usable,
        records=tuple(records),
        position_error_to_uncertainty_ratio_min=pos_min,
        position_error_to_uncertainty_ratio_max=pos_max,
        position_error_to_uncertainty_ratio_mean=pos_mean,
        orientation_error_to_uncertainty_ratio_min=ori_min,
        orientation_error_to_uncertainty_ratio_max=ori_max,
        orientation_error_to_uncertainty_ratio_mean=ori_mean,
    )


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def _decode_calibration_record(
    raw: Mapping[str, Any],
) -> BeliefCalibrationRecord:
    return BeliefCalibrationRecord(
        timestamp_ns=raw["timestamp_ns"],
        position_error_norm_m=raw["position_error_norm_m"],
        orientation_error_rad=raw["orientation_error_rad"],
        covariance_trace=raw["covariance_trace"],
        covariance_sqrt_trace=raw["covariance_sqrt_trace"],
        position_error_to_uncertainty_ratio=raw[
            "position_error_to_uncertainty_ratio"
        ],
        orientation_error_to_uncertainty_ratio=raw[
            "orientation_error_to_uncertainty_ratio"
        ],
        usable_for_calibration=raw["usable_for_calibration"],
        analysis_version=raw.get(
            "analysis_version", BELIEF_CALIBRATION_ANALYSIS_VERSION
        ),
    )


def _decode_calibration_inner(
    raw: Mapping[str, Any],
) -> BeliefCalibrationReport:
    analysis_version = raw.get(
        "analysis_version", BELIEF_CALIBRATION_ANALYSIS_VERSION
    )
    if analysis_version != BELIEF_CALIBRATION_ANALYSIS_VERSION:
        raise ValueError(
            f"incompatible analysis_version {analysis_version!r}; "
            f"expected {BELIEF_CALIBRATION_ANALYSIS_VERSION!r}"
        )
    return BeliefCalibrationReport(
        source_belief_report_sha256=raw["source_belief_report_sha256"],
        total_records=raw["total_records"],
        records_usable_for_calibration=raw["records_usable_for_calibration"],
        records_not_usable=raw["records_not_usable"],
        records=tuple(
            _decode_calibration_record(r) for r in raw["records"]
        ),
        position_error_to_uncertainty_ratio_min=raw[
            "position_error_to_uncertainty_ratio_min"
        ],
        position_error_to_uncertainty_ratio_max=raw[
            "position_error_to_uncertainty_ratio_max"
        ],
        position_error_to_uncertainty_ratio_mean=raw[
            "position_error_to_uncertainty_ratio_mean"
        ],
        orientation_error_to_uncertainty_ratio_min=raw[
            "orientation_error_to_uncertainty_ratio_min"
        ],
        orientation_error_to_uncertainty_ratio_max=raw[
            "orientation_error_to_uncertainty_ratio_max"
        ],
        orientation_error_to_uncertainty_ratio_mean=raw[
            "orientation_error_to_uncertainty_ratio_mean"
        ],
        analysis_version=analysis_version,
    )


def decode_calibration_report_from_json(
    data: Mapping[str, Any],
) -> BeliefCalibrationReport:
    """Reconstruct a ``BeliefCalibrationReport`` from canonical JSON.

    Validates ``schema_version`` and ``analysis_version`` against the
    literals in this module; raises ``ValueError`` on either mismatch.
    """
    inner = _validate_envelope(
        data,
        schema_version=BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION,
        inner_key="calibration",
    )
    return _decode_calibration_inner(inner)


# ---------------------------------------------------------------------------
# Encoder + writer
# ---------------------------------------------------------------------------


def encode_calibration_report_to_bytes(
    report: BeliefCalibrationReport,
) -> bytes:
    """Encode ``report`` as canonical JSON bytes."""
    document = {
        "schema_version": BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION,
        "calibration": dataclasses.asdict(report),
    }
    serialized = json.dumps(
        document,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


def generate_calibration_report(
    report: BeliefCalibrationReport, output_path: Path
) -> None:
    """Write ``report`` as canonical JSON to ``output_path``."""
    output_path.write_bytes(encode_calibration_report_to_bytes(report))


__all__ = [
    "BELIEF_CALIBRATION_ANALYSIS_VERSION",
    "BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION",
    "BeliefCalibrationRecord",
    "BeliefCalibrationReport",
    "analyze_belief_calibration",
    "decode_calibration_report_from_json",
    "encode_calibration_report_to_bytes",
    "generate_calibration_report",
]
