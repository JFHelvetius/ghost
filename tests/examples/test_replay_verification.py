"""Tests del ``replay_downstream_from_fusion`` (ADR-0030).

Cubre:

- Summary fields and path invariants.
- All downstream channels are byte-equal after replay.
- Per-channel message counts match the smoke cycle structure.
- Replay MCAP contains exactly the six downstream channels.
- SHA-256 of source and replay differ (different channel sets).
- Replay is deterministic: 3 independent calls → identical replay MCAPs.
- Custom ``ground_truth_fn`` that returns a wrong pose breaks equality.
- ``ChannelVerification`` fields are correct for byte-equal channels.
- Outcome count is one less than fusion count (first cycle has no prior).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.examples.replay_verification import (
    ChannelVerification,
    ReplayVerificationSummary,
    replay_downstream_from_fusion,
)
from project_ghost.state.messages import Pose
from project_ghost.telemetry import (
    CHANNEL_ACTUATIONS,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    CHANNEL_DECISIONS,
    CHANNEL_FORWARD_PREDICTIONS,
    CHANNEL_PREDICTION_OUTCOMES,
    CHANNEL_SELF_ASSESSMENT,
    MCAPReplayReader,
)

if TYPE_CHECKING:
    from pathlib import Path

_N = 10  # cycles used in all smoke calls below

_DOWNSTREAM = frozenset(
    {
        CHANNEL_SELF_ASSESSMENT,
        CHANNEL_CALIBRATED_SELF_ASSESSMENT,
        CHANNEL_DECISIONS,
        CHANNEL_ACTUATIONS,
        CHANNEL_FORWARD_PREDICTIONS,
        CHANNEL_PREDICTION_OUTCOMES,
    }
)


@pytest.fixture(scope="module")
def smoke_mcap(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Single smoke run shared by all read-only tests in this module."""
    out = tmp_path_factory.mktemp("replay") / "smoke.mcap"
    run_closed_loop_smoke(out, n_cycles=_N)
    return out


# ---------------------------------------------------------------------------
# Summary structure
# ---------------------------------------------------------------------------


def test_summary_is_dataclass_instance(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    assert isinstance(summary, ReplayVerificationSummary)


def test_summary_paths_match_arguments(smoke_mcap: Path, tmp_path: Path) -> None:
    replay = tmp_path / "r.mcap"
    summary = replay_downstream_from_fusion(smoke_mcap, replay)
    assert summary.source_path == smoke_mcap
    assert summary.replay_path == replay


def test_summary_has_six_channel_verifications(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    assert len(summary.channels) == 6


def test_channel_verifications_are_frozen_dataclasses(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    for cv in summary.channels:
        assert isinstance(cv, ChannelVerification)


# ---------------------------------------------------------------------------
# Byte-equality
# ---------------------------------------------------------------------------


def test_all_downstream_channels_byte_equal(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    assert summary.all_channels_byte_equal is True


def test_each_channel_verification_byte_equal(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    for cv in summary.channels:
        assert cv.byte_equal, f"channel {cv.channel!r} not byte-equal"


def test_byte_equal_channels_have_no_mismatch_index(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    for cv in summary.channels:
        if cv.byte_equal:
            assert cv.first_mismatch_index is None


# ---------------------------------------------------------------------------
# Per-channel message counts
# ---------------------------------------------------------------------------


def test_self_assessment_count(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    cv = next(c for c in summary.channels if c.channel == CHANNEL_SELF_ASSESSMENT)
    assert cv.source_count == _N
    assert cv.replay_count == _N


def test_decisions_count(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    cv = next(c for c in summary.channels if c.channel == CHANNEL_DECISIONS)
    assert cv.source_count == _N
    assert cv.replay_count == _N


def test_outcomes_count_is_n_minus_one(smoke_mcap: Path, tmp_path: Path) -> None:
    """First cycle has no prior prediction; outcomes = n_cycles - 1."""
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    cv = next(c for c in summary.channels if c.channel == CHANNEL_PREDICTION_OUTCOMES)
    assert cv.source_count == _N - 1
    assert cv.replay_count == _N - 1


# ---------------------------------------------------------------------------
# Replay MCAP channel set
# ---------------------------------------------------------------------------


def test_replay_mcap_contains_exactly_downstream_channels(smoke_mcap: Path, tmp_path: Path) -> None:
    replay = tmp_path / "r.mcap"
    replay_downstream_from_fusion(smoke_mcap, replay)
    with MCAPReplayReader(replay) as reader:
        channels = {msg.channel for msg in reader.iter_messages()}
    assert channels == _DOWNSTREAM


# ---------------------------------------------------------------------------
# SHA-256 invariants
# ---------------------------------------------------------------------------


def test_source_sha256_is_hex_string(smoke_mcap: Path, tmp_path: Path) -> None:
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    assert len(summary.source_sha256) == 64
    assert all(c in "0123456789abcdef" for c in summary.source_sha256)


def test_source_and_replay_sha256_differ(smoke_mcap: Path, tmp_path: Path) -> None:
    """Source (8 channels) and replay (6 channels) produce different MCAPs."""
    summary = replay_downstream_from_fusion(smoke_mcap, tmp_path / "r.mcap")
    assert summary.source_sha256 != summary.replay_sha256


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_replay_is_byte_deterministic_3x(smoke_mcap: Path, tmp_path: Path) -> None:
    """Three independent replay runs produce identical MCAP bytes."""
    paths = [tmp_path / f"r{i}.mcap" for i in range(3)]
    shas = []
    for p in paths:
        s = replay_downstream_from_fusion(smoke_mcap, p)
        shas.append(s.replay_sha256)
    assert shas[0] == shas[1] == shas[2]
    assert all(p.read_bytes() == paths[0].read_bytes() for p in paths[1:])


# ---------------------------------------------------------------------------
# Custom ground_truth_fn — breaks equality
# ---------------------------------------------------------------------------


def test_wrong_ground_truth_breaks_byte_equality(smoke_mcap: Path, tmp_path: Path) -> None:
    """Passing a wrong ground-truth function changes divergence outcomes,
    which cascades through calibration and decisions, making at least one
    downstream channel non-byte-equal."""

    def zero_ground_truth(t_ns: int) -> Pose:
        return Pose(
            position_enu_m=np.zeros(3, dtype=np.float64),
            orientation_q=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
        )

    summary = replay_downstream_from_fusion(
        smoke_mcap,
        tmp_path / "r.mcap",
        ground_truth_fn=zero_ground_truth,
    )
    assert summary.all_channels_byte_equal is False
