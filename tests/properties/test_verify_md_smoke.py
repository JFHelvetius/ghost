"""Sanity tests for :func:`verify_md` against the reference closed-loop
smoke. Counterpart of :mod:`tests.properties.test_verify_baud_smoke`
and :mod:`tests.properties.test_verify_erur_smoke`.

The smoke fixes ``raw.overall_level = KNOWN`` for all 10 cycles (small
declared covariance, ADR-0020 thresholds). The reference calibration
policy either passes through (early cycles) or downgrades KNOWN →
UNCERTAIN (after cycle 4). Both branches satisfy MD-v1 by construction.

Therefore the smoke exercises MD-v1 weakly (only the
``raw=KNOWN → adjusted∈{KNOWN, UNCERTAIN}`` slice). Strong coverage
across the full 3x3 raw-x-adjusted matrix lives in the property test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke
from project_ghost.properties import (
    MD_PROPERTY_VERSION,
    MDVerificationReport,
    verify_md,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def smoke_mcap(tmp_path: Path) -> Path:
    mcap_path = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(mcap_path, n_cycles=10)
    return mcap_path


def test_reference_smoke_satisfies_md_v1(smoke_mcap: Path) -> None:
    """The reference smoke is a witness for the
    ``raw=KNOWN → adj∈{KNOWN, UNCERTAIN}`` slice of MD-v1."""
    report = verify_md(smoke_mcap)
    assert isinstance(report, MDVerificationReport)
    assert report.holds, f"MD-v1 violated by reference smoke: {report.violations}"


def test_report_has_expected_shape(smoke_mcap: Path) -> None:
    report = verify_md(smoke_mcap)
    assert report.property_version == MD_PROPERTY_VERSION
    assert report.cycles_total == 10
    # MD has no precondition — every cycle is evaluated.
    assert report.cycles_precondition_held == 10
    assert report.first_precondition_cycle_stamp_sim_ns is not None
    assert len(report.mcap_sha256) == 64


def test_smoke_exercises_both_passthrough_and_downgrade(
    smoke_mcap: Path,
) -> None:
    """The smoke's first cycles are passthrough (raw=adj=KNOWN); the
    later cycles are downgrade (raw=KNOWN, adj=UNCERTAIN). MD must
    hold on both branches.
    """
    from project_ghost.core.feedback.types import CalibratedSelfAssessment
    from project_ghost.telemetry import (
        CHANNEL_CALIBRATED_SELF_ASSESSMENT,
        MCAPReplayReader,
        decode_message,
    )

    transitions = set()
    with MCAPReplayReader(smoke_mcap) as reader:
        for msg in reader.iter_messages():
            if msg.channel != CHANNEL_CALIBRATED_SELF_ASSESSMENT:
                continue
            c = decode_message(msg)
            if not isinstance(c, CalibratedSelfAssessment):
                continue
            transitions.add(
                (
                    c.raw_assessment.overall_level.value,
                    c.adjusted_overall_level.value,
                )
            )
    assert ("known", "known") in transitions, (
        "Smoke MCAP no longer exercises the passthrough branch."
    )
    assert ("known", "uncertain") in transitions, (
        "Smoke MCAP no longer exercises the downgrade branch."
    )


def test_same_inputs_same_report(smoke_mcap: Path) -> None:
    a = verify_md(smoke_mcap)
    b = verify_md(smoke_mcap)
    assert a == b
    assert a.mcap_sha256 == b.mcap_sha256
