"""Integration test for the closed-loop smoke (ADR-0019 through
ADR-0028 composed in a single pipeline).

This test is **not** a contract test — it verifies that the contracts
*compose*. When this test breaks because a single ADR shape changed,
the right response is usually to revisit the offending ADR for
composability, not to patch the smoke.

ADR-0027 closed the gap originally surfaced by ADR-0026: the smoke
now wires the calibrated assessment through ``DecisionContext`` and
the reference policy reads ``effective_overall_level``. Decisions
transition from PROCEED to HOLD as the calibration downgrades the
effective level. The previously pinned "gap" test is replaced by the
"closure" test below.

ADR-0028 adds the fusion layer: the smoke now uses
``LinearMotionOracleFusionPolicy`` to produce the belief at each cycle
and publishes ``FusionResult`` records to ``/fusion/results``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.fusion.types import FusionResult
from project_ghost.core.prediction.divergence import PredictionOutcome
from project_ghost.core.prediction.types import BeliefForwardPrediction
from project_ghost.core.uncertainty.self_assessment import (
    BeliefSelfAssessment,
)
from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.telemetry import (
    CHANNEL_ACTUATIONS,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    CHANNEL_DECISIONS,
    CHANNEL_FORWARD_PREDICTIONS,
    CHANNEL_FUSION_RESULTS,
    CHANNEL_PREDICTION_OUTCOMES,
    CHANNEL_SELF_ASSESSMENT,
    CHANNEL_STATE_NAV,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_smoke_runs_and_produces_summary(tmp_path: Path) -> None:
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)
    assert summary.n_cycles == 10
    assert summary.n_outcomes == 9  # one less than cycles
    assert summary.n_decisions == 10
    assert out.exists()


def test_smoke_is_byte_deterministic(tmp_path: Path) -> None:
    """Two runs with identical inputs produce identical MCAP bytes."""
    a = tmp_path / "a.mcap"
    b = tmp_path / "b.mcap"
    sa = run_closed_loop_smoke(a, n_cycles=10)
    sb = run_closed_loop_smoke(b, n_cycles=10)
    assert sa.mcap_sha256 == sb.mcap_sha256
    assert a.read_bytes() == b.read_bytes()


def test_smoke_rejects_too_few_cycles(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="n_cycles must be >= 2"):
        run_closed_loop_smoke(tmp_path / "x.mcap", n_cycles=1)


def test_smoke_overconfidence_surfaces_in_outcomes(
    tmp_path: Path,
) -> None:
    """All outcomes should be ``beyond_5_std`` because the predictor
    declares zero motion but ground truth drifts at 5 m/s."""
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)
    assert summary.final_verdict == "beyond_5_std"


def test_smoke_calibration_downgrades_after_threshold(
    tmp_path: Path,
) -> None:
    """Feedback policy (min_outcomes=4, downgrade_threshold=2) must
    downgrade once 4+ outcomes are observed, all beyond_5_std."""
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)
    # First cycle: 0 outcomes -> passthrough KNOWN.
    # Cycles 2-4: 1-3 outcomes, below min -> passthrough KNOWN.
    # Cycle 5 onward (4+ outcomes, all beyond_5) -> downgrade.
    assert summary.calibrated_levels_observed[0] == "known"
    assert summary.calibrated_levels_observed[3] == "known"
    assert summary.calibrated_levels_observed[4] == "uncertain"
    assert summary.calibrated_levels_observed[-1] == "uncertain"


def test_smoke_decisions_track_calibration_closure(
    tmp_path: Path,
) -> None:
    """ADR-0027 closure of the ADR-0026 gap.

    With ``calibrated_self_assessment`` wired into ``DecisionContext``,
    the reference policy reads ``effective_overall_level`` (calibrated
    priority). When the feedback downgrade fires at cycle 5, decisions
    flip from PROCEED to HOLD.

    Expected: 4 PROCEED (cycles 1-4, calibration still KNOWN) +
    6 HOLD (cycles 5-10, calibration downgraded to UNCERTAIN).
    """
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)
    assert summary.decisions_by_kind == {"proceed": 4, "hold": 6}


def test_smoke_mcap_contains_all_expected_channels(
    tmp_path: Path,
) -> None:
    """All eight channels must be present in the captured MCAP."""
    out = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(out, n_cycles=10)
    with MCAPReplayReader(out) as reader:
        channels = {msg.channel for msg in reader.iter_messages()}
    assert channels == {
        CHANNEL_FUSION_RESULTS,
        CHANNEL_STATE_NAV,
        CHANNEL_SELF_ASSESSMENT,
        CHANNEL_CALIBRATED_SELF_ASSESSMENT,
        CHANNEL_DECISIONS,
        CHANNEL_ACTUATIONS,
        CHANNEL_FORWARD_PREDICTIONS,
        CHANNEL_PREDICTION_OUTCOMES,
    }


def test_smoke_mcap_message_counts_per_channel(tmp_path: Path) -> None:
    """Per-channel counts match the cycle structure."""
    out = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(out, n_cycles=10)
    with MCAPReplayReader(out) as reader:
        counts: dict[str, int] = {}
        for msg in reader.iter_messages():
            counts[msg.channel] = counts.get(msg.channel, 0) + 1
    # 10 per cycle for fusion/state/assess/cal/dec/act/pred; 9 for outcomes.
    assert counts[CHANNEL_FUSION_RESULTS] == 10
    assert counts[CHANNEL_STATE_NAV] == 10
    assert counts[CHANNEL_SELF_ASSESSMENT] == 10
    assert counts[CHANNEL_CALIBRATED_SELF_ASSESSMENT] == 10
    assert counts[CHANNEL_DECISIONS] == 10
    assert counts[CHANNEL_ACTUATIONS] == 10
    assert counts[CHANNEL_FORWARD_PREDICTIONS] == 10
    assert counts[CHANNEL_PREDICTION_OUTCOMES] == 9


def test_smoke_mcap_messages_decode_to_expected_types(
    tmp_path: Path,
) -> None:
    """Each channel's payload decodes to the right dataclass."""
    out = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(out, n_cycles=10)
    expected_type_per_channel: dict[str, type] = {
        CHANNEL_FUSION_RESULTS: FusionResult,
        CHANNEL_SELF_ASSESSMENT: BeliefSelfAssessment,
        CHANNEL_CALIBRATED_SELF_ASSESSMENT: CalibratedSelfAssessment,
        CHANNEL_FORWARD_PREDICTIONS: BeliefForwardPrediction,
        CHANNEL_PREDICTION_OUTCOMES: PredictionOutcome,
    }
    with MCAPReplayReader(out) as reader:
        for msg in reader.iter_messages():
            if msg.channel not in expected_type_per_channel:
                continue
            decoded = decode_message(msg)
            assert isinstance(
                decoded, expected_type_per_channel[msg.channel]
            )


def test_smoke_per_channel_log_times_are_monotonic(tmp_path: Path) -> None:
    """Each MCAP channel's log_times are non-decreasing — required for
    deterministic replay."""
    out = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(out, n_cycles=10)
    last_seen: dict[str, int] = {}
    with MCAPReplayReader(out) as reader:
        for msg in reader.iter_messages():
            prev = last_seen.get(msg.channel)
            if prev is not None:
                assert msg.log_time_sim_ns >= prev, (
                    f"non-monotonic log_time on {msg.channel}: "
                    f"{prev} -> {msg.log_time_sim_ns}"
                )
            last_seen[msg.channel] = msg.log_time_sim_ns


def test_smoke_outcome_predictions_link_back_to_forward_records(
    tmp_path: Path,
) -> None:
    """Each PredictionOutcome carries inline the original prediction.
    Stamps must satisfy actual_stamp == predicted_observation_stamp."""
    out = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(out, n_cycles=10)
    with MCAPReplayReader(out) as reader:
        for msg in reader.iter_messages():
            if msg.channel != CHANNEL_PREDICTION_OUTCOMES:
                continue
            outcome = decode_message(msg)
            assert isinstance(outcome, PredictionOutcome)
            assert (
                outcome.actual_belief_stamp_sim_ns
                == outcome.prediction.predicted_observation_stamp_sim_ns
            )
