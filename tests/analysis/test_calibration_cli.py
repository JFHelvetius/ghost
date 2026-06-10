"""Tests del CLI `ghost analyze-calibration` (ADR-0019).

Cubre:

- éxito con --belief-report + --output
- stdout cuando --output se omite
- archivo inexistente → rc=1
- JSON malformed → rc=1
- belief_report con schema_version incorrecto → rc=1
- argparse missing args → rc=2
- byte-identical entre dos invocaciones con mismo input
- SHA-256 del source es el de hashlib.sha256 del archivo
- --help muestra el subcomando
- pipeline completa: analyze-belief → analyze-calibration (smoke)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from project_ghost.analysis import (
    BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION,
    BeliefTraceabilityReport,
    BeliefTraceRecord,
    encode_belief_report_to_bytes,
)
from project_ghost.cli import main


def _make_report() -> BeliefTraceabilityReport:
    """Reporte de muestra con un mix: 1 record con cov, 1 sin cov."""
    recs = (
        BeliefTraceRecord(
            timestamp_ns=0,
            truth_position_xyz=(0.0, 0.0, 0.0),
            belief_position_xyz=(0.5, 0.0, 0.0),
            truth_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            belief_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            position_error_norm_m=0.5,
            orientation_error_rad=0.1,
            covariance_trace=0.04,  # sqrt = 0.2
            covariance_condition_number=1.0,
            covariance_available=True,
        ),
        BeliefTraceRecord(
            timestamp_ns=1000,
            truth_position_xyz=(0.0, 0.0, 0.0),
            belief_position_xyz=(1.0, 0.0, 0.0),
            truth_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            belief_orientation_xyzw=(0.0, 0.0, 0.0, 1.0),
            position_error_norm_m=1.0,
            orientation_error_rad=0.0,
            covariance_trace=None,
            covariance_condition_number=None,
            covariance_available=False,
        ),
    )
    return BeliefTraceabilityReport(
        total_samples=2,
        samples_with_covariance=1,
        samples_without_covariance=1,
        mean_position_error_m=0.75,
        max_position_error_m=1.0,
        mean_orientation_error_rad=0.05,
        max_orientation_error_rad=0.1,
        records=recs,
    )


def _write_report(path: Path) -> bytes:
    """Write the report to ``path``; return the bytes (so tests can hash)."""
    raw = encode_belief_report_to_bytes(_make_report())
    path.write_bytes(raw)
    return raw


def test_cli_analyze_calibration_writes_to_output_file(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "belief.json"
    raw_bytes = _write_report(report_path)
    expected_sha = hashlib.sha256(raw_bytes).hexdigest()
    out_path = tmp_path / "cal.json"

    rc = main(
        [
            "analyze-calibration",
            "--belief-report",
            str(report_path),
            "--output",
            str(out_path),
        ]
    )

    assert rc == 0
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION
    assert data["calibration"]["total_records"] == 2
    assert data["calibration"]["records_usable_for_calibration"] == 1
    assert data["calibration"]["records_not_usable"] == 1
    # Provenance: SHA matches hashlib of the input file bytes.
    assert data["calibration"]["source_belief_report_sha256"] == expected_sha


def test_cli_analyze_calibration_writes_to_stdout_when_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "belief.json"
    _write_report(report_path)

    rc = main(
        [
            "analyze-calibration",
            "--belief-report",
            str(report_path),
        ]
    )

    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["schema_version"] == BELIEF_CALIBRATION_REPORT_SCHEMA_VERSION
    assert parsed["calibration"]["total_records"] == 2


def test_cli_analyze_calibration_byte_identical_outputs(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "belief.json"
    _write_report(report_path)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"

    main(
        [
            "analyze-calibration",
            "--belief-report",
            str(report_path),
            "--output",
            str(a),
        ]
    )
    main(
        [
            "analyze-calibration",
            "--belief-report",
            str(report_path),
            "--output",
            str(b),
        ]
    )

    assert a.read_bytes() == b.read_bytes()


def test_cli_analyze_calibration_missing_args_fails() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze-calibration"])
    assert exc_info.value.code == 2


def test_cli_analyze_calibration_nonexistent_file_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "analyze-calibration",
            "--belief-report",
            str(tmp_path / "does_not_exist.json"),
        ]
    )
    assert rc == 1
    assert capsys.readouterr().err


def test_cli_analyze_calibration_malformed_json_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    rc = main(
        [
            "analyze-calibration",
            "--belief-report",
            str(bad),
        ]
    )
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_cli_analyze_calibration_schema_mismatch_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad_schema.json"
    bad.write_text(
        json.dumps({"schema_version": "999", "report": {}}),
        encoding="utf-8",
    )
    rc = main(
        [
            "analyze-calibration",
            "--belief-report",
            str(bad),
        ]
    )
    assert rc == 1
    assert "schema_version" in capsys.readouterr().err


def test_cli_help_includes_analyze_calibration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "analyze-calibration" in out


def test_cli_pipeline_belief_to_calibration_completes(
    tmp_path: Path,
) -> None:
    """Smoke test del pipeline canónico: producimos un belief_report
    desde código (en vez de via analyze-belief con MCAPs), luego
    invocamos analyze-calibration. La integración con MCAPs reales ya
    está cubierta por test_belief_traceability_cli + este test verifica
    el último eslabón."""
    report_path = tmp_path / "belief.json"
    _write_report(report_path)
    cal_path = tmp_path / "cal.json"

    rc = main(
        [
            "analyze-calibration",
            "--belief-report",
            str(report_path),
            "--output",
            str(cal_path),
        ]
    )
    assert rc == 0

    parsed = json.loads(cal_path.read_text(encoding="utf-8"))
    cal = parsed["calibration"]
    assert cal["total_records"] == 2
    # First record is usable (covariance present, trace > 0); compute
    # expected ratio: 0.5 / sqrt(0.04) = 0.5 / 0.2 = 2.5.
    usable_record = cal["records"][0]
    assert usable_record["usable_for_calibration"] is True
    assert abs(usable_record["position_error_to_uncertainty_ratio"] - 2.5) < 1e-12


def test_cli_analyze_calibration_writes_provenance_sha_correctly(
    tmp_path: Path,
) -> None:
    """The output's source_belief_report_sha256 must equal the SHA-256
    of the input file bytes — independently verifiable."""
    report_path = tmp_path / "belief.json"
    raw = _write_report(report_path)
    expected = hashlib.sha256(raw).hexdigest()
    out_path = tmp_path / "cal.json"

    rc = main(
        [
            "analyze-calibration",
            "--belief-report",
            str(report_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    parsed = json.loads(out_path.read_text(encoding="utf-8"))
    assert parsed["calibration"]["source_belief_report_sha256"] == expected
