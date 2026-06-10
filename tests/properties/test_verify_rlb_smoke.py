"""Sanity tests for :func:`verify_rlb` against the reference closed-loop
smoke. The smoke uses sustained drift (5 m/s linear motion), so no
recovery transition is ever observed. RLB-v1 holds vacuously, with
``cycles_precondition_held == 0``.

The tests pin exactly that shape — the smoke is the baseline witness
that RLB does not produce false positives under sustained-drift
executions. Strong coverage of actual recovery transitions lives in
the property test (``test_rlb_property.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.properties import (
    RLB_PROPERTY_VERSION,
    RLBVerificationReport,
    verify_rlb,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def smoke_mcap(tmp_path: Path) -> Path:
    mcap_path = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(mcap_path, n_cycles=10)
    return mcap_path


def test_reference_smoke_satisfies_rlb_v1_vacuously(
    smoke_mcap: Path,
) -> None:
    """No recovery transition in sustained-drift smoke → trivially holds."""
    report = verify_rlb(smoke_mcap)
    assert isinstance(report, RLBVerificationReport)
    assert report.holds
    assert report.cycles_precondition_held == 0
    assert report.first_precondition_cycle_stamp_sim_ns is None
    assert report.violations == ()


def test_report_has_expected_shape(smoke_mcap: Path) -> None:
    report = verify_rlb(smoke_mcap)
    assert report.property_version == RLB_PROPERTY_VERSION
    assert report.max_history == 32
    assert report.cycles_total == 10
    assert len(report.mcap_sha256) == 64


def test_invalid_max_history_rejected(smoke_mcap: Path) -> None:
    with pytest.raises(ValueError, match="max_history"):
        verify_rlb(smoke_mcap, max_history=-1)


def test_same_inputs_same_report(smoke_mcap: Path) -> None:
    a = verify_rlb(smoke_mcap)
    b = verify_rlb(smoke_mcap)
    assert a == b
    assert a.mcap_sha256 == b.mcap_sha256
