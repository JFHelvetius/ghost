"""Integration tests for the drift-then-recovery smoke.

This smoke complements the sustained-drift one by engineering exactly
one RLB-v1 recovery transition. The tests pin both the per-property
shape and the cross-property invariants that prove the smoke is a
meaningful witness for *every* member of the safety property set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_ghost.examples.closed_loop_smoke_with_recovery import (
    run_closed_loop_smoke_with_recovery,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_recovery_smoke_runs_and_produces_summary(tmp_path: Path) -> None:
    out = tmp_path / "recovery.mcap"
    summary = run_closed_loop_smoke_with_recovery(out)
    assert summary.n_cycles == 50
    assert summary.n_outcomes == 49  # one less than cycles
    assert summary.n_decisions == 50
    assert out.exists()


def test_recovery_smoke_is_byte_deterministic(tmp_path: Path) -> None:
    """Two runs with identical inputs produce identical MCAP bytes,
    same as the sustained-drift smoke."""
    a = tmp_path / "a.mcap"
    b = tmp_path / "b.mcap"
    sa = run_closed_loop_smoke_with_recovery(a)
    sb = run_closed_loop_smoke_with_recovery(b)
    assert sa.mcap_sha256 == sb.mcap_sha256
    assert a.read_bytes() == b.read_bytes()


def test_recovery_smoke_rejects_invalid_phase_lengths(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="n_drift_cycles must be >= 2"):
        run_closed_loop_smoke_with_recovery(
            tmp_path / "x.mcap",
            n_drift_cycles=1,
            n_recovery_cycles=10,
        )
    with pytest.raises(ValueError, match="n_recovery_cycles must be >= 1"):
        run_closed_loop_smoke_with_recovery(
            tmp_path / "x.mcap",
            n_drift_cycles=5,
            n_recovery_cycles=0,
        )


def test_recovery_smoke_calibration_returns_to_known(
    tmp_path: Path,
) -> None:
    """Engineering goal: the calibration window flushes after the
    recovery phase starts. Late cycles must observe ``adjusted_overall_level
    == known`` again, proving the calibrator reactivates correctly.
    """
    out = tmp_path / "recovery.mcap"
    summary = run_closed_loop_smoke_with_recovery(out)
    levels = summary.calibrated_levels_observed
    # Last three cycles must all be known (window has fully flushed).
    assert levels[-1] == "known"
    assert levels[-2] == "known"
    assert levels[-3] == "known"
    # At least one cycle in the middle must have been uncertain
    # (otherwise the smoke is no longer a witness for BAUD).
    assert "uncertain" in levels


def test_recovery_smoke_decisions_track_calibration(
    tmp_path: Path,
) -> None:
    """Decision histogram echoes the calibration trajectory: PROCEED
    only when calibration is known (cycles 1-3 + 38-49 with default
    parameters), HOLD otherwise.
    """
    out = tmp_path / "recovery.mcap"
    summary = run_closed_loop_smoke_with_recovery(out)
    # Total decisions = total cycles.
    assert sum(summary.decisions_by_kind.values()) == 50
    # PROCEED count matches the cycles where calibration was known.
    assert summary.decisions_by_kind.get("proceed", 0) == 16
    # HOLD count matches the cycles where calibration was uncertain.
    assert summary.decisions_by_kind.get("hold", 0) == 34


def test_recovery_smoke_satisfies_baud(tmp_path: Path) -> None:
    summary = run_closed_loop_smoke_with_recovery(tmp_path / "r.mcap")
    assert summary.baud_report.holds
    # BAUD fires during the drift accumulation + window-flush phases.
    assert summary.baud_report.cycles_precondition_held == 34


def test_recovery_smoke_satisfies_erur(tmp_path: Path) -> None:
    summary = run_closed_loop_smoke_with_recovery(tmp_path / "r.mcap")
    assert summary.erur_report.holds
    # ERUR fires during the pre-BAUD warmup + post-recovery cycles.
    assert summary.erur_report.cycles_precondition_held == 16


def test_recovery_smoke_satisfies_md(tmp_path: Path) -> None:
    summary = run_closed_loop_smoke_with_recovery(tmp_path / "r.mcap")
    assert summary.md_report.holds
    # MD is unconditional, so every cycle is evaluated.
    assert summary.md_report.cycles_precondition_held == 50


def test_recovery_smoke_satisfies_rlb_with_non_vacuous_witness(
    tmp_path: Path,
) -> None:
    """The whole point of this smoke: RLB fires at least once with a
    real recovery transition.

    The sustained-drift smoke has ``cycles_precondition_held == 0`` and
    holds vacuously. This smoke has ``cycles_precondition_held == 1``
    with a concrete bound exercised, proving RLB has a strong witness
    in CI and not just in property tests.
    """
    summary = run_closed_loop_smoke_with_recovery(tmp_path / "r.mcap")
    assert summary.rlb_report.holds
    # Engineered to produce exactly one recovery transition.
    assert summary.rlb_report.cycles_precondition_held == 1
    # And the first recovery cycle stamp must be populated.
    assert summary.rlb_report.first_precondition_cycle_stamp_sim_ns is not None


def test_recovery_smoke_satisfies_fpb_with_higher_fire_fraction(
    tmp_path: Path,
) -> None:
    """The recovery smoke runs BAUD-precondition territory for more
    cycles than the sustained-drift one (because the window flush
    takes time), so its fire fraction is higher: 0.68 vs 0.60."""
    summary = run_closed_loop_smoke_with_recovery(tmp_path / "r.mcap")
    assert summary.fpb_report.holds
    assert summary.fpb_report.fire_fraction == pytest.approx(0.68, rel=0.01)


def test_recovery_smoke_baud_and_erur_partition_the_cycle_space(
    tmp_path: Path,
) -> None:
    """As with the sustained-drift smoke, BAUD + ERUR cover every cycle
    between them with no overlap. Confirms the partition is robust
    across scenarios."""
    summary = run_closed_loop_smoke_with_recovery(tmp_path / "r.mcap")
    total = summary.baud_report.cycles_total
    fired = (
        summary.baud_report.cycles_precondition_held + summary.erur_report.cycles_precondition_held
    )
    assert fired == total
    assert summary.baud_report.holds
    assert summary.erur_report.holds


def test_recovery_smoke_final_verdict_is_within_1_std(
    tmp_path: Path,
) -> None:
    """The last outcome in the run is in the recovery phase, so its
    verdict must be ``within_1_std`` — confirming the recovery is
    real and not just a window-counting artefact."""
    summary = run_closed_loop_smoke_with_recovery(tmp_path / "r.mcap")
    assert summary.final_verdict == "within_1_std"
