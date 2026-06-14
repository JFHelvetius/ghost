"""End-to-end test of the real-ULog discrimination experiment (paper §8.8).

Drives ``project_ghost.adapters.real_ulog_discrimination.run_real_ulog_discrimination``
on the bundled real PX4 ULog and asserts the verifier flips its
verdict from HOLDS to VIOLATED on every buggy category.

Pinning rationale: the nominal MCAP SHA-256 already pinned in
``tests/adapters/test_real_ulog_smoke.py`` is the §8.7 anchor;
this test adds §8.8's anchor — the *delta* between nominal and
buggy verdicts on the same real log. If a future change either
makes the buggy runs HOLD (false negative) or makes the nominal
run VIOLATED (false positive), this test will catch it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_ghost.adapters.real_ulog_discrimination import (
    RealULogBugCategory,
    RealULogDiscriminationResults,
    run_real_ulog_discrimination,
)

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


def test_discrimination_returns_results_for_every_category(
    real_ulog_path: Path, tmp_path: Path
) -> None:
    """One buggy cell per ``RealULogBugCategory`` is produced."""
    results = run_real_ulog_discrimination(real_ulog_path, tmp_path)

    assert isinstance(results, RealULogDiscriminationResults)
    categories_run = {cell.category for cell in results.buggy_cells}
    assert categories_run == set(RealULogBugCategory)


def test_nominal_real_ulog_all_holds(real_ulog_path: Path, tmp_path: Path) -> None:
    """Reference policies on real ULog → all five properties HOLD.

    This is the §8.7 verdict embedded in the §8.8 experiment.
    """
    results = run_real_ulog_discrimination(real_ulog_path, tmp_path)
    nom = results.nominal
    assert nom.baud_holds is True
    assert nom.erur_holds is True
    assert nom.md_holds is True
    assert nom.rlb_holds is True
    assert nom.fpb_holds is True


def test_every_buggy_category_discriminates(
    real_ulog_path: Path, tmp_path: Path
) -> None:
    """Each buggy category flips its expected property on the real ULog.

    This is the §8.8 contribution: not a vacuous all-HOLDS but a
    real-data discrimination demonstration.
    """
    results = run_real_ulog_discrimination(real_ulog_path, tmp_path)
    assert results.all_discriminate is True
    for cell in results.buggy_cells:
        assert cell.discriminates is True, (
            f"category {cell.category.value} expected to flip "
            f"{cell.expected_violator} but it held"
        )


def test_buggy_mcap_shas_differ_from_nominal(
    real_ulog_path: Path, tmp_path: Path
) -> None:
    """Buggy runs leave a visible mark in MCAP (different policy_id,
    different reason), so SHAs must differ from nominal.
    """
    results = run_real_ulog_discrimination(real_ulog_path, tmp_path)
    nominal_sha = results.nominal.mcap_sha256
    for cell in results.buggy_cells:
        assert cell.summary.mcap_sha256 != nominal_sha


def test_discrimination_isolates_violation_to_baud(
    real_ulog_path: Path, tmp_path: Path
) -> None:
    """Both currently-shipped buggy categories attack BAUD-v1
    specifically; the other four properties must remain HOLD on each
    buggy run. This is what 'isolation' means in the discrimination
    matrix.
    """
    results = run_real_ulog_discrimination(real_ulog_path, tmp_path)
    for cell in results.buggy_cells:
        assert cell.summary.baud_holds is False
        assert cell.summary.erur_holds is True
        assert cell.summary.md_holds is True
        assert cell.summary.rlb_holds is True
        assert cell.summary.fpb_holds is True


def test_discrimination_is_deterministic(real_ulog_path: Path, tmp_path: Path) -> None:
    """Same ULog → same MCAP SHAs across two independent runs."""
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    ra = run_real_ulog_discrimination(real_ulog_path, out_a)
    rb = run_real_ulog_discrimination(real_ulog_path, out_b)
    assert ra.nominal.mcap_sha256 == rb.nominal.mcap_sha256
    a_by_cat = {c.category: c.summary.mcap_sha256 for c in ra.buggy_cells}
    b_by_cat = {c.category: c.summary.mcap_sha256 for c in rb.buggy_cells}
    assert a_by_cat == b_by_cat
