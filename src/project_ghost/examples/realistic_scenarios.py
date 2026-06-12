"""Realistic-shape closed-loop scenarios (paper §8.6; Action B).

Three closed-loop smokes that go beyond the simple sustained-drift /
single-recovery patterns of the reference smokes by encoding
drift profiles informed by the SLAM/VIO literature. Each scenario
uses the same closed-loop pipeline (fusion → self-assessment →
calibration → decision → actuation → forward prediction → divergence)
as the reference smoke, but with a custom ground-truth function that
shapes the prediction-error stream into a recognisable failure mode.

Scenarios:

- ``run_gps_denial_smoke()``: simulates a vision/inertial agent
  that loses GPS lockduring a sustained interval, drifts steadily,
  and then recovers GPS lock. The drift duration is parameterised;
  the recovery phase is long enough to flush the calibration
  window. Theorem 1's recovery latency bound applies.

- ``run_slow_biased_drift_smoke()``: simulates a chronic
  low-magnitude bias in the visual odometry — the kind that
  manifests as slow position drift that integration tools take
  many cycles to detect. The drift rate is below the threshold
  that triggers immediate BAUD downgrade, so the calibration
  window has to accumulate evidence over more cycles than the
  basic smoke.

- ``run_cascading_failure_smoke()``: simulates a multi-axis
  failure where position drift triggers first, orientation drift
  triggers second, and the agent's calibrated confidence
  cascades down through KNOWN → UNCERTAIN → (eventually if the
  per-axis hysteresis fires) UNKNOWN.

These are **shape-realistic, not data-real**: the ground-truth
functions are deterministic synthetic profiles informed by failure
modes documented in VIO/SLAM evaluation papers. For PX4 ULog or
ROSBag integration with real flight telemetry, see the roadmap in
``docs/paper/venues/dataset_integration.md`` — out of scope for
v0.2.x.

Each scenario can be invoked directly:

    $ python -m project_ghost.examples.realistic_scenarios

Produces three MCAPs and verifies the property set on each, printing
a markdown summary. Exit code 1 iff any property unexpectedly fails.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np

from project_ghost.examples.closed_loop_smoke import (
    _DT_NS,
    _T0_NS,
    SmokeSummary,
    run_closed_loop_smoke,
)
from project_ghost.state.messages import Pose

if TYPE_CHECKING:
    from collections.abc import Callable

_Q_IDENTITY: Final[np.ndarray] = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


# ---------------------------------------------------------------------------
# Scenario 1: GPS denial → drift → recovery
# ---------------------------------------------------------------------------

# Defaults so the scenario fits comfortably in a small-W TLC analogue
# while exercising a meaningful recovery.
_GPS_DENIAL_DRIFT_CYCLES: Final[int] = 6
_GPS_DENIAL_RECOVERY_CYCLES: Final[int] = 44
_GPS_DENIAL_DRIFT_X_MPS: Final[float] = 4.0


def _make_gps_denial_ground_truth(
    n_drift_cycles: int,
    drift_x_mps: float,
) -> Callable[[int], Pose]:
    """Drift linearly along +x during the denial window, then return
    to origin (the agent's belief stays at origin, so post-recovery
    cycles are within_1_std).
    """
    drift_end_ns = _T0_NS + n_drift_cycles * _DT_NS

    def _fn(t_ns: int) -> Pose:
        if t_ns < drift_end_ns:
            dt_s = (t_ns - _T0_NS) / 1e9
            return Pose(
                position_enu_m=np.array([drift_x_mps * dt_s, 0.0, 0.0], dtype=np.float64),
                orientation_q=_Q_IDENTITY,
            )
        return Pose(
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_Q_IDENTITY,
        )

    return _fn


def run_gps_denial_smoke(
    output_path: Path,
    *,
    n_drift_cycles: int = _GPS_DENIAL_DRIFT_CYCLES,
    n_recovery_cycles: int = _GPS_DENIAL_RECOVERY_CYCLES,
    drift_x_mps: float = _GPS_DENIAL_DRIFT_X_MPS,
) -> SmokeSummary:
    """Run the GPS-denial-then-recovery scenario and return its
    ``SmokeSummary`` (with the five inline property reports).
    """
    n_cycles = n_drift_cycles + n_recovery_cycles
    return run_closed_loop_smoke(
        output_path,
        n_cycles=n_cycles,
        _ground_truth_fn=_make_gps_denial_ground_truth(n_drift_cycles, drift_x_mps),
    )


# ---------------------------------------------------------------------------
# Scenario 2: Slow biased drift
# ---------------------------------------------------------------------------

# A small chronic drift rate exercises the calibration window's
# accumulation: dirty outcomes appear but at a low rate, so the
# count-of-K-in-W threshold takes longer to fire than in the basic
# smoke. The scenario length is chosen so the threshold eventually
# fires and we can witness BAUD activating.
_SLOW_DRIFT_CYCLES: Final[int] = 50
_SLOW_DRIFT_X_MPS: Final[float] = 1.0


def _make_slow_drift_ground_truth(drift_x_mps: float) -> Callable[[int], Pose]:
    """Linear drift at a low rate. Each cycle's outcome registers as
    slightly off-prediction, but the per-cycle Mahalanobis is smaller
    than the fast-drift scenario so it takes more cycles to push the
    sliding window above the K threshold.
    """

    def _fn(t_ns: int) -> Pose:
        dt_s = (t_ns - _T0_NS) / 1e9
        return Pose(
            position_enu_m=np.array([drift_x_mps * dt_s, 0.0, 0.0], dtype=np.float64),
            orientation_q=_Q_IDENTITY,
        )

    return _fn


def run_slow_biased_drift_smoke(
    output_path: Path,
    *,
    n_cycles: int = _SLOW_DRIFT_CYCLES,
    drift_x_mps: float = _SLOW_DRIFT_X_MPS,
) -> SmokeSummary:
    """Run the slow-biased-drift scenario."""
    return run_closed_loop_smoke(
        output_path,
        n_cycles=n_cycles,
        _ground_truth_fn=_make_slow_drift_ground_truth(drift_x_mps),
    )


# ---------------------------------------------------------------------------
# Scenario 3: Cascading multi-axis failure
# ---------------------------------------------------------------------------

_CASCADING_CYCLES: Final[int] = 30
_CASCADING_POS_DRIFT_MPS: Final[float] = 5.0
_CASCADING_YAW_DRIFT_RPS: Final[float] = 0.5  # ~28.6 deg/s yaw drift


def _make_cascading_ground_truth(
    pos_drift_mps: float, yaw_drift_rps: float
) -> Callable[[int], Pose]:
    """First N/3 cycles: stationary truth (no error).
    Middle N/3: position drifts along +x.
    Last N/3: position keeps drifting AND yaw rotates — multi-axis
    failure.

    The cumulative yaw is encoded as a quaternion rotation about
    the z axis: q = [cos(θ/2), 0, 0, sin(θ/2)].
    """

    def _fn(t_ns: int) -> Pose:
        dt_s = (t_ns - _T0_NS) / 1e9
        # Phase boundaries by time, not cycle index, so the function
        # depends only on its argument.
        phase_len_s = (_CASCADING_CYCLES / 3) * (_DT_NS / 1e9)
        if dt_s < phase_len_s:
            # Phase 0: stationary, no error.
            return Pose(
                position_enu_m=np.zeros(3, dtype=np.float64),
                orientation_q=_Q_IDENTITY,
            )
        if dt_s < 2.0 * phase_len_s:
            # Phase 1: position drift only.
            return Pose(
                position_enu_m=np.array(
                    [pos_drift_mps * (dt_s - phase_len_s), 0.0, 0.0],
                    dtype=np.float64,
                ),
                orientation_q=_Q_IDENTITY,
            )
        # Phase 2: position drift continues + yaw drift starts.
        pos_x = pos_drift_mps * (dt_s - phase_len_s)
        yaw_rad = yaw_drift_rps * (dt_s - 2.0 * phase_len_s)
        return Pose(
            position_enu_m=np.array([pos_x, 0.0, 0.0], dtype=np.float64),
            orientation_q=np.array(
                [np.cos(yaw_rad / 2.0), 0.0, 0.0, np.sin(yaw_rad / 2.0)],
                dtype=np.float64,
            ),
        )

    return _fn


def run_cascading_failure_smoke(
    output_path: Path,
    *,
    n_cycles: int = _CASCADING_CYCLES,
    pos_drift_mps: float = _CASCADING_POS_DRIFT_MPS,
    yaw_drift_rps: float = _CASCADING_YAW_DRIFT_RPS,
) -> SmokeSummary:
    """Run the cascading multi-axis failure scenario."""
    return run_closed_loop_smoke(
        output_path,
        n_cycles=n_cycles,
        _ground_truth_fn=_make_cascading_ground_truth(pos_drift_mps, yaw_drift_rps),
    )


# ---------------------------------------------------------------------------
# Main: run all three and print summary
# ---------------------------------------------------------------------------


def _row(label: str, summary: SmokeSummary) -> str:
    def _badge(holds: bool) -> str:
        return "OK" if holds else "VIOL"

    return (
        f"| {label} | {summary.n_cycles} | "
        f"{_badge(summary.baud_report.holds)} | "
        f"{_badge(summary.erur_report.holds)} | "
        f"{_badge(summary.md_report.holds)} | "
        f"{_badge(summary.rlb_report.holds)} | "
        f"{_badge(summary.fpb_report.holds)} | "
        f"{summary.fpb_report.fire_fraction:.2f} |"
    )


def main() -> None:
    out_dir = Path("realistic_scenarios_out").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Running realistic scenarios...\n")

    gps = run_gps_denial_smoke(out_dir / "gps_denial.mcap")
    slow = run_slow_biased_drift_smoke(out_dir / "slow_biased_drift.mcap")
    cascading = run_cascading_failure_smoke(out_dir / "cascading_failure.mcap")

    print("| Scenario | Cycles | BAUD | ERUR | MD | RLB | FPB | fire_frac |")
    print("|---|---:|:---:|:---:|:---:|:---:|:---:|---:|")
    print(_row("gps_denial", gps))
    print(_row("slow_biased_drift", slow))
    print(_row("cascading_failure", cascading))
    print()

    all_pass = all(
        s.baud_report.holds
        and s.erur_report.holds
        and s.md_report.holds
        and s.rlb_report.holds
        and s.fpb_report.holds
        for s in (gps, slow, cascading)
    )
    if all_pass:
        print("All three scenarios: 5/5 properties HOLD under the reference policy.")
        sys.exit(0)
    print("At least one property violated; inspect the report fields.")
    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "run_cascading_failure_smoke",
    "run_gps_denial_smoke",
    "run_slow_biased_drift_smoke",
]
