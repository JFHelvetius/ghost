"""End-to-end pinning of the GT-source A/B (paper §8.8.2).

These tests close the §8.8.2 claim that **switching the GT source
flips the verdict on the stationary ULog**, without touching the
verifier or producer policies. If a future change weakens the
distinction (e.g. by collapsing SITL GT back onto the EKF2 sample
stream), one of these tests fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_ghost.adapters.px4_ulog import GroundTruthSource, ULogParseError
from project_ghost.adapters.real_ulog_smoke import run_real_ulog_smoke


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2]


@pytest.fixture
def stationary_ulog() -> Path:
    p = _repo_root() / "docs" / "paper" / "data" / "corpus" / "sample_logging_tagged.ulg"
    if not p.exists():
        pytest.skip(f"corpus ULog missing: {p}")
    return p


@pytest.fixture
def real_only_ulog() -> Path:
    p = _repo_root() / "docs" / "paper" / "data" / "sample.ulg"
    if not p.exists():
        pytest.skip(f"sample ULog missing: {p}")
    return p


def test_auto_detect_picks_sitl_on_stationary_log(
    stationary_ulog: Path, tmp_path: Path
) -> None:
    """Default ``groundtruth_source=None`` upgrades stationary log to SITL."""
    out = tmp_path / "auto.mcap"
    summary = run_real_ulog_smoke(stationary_ulog, out)
    assert summary.groundtruth_source is GroundTruthSource.SITL_SIMULATOR
    # And the precondition actually fires.
    assert summary.fpb_fire_fraction > 0.1


def test_auto_detect_picks_ekf2_on_real_only_log(
    real_only_ulog: Path, tmp_path: Path
) -> None:
    """A ULog with no GT topics auto-detects as EKF2_FALLBACK."""
    out = tmp_path / "auto.mcap"
    summary = run_real_ulog_smoke(real_only_ulog, out)
    assert summary.groundtruth_source is GroundTruthSource.EKF2_FALLBACK


def test_forced_ekf2_on_stationary_log_keeps_legacy_behaviour(
    stationary_ulog: Path, tmp_path: Path
) -> None:
    """Forcing EKF2_FALLBACK reproduces the v0.2.4 vacuous-holds run.

    Used by paper §8.8.2 to A/B the two GT sources on the same ULog
    without varying anything else.
    """
    out = tmp_path / "forced_ekf2.mcap"
    summary = run_real_ulog_smoke(
        stationary_ulog,
        out,
        groundtruth_source=GroundTruthSource.EKF2_FALLBACK,
    )
    assert summary.groundtruth_source is GroundTruthSource.EKF2_FALLBACK
    # With circular GT, fire_fraction should collapse to ~0.
    assert summary.fpb_fire_fraction < 0.01


def test_gt_source_flips_fire_fraction_on_stationary_log(
    stationary_ulog: Path, tmp_path: Path
) -> None:
    """The A/B: same ULog, two GT sources, fire_fraction must rise > 0.5
    going from EKF2 to SITL. This is §8.8.2's load-bearing quantitative
    result; if it collapses, the §8.8.1 vacuous-HOLDS gap is no longer
    being closed.
    """
    ekf2_out = tmp_path / "ekf2.mcap"
    sitl_out = tmp_path / "sitl.mcap"
    ekf2 = run_real_ulog_smoke(
        stationary_ulog,
        ekf2_out,
        groundtruth_source=GroundTruthSource.EKF2_FALLBACK,
    )
    sitl = run_real_ulog_smoke(
        stationary_ulog,
        sitl_out,
        groundtruth_source=GroundTruthSource.SITL_SIMULATOR,
    )
    assert sitl.fpb_fire_fraction - ekf2.fpb_fire_fraction > 0.5, (
        f"SITL GT must lift fire_fraction substantially above EKF2 "
        f"on the stationary ULog. Got EKF2={ekf2.fpb_fire_fraction:.4f}, "
        f"SITL={sitl.fpb_fire_fraction:.4f}."
    )


def test_forced_sitl_on_real_only_log_raises(
    real_only_ulog: Path, tmp_path: Path
) -> None:
    """Forcing SITL on a ULog without GT topics is a programmer error."""
    out = tmp_path / "should_not_exist.mcap"
    with pytest.raises(ULogParseError):
        run_real_ulog_smoke(
            real_only_ulog,
            out,
            groundtruth_source=GroundTruthSource.SITL_SIMULATOR,
        )
