"""Tests for the independent-GT-source adapter (ADR-0037, paper §8.8.2).

Pins the v0.2.5 behaviour:

- ``detect_groundtruth_source`` returns ``SITL_SIMULATOR`` iff both
  ``vehicle_local_position_groundtruth`` and
  ``vehicle_attitude_groundtruth`` are present.
- ``parse_ulog_groundtruth_samples`` raises ``ULogParseError`` (not
  silent EKF2 fallback) on a ULog without GT topics. Silent fallback
  would re-introduce the circular GT that §8.8.2 exists to remove.
- The bundled corpus matches its design intent:
  ``sample_logging_tagged.ulg`` carries SITL GT; ``sample.ulg`` and
  ``sample_appended.ulg`` do not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_ghost.adapters.px4_ulog import (
    GroundTruthSource,
    ULogGroundTruthSample,
    ULogParseError,
    detect_groundtruth_source,
    parse_ulog_groundtruth_samples,
    parse_ulog_pose_samples,
)


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


def test_detect_returns_sitl_simulator_when_gt_topics_present(
    stationary_ulog: Path,
) -> None:
    """The stationary corpus ULog ships SITL GT topics."""
    assert detect_groundtruth_source(stationary_ulog) is GroundTruthSource.SITL_SIMULATOR


def test_detect_returns_ekf2_fallback_when_gt_topics_absent(
    real_only_ulog: Path,
) -> None:
    """The original sample ULog has no SITL GT."""
    assert detect_groundtruth_source(real_only_ulog) is GroundTruthSource.EKF2_FALLBACK


def test_parse_returns_samples_with_expected_shape(stationary_ulog: Path) -> None:
    """Each parsed sample has stamp_us, position_m, quaternion_wxyz; no std."""
    gt = parse_ulog_groundtruth_samples(stationary_ulog)
    assert len(gt) > 0
    s = gt[0]
    assert isinstance(s, ULogGroundTruthSample)
    assert isinstance(s.stamp_us, int)
    assert len(s.position_m) == 3
    assert all(isinstance(v, float) for v in s.position_m)
    assert len(s.quaternion_wxyz) == 4
    assert all(isinstance(v, float) for v in s.quaternion_wxyz)
    # Unit quaternion invariant.
    norm_sq = sum(v * v for v in s.quaternion_wxyz)
    assert 0.99 < norm_sq < 1.01


def test_parse_is_chronological(stationary_ulog: Path) -> None:
    """The returned list must be sorted by stamp_us so the consumer can
    interpolate without re-sorting."""
    gt = parse_ulog_groundtruth_samples(stationary_ulog)
    stamps = [s.stamp_us for s in gt]
    assert stamps == sorted(stamps)


def test_parse_raises_on_ulog_without_gt(real_only_ulog: Path) -> None:
    """Silent fallback to EKF2 would defeat §8.8.2's purpose."""
    with pytest.raises(ULogParseError, match="vehicle_local_position_groundtruth"):
        parse_ulog_groundtruth_samples(real_only_ulog)


def test_parse_raises_on_missing_file(tmp_path: Path) -> None:
    """Missing ULog is FileNotFoundError, not a misleading parse error."""
    with pytest.raises(FileNotFoundError):
        parse_ulog_groundtruth_samples(tmp_path / "does_not_exist.ulg")


def test_gt_disagrees_with_ekf2_on_stationary_log(stationary_ulog: Path) -> None:
    """The whole motivation for §8.8.2: GT must actually disagree with
    EKF2 on the stationary ULog, otherwise sourcing GT independently
    does nothing useful.

    Quantitative check: GT pose x-range > EKF2 pose x-range. We do
    not pin exact numbers (the upstream ULog is a fixed fixture but
    we want the assertion to survive an upstream refresh that keeps
    the same qualitative property).
    """
    gt = parse_ulog_groundtruth_samples(stationary_ulog)
    ekf2 = parse_ulog_pose_samples(stationary_ulog)

    def xrange(samples: list) -> float:  # type: ignore[type-arg]
        xs = [s.position_m[0] for s in samples]
        return float(max(xs) - min(xs))

    gt_range = xrange(gt)
    ekf2_range = xrange(ekf2)
    assert gt_range > 5 * ekf2_range, (
        f"GT and EKF2 too similar on stationary ULog: "
        f"GT x-range = {gt_range:.4f} m vs EKF2 x-range = {ekf2_range:.4f} m. "
        "§8.8.2's premise is that GT oscillates further than EKF2 "
        "claims; if that gap collapses, the experiment loses its point."
    )
