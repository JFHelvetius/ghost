"""Tests del `generate_trace_report` + `encode_trace_to_bytes`.

Cubre criterio 10 del spec T6 (byte-identical JSON) + validación de
schema + roundtrip.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from project_ghost.traceability import (
    TRACE_REPORT_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    BehaviorTrace,
    TracedMessage,
    encode_trace_to_bytes,
    generate_trace_report,
)


def _trace(**overrides: object) -> BehaviorTrace:
    defaults: dict[str, object] = {
        "event_id": 7,
        "event_type": "safety_violation",
        "preceding_events": (
            TracedMessage(
                channel="/events",
                log_time_sim_ns=100,
                schema_name="project_ghost.events.types.Event",
                summary={
                    "type": "armed",
                    "sequence": 0,
                    "severity": 20,
                    "source": "test",
                    "correlation_id": None,
                },
            ),
        ),
        "preceding_sensor_samples": (),
        "preceding_actuator_commands": (),
        "preceding_state_changes": (),
        "window_start_ns": 0,
        "window_end_ns": 200,
    }
    defaults.update(overrides)
    return BehaviorTrace(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_trace_report_has_wrapper_schema_version() -> None:
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    assert data["schema_version"] == TRACE_REPORT_SCHEMA_VERSION


def test_trace_report_has_trace_field() -> None:
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    assert "trace" in data
    assert isinstance(data["trace"], dict)


def test_trace_report_contains_all_behavior_trace_fields() -> None:
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    trace = data["trace"]
    expected = {
        "event_id",
        "event_type",
        "preceding_events",
        "preceding_sensor_samples",
        "preceding_actuator_commands",
        "preceding_state_changes",
        "window_start_ns",
        "window_end_ns",
        "schema_version",
    }
    assert set(trace.keys()) == expected


def test_trace_report_inner_schema_version_present() -> None:
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    assert data["trace"]["schema_version"] == TRACE_SCHEMA_VERSION


def test_trace_report_top_level_keys_alphabetical() -> None:
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    assert list(data.keys()) == sorted(data.keys())


def test_trace_report_trace_keys_alphabetical() -> None:
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    assert list(data["trace"].keys()) == sorted(data["trace"].keys())


def test_trace_report_traced_message_summary_keys_alphabetical() -> None:
    """Each TracedMessage's summary dict has its keys sorted alphabetically."""
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    summary_keys = list(data["trace"]["preceding_events"][0]["summary"].keys())
    assert summary_keys == sorted(summary_keys)


# ---------------------------------------------------------------------------
# Byte determinism (criterio 10)
# ---------------------------------------------------------------------------


def test_encode_trace_to_bytes_is_byte_identical_for_same_input() -> None:
    t = _trace()
    a = encode_trace_to_bytes(t)
    b = encode_trace_to_bytes(t)
    c = encode_trace_to_bytes(t)
    assert a == b == c


def test_generate_trace_report_writes_same_bytes_as_encoder(tmp_path: Path) -> None:
    t = _trace()
    p = tmp_path / "trace.json"
    generate_trace_report(t, p)
    assert p.read_bytes() == encode_trace_to_bytes(t)


def test_generate_trace_report_to_stdout_when_output_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    generate_trace_report(_trace(), output=None)
    captured = capsys.readouterr().out
    assert json.loads(captured)["schema_version"] == TRACE_REPORT_SCHEMA_VERSION


def test_generate_trace_report_to_text_stream() -> None:
    t = _trace()
    buf = io.StringIO()
    generate_trace_report(t, output=buf)
    assert json.loads(buf.getvalue())["schema_version"] == TRACE_REPORT_SCHEMA_VERSION


def test_generate_trace_report_rejects_string_output() -> None:
    """str/bytes are NOT writable streams; loud rejection."""
    t = _trace()
    with pytest.raises(TypeError, match="Path or a writable text stream"):
        generate_trace_report(t, output="some-string")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Format details
# ---------------------------------------------------------------------------


def test_trace_report_uses_indent_2() -> None:
    encoded = encode_trace_to_bytes(_trace()).decode("utf-8")
    assert '\n  "schema_version"' in encoded or '\n  "trace"' in encoded


def test_trace_report_has_trailing_newline() -> None:
    encoded = encode_trace_to_bytes(_trace())
    assert encoded.endswith(b"\n")


def test_trace_report_is_utf8() -> None:
    encoded = encode_trace_to_bytes(_trace())
    encoded.decode("utf-8")


def test_trace_report_handles_non_ascii_event_type() -> None:
    encoded = encode_trace_to_bytes(_trace(event_type="ñ-evento"))
    text = encoded.decode("utf-8")
    assert "ñ-evento" in text


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------


def test_trace_report_roundtrips_via_json_loads(tmp_path: Path) -> None:
    t = _trace(event_id=99, event_type="collision")
    p = tmp_path / "trace.json"
    generate_trace_report(t, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["trace"]["event_id"] == 99
    assert data["trace"]["event_type"] == "collision"


def test_trace_report_preserves_traced_message_structure(tmp_path: Path) -> None:
    t = _trace()
    p = tmp_path / "trace.json"
    generate_trace_report(t, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    msg = data["trace"]["preceding_events"][0]
    assert msg["channel"] == "/events"
    assert msg["log_time_sim_ns"] == 100
    assert msg["summary"]["type"] == "armed"


def test_trace_report_empty_lists_serialize_as_empty_arrays() -> None:
    """Empty tuples → empty JSON arrays (not omitted, not null)."""
    encoded = encode_trace_to_bytes(_trace())
    data = json.loads(encoded)
    assert data["trace"]["preceding_sensor_samples"] == []
    assert data["trace"]["preceding_actuator_commands"] == []
    assert data["trace"]["preceding_state_changes"] == []
