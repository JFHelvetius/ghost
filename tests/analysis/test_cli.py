"""Tests del CLI `ghost analyze-run` (criterio 10 del spec T5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_ghost.analysis import REPORT_SCHEMA_VERSION
from project_ghost.cli import main
from project_ghost.events import EventType
from project_ghost.telemetry import CHANNEL_EVENTS, MCAPFileSink

from .conftest import make_event, make_vehicle_state, write_state_json


def _setup_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create mcap + state files; return (mcap, state, output_path)."""
    mcap = tmp_path / "test_run.mcap"
    state_path = tmp_path / "state.json"
    output = tmp_path / "report.json"

    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(type_=EventType.ARMED))
        sink.publish(CHANNEL_EVENTS, 200, make_event(type_=EventType.TAKEOFF))

    write_state_json(make_vehicle_state(), state_path)
    return mcap, state_path, output


def test_cli_analyze_run_succeeds_with_required_args(tmp_path: Path) -> None:
    mcap, state_path, output = _setup_run(tmp_path)
    rc = main(
        [
            "analyze-run",
            "--mcap",
            str(mcap),
            "--state",
            str(state_path),
            "--output",
            str(output),
        ]
    )
    assert rc == 0


def test_cli_analyze_run_writes_report_file(tmp_path: Path) -> None:
    mcap, state_path, output = _setup_run(tmp_path)
    main(
        [
            "analyze-run",
            "--mcap",
            str(mcap),
            "--state",
            str(state_path),
            "--output",
            str(output),
        ]
    )
    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == REPORT_SCHEMA_VERSION


def test_cli_analyze_run_counts_events_correctly(tmp_path: Path) -> None:
    mcap, state_path, output = _setup_run(tmp_path)
    main(
        [
            "analyze-run",
            "--mcap",
            str(mcap),
            "--state",
            str(state_path),
            "--output",
            str(output),
        ]
    )
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["event_count"] == 2
    assert data["summary"]["event_type_counts"] == {"armed": 1, "takeoff": 1}


def test_cli_analyze_run_default_run_id_is_mcap_stem(tmp_path: Path) -> None:
    mcap, state_path, output = _setup_run(tmp_path)
    main(
        [
            "analyze-run",
            "--mcap",
            str(mcap),
            "--state",
            str(state_path),
            "--output",
            str(output),
        ]
    )
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["run_id"] == "test_run"


def test_cli_analyze_run_accepts_explicit_run_id(tmp_path: Path) -> None:
    mcap, state_path, output = _setup_run(tmp_path)
    main(
        [
            "analyze-run",
            "--mcap",
            str(mcap),
            "--state",
            str(state_path),
            "--output",
            str(output),
            "--run-id",
            "custom-id-7",
        ]
    )
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["run_id"] == "custom-id-7"


def test_cli_analyze_run_missing_required_args_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze-run"])
    # argparse exits with code 2 on argument errors
    assert exc_info.value.code == 2


def test_cli_no_subcommand_fails(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2


def test_cli_help_text_includes_analyze_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "analyze-run" in out


def test_cli_byte_identical_output_for_same_inputs(tmp_path: Path) -> None:
    mcap, state_path, output_a = _setup_run(tmp_path)
    output_b = tmp_path / "report_b.json"

    main(
        [
            "analyze-run",
            "--mcap",
            str(mcap),
            "--state",
            str(state_path),
            "--output",
            str(output_a),
        ]
    )
    main(
        [
            "analyze-run",
            "--mcap",
            str(mcap),
            "--state",
            str(state_path),
            "--output",
            str(output_b),
        ]
    )
    assert output_a.read_bytes() == output_b.read_bytes()
