"""Drift-then-recovery closed-loop smoke (RLB-v1 strong witness).

The original ``closed_loop_smoke`` uses sustained drift: ground truth
moves at 5 m/s for the entire run, so the calibration history is dirty
from cycle 1 onwards and never recovers. RLB-v1 holds *vacuously*
because there are no recovery transitions to verify.

This complementary smoke engineers exactly one recovery transition by
running drift for ``n_drift_cycles`` and then teleporting ground truth
back to the origin (matching the agent's belief). After enough clean
cycles the calibration window fully flushes the dirty outcomes and
the precondition for ``count_beyond_3_or_worse == 0`` fires —
RLB-v1's ``cycles_precondition_held`` becomes ``> 0`` and the
``L(t) <= peak + W - 1`` bound is exercised against a concrete
non-trivial run.

Defaults are chosen so the recovery transition lands exactly at the
RLB bound (``L = peak + W - 1``):

- ``n_drift_cycles = 8``     → peak count of 7 (8 drift outcomes,
  the last clean outcome is from the recovery cycle itself)
- ``n_recovery_cycles = 42`` → window flushes by cycle 39, leaving
  11 trailing clean cycles for ERUR to witness PROCEED reactivation

Smoke shape (total 50 cycles):

```
cycles  1 -  3 : drift accumulating, BAUD precondition not yet met
cycles  4 -  7 : drift continues, BAUD fires (count_beyond_3+5 reaches K)
cycles  8 - 32 : ground truth at origin, outcomes within_1; window full of mix
cycles 33 - 38 : sliding window expels dirty outcomes one per cycle
cycle  39      : window fully clean - RLB recovery transition fires
cycles 39 - 49 : ERUR fires, agent emits PROCEED again
```

Stdlib + numpy + internal modules only; no clock, no random.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np

from project_ghost.examples.closed_loop_smoke import (
    _DT_NS,
    _GROUND_TRUTH_DRIFT_X_MPS,
    _T0_NS,
    SmokeSummary,
    run_closed_loop_smoke,
)
from project_ghost.state.messages import Pose

if TYPE_CHECKING:
    from collections.abc import Callable

# Default schedule chosen so the RLB bound is met *exactly* — strong
# witness that the bound is tight and the windowing logic is correct.
_DEFAULT_DRIFT_CYCLES: Final[int] = 8
_DEFAULT_RECOVERY_CYCLES: Final[int] = 42

# Drift phase must publish at least one outcome (cycle 0 has none —
# outcomes are computed from the *previous* cycle's prediction).
_MIN_DRIFT_CYCLES: Final[int] = 2
_MIN_RECOVERY_CYCLES: Final[int] = 1

# Identity orientation re-used for every ground-truth pose. Kept here
# rather than inline so the recovery-phase pose construction matches
# the drift-phase one byte-for-byte modulo the position vector.
_Q_IDENTITY: Final[np.ndarray] = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_recovery_ground_truth_fn(
    n_drift_cycles: int,
) -> Callable[[int], Pose]:
    """Build the ground-truth function for the drift-then-recovery scenario.

    Closure over ``n_drift_cycles`` so the same callable type as
    :func:`closed_loop_smoke._ground_truth_pose` (``(int) -> Pose``) is
    accepted by ``run_closed_loop_smoke`` without changing its signature.

    Behavior:

    - For ``t_ns < n_drift_cycles * _DT_NS`` after ``_T0_NS``: drift at
      ``_GROUND_TRUTH_DRIFT_X_MPS`` m/s along +X, matching the
      sustained-drift smoke.
    - For ``t_ns >= n_drift_cycles * _DT_NS`` after ``_T0_NS``: stationary
      at origin, matching the agent's oracle belief. Outcomes from here
      onwards are within_1_std, so the calibration window can clean
      itself.
    """
    drift_end_ns = _T0_NS + n_drift_cycles * _DT_NS

    def _ground_truth_pose_with_recovery(t_ns: int) -> Pose:
        if t_ns < drift_end_ns:
            dt_s = (t_ns - _T0_NS) / 1e9
            return Pose(
                position_enu_m=np.array(
                    [_GROUND_TRUTH_DRIFT_X_MPS * dt_s, 0.0, 0.0],
                    dtype=np.float64,
                ),
                orientation_q=_Q_IDENTITY,
            )
        return Pose(
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=_Q_IDENTITY,
        )

    return _ground_truth_pose_with_recovery


def run_closed_loop_smoke_with_recovery(
    output_path: Path,
    *,
    n_drift_cycles: int = _DEFAULT_DRIFT_CYCLES,
    n_recovery_cycles: int = _DEFAULT_RECOVERY_CYCLES,
) -> SmokeSummary:
    """Run the drift-then-recovery smoke and verify the property set.

    The total number of cycles is ``n_drift_cycles + n_recovery_cycles``.
    The smoke is *engineered* to fire exactly one RLB-v1 recovery
    transition with ``L = peak + W - 1`` (the bound is met exactly,
    proving it is tight).

    Parameters
    ----------
    output_path
        Where the MCAP is written. Same I/O semantics as the
        sustained-drift smoke.
    n_drift_cycles
        Length of the drift phase. Defaults to 8 so the resulting peak
        of dirty outcomes in the window is 7 (matching the RLB bound at
        the default W=32 + the default recovery length).
    n_recovery_cycles
        Length of the recovery phase. Defaults to 42 so the window
        fully flushes by cycle 39 and the agent emits PROCEED for the
        remaining 11 trailing cycles, providing ERUR witnesses.

    Returns the same ``SmokeSummary`` shape as
    :func:`run_closed_loop_smoke`, including the five property reports
    inline.
    """
    if n_drift_cycles < _MIN_DRIFT_CYCLES:
        raise ValueError(
            f"n_drift_cycles must be >= {_MIN_DRIFT_CYCLES} (so at "
            "least one outcome is published during the drift phase); "
            f"got {n_drift_cycles}"
        )
    if n_recovery_cycles < _MIN_RECOVERY_CYCLES:
        raise ValueError(
            f"n_recovery_cycles must be >= {_MIN_RECOVERY_CYCLES}; got {n_recovery_cycles}"
        )

    total_cycles = n_drift_cycles + n_recovery_cycles
    ground_truth_fn = _make_recovery_ground_truth_fn(n_drift_cycles)
    summary = run_closed_loop_smoke(
        output_path,
        n_cycles=total_cycles,
        _ground_truth_fn=ground_truth_fn,
    )
    return summary


def main() -> None:
    """CLI entry: write ``./closed_loop_smoke_with_recovery.mcap`` and print summary."""
    out = Path("closed_loop_smoke_with_recovery.mcap").resolve()
    summary = run_closed_loop_smoke_with_recovery(out)
    mcap_bytes = out.read_bytes()
    mcap_sha = hashlib.sha256(mcap_bytes).hexdigest()
    print(f"MCAP:               {summary.mcap_path}")
    print(f"SHA-256:            {mcap_sha}")
    print(f"Cycles:             {summary.n_cycles}")
    print(f"Outcomes:           {summary.n_outcomes}")
    print(f"Final verdict:      {summary.final_verdict}")
    print(f"Decisions by kind:  {summary.decisions_by_kind}")
    print(
        "Calibrated levels:  "
        + " -> ".join(summary.calibrated_levels_observed[:6])
        + " ... -> "
        + " -> ".join(summary.calibrated_levels_observed[-3:])
    )
    for tag, report, params_str in (
        (
            "BAUD-v1",
            summary.baud_report,
            f"M={summary.baud_report.min_outcomes}, K={summary.baud_report.downgrade_threshold}, ",
        ),
        (
            "ERUR-v1",
            summary.erur_report,
            f"M={summary.erur_report.min_outcomes}, K={summary.erur_report.downgrade_threshold}, ",
        ),
        ("MD-v1", summary.md_report, ""),
        ("RLB-v1", summary.rlb_report, f"W={summary.rlb_report.max_history}, "),
        ("FPB-v1", summary.fpb_report, f"fire_fraction={summary.fpb_report.fire_fraction:.2f}, "),
    ):
        verdict = "HOLDS" if report.holds else "VIOLATED"
        print(
            f"{tag}:           {verdict}  "
            f"({params_str}"
            f"{report.cycles_precondition_held}/{report.cycles_total} "
            "cycles evaluated)"
        )


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "run_closed_loop_smoke_with_recovery",
]
