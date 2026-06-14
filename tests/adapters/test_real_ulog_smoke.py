"""End-to-end test of the real-ULog orchestrator (paper §8.7).

Drives ``project_ghost.adapters.real_ulog_smoke.run_real_ulog_smoke``
against the bundled real PX4 ULog
(``docs/paper/data/sample.ulg``, downloaded from
PX4/pyulog test fixtures) and asserts the end-to-end pipeline yields
a deterministic MCAP and a non-empty property-verdict bundle.

This is the test that closes paper §8.7's standing critique
(``no real-data validation``). It is deliberately *not*
parametrised — the bundled ULog is the canonical real-flight
artefact this release ships against. A future ADR-0037 will widen
this to motion-capture / RTK-GPS ground truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_ghost.adapters.real_ulog_smoke import (
    RealULogSmokeSummary,
    run_real_ulog_smoke,
)

_REPO_ROOT_FROM_TESTS = ("..", "..")  # tests/adapters/ → repo root
_ULOG_RELATIVE = ("docs", "paper", "data", "sample.ulg")


def _ulog_path_in_repo() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2].joinpath(*_ULOG_RELATIVE)


@pytest.fixture
def real_ulog_path() -> Path:
    path = _ulog_path_in_repo()
    if not path.exists():
        pytest.skip(
            f"Real ULog fixture not present at {path}; download via the URL recorded in paper §8.7."
        )
    return path


def test_real_ulog_smoke_runs_end_to_end(real_ulog_path: Path, tmp_path: Path) -> None:
    """Full pipeline executes on real PX4 telemetry, yields a verdict."""
    out_mcap = tmp_path / "real_ulog_smoke.mcap"
    summary = run_real_ulog_smoke(real_ulog_path, out_mcap)

    assert isinstance(summary, RealULogSmokeSummary)
    assert summary.n_pose_samples_in_ulog > 100
    assert summary.n_cycles_run >= 2
    assert summary.mcap_path == out_mcap
    assert out_mcap.exists()
    assert len(summary.mcap_sha256) == 64
    assert len(summary.ulog_sha256) == 64
    # Every property is well-defined and a bool.
    for holds_value in (
        summary.baud_holds,
        summary.erur_holds,
        summary.md_holds,
        summary.rlb_holds,
        summary.fpb_holds,
    ):
        assert isinstance(holds_value, bool)
    assert 0.0 <= summary.fpb_fire_fraction <= 1.0


def test_real_ulog_smoke_mcap_is_deterministic(real_ulog_path: Path, tmp_path: Path) -> None:
    """Same ULog input → byte-identical MCAP output across two runs.

    This is the cross-replica leg of the PV-1 reproducibility primitive
    applied to real telemetry.
    """
    out_a = tmp_path / "a.mcap"
    out_b = tmp_path / "b.mcap"
    sa = run_real_ulog_smoke(real_ulog_path, out_a)
    sb = run_real_ulog_smoke(real_ulog_path, out_b)
    assert sa.mcap_sha256 == sb.mcap_sha256
    assert sa.ulog_sha256 == sb.ulog_sha256
    assert sa.n_cycles_run == sb.n_cycles_run


def test_real_ulog_smoke_known_fixture_verdict(real_ulog_path: Path, tmp_path: Path) -> None:
    """The bundled PX4 sample log produces the verdict reported in
    paper §8.7. If this test fails, either the ULog was replaced or
    the pipeline changed semantics; both are paper-significant.
    """
    out_mcap = tmp_path / "fixture_smoke.mcap"
    summary = run_real_ulog_smoke(real_ulog_path, out_mcap)
    # Pinning the verdict that paper §8.7 cites; an unexpected
    # change here must be reflected in the paper text.
    assert summary.baud_holds is True
    assert summary.erur_holds is True
    assert summary.md_holds is True
    assert summary.rlb_holds is True
    assert summary.fpb_holds is True
