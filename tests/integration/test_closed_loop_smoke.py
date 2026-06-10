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

from project_ghost.core.actuation.types import ActuationDirective
from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.fusion.types import FusionResult
from project_ghost.core.prediction.divergence import PredictionOutcome
from project_ghost.core.prediction.types import BeliefForwardPrediction
from project_ghost.core.uncertainty.self_assessment import (
    BeliefSelfAssessment,
)
from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.hal.messages.actuators import AttitudeCommand
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


def test_smoke_carries_inline_baud_verification(tmp_path: Path) -> None:
    """ADR-0031 §3.2 — every smoke run carries its own BAUD-v1 veredicto.

    The integration test of the integration test: if this ever fails,
    either the reference pipeline regressed (and BAUD detected it), or
    the verifier regressed (and the smoke is fine). Either way, the
    citable claim "Project Ghost satisfies BAUD-v1" is at risk and a
    human must look.
    """
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)

    report = summary.baud_report
    assert report.holds, f"BAUD-v1 violated by smoke: {report.violations}"
    assert report.property_version == "BAUD-v1"
    # The smoke wires (M=4, K=2) — verify the report queries the same.
    assert report.min_outcomes == 4
    assert report.downgrade_threshold == 2
    # The 5 m/s drift trap is engineered to fire the precondition. If
    # it stops firing, the smoke is no longer a meaningful BAUD witness.
    assert report.cycles_precondition_held > 0
    # The SHA-256 in the BAUD report must match the SHA-256 the smoke
    # itself recorded — same MCAP bytes were verified.
    assert report.mcap_sha256 == summary.mcap_sha256


def test_smoke_baud_report_is_byte_deterministic(tmp_path: Path) -> None:
    """Two byte-identical smoke runs produce identical BAUD reports.

    This catches non-determinism in the verifier itself (e.g. dict
    iteration order leaking into a serialised report) — a real risk
    because the verifier is the citable surface.
    """
    a = tmp_path / "a.mcap"
    b = tmp_path / "b.mcap"
    sa = run_closed_loop_smoke(a, n_cycles=10)
    sb = run_closed_loop_smoke(b, n_cycles=10)
    assert sa.baud_report == sb.baud_report


def test_smoke_carries_inline_erur_verification(tmp_path: Path) -> None:
    """ADR-0032 §4.4 — every smoke run carries its own ERUR-v1 veredicto."""
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)

    report = summary.erur_report
    assert report.holds, f"ERUR-v1 violated by smoke: {report.violations}"
    assert report.property_version == "ERUR-v1"
    assert report.min_outcomes == 4
    assert report.downgrade_threshold == 2
    # Cycles 1-4 of the smoke are drift-clean (M-guard pre-fires) and
    # raw-known, so ERUR must fire there. If the early cycles stop
    # firing the smoke regressed in a way ERUR catches.
    assert report.cycles_precondition_held >= 4
    assert report.mcap_sha256 == summary.mcap_sha256


def test_smoke_baud_and_erur_partition_the_cycle_space(
    tmp_path: Path,
) -> None:
    """The pair (BAUD-v1, ERUR-v1) covers every cycle of the smoke
    between them with no overlap. This is the structural witness that
    the safety claim is bidirectional and complete at the smoke's
    parameters.
    """
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)
    total = summary.baud_report.cycles_total
    fired = (
        summary.baud_report.cycles_precondition_held
        + summary.erur_report.cycles_precondition_held
    )
    assert fired == total
    assert summary.baud_report.holds
    assert summary.erur_report.holds


def test_smoke_carries_inline_md_verification(tmp_path: Path) -> None:
    """ADR-0033 §4.4 — every smoke run carries its own MD-v1 veredicto.

    MD is unconditional: every cycle is evaluated. cycles_precondition_held
    must equal cycles_total.
    """
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)

    report = summary.md_report
    assert report.holds, f"MD-v1 violated by smoke: {report.violations}"
    assert report.property_version == "MD-v1"
    assert report.cycles_total == 10
    assert report.cycles_precondition_held == report.cycles_total
    assert report.mcap_sha256 == summary.mcap_sha256


def test_smoke_carries_inline_rlb_verification(tmp_path: Path) -> None:
    """ADR-0034 §4.4 — every smoke run carries its own RLB-v1 veredicto.

    The smoke is sustained-drift, so RLB observes zero recovery
    transitions — it holds vacuously. The test pins exactly that
    shape: vacuously-true baseline that catches any future change to
    the smoke's outcome trajectory.
    """
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)

    report = summary.rlb_report
    assert report.holds, f"RLB-v1 violated by smoke: {report.violations}"
    assert report.property_version == "RLB-v1"
    assert report.max_history == 32
    assert report.cycles_total == 10
    assert report.cycles_precondition_held == 0  # no recovery transitions
    assert report.mcap_sha256 == summary.mcap_sha256


def test_smoke_carries_inline_fpb_verification(tmp_path: Path) -> None:
    """ADR-0035 §4.4 — every smoke run carries its own FPB-v1 report.

    FPB is observational. The smoke baseline fire_fraction is 0.6
    (BAUD fires in 6 of 10 cycles). With default max_fire_fraction=1.0
    it holds, but the test pins the observed fraction as a regression
    gate. If a refactor changes the smoke's behavior, this catches it.
    """
    out = tmp_path / "smoke.mcap"
    summary = run_closed_loop_smoke(out, n_cycles=10)

    report = summary.fpb_report
    assert report.holds
    assert report.property_version == "FPB-v1"
    assert report.cycles_total == 10
    # The pinned regression value for the smoke baseline.
    assert report.fire_fraction == 0.6
    assert report.cycles_precondition_held == 6
    assert report.mcap_sha256 == summary.mcap_sha256


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


def test_smoke_proceed_directives_carry_attitude_command(
    tmp_path: Path,
) -> None:
    """ADR-0029 closure: PROCEED decisions produce AttitudeCommand
    instances (not None) via AttitudeHoldReferencePolicy."""
    out = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(out, n_cycles=10)
    proceed_commands = []
    with MCAPReplayReader(out) as reader:
        for msg in reader.iter_messages():
            if msg.channel != CHANNEL_ACTUATIONS:
                continue
            directive = decode_message(msg)
            assert isinstance(directive, ActuationDirective)
            if directive.decision.kind.value == "proceed":
                proceed_commands.append(directive.actuator_command)
    assert len(proceed_commands) == 4
    assert all(isinstance(c, AttitudeCommand) for c in proceed_commands)


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
