"""Belief traceability report (ADR-0016).

Pure, deterministic, observational. Aligns truth and belief streams
by ``stamp_sim_ns``, computes per-sample positional / orientation
error and per-sample covariance diagnostics, and produces a frozen
``BeliefTraceabilityReport``.

**Honest framing.** This module reconstructs paired observations of
truth and belief. It does NOT:

- correct belief from truth,
- score how good the belief was,
- compute consistency metrics (NEES / NIS),
- decide whether covariance was justified,
- recommend corrective action.

Operators read the records and form their own hypotheses. The system
explicitly refuses to do so.

Encoding posture (same as ADR-0013 reports): ``sort_keys=True``,
``indent=2``, ``ensure_ascii=False``, trailing newline, UTF-8. Byte
determinism within a fixed ``(CPython, numpy, mcap library)`` tuple.
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from project_ghost.state.transforms import quat_hamilton_to_scipy

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from project_ghost.state.messages import VehicleState


BELIEF_TRACEABILITY_ANALYSIS_VERSION: int = 1
BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION: str = "1"

_POSITION_DIM: int = 3
_QUAT_DIM: int = 4


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeliefTraceRecord:
    """One aligned (truth, belief) sample.

    Quaternion fields are emitted in **scipy order** ``[x, y, z, w]``
    even though internal computation uses Hamilton ``[w, x, y, z]``;
    the conversion happens at the record boundary so downstream
    consumers (often outside Project Ghost) see the external de-facto
    standard.

    ``covariance_trace`` / ``covariance_condition_number`` are
    ``None`` when the belief sample has no covariance or when the
    computed metric is non-finite (e.g. degenerate covariance).
    ``covariance_available`` reflects only whether the belief sample
    carried a non-``None`` matrix — it does NOT reflect whether the
    metrics themselves are finite.
    """

    timestamp_ns: int
    truth_position_xyz: tuple[float, float, float]
    belief_position_xyz: tuple[float, float, float]
    truth_orientation_xyzw: tuple[float, float, float, float]
    belief_orientation_xyzw: tuple[float, float, float, float]
    position_error_norm_m: float
    orientation_error_rad: float
    covariance_trace: float | None
    covariance_condition_number: float | None
    covariance_available: bool
    analysis_version: int = BELIEF_TRACEABILITY_ANALYSIS_VERSION


@dataclass(frozen=True)
class BeliefTraceabilityReport:
    """Aggregated report over a paired (truth, belief) trajectory.

    ``records`` is preserved in input order. The report does NOT
    re-sort, dedupe, or filter.

    Aggregates over empty input are emitted as ``0.0`` by convention
    (see ADR-0016 "Limits"). ``total_samples == 0`` is the unambiguous
    signal that the aggregates carry no information.
    """

    total_samples: int
    samples_with_covariance: int
    samples_without_covariance: int
    mean_position_error_m: float
    max_position_error_m: float
    mean_orientation_error_rad: float
    max_orientation_error_rad: float
    records: tuple[BeliefTraceRecord, ...]
    analysis_version: int = BELIEF_TRACEABILITY_ANALYSIS_VERSION


# ---------------------------------------------------------------------------
# Pure error functions
# ---------------------------------------------------------------------------


def compute_position_error(truth_pos: np.ndarray, belief_pos: np.ndarray) -> float:
    """Euclidean norm of ``belief_pos - truth_pos`` in meters.

    Both inputs must be shape ``(3,)``, dtype ``float64``. The function
    does not seal or copy inputs.
    """
    _validate_vec(truth_pos, name="truth_pos", expected_len=_POSITION_DIM)
    _validate_vec(belief_pos, name="belief_pos", expected_len=_POSITION_DIM)
    return float(np.linalg.norm(belief_pos - truth_pos))


def compute_orientation_error(truth_q_wxyz: np.ndarray, belief_q_wxyz: np.ndarray) -> float:
    """Angle between two unit quaternions, in radians.

    Inputs are **Hamilton** ``[w, x, y, z]`` unit quaternions. The
    angle is ``2 * arccos(|dot(q_truth, q_belief)|)`` — the absolute
    value collapses the double cover (``q`` and ``-q`` represent the
    same rotation), giving an angle in ``[0, π]``.

    The dot product is clamped to ``[-1, 1]`` before ``arccos`` to
    absorb numerical drift on near-identical inputs.
    """
    _validate_vec(truth_q_wxyz, name="truth_q_wxyz", expected_len=_QUAT_DIM)
    _validate_vec(belief_q_wxyz, name="belief_q_wxyz", expected_len=_QUAT_DIM)
    dot = float(np.dot(truth_q_wxyz, belief_q_wxyz))
    clamped = max(-1.0, min(1.0, abs(dot)))
    return 2.0 * math.acos(clamped)


def _validate_vec(arr: np.ndarray, *, name: str, expected_len: int) -> None:
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{name} debe ser np.ndarray; recibido {type(arr).__name__}")
    if arr.shape != (expected_len,):
        raise TypeError(f"{name} debe tener shape ({expected_len},); recibido {arr.shape}")
    if arr.dtype != np.float64:
        raise TypeError(f"{name} debe tener dtype float64; recibido {arr.dtype}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} contiene NaN o Inf")


# ---------------------------------------------------------------------------
# Covariance diagnostics
# ---------------------------------------------------------------------------


def _covariance_metrics(
    cov: np.ndarray | None,
) -> tuple[float | None, float | None]:
    """Return ``(trace, condition_number)``; ``None`` if degenerate.

    JSON does not have a portable representation for ``inf`` / ``nan``,
    so non-finite metrics collapse to ``None``. This includes:

    - all-zero covariance (cond = inf via zero min eigenvalue),
    - rank-deficient covariance (cond = inf),
    - any covariance whose trace itself is non-finite (shouldn't
      happen for PSD-validated inputs, but documented defensively).
    """
    if cov is None:
        return (None, None)
    trace = float(np.trace(cov))
    # Defensive: a PSD-validated covariance with finite entries cannot
    # produce a non-finite trace, but we guard JSON output unconditionally.
    if not math.isfinite(trace):  # pragma: no cover
        trace_out: float | None = None
    else:
        trace_out = trace
    # `np.linalg.cond` returns inf for singular matrices; numpy returns a
    # numpy scalar that we coerce to float for type stability.
    cond_raw = float(np.linalg.cond(cov))
    if not math.isfinite(cond_raw):
        cond_out: float | None = None
    else:
        cond_out = cond_raw
    return (trace_out, cond_out)


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_traceability_report(
    *,
    truth: Sequence[VehicleState],
    belief: Sequence[VehicleState],
) -> BeliefTraceabilityReport:
    """Align ``truth`` and ``belief`` and produce a report.

    Requires:

    - ``len(truth) == len(belief)``; otherwise ``ValueError``.
    - ``truth[i].stamp_sim_ns == belief[i].stamp_sim_ns`` for every
      index; otherwise ``ValueError`` naming the first mismatch.

    The function does NOT interpolate, resample, or align by nearest
    neighbor. Alignment is the producer's responsibility (ADR-0016).
    """
    if len(truth) != len(belief):
        raise ValueError(
            f"build_traceability_report: longitudes incompatibles "
            f"truth={len(truth)} belief={len(belief)}"
        )

    records: list[BeliefTraceRecord] = []
    total_pos_err = 0.0
    total_ori_err = 0.0
    max_pos_err = 0.0
    max_ori_err = 0.0
    samples_with_cov = 0

    for i, (t_state, b_state) in enumerate(zip(truth, belief, strict=True)):
        if t_state.stamp_sim_ns != b_state.stamp_sim_ns:
            raise ValueError(
                f"build_traceability_report: stamp_sim_ns mismatch en "
                f"índice {i}: truth={t_state.stamp_sim_ns} "
                f"belief={b_state.stamp_sim_ns}"
            )

        t_pos = t_state.nav.pose.position_enu_m
        b_pos = b_state.nav.pose.position_enu_m
        t_q_wxyz = t_state.nav.pose.orientation_q
        b_q_wxyz = b_state.nav.pose.orientation_q

        pos_err = compute_position_error(t_pos, b_pos)
        ori_err = compute_orientation_error(t_q_wxyz, b_q_wxyz)

        cov = b_state.nav.covariance_15x15
        cov_available = cov is not None
        cov_trace, cov_cond = _covariance_metrics(cov)

        record = BeliefTraceRecord(
            timestamp_ns=int(t_state.stamp_sim_ns),
            truth_position_xyz=_as_xyz_tuple(t_pos),
            belief_position_xyz=_as_xyz_tuple(b_pos),
            truth_orientation_xyzw=_as_xyzw_tuple(quat_hamilton_to_scipy(t_q_wxyz)),
            belief_orientation_xyzw=_as_xyzw_tuple(quat_hamilton_to_scipy(b_q_wxyz)),
            position_error_norm_m=pos_err,
            orientation_error_rad=ori_err,
            covariance_trace=cov_trace,
            covariance_condition_number=cov_cond,
            covariance_available=cov_available,
        )
        records.append(record)

        total_pos_err += pos_err
        total_ori_err += ori_err
        max_pos_err = max(max_pos_err, pos_err)
        max_ori_err = max(max_ori_err, ori_err)
        if cov_available:
            samples_with_cov += 1

    n = len(records)
    if n == 0:
        mean_pos_err = 0.0
        mean_ori_err = 0.0
    else:
        mean_pos_err = total_pos_err / n
        mean_ori_err = total_ori_err / n

    return BeliefTraceabilityReport(
        total_samples=n,
        samples_with_covariance=samples_with_cov,
        samples_without_covariance=n - samples_with_cov,
        mean_position_error_m=mean_pos_err,
        max_position_error_m=max_pos_err,
        mean_orientation_error_rad=mean_ori_err,
        max_orientation_error_rad=max_ori_err,
        records=tuple(records),
    )


def _as_xyz_tuple(arr: np.ndarray) -> tuple[float, float, float]:
    return (float(arr[0]), float(arr[1]), float(arr[2]))


def _as_xyzw_tuple(arr: np.ndarray) -> tuple[float, float, float, float]:
    return (float(arr[0]), float(arr[1]), float(arr[2]), float(arr[3]))


# ---------------------------------------------------------------------------
# JSON serializer
# ---------------------------------------------------------------------------


def encode_belief_report_to_bytes(
    report: BeliefTraceabilityReport,
) -> bytes:
    """Encode ``report`` to deterministic UTF-8 JSON bytes.

    Output structure::

        {
          "schema_version": "1",
          "report": { ... fields, alphabetically sorted ... }
        }

    Encoding rules (frozen):

    - ``sort_keys=True``
    - ``indent=2``
    - ``ensure_ascii=False``
    - trailing newline
    - UTF-8

    Byte-deterministic within a fixed CPython version.
    """
    document = {
        "schema_version": BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION,
        "report": dataclasses.asdict(report),
    }
    serialized = json.dumps(
        document,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


def generate_belief_report(report: BeliefTraceabilityReport, output_path: Path) -> None:
    """Write ``report`` as a JSON file at ``output_path``.

    Overwrites if the file exists. Does not create parent directories
    — paths are not invented by this function.
    """
    output_path.write_bytes(encode_belief_report_to_bytes(report))


__all__ = [
    "BELIEF_TRACEABILITY_ANALYSIS_VERSION",
    "BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION",
    "BeliefTraceRecord",
    "BeliefTraceabilityReport",
    "build_traceability_report",
    "compute_orientation_error",
    "compute_position_error",
    "encode_belief_report_to_bytes",
    "generate_belief_report",
]
