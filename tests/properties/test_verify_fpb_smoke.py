"""Sanity tests for :func:`verify_fpb` against the reference closed-loop
smoke. FPB-v1 is observational, not pass/fail by nature, so the tests
pin the **observed fire fraction** as the smoke baseline regression
gate (cycles_baud_fires / cycles_total = 6 / 10 = 0.6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.properties import (
    FPB_PROPERTY_VERSION,
    FPBVerificationReport,
    verify_fpb,
)

if TYPE_CHECKING:
    from pathlib import Path


_EXPECTED_FIRE_FRACTION = 0.6  # 6 BAUD fires in 10-cycle smoke


@pytest.fixture
def smoke_mcap(tmp_path: Path) -> Path:
    mcap_path = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(mcap_path, n_cycles=10)
    return mcap_path


def test_default_observer_always_holds(smoke_mcap: Path) -> None:
    """Default ``max_fire_fraction=1.0`` is a pure observer — never fails."""
    report = verify_fpb(smoke_mcap)
    assert isinstance(report, FPBVerificationReport)
    assert report.holds
    assert report.fire_fraction == _EXPECTED_FIRE_FRACTION
    assert report.max_fire_fraction == 1.0


def test_report_has_expected_shape(smoke_mcap: Path) -> None:
    report = verify_fpb(smoke_mcap)
    assert report.property_version == FPB_PROPERTY_VERSION
    assert report.min_outcomes == 4
    assert report.downgrade_threshold == 2
    assert report.cycles_total == 10
    assert report.cycles_precondition_held == 6
    assert len(report.mcap_sha256) == 64


def test_loose_bound_holds(smoke_mcap: Path) -> None:
    """A bound looser than the observed fraction still holds."""
    report = verify_fpb(smoke_mcap, max_fire_fraction=0.7)
    assert report.holds


def test_tight_bound_fails_as_regression_gate(smoke_mcap: Path) -> None:
    """A bound tighter than the observed fraction fails — this is how
    FPB acts as a regression gate."""
    report = verify_fpb(smoke_mcap, max_fire_fraction=0.5)
    assert not report.holds
    assert len(report.violations) == 1


def test_exact_bound_at_observed_value_holds(smoke_mcap: Path) -> None:
    """The bound is inclusive: bound == observed still holds."""
    report = verify_fpb(smoke_mcap, max_fire_fraction=_EXPECTED_FIRE_FRACTION)
    assert report.holds


@pytest.mark.parametrize(
    ("min_outcomes", "downgrade_threshold", "max_fire_fraction"),
    [
        (-1, 2, 1.0),
        (4, 0, 1.0),
        (4, 2, -0.1),
        (4, 2, 1.5),
        (4, 2, float("nan")),
    ],
)
def test_invalid_parameters_rejected(
    smoke_mcap: Path,
    min_outcomes: int,
    downgrade_threshold: int,
    max_fire_fraction: float,
) -> None:
    with pytest.raises(ValueError):
        verify_fpb(
            smoke_mcap,
            min_outcomes=min_outcomes,
            downgrade_threshold=downgrade_threshold,
            max_fire_fraction=max_fire_fraction,
        )


def test_same_inputs_same_report(smoke_mcap: Path) -> None:
    a = verify_fpb(smoke_mcap)
    b = verify_fpb(smoke_mcap)
    assert a == b


def test_fire_fraction_matches_baud_cycles(smoke_mcap: Path) -> None:
    """FPB's count of fired cycles must match BAUD's
    ``cycles_precondition_held`` exactly — both re-evaluate the same
    precondition. Cross-property consistency witness."""
    from project_ghost.properties import verify_baud
    fpb = verify_fpb(smoke_mcap)
    baud = verify_baud(smoke_mcap)
    assert fpb.cycles_precondition_held == baud.cycles_precondition_held
