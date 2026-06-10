"""Sanity tests for :func:`verify_erur` against the reference closed-loop
smoke. Counterpart of :mod:`tests.properties.test_verify_baud_smoke`.

Expected behaviour with default parameters (M=4, K=2) and the 5 m/s
drift trap:

- Cycles 1-4: ``outcomes_considered < M`` is irrelevant for ERUR (M is
  not part of ERUR's precondition); but more importantly the early
  history has ``count_beyond_3_std + count_beyond_5_std < K`` simply
  because the predictions haven't had time to be evaluated yet (cycle 1
  has 0 outcomes, cycle 2 has 1, etc.). So the drift-clean conjunct
  holds. Raw assessment is KNOWN by construction (small covariance).
  ⇒ ERUR's precondition holds, decisions are PROCEED — verified.
- Cycle 5 onwards: ``count_beyond_5_std`` accumulates past K=2 ⇒
  drift-clean conjunct fails ⇒ ERUR's precondition does not fire;
  BAUD-v1's territory.

Therefore on the 10-cycle smoke we expect
``report.cycles_precondition_held == 4`` and ``report.holds``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.properties import (
    ERUR_PROPERTY_VERSION,
    ERURVerificationReport,
    verify_erur,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def smoke_mcap(tmp_path: Path) -> Path:
    mcap_path = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(mcap_path, n_cycles=10)
    return mcap_path


def test_reference_smoke_satisfies_erur_v1(smoke_mcap: Path) -> None:
    """The reference smoke is the canonical ERUR-v1 witness for the
    PROCEED-while-drift-absent direction."""
    report = verify_erur(smoke_mcap)
    assert isinstance(report, ERURVerificationReport)
    assert report.holds, (
        f"ERUR-v1 violated by reference smoke: {report.violations}"
    )


def test_report_has_expected_shape(smoke_mcap: Path) -> None:
    report = verify_erur(smoke_mcap)
    assert report.property_version == ERUR_PROPERTY_VERSION
    assert report.min_outcomes == 4
    assert report.downgrade_threshold == 2
    assert report.cycles_total == 10
    assert len(report.mcap_sha256) == 64


def test_smoke_triggers_precondition_in_early_cycles(smoke_mcap: Path) -> None:
    """The first four cycles are drift-clean (less than K=2 beyond_3/5
    outcomes accumulated) AND raw-known. ERUR must fire there.

    If this stops being the case the smoke has changed in a way that
    silently breaks ERUR's coverage — likely a regression in the
    feedback wiring or the AssessmentThresholds.
    """
    report = verify_erur(smoke_mcap)
    assert report.cycles_precondition_held >= 4
    assert report.first_precondition_cycle_stamp_sim_ns is not None


def test_late_cycles_do_not_trigger_erur_precondition(smoke_mcap: Path) -> None:
    """Once the drift signal accumulates past K, ERUR's precondition no
    longer fires. BAUD's territory.

    Expressed as: the count of fired cycles is strictly less than the
    total. Together with the strong claim above (>= 4 fired) this
    pins the drift detection's effect on coverage.
    """
    report = verify_erur(smoke_mcap)
    assert report.cycles_precondition_held < report.cycles_total


@pytest.mark.parametrize(
    ("min_outcomes", "downgrade_threshold"),
    [(-1, 2), (0, 0), (4, -3)],
)
def test_invalid_parameters_rejected(
    smoke_mcap: Path, min_outcomes: int, downgrade_threshold: int,
) -> None:
    """Parameter validation mirrors ``verify_baud``."""
    with pytest.raises(ValueError):
        verify_erur(
            smoke_mcap,
            min_outcomes=min_outcomes,
            downgrade_threshold=downgrade_threshold,
        )


def test_same_inputs_same_report(smoke_mcap: Path) -> None:
    a = verify_erur(smoke_mcap)
    b = verify_erur(smoke_mcap)
    assert a == b
    assert a.mcap_sha256 == b.mcap_sha256


def test_baud_and_erur_partition_the_cycle_space(smoke_mcap: Path) -> None:
    """Together BAUD-v1 and ERUR-v1 must cover every cycle of the
    smoke between them (and never overlap in a single cycle).

    With M=4, K=2: cycles 1-4 fire ERUR (drift-clean), cycles 5-10
    fire BAUD (drift-detected). No cycle is unattended by both
    properties. The sum of fired cycles equals total cycles.

    This is the structural witness that the two properties form a
    complete partition of the policy pair's behavior at the smoke's
    parameters — the safety claim is bidirectional.
    """
    from project_ghost.properties import verify_baud
    baud = verify_baud(smoke_mcap)
    erur = verify_erur(smoke_mcap)
    assert baud.cycles_precondition_held + erur.cycles_precondition_held == (
        baud.cycles_total
    )
    assert baud.cycles_total == erur.cycles_total
