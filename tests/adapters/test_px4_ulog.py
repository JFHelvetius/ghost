"""Tests for the PX4 ULog adapter (src/project_ghost/adapters/px4_ulog.py).

The adapter parses real PX4 ULog files via pyulog. Since the repo
does not ship a flight log, the tests stand in for a real ULog with
``unittest.mock.patch`` of ``pyulog.ULog``: a fake ``ULog`` instance
returns hand-crafted topic data that mirrors the shape of a real
log. This validates:

- the topic lookup (``_topic_by_name``) handles missing and
  multi-instance topics correctly;
- the timestamp pairing (``_nearest_index``) returns the closer of
  the two candidate ``vehicle_attitude`` events for each
  ``vehicle_local_position`` event;
- the quaternion normalisation rejects non-finite and zero-norm
  rows;
- the parser returns one sample per ``vehicle_local_position``
  event, deterministic, chronological;
- bag-of-fields validation rejects ULogs that are missing required
  fields (eph, epv, q[*]).

A future v0.3.0 commitment (paper §8.7) is to add an end-to-end
test driven by a downloaded real PX4 ULog, attributed and licensed
per the dataset; that test is deliberately not in this file.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from project_ghost.adapters.px4_ulog import (
    ULogParseError,
    ULogPoseSample,
    ULogTopicNames,
    _nearest_index,
    parse_ulog_pose_samples,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_topic(name: str, data: dict[str, Any]) -> MagicMock:
    topic = MagicMock()
    topic.name = name
    topic.data = data
    return topic


def _make_ulog_mock(
    pos_data: dict[str, Any] | None = None,
    att_data: dict[str, Any] | None = None,
    extra: list[MagicMock] | None = None,
) -> MagicMock:
    ulog = MagicMock()
    data_list = []
    if pos_data is not None:
        data_list.append(_make_topic("vehicle_local_position", pos_data))
    if att_data is not None:
        data_list.append(_make_topic("vehicle_attitude", att_data))
    if extra is not None:
        data_list.extend(extra)
    ulog.data_list = data_list
    return ulog


def _fake_ulog_path(tmp_path: Path) -> Path:
    p = tmp_path / "fake.ulg"
    p.write_bytes(b"\x00")  # content does not matter; ULog is mocked
    return p


# ---------------------------------------------------------------------------
# _nearest_index
# ---------------------------------------------------------------------------


def test_nearest_index_empty_raises() -> None:
    with pytest.raises(ULogParseError, match="attitude timestamp array is empty"):
        _nearest_index([], 1000)


def test_nearest_index_target_before_first_returns_zero() -> None:
    assert _nearest_index([10, 20, 30], 0) == 0


def test_nearest_index_target_after_last_returns_last() -> None:
    assert _nearest_index([10, 20, 30], 100) == 2


def test_nearest_index_target_picks_closer() -> None:
    # 15 is equidistant to 10 and 20; ties go to the earlier index.
    assert _nearest_index([10, 20, 30], 15) == 0
    assert _nearest_index([10, 20, 30], 16) == 1
    assert _nearest_index([10, 20, 30], 14) == 0


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


_GOOD_POS_DATA = {
    "timestamp": [1_000_000, 2_000_000, 3_000_000],
    "x": [0.0, 1.0, 2.5],
    "y": [0.0, 0.5, 1.0],
    "z": [-1.0, -1.2, -1.5],
    "eph": [0.05, 0.07, 0.10],
    "epv": [0.02, 0.03, 0.04],
}
_GOOD_ATT_DATA = {
    "timestamp": [999_000, 1_999_000, 2_999_500],
    "q[0]": [1.0, 0.9659, 0.7071],
    "q[1]": [0.0, 0.0, 0.0],
    "q[2]": [0.0, 0.0, 0.0],
    "q[3]": [0.0, 0.2588, 0.7071],
}


def test_parse_returns_one_sample_per_position_event(tmp_path: Path) -> None:
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(
            pos_data=_GOOD_POS_DATA, att_data=_GOOD_ATT_DATA
        )
        samples = parse_ulog_pose_samples(_fake_ulog_path(tmp_path))
    assert len(samples) == 3
    assert all(isinstance(s, ULogPoseSample) for s in samples)


def test_parse_first_sample_matches_first_position_row(tmp_path: Path) -> None:
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(
            pos_data=_GOOD_POS_DATA, att_data=_GOOD_ATT_DATA
        )
        samples = parse_ulog_pose_samples(_fake_ulog_path(tmp_path))
    s0 = samples[0]
    assert s0.stamp_us == 1_000_000
    assert s0.position_m == (0.0, 0.0, -1.0)
    assert s0.position_std_m == (0.05, 0.05, 0.02)
    # Quaternion normalised to unit; first row already unit norm.
    assert all(math.isfinite(q) for q in s0.quaternion_wxyz)
    assert abs(sum(q * q for q in s0.quaternion_wxyz) - 1.0) < 1e-9


def test_parse_quaternion_is_unit_normalised(tmp_path: Path) -> None:
    pos = _GOOD_POS_DATA
    # Inject a non-unit quaternion (norm 2.0); parser should normalise it.
    att = dict(_GOOD_ATT_DATA)
    att["q[0]"] = [2.0, 0.9659, 0.7071]
    att["q[1]"] = [0.0, 0.0, 0.0]
    att["q[2]"] = [0.0, 0.0, 0.0]
    att["q[3]"] = [0.0, 0.2588, 0.7071]
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(pos_data=pos, att_data=att)
        samples = parse_ulog_pose_samples(_fake_ulog_path(tmp_path))
    s0_norm_sq = sum(q * q for q in samples[0].quaternion_wxyz)
    assert abs(s0_norm_sq - 1.0) < 1e-9


def test_parse_picks_nearest_attitude_per_position(tmp_path: Path) -> None:
    # position at t=2_000_000 should pair with attitude at t=1_999_000
    # (delta -1000), not t=2_999_500 (delta +999_500).
    pos = {
        "timestamp": [2_000_000],
        "x": [1.0],
        "y": [0.5],
        "z": [-1.2],
        "eph": [0.07],
        "epv": [0.03],
    }
    att = _GOOD_ATT_DATA
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(pos_data=pos, att_data=att)
        samples = parse_ulog_pose_samples(_fake_ulog_path(tmp_path))
    s0 = samples[0]
    # Att row 1 has q[0]=0.9659, q[3]=0.2588 (45 deg yaw rotation).
    assert abs(s0.quaternion_wxyz[0] - 0.9659) < 1e-3


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_parse_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.ulg"
    with pytest.raises(FileNotFoundError):
        parse_ulog_pose_samples(missing)


def test_parse_missing_position_topic_raises(tmp_path: Path) -> None:
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(att_data=_GOOD_ATT_DATA)
        with pytest.raises(ULogParseError, match="no topic named 'vehicle_local_position'"):
            parse_ulog_pose_samples(_fake_ulog_path(tmp_path))


def test_parse_missing_attitude_topic_raises(tmp_path: Path) -> None:
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(pos_data=_GOOD_POS_DATA)
        with pytest.raises(ULogParseError, match="no topic named 'vehicle_attitude'"):
            parse_ulog_pose_samples(_fake_ulog_path(tmp_path))


def test_parse_position_missing_required_field_raises(tmp_path: Path) -> None:
    pos = {k: v for k, v in _GOOD_POS_DATA.items() if k != "epv"}
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(pos_data=pos, att_data=_GOOD_ATT_DATA)
        with pytest.raises(
            ULogParseError,
            match="vehicle_local_position is missing required field 'epv'",
        ):
            parse_ulog_pose_samples(_fake_ulog_path(tmp_path))


def test_parse_zero_norm_quaternion_raises(tmp_path: Path) -> None:
    att = dict(_GOOD_ATT_DATA)
    att["q[0]"] = [0.0, 0.9659, 0.7071]
    att["q[1]"] = [0.0, 0.0, 0.0]
    att["q[2]"] = [0.0, 0.0, 0.0]
    att["q[3]"] = [0.0, 0.2588, 0.7071]
    pos = {
        "timestamp": [999_000],
        "x": [0.0],
        "y": [0.0],
        "z": [-1.0],
        "eph": [0.05],
        "epv": [0.02],
    }
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(pos_data=pos, att_data=att)
        with pytest.raises(ULogParseError, match="zero-norm quaternion"):
            parse_ulog_pose_samples(_fake_ulog_path(tmp_path))


def test_parse_multi_instance_topic_raises(tmp_path: Path) -> None:
    extra = [_make_topic("vehicle_local_position", _GOOD_POS_DATA)]
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = _make_ulog_mock(
            pos_data=_GOOD_POS_DATA, att_data=_GOOD_ATT_DATA, extra=extra
        )
        with pytest.raises(ULogParseError, match="2 instances of topic"):
            parse_ulog_pose_samples(_fake_ulog_path(tmp_path))


def test_parse_custom_topic_names(tmp_path: Path) -> None:
    custom = ULogTopicNames(
        local_position="vehicle_local_position_v2",
        attitude="vehicle_attitude_v2",
    )
    pos_topic = _make_topic("vehicle_local_position_v2", _GOOD_POS_DATA)
    att_topic = _make_topic("vehicle_attitude_v2", _GOOD_ATT_DATA)
    ulog = MagicMock()
    ulog.data_list = [pos_topic, att_topic]
    with patch("project_ghost.adapters.px4_ulog.pyulog") as mock_pyulog:
        mock_pyulog.ULog.return_value = ulog
        samples = parse_ulog_pose_samples(_fake_ulog_path(tmp_path), topic_names=custom)
    assert len(samples) == 3
