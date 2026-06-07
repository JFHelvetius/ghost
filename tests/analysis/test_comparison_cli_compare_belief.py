"""Tests del CLI `ghost compare-belief` (ADR-0018).

Cubre:

- éxito con 2 summaries y --output
- éxito con 3 summaries
- éxito con summary + manifest emparejados
- mix: 2 summaries, 1 con manifest
- stdout cuando --output se omite
- argparse missing --summary → rc=2
- duplicate label en --summary → rc=1
- duplicate label en --manifest → rc=1
- --summary sin '=' → rc=1
- --manifest sin '=' → rc=1
- summary file inexistente → rc=1
- summary con JSON malformado → rc=1
- summary con schema_version incorrecto → rc=1
- manifest con label sin matching summary → rc=1
- byte-identical entre dos invocaciones
- --help muestra el subcomando
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_ghost.analysis import (
    BELIEF_COMPARISON_REPORT_SCHEMA_VERSION,
    BeliefConsistencySummary,
    encode_consistency_summary_to_bytes,
    encode_run_manifest_to_bytes,
)
from project_ghost.analysis.comparison import RunManifest
from project_ghost.cli import main


def _summary(total_samples: int = 0) -> BeliefConsistencySummary:
    return BeliefConsistencySummary(
        total_samples=total_samples,
        samples_with_covariance=0,
        samples_without_covariance=0,
        timestamp_first_ns=None,
        timestamp_last_ns=None,
        timestamp_span_ns=None,
        position_error_min_m=0.0,
        position_error_max_m=0.0,
        position_error_mean_m=0.0,
        orientation_error_min_rad=0.0,
        orientation_error_max_rad=0.0,
        orientation_error_mean_rad=0.0,
        covariance_trace_min=None,
        covariance_trace_max=None,
        covariance_trace_mean=None,
        covariance_condition_number_min=None,
        covariance_condition_number_max=None,
        covariance_condition_number_mean=None,
        samples_with_finite_trace=0,
        samples_with_finite_condition_number=0,
    )


def _write_summary(path: Path, total_samples: int) -> None:
    path.write_bytes(
        encode_consistency_summary_to_bytes(_summary(total_samples))
    )


def _write_manifest(path: Path, run_id: str) -> None:
    m = RunManifest(
        run_id=run_id, config_descriptor={"k": run_id}, inputs=(), outputs=()
    )
    path.write_bytes(encode_run_manifest_to_bytes(m))


def test_cli_compare_belief_two_summaries(tmp_path: Path) -> None:
    s_a = tmp_path / "a.json"
    s_b = tmp_path / "b.json"
    _write_summary(s_a, total_samples=10)
    _write_summary(s_b, total_samples=20)
    out = tmp_path / "comp.json"

    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s_a}",
            "--summary",
            f"B={s_b}",
            "--output",
            str(out),
        ]
    )

    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert (
        data["schema_version"] == BELIEF_COMPARISON_REPORT_SCHEMA_VERSION
    )
    assert data["comparison"]["baseline_label"] == "A"
    assert data["comparison"]["labels"] == ["A", "B"]
    assert (
        data["comparison"]["metrics"]["total_samples"]["deltas"]["B"]
        == 10
    )


def test_cli_compare_belief_three_summaries(tmp_path: Path) -> None:
    paths = []
    for i, totals in enumerate([5, 10, 15]):
        p = tmp_path / f"s{i}.json"
        _write_summary(p, total_samples=totals)
        paths.append(p)
    out = tmp_path / "comp.json"

    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={paths[0]}",
            "--summary",
            f"B={paths[1]}",
            "--summary",
            f"C={paths[2]}",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["comparison"]["labels"] == ["A", "B", "C"]


def test_cli_compare_belief_with_paired_manifests(tmp_path: Path) -> None:
    s_a = tmp_path / "a.json"
    s_b = tmp_path / "b.json"
    m_a = tmp_path / "ma.json"
    m_b = tmp_path / "mb.json"
    _write_summary(s_a, total_samples=10)
    _write_summary(s_b, total_samples=20)
    _write_manifest(m_a, "run_a")
    _write_manifest(m_b, "run_b")
    out = tmp_path / "comp.json"

    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s_a}",
            "--summary",
            f"B={s_b}",
            "--manifest",
            f"A={m_a}",
            "--manifest",
            f"B={m_b}",
            "--output",
            str(out),
        ]
    )

    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["comparison"]["manifests"]["A"]["run_id"] == "run_a"
    assert data["comparison"]["manifests"]["B"]["run_id"] == "run_b"


def test_cli_compare_belief_mix_with_and_without_manifest(
    tmp_path: Path,
) -> None:
    s_a = tmp_path / "a.json"
    s_b = tmp_path / "b.json"
    m_a = tmp_path / "ma.json"
    _write_summary(s_a, total_samples=10)
    _write_summary(s_b, total_samples=20)
    _write_manifest(m_a, "run_a")
    out = tmp_path / "comp.json"

    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s_a}",
            "--summary",
            f"B={s_b}",
            "--manifest",
            f"A={m_a}",
            "--output",
            str(out),
        ]
    )

    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["comparison"]["manifests"]["A"]["run_id"] == "run_a"
    assert data["comparison"]["manifests"]["B"] is None


def test_cli_compare_belief_stdout_when_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = tmp_path / "s.json"
    _write_summary(s, total_samples=7)
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"X={s}",
        ]
    )
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["comparison"]["baseline_label"] == "X"


def test_cli_compare_belief_byte_identical_outputs(tmp_path: Path) -> None:
    s_a = tmp_path / "a.json"
    s_b = tmp_path / "b.json"
    _write_summary(s_a, total_samples=3)
    _write_summary(s_b, total_samples=5)
    out_a = tmp_path / "x.json"
    out_b = tmp_path / "y.json"

    main(
        [
            "compare-belief",
            "--summary",
            f"A={s_a}",
            "--summary",
            f"B={s_b}",
            "--output",
            str(out_a),
        ]
    )
    main(
        [
            "compare-belief",
            "--summary",
            f"A={s_a}",
            "--summary",
            f"B={s_b}",
            "--output",
            str(out_b),
        ]
    )

    assert out_a.read_bytes() == out_b.read_bytes()


def test_cli_compare_belief_missing_summary_fails() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["compare-belief"])
    assert exc_info.value.code == 2


def test_cli_compare_belief_duplicate_summary_label_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = tmp_path / "s.json"
    _write_summary(s, total_samples=3)
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s}",
            "--summary",
            f"A={s}",
        ]
    )
    assert rc == 1
    assert "duplicate" in capsys.readouterr().err


def test_cli_compare_belief_duplicate_manifest_label_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = tmp_path / "s.json"
    m = tmp_path / "m.json"
    _write_summary(s, total_samples=3)
    _write_manifest(m, "x")
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s}",
            "--manifest",
            f"A={m}",
            "--manifest",
            f"A={m}",
        ]
    )
    assert rc == 1
    assert "duplicate" in capsys.readouterr().err


def test_cli_compare_belief_summary_without_equals_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "compare-belief",
            "--summary",
            "no_separator",
        ]
    )
    assert rc == 1
    assert "LABEL=PATH" in capsys.readouterr().err


def test_cli_compare_belief_manifest_without_equals_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = tmp_path / "s.json"
    _write_summary(s, total_samples=3)
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s}",
            "--manifest",
            "no_separator",
        ]
    )
    assert rc == 1
    assert "LABEL=PATH" in capsys.readouterr().err


def test_cli_compare_belief_summary_file_missing_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={tmp_path / 'does_not_exist.json'}",
        ]
    )
    assert rc == 1
    assert capsys.readouterr().err


def test_cli_compare_belief_summary_malformed_json_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={bad}",
        ]
    )
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_cli_compare_belief_summary_non_object_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "list.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={bad}",
        ]
    )
    assert rc == 1
    assert "JSON object" in capsys.readouterr().err


def test_cli_compare_belief_summary_schema_mismatch_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"schema_version": "999", "summary": {}}),
        encoding="utf-8",
    )
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={bad}",
        ]
    )
    assert rc == 1
    assert "schema_version" in capsys.readouterr().err


def test_cli_compare_belief_manifest_without_matching_summary_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = tmp_path / "s.json"
    m = tmp_path / "m.json"
    _write_summary(s, total_samples=3)
    _write_manifest(m, "x")
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s}",
            "--manifest",
            f"B={m}",  # B no aparece como summary
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "no matching" in err
    assert "'B'" in err


def test_cli_compare_belief_manifest_malformed_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = tmp_path / "s.json"
    m = tmp_path / "m_bad.json"
    _write_summary(s, total_samples=3)
    m.write_text("not json", encoding="utf-8")
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s}",
            "--manifest",
            f"A={m}",
        ]
    )
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_cli_compare_belief_summary_empty_label_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`=path` tiene LABEL vacío → debe ser rechazado."""
    s = tmp_path / "s.json"
    _write_summary(s, total_samples=3)
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"={s}",
        ]
    )
    assert rc == 1
    assert "non-empty" in capsys.readouterr().err


def test_cli_compare_belief_manifest_schema_mismatch_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Manifest JSON válido pero con schema_version incompatible."""
    s = tmp_path / "s.json"
    bad_manifest = tmp_path / "bad_m.json"
    _write_summary(s, total_samples=3)
    bad_manifest.write_text(
        json.dumps({"schema_version": "999", "manifest": {}}),
        encoding="utf-8",
    )
    rc = main(
        [
            "compare-belief",
            "--summary",
            f"A={s}",
            "--manifest",
            f"A={bad_manifest}",
        ]
    )
    assert rc == 1
    assert "schema_version" in capsys.readouterr().err


def test_cli_help_includes_compare_belief(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "compare-belief" in out
