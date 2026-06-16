"""Hypothesis property tests for ADR-0040 (ERUR-v2, policy-parametric).

Three invariants the v2 verifier must satisfy on any captured smoke:

P1. **v1/v2 agreement on the reference Mahalanobis policy.** When the
    drift predicate registered for the Mahalanobis policy is its own
    ``drift_precondition`` method (the v1 rule expressed as a callable),
    v2 must agree with v1 byte-for-byte on every metric: ``holds``,
    ``cycles_precondition_held``, and the set of violations. This is
    the structural soundness check: v2 strictly generalises v1, so on
    a reference instance they cannot diverge.

P2. **Drift / no-drift partition on any policy that implements the
    Protocol.** On every captured CalibratedSelfAssessment, the policy's
    ``drift_precondition(history)`` either fires or does not; ERUR-v2's
    precondition is exactly the "does-not-fire AND raw KNOWN" branch.
    This test asserts that ``verify_erur_v2`` correctly counts the
    cycles where the registered predicate returns False *and* raw is
    KNOWN — independent of what the policy is.

P3. **UnknownPolicyError is raised exactly when a policy_id is missing
    from the predicate mapping.** If every policy that appears in the
    MCAP is registered, no error. If even one is missing, the error
    fires with an actionable message and the missing id name in it.

These three properties together pin v2's behaviour without depending
on the specific reference smoke MCAP — the smoke is just an input
generator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from project_ghost.core.feedback import MahalanobisDowngradePolicy
from project_ghost.core.feedback.alternative_policies import (
    EWMADowngradePolicy,
    PerAxisHysteresisDowngradePolicy,
)
from project_ghost.core.feedback.protocols import DriftPreconditionProvider
from project_ghost.core.feedback.types import CalibrationHistory
from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.properties.erur import verify_erur
from project_ghost.properties.erur_v2 import (
    UnknownPolicyError,
    verify_erur_v2,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reference_mcap(tmp_path: Path) -> Path:
    """Run the reference smoke once and return its MCAP path.

    Used as a common fixture so we exercise v2 against an MCAP whose
    schema and channel layout match what production CI produces.
    """
    mcap = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(mcap)
    return mcap


# ---------------------------------------------------------------------------
# P1 — v1/v2 agreement on the reference Mahalanobis policy
# ---------------------------------------------------------------------------


def test_v2_agrees_with_v1_on_reference_mahalanobis_smoke(tmp_path: Path) -> None:
    """v2 with M's drift_precondition reduces to v1; verdicts must match.

    On the reference closed-loop smoke (Mahalanobis(M=4, K=2)), running
    v1 and v2 should produce identical:
    - ``holds`` verdict
    - ``cycles_total`` and ``cycles_precondition_held``
    - ``first_precondition_cycle_stamp_sim_ns``
    - The number of violations (v2 does not change ``_check_postconditions``).
    """
    mcap = _make_reference_mcap(tmp_path)
    policy = MahalanobisDowngradePolicy()

    r1 = verify_erur(mcap)
    r2 = verify_erur_v2(
        mcap,
        drift_predicates={policy.policy_id: policy.drift_precondition},
    )

    assert r1.holds == r2.holds
    assert r1.cycles_total == r2.cycles_total
    assert r1.cycles_precondition_held == r2.cycles_precondition_held
    assert (
        r1.first_precondition_cycle_stamp_sim_ns
        == r2.first_precondition_cycle_stamp_sim_ns
    )
    assert len(r1.violations) == len(r2.violations)
    assert r2.policies_dispatched == (policy.policy_id,)


# ---------------------------------------------------------------------------
# P2 — Drift/no-drift partition for any DriftPreconditionProvider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy_class",
    [
        MahalanobisDowngradePolicy,
        EWMADowngradePolicy,
        PerAxisHysteresisDowngradePolicy,
    ],
)
def test_v2_partitions_cycles_by_drift_precondition(
    policy_class: type, tmp_path: Path
) -> None:
    """For any DriftPreconditionProvider, v2 partitions cycles exactly.

    Run v2 with the policy's ``drift_precondition`` registered against
    the reference MCAP. The number of cycles where the precondition
    *fires* (counted by the verifier) must equal the number of cycles
    where ``policy.drift_precondition(history) is False`` AND raw is
    KNOWN — independently re-derived from the MCAP by reading the
    CalibratedSelfAssessment records.

    This is the structural correctness test: the verifier doesn't get
    to invent its own precondition logic, it must delegate exactly to
    the predicate provided.
    """
    mcap = _make_reference_mcap(tmp_path)
    policy = policy_class()

    # Sanity: the policy actually implements the Protocol.
    assert isinstance(policy, DriftPreconditionProvider)

    # The reference smoke writes the Mahalanobis policy_id only. To
    # exercise the verifier's dispatch under each alternative policy
    # without producing a separate MCAP per policy, we register that
    # policy's predicate UNDER the Mahalanobis id present in the MCAP.
    # The verifier's lookup-then-apply path is what we want to test;
    # we don't care that the MCAP nominally says "Mahalanobis" because
    # the verifier just resolves the id to the predicate we gave.
    reference_id = MahalanobisDowngradePolicy().policy_id

    # Independently count from the MCAP what the v2 precondition would
    # fire on, given this policy's predicate.
    from project_ghost.core.feedback.types import CalibratedSelfAssessment
    from project_ghost.core.uncertainty.self_assessment import SelfAssessmentLevel
    from project_ghost.telemetry import (
        CHANNEL_CALIBRATED_SELF_ASSESSMENT,
        MCAPReplayReader,
        decode_message,
    )

    expected_held = 0
    seen_calibrated_stamps: set[int] = set()
    with MCAPReplayReader(mcap) as reader:
        for msg in reader.iter_messages():
            if msg.channel != CHANNEL_CALIBRATED_SELF_ASSESSMENT:
                continue
            c = decode_message(msg)
            if not isinstance(c, CalibratedSelfAssessment):
                continue
            stamp = c.raw_assessment.belief_stamp_sim_ns
            if stamp in seen_calibrated_stamps:
                continue
            seen_calibrated_stamps.add(stamp)
            drift_present = policy.drift_precondition(c.calibration_history)
            raw_known = c.raw_assessment.overall_level is SelfAssessmentLevel.KNOWN
            if (not drift_present) and raw_known:
                expected_held += 1

    # Run v2 with the policy's predicate registered under the MCAP's id.
    report = verify_erur_v2(
        mcap,
        drift_predicates={reference_id: policy.drift_precondition},
    )
    assert report.cycles_precondition_held == expected_held, (
        f"v2 verifier reported {report.cycles_precondition_held} "
        f"precondition-holding cycles but independent re-derivation "
        f"says {expected_held} for policy {policy_class.__name__}"
    )


# ---------------------------------------------------------------------------
# P3 — UnknownPolicyError fires when a policy_id is missing
# ---------------------------------------------------------------------------


def test_v2_raises_unknown_policy_error_on_missing_id(tmp_path: Path) -> None:
    """If even one policy_id in the MCAP is unregistered, raise.

    The reference MCAP contains records with
    ``adjustment_policy_id == 'mahalanobis_downgrade_v1_min4_thr2'``.
    A predicate map that does not contain that id must raise
    UnknownPolicyError on the first such record, with the unknown id
    and the registered ids in the message.
    """
    mcap = _make_reference_mcap(tmp_path)
    with pytest.raises(UnknownPolicyError) as excinfo:
        verify_erur_v2(
            mcap, drift_predicates={"some_other_policy_id": lambda h: False}
        )
    msg = str(excinfo.value)
    assert "mahalanobis_downgrade_v1_min4_thr2" in msg
    assert "some_other_policy_id" in msg
    assert "drift_predicates" in msg


def test_v2_succeeds_when_all_policies_registered(tmp_path: Path) -> None:
    """If every policy_id in the MCAP is registered, no error.

    Symmetric counterpart of the above: the same MCAP, but with the
    correct id registered, must run to completion.
    """
    mcap = _make_reference_mcap(tmp_path)
    policy = MahalanobisDowngradePolicy()
    report = verify_erur_v2(
        mcap,
        drift_predicates={policy.policy_id: policy.drift_precondition},
    )
    # Reference smoke holds under v1 (and therefore under v2 with
    # equivalent predicate); we already confirmed agreement in P1.
    assert report.holds is True
    assert policy.policy_id in report.policies_dispatched


# ---------------------------------------------------------------------------
# P4 (bonus) — drift_precondition ↔ adjust consistency on each policy
# ---------------------------------------------------------------------------


@given(
    outcomes=st.integers(min_value=0, max_value=20),
    n_dirty=st.integers(min_value=0, max_value=20),
    min_outcomes=st.integers(min_value=1, max_value=10),
    threshold=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=100, deadline=None)
def test_mahalanobis_drift_precondition_matches_specification(
    outcomes: int, n_dirty: int, min_outcomes: int, threshold: int
) -> None:
    """``MahalanobisDowngradePolicy.drift_precondition`` is the literal
    rule: ``outcomes >= M AND dirty_count >= K`` (for ``outcomes > 0``).

    Tests the spec-vs-implementation equivalence with Hypothesis-
    generated histories and parameters, covering the boundary cases
    that distinguish drift-clean from drift-present.
    """
    if n_dirty > outcomes:
        return  # not a valid history; skip

    history = CalibrationHistory(
        outcomes_considered=outcomes,
        count_within_1_std=outcomes - n_dirty,
        count_beyond_1_std=0,
        count_beyond_3_std=n_dirty,
        count_beyond_5_std=0,
        worst_position_mahalanobis=0.0 if outcomes == 0 else 3.5,
        worst_orientation_mahalanobis=0.0 if outcomes == 0 else 3.5,
        most_recent_observed_stamp_sim_ns=None if outcomes == 0 else 1000,
    )
    policy = MahalanobisDowngradePolicy(
        min_outcomes=min_outcomes, downgrade_threshold=threshold
    )
    observed = policy.drift_precondition(history)

    # Spec: drift iff outcomes_considered > 0 AND outcomes >= M AND
    # dirty_count >= K.
    expected = (
        outcomes > 0
        and outcomes >= min_outcomes
        and n_dirty >= threshold
    )
    assert observed == expected, (
        f"drift_precondition={observed} but spec says {expected} on "
        f"history outcomes={outcomes} n_dirty={n_dirty} "
        f"(min_outcomes={min_outcomes}, threshold={threshold})"
    )
