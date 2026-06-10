"""Tests del CLI `ghost summarize-belief` (ADR-0017).

Cubre:

- éxito con `--output`
- escritura a stdout cuando `--output` no se pasa
- bytes idénticos entre invocaciones con el mismo report
- argparse: falta de args requeridos → rc=2
- archivo de input inexistente → rc=1 + stderr
- JSON malformado → rc=1 + stderr
- schema_version incompatible → rc=1 + stderr
- `--help` muestra el subcomando
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_ghost.analysis import (
    BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION,
    BeliefTraceabilityReport,
    BeliefTraceRecord,
    encode_belief_report_to_bytes,
)
from project_ghost.cli import main


def _make_report() -> BeliefTraceabilityReport:
    """Reporte de muestra: 2 records con covarianza."""
    recs = (
        BeliefTraceRecord(
            timestamp_ns=0,
            truth_position_xyz=(0.0, 0.0, 0.0),
            belief_position_xyz=(0.1, 0.0, 0.0),
            truth_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            belief_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            position_error_norm_m=0.1,
            orientation_error_rad=0.05,
            covariance_trace=0.015,
            covariance_condition_number=1.0,
            covariance_available=True,
        ),
        BeliefTraceRecord(
            timestamp_ns=1000,
            truth_position_xyz=(0.0, 0.0, 0.0),
            belief_position_xyz=(0.2, 0.0, 0.0),
            truth_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            belief_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            position_error_norm_m=0.2,
            orientation_error_rad=0.10,
            covariance_trace=0.015,
            covariance_condition_number=1.0,
            covariance_available=True,
        ),
    )
    return BeliefTraceabilityReport(
        total_samples=2,
        samples_with_covariance=2,
        samples_without_covariance=0,
        mean_position_error_m=0.15,
        max_position_error_m=0.2,
        mean_orientation_error_rad=0.075,
        max_orientation_error_rad=0.10,
        records=recs,
    )


def _write_report_json(path: Path) -> None:
    path.write_bytes(encode_belief_report_to_bytes(_make_report()))


def test_cli_summarize_belief_writes_to_output_file(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    _write_report_json(report_path)
    output = tmp_path / "summary.json"

    rc = main(
        [
            "summarize-belief",
            "--report",
            str(report_path),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION
    assert data["summary"]["total_samples"] == 2
    assert data["summary"]["samples_with_finite_trace"] == 2


def test_cli_summarize_belief_writes_to_stdout_when_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "report.json"
    _write_report_json(report_path)

    rc = main(
        [
            "summarize-belief",
            "--report",
            str(report_path),
        ]
    )

    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["schema_version"] == BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION
    assert parsed["summary"]["total_samples"] == 2


def test_cli_summarize_belief_byte_identical_outputs(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    _write_report_json(report_path)
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"

    main(
        [
            "summarize-belief",
            "--report",
            str(report_path),
            "--output",
            str(out_a),
        ]
    )
    main(
        [
            "summarize-belief",
            "--report",
            str(report_path),
            "--output",
            str(out_b),
        ]
    )

    assert out_a.read_bytes() == out_b.read_bytes()


def test_cli_summarize_belief_missing_args_fails() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["summarize-belief"])
    assert exc_info.value.code == 2


def test_cli_summarize_belief_nonexistent_file_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "summarize-belief",
            "--report",
            str(tmp_path / "does_not_exist.json"),
        ]
    )
    assert rc == 1
    assert capsys.readouterr().err  # algo se reportó por stderr


def test_cli_summarize_belief_malformed_json_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")

    rc = main(
        [
            "summarize-belief",
            "--report",
            str(bad),
        ]
    )
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_cli_summarize_belief_schema_mismatch_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad_schema.json"
    bad.write_text(
        json.dumps({"schema_version": "999", "report": {}}),
        encoding="utf-8",
    )

    rc = main(
        [
            "summarize-belief",
            "--report",
            str(bad),
        ]
    )
    assert rc == 1
    assert "schema_version" in capsys.readouterr().err


def test_cli_help_includes_summarize_belief(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "summarize-belief" in out
