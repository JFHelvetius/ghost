"""Sanity tests for :func:`verify_baud` against the reference closed-loop
smoke. These are *not* the property-based suite (that arrives in step 3
of the ADR-0031 roadmap) — they just exercise the verifier end-to-end on
a real MCAP produced by the reference pipeline.

Expectations:

- The reference smoke MCAP satisfies BAUD-v1 with default parameters
  (the smoke deliberately triggers the precondition; the reference
  policy pair is exactly the one BAUD-v1 names).
- Tightening ``downgrade_threshold`` past anything the smoke can
  produce yields a trivially-holding report.
- Input validation matches the underlying ``MahalanobisDowngradePolicy``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.properties import (
    BAUD_PROPERTY_VERSION,
    BAUDVerificationReport,
    verify_baud,
)


@pytest.fixture
def smoke_mcap(tmp_path: Path) -> Path:
    """Run the 10-cycle smoke and yield the resulting MCAP path."""
    mcap_path = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(mcap_path, n_cycles=10)
    return mcap_path


def test_reference_smoke_satisfies_baud_v1(smoke_mcap: Path) -> None:
    """The reference smoke is the canonical BAUD-v1 witness."""
    report = verify_baud(smoke_mcap)
    assert isinstance(report, BAUDVerificationReport)
    assert report.holds, f"BAUD-v1 violated by reference smoke: {report.violations}"


def test_report_has_expected_shape(smoke_mcap: Path) -> None:
    """Report metadata is well-formed for citation in CI logs."""
    report = verify_baud(smoke_mcap)
    assert report.property_version == BAUD_PROPERTY_VERSION
    assert report.min_outcomes == 4
    assert report.downgrade_threshold == 2
    assert report.cycles_total == 10
    # SHA-256 hex is exactly 64 chars; __post_init__ enforces it but
    # double-check for the human reader.
    assert len(report.mcap_sha256) == 64


def test_smoke_triggers_precondition_at_least_once(smoke_mcap: Path) -> None:
    """The 5 m/s drift trap is engineered to fire the precondition.

    If this test fails the smoke has stopped being a meaningful witness
    for BAUD — likely a regression in the calibration history builder or
    the reference policy parameters.
    """
    report = verify_baud(smoke_mcap)
    assert report.cycles_precondition_held > 0
    assert report.first_precondition_cycle_stamp_sim_ns is not None


def test_smoke_exercises_safe_reason_path(smoke_mcap: Path) -> None:
    """The reference smoke wires the AttitudeHoldReferencePolicy
    (ADR-0029), which under HOLD emits an ``AttitudeCommand`` (non-None)
    with reason ``attitude_hold_hold``. This is the case that BAUD-v1's
    postcondition 3 explicitly handles via the safe-reason set
    (ADR-0031 §1.1).

    If this test fails — i.e., the smoke now hits only the trivial
    ``actuator_command is None`` path under non-PROCEED — then the
    smoke is no longer a meaningful witness for the *non-trivial* part
    of the property, and we should change the smoke before changing
    BAUD.
    """
    from project_ghost.core.actuation.types import ActuationDirective
    from project_ghost.telemetry import (
        CHANNEL_ACTUATIONS,
        MCAPReplayReader,
        decode_message,
    )

    has_non_none_hold_command = False
    with MCAPReplayReader(smoke_mcap) as reader:
        for msg in reader.iter_messages():
            if msg.channel != CHANNEL_ACTUATIONS:
                continue
            a = decode_message(msg)
            if not isinstance(a, ActuationDirective):
                continue
            if a.decision.kind.value != "proceed" and a.actuator_command is not None:
                has_non_none_hold_command = True
                # safe-reason whitelist check belongs to the verifier;
                # here we only certify the smoke exercises this path.
                assert a.reason == "attitude_hold_hold"
                break
    assert has_non_none_hold_command, (
        "Smoke MCAP no longer exercises the non-None command under "
        "non-PROCEED path — BAUD-v1's postcondition 3 safe-reason "
        "exception is not being witnessed."
    )


def test_unsatisfiable_threshold_yields_empty_held_count(
    smoke_mcap: Path,
) -> None:
    """A threshold higher than the smoke ever reaches is trivially
    holding because the precondition never fires.

    Useful as a smoke test of the verifier's negative path: it should
    return ``holds=True`` with ``cycles_precondition_held=0`` rather
    than ``raise`` or silently mis-evaluate.
    """
    report = verify_baud(smoke_mcap, downgrade_threshold=10_000)
    assert report.holds
    assert report.cycles_precondition_held == 0
    assert report.first_precondition_cycle_stamp_sim_ns is None
    assert report.violations == ()


@pytest.mark.parametrize(
    ("min_outcomes", "downgrade_threshold"),
    [(-1, 2), (0, 0), (4, -3)],
)
def test_invalid_parameters_rejected(
    smoke_mcap: Path, min_outcomes: int, downgrade_threshold: int
) -> None:
    """Parameter validation mirrors ``MahalanobisDowngradePolicy``."""
    with pytest.raises(ValueError):
        verify_baud(
            smoke_mcap,
            min_outcomes=min_outcomes,
            downgrade_threshold=downgrade_threshold,
        )


def test_same_inputs_same_report(smoke_mcap: Path) -> None:
    """The verifier is deterministic: same MCAP, same params, same
    report.
    """
    a = verify_baud(smoke_mcap)
    b = verify_baud(smoke_mcap)
    assert a == b
    assert a.mcap_sha256 == b.mcap_sha256
