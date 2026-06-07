"""Tests del CLI `ghost trace-event` (criterio 11 del spec T6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_ghost.cli import main
from project_ghost.events import EventType
from project_ghost.telemetry import CHANNEL_EVENTS, MCAPFileSink

from .conftest import make_event


def _setup_run(tmp_path: Path) -> Path:
    mcap = tmp_path / "run.mcap"
    with MCAPFileSink(mcap) as sink:
        sink.publish(CHANNEL_EVENTS, 100, make_event(sequence=0, type_=EventType.ARMED))
        sink.publish(CHANNEL_EVENTS, 200, make_event(sequence=1, type_=EventType.TAKEOFF))
        sink.publish(CHANNEL_EVENTS, 300, make_event(sequence=2, type_=EventType.LANDED))
    return mcap


def test_cli_trace_event_succeeds_with_required_args(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = _setup_run(tmp_path)
    rc = main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "2",
            "--window-seconds",
            "5.0",
        ]
    )
    assert rc == 0


def test_cli_trace_event_writes_json_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = _setup_run(tmp_path)
    main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "2",
            "--window-seconds",
            "5.0",
        ]
    )
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["schema_version"] == "1"
    assert data["trace"]["event_id"] == 2
    assert data["trace"]["event_type"] == "landed"


def test_cli_trace_event_default_window_is_5_seconds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = _setup_run(tmp_path)
    main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "2",
        ]
    )
    out = capsys.readouterr().out
    data = json.loads(out)
    # window_ns = int(5.0 * 1e9) = 5_000_000_000
    assert data["trace"]["window_end_ns"] - data["trace"]["window_start_ns"] == 5_000_000_000


def test_cli_trace_event_unknown_event_id_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = _setup_run(tmp_path)
    rc = main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "999",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "999" in err


def test_cli_trace_event_negative_window_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = _setup_run(tmp_path)
    rc = main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "0",
            "--window-seconds",
            "-1",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "window-seconds" in err


def test_cli_trace_event_zero_window_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = _setup_run(tmp_path)
    rc = main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "2",
            "--window-seconds",
            "0",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["trace"]["preceding_events"] == []


def test_cli_trace_event_missing_required_args_exits_2(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["trace-event"])
    assert exc_info.value.code == 2


def test_cli_help_text_includes_trace_event(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "trace-event" in out


def test_cli_byte_identical_stdout_for_same_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = _setup_run(tmp_path)
    main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "2",
            "--window-seconds",
            "5.0",
        ]
    )
    first = capsys.readouterr().out

    main(
        [
            "trace-event",
            "--mcap",
            str(mcap),
            "--event-id",
            "2",
            "--window-seconds",
            "5.0",
        ]
    )
    second = capsys.readouterr().out

    assert first == second
