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


def test_active_ulogs_discriminate_all_six_categories(
    corpus_paths: list[Path],
    corpus_results: tuple[MultiULogCorpusResults, Path],
) -> None:
    """ULogs with ``fire_fraction > 0.9`` discriminate every category.

    These are the cells the paper §8.8.1 claim rests on. If this
    regresses, the §8.8.1 detection sub-claim is invalid and the
    paper must be updated before merging.
    """
    results, _ = corpus_results

    active = [
        p.name for p in corpus_paths
        if results.per_ulog[p.name].nominal.fpb_fire_fraction > 0.9
    ]
    assert active, "no active (fire_fraction > 0.9) ULog in corpus"

    for cat, row in results.matrix.items():
        for ulog_name in active:
            assert row[ulog_name] is True, (
                f"{cat} regressed on active ULog {ulog_name} "
                f"(fire_fraction > 0.9 but discriminates=False)"
            )


def test_stationary_ulog_holds_vacuously(
    corpus_paths: list[Path],
    corpus_results: tuple[MultiULogCorpusResults, Path],
) -> None:
    """ULogs with ``fire_fraction ≈ 0`` MUST report mostly HOLDS.

    Otherwise the verifier is flipping properties on a log where
    no precondition has fired — that would be a false positive
    and §8.8.1's honesty about "informative non-discrimination"
    would be retroactively false. We allow up to 2/6 categories
    to legitimately fire (calibrator_invents_confidence and
    decision_never_proceeds can fire on stationary logs because
    they do not require drift to be observed).
    """
    results, _ = corpus_results

    stationary = [
        p.name for p in corpus_paths
        if results.per_ulog[p.name].nominal.fpb_fire_fraction < 0.01
    ]
    if not stationary:
        pytest.skip("no stationary ULog (fire_fraction < 0.01) in corpus")

    for ulog_name in stationary:
        detected = sum(
            1 for row in results.matrix.values() if row.get(ulog_name) is True
        )
        assert detected <= 2, (
            f"{ulog_name} fired {detected}/6 categories despite "
            f"fire_fraction < 0.01 — likely a false-positive regression"
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
