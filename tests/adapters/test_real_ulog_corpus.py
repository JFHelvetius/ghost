"""End-to-end test of the multi-ULog discrimination corpus (paper §8.8.1).

Drives ``run_multi_ulog_discrimination`` over the bundled 3-ULog
corpus and pins the **honest** matrix shape — including the
informative non-discrimination cells (the ``sample_logging_tagged.ulg``
row where ``fpb_fire_fraction ≈ 0`` and the buggy producers' drift
precondition never fires).

Pinning rationale: §8.8 was previously pinned only on ``sample.ulg``.
This test extends that pin to the corpus so that:

- if a future change regresses discrimination on the active ULogs
  (``sample.ulg`` and ``sample_appended.ulg`` — both with
  ``fire_fraction > 0.9``), the test fails;
- if the verifier *starts* flipping properties on a stationary
  ULog without anything firing — i.e. a false-positive on a log
  where preconditions are vacuously satisfied — the test fails;
- the JSON artefact ``out_dir/matrix.json`` is produced and is
  self-describing (schema_version, diagnostics, both matrices).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_ghost.adapters.real_ulog_corpus import (
    MultiULogCorpusResults,
    run_multi_ulog_discrimination,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2]


def _corpus_paths_or_skip() -> list[Path]:
    root = _repo_root()
    paths = [
        root / "docs" / "paper" / "data" / "sample.ulg",
        root / "docs" / "paper" / "data" / "corpus" / "sample_appended.ulg",
        root / "docs" / "paper" / "data" / "corpus" / "sample_logging_tagged.ulg",
    ]
    missing = [p for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"Corpus ULog(s) missing: {[str(p) for p in missing]}")
    return paths


@pytest.fixture(scope="module")
def corpus_paths() -> list[Path]:
    return _corpus_paths_or_skip()


@pytest.fixture(scope="module")
def corpus_results(
    corpus_paths: list[Path], tmp_path_factory: pytest.TempPathFactory
) -> tuple[MultiULogCorpusResults, Path]:
    """Single matrix run shared across all tests in this module.

    Re-running the matrix per test would multiply CI time by 6x
    for no extra coverage; we share one run, then each test makes
    independent assertions on its shape.
    """
    out_dir = tmp_path_factory.mktemp("multi_ulog_corpus")
    results = run_multi_ulog_discrimination(corpus_paths, out_dir, emit_json=True)
    return results, out_dir


def test_run_multi_ulog_rejects_empty_corpus(tmp_path: Path) -> None:
    """Empty corpus is a programmer error, not a "no data" condition."""
    with pytest.raises(ValueError, match="empty"):
        run_multi_ulog_discrimination([], tmp_path)


def test_matrices_have_expected_shape(
    corpus_paths: list[Path],
    corpus_results: tuple[MultiULogCorpusResults, Path],
) -> None:
    """Detection + isolation matrices both have shape 6-by-N(corpus)."""
    results, _ = corpus_results

    assert isinstance(results, MultiULogCorpusResults)
    assert len(results.matrix) == 6, "exactly 6 bug categories expected"
    assert len(results.isolation_matrix) == 6
    for row in results.matrix.values():
        assert set(row.keys()) == {p.name for p in corpus_paths}
    for row in results.isolation_matrix.values():
        assert set(row.keys()) == {p.name for p in corpus_paths}


def test_every_ulog_discriminates_every_category(
    corpus_paths: list[Path],
    corpus_results: tuple[MultiULogCorpusResults, Path],
) -> None:
    """With v0.2.5 (SITL GT auto-detect), every cell discriminates.

    Paper §8.8.2 reports the corpus matrix as fully green
    (``all_discriminate=True``) once independent GT is sourced where
    available. If this regresses, either the SITL GT path broke or
    the EKF2 fallback regressed on a previously-active ULog — both
    are paper-load-bearing failures.
    """
    results, _ = corpus_results

    assert results.all_discriminate is True, (
        "corpus matrix regressed below 18/18 cells. "
        "Inspect matrix.json and identify which (category, ULog) cell "
        "is now reporting HOLDS for both nominal and buggy."
    )


def test_stationary_ulog_uses_sitl_gt(
    corpus_paths: list[Path],
    corpus_results: tuple[MultiULogCorpusResults, Path],
) -> None:
    """``sample_logging_tagged.ulg`` MUST be upgraded to SITL GT.

    The whole point of v0.2.5 / paper §8.8.2 is closing the
    "vacuous holds on stationary ULogs" gap. If the auto-detect
    silently falls back to EKF2 on this ULog, the §8.8.2 claim is
    retroactively false. The ULog carries
    ``vehicle_local_position_groundtruth`` + ``vehicle_attitude_groundtruth``
    (this is the fixture invariant the test pins).
    """
    results, _ = corpus_results

    name = "sample_logging_tagged.ulg"
    if name not in results.per_ulog:
        pytest.skip(f"corpus does not include {name}")
    summary = results.per_ulog[name].nominal
    assert summary.groundtruth_source.value == "sitl_simulator", (
        f"{name} should auto-detect SITL GT (PX4 SITL log with "
        f"groundtruth topics). Got: {summary.groundtruth_source.value}"
    )
    # And the precondition must now actually fire (fire_fraction > 0).
    assert summary.fpb_fire_fraction > 0.1, (
        f"{name} with SITL GT should exercise BAUD-v1's drift "
        f"precondition; got fire_fraction = {summary.fpb_fire_fraction}"
    )


def test_emit_json_writes_self_describing_artefact(
    corpus_paths: list[Path],
    corpus_results: tuple[MultiULogCorpusResults, Path],
) -> None:
    """``matrix.json`` exists, is parseable, and carries diagnostics."""
    _, out_dir = corpus_results

    json_path = out_dir / "matrix.json"
    assert json_path.exists(), "matrix.json was not emitted"

    payload = json.loads(json_path.read_text())
    assert payload["schema_version"] == 1
    assert payload["experiment"] == "multi_ulog_discrimination"
    assert set(payload["ulog_corpus"]) == {p.name for p in corpus_paths}
    assert set(payload["diagnostics"].keys()) == {p.name for p in corpus_paths}
    for diag in payload["diagnostics"].values():
        assert "fpb_fire_fraction" in diag
        assert "cycles_run" in diag
        assert "groundtruth_source" in diag
        assert diag["groundtruth_source"] in (
            "ekf2_fallback",
            "sitl_simulator",
        )
    assert "detection_matrix" in payload
    assert "isolation_matrix" in payload
    assert isinstance(payload["all_discriminate"], bool)
    assert isinstance(payload["all_isolated"], bool)


def test_emit_json_can_be_disabled(corpus_paths: list[Path], tmp_path: Path) -> None:
    """``emit_json=False`` produces no ``matrix.json``.

    Run with a single ULog to keep this fast; the JSON-emission
    decision is orthogonal to corpus size.
    """
    single = [corpus_paths[0]]
    run_multi_ulog_discrimination(single, tmp_path, emit_json=False)
    assert not (tmp_path / "matrix.json").exists()
