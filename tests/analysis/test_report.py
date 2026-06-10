"""Tests del `generate_run_report` + `encode_report_to_bytes`.

Cubre criterios 8, 11, 15 del spec T5: byte-identical generation, schema
validation, roundtrip.
"""

from __future__ import annotations

import json
from pathlib import Path

from project_ghost.analysis import (
    REPORT_SCHEMA_VERSION,
    RunSummary,
    encode_report_to_bytes,
    generate_run_report,
)


def _summary(**overrides: object) -> RunSummary:
    defaults: dict[str, object] = {
        "run_id": "test-run",
        "event_count": 3,
        "sensor_sample_count": 10,
        "actuator_command_count": 2,
        "state_transition_count": 1,
        "healthy_sensor_count": 2,
        "unhealthy_sensor_count": 1,
        "first_timestamp_ns": 0,
        "last_timestamp_ns": 1000,
        "duration_ns": 1000,
        "event_type_counts": {"armed": 1, "takeoff": 1, "landed": 1},
        "sensor_type_counts": {"IMUPayload": 10},
        "actuator_type_counts": {"DirectMotorCommand": 2},
        "final_state_hash": "abcdef1234567890" * 4,
    }
    defaults.update(overrides)
    return RunSummary(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema validation (Test 11)
# ---------------------------------------------------------------------------


def test_report_has_wrapper_schema_version_field() -> None:
    encoded = encode_report_to_bytes(_summary())
    data = json.loads(encoded)
    assert data["schema_version"] == REPORT_SCHEMA_VERSION


def test_report_has_summary_field() -> None:
    encoded = encode_report_to_bytes(_summary())
    data = json.loads(encoded)
    assert "summary" in data
    assert isinstance(data["summary"], dict)


def test_report_summary_contains_all_run_summary_fields() -> None:
    encoded = encode_report_to_bytes(_summary())
    data = json.loads(encoded)
    summary = data["summary"]
    expected_fields = {
        "run_id",
        "event_count",
        "sensor_sample_count",
        "actuator_command_count",
        "state_transition_count",
        "healthy_sensor_count",
        "unhealthy_sensor_count",
        "first_timestamp_ns",
        "last_timestamp_ns",
        "duration_ns",
        "event_type_counts",
        "sensor_type_counts",
        "actuator_type_counts",
        "final_state_hash",
        "schema_version",
        # T6 (ADR-0014): backward-compatible extension
        "traceable_events_count",
    }
    assert set(summary.keys()) == expected_fields


def test_report_top_level_keys_alphabetical() -> None:
    """sort_keys=True at every level."""
    encoded = encode_report_to_bytes(_summary())
    data = json.loads(encoded)
    assert list(data.keys()) == sorted(data.keys())


def test_report_summary_keys_alphabetical() -> None:
    encoded = encode_report_to_bytes(_summary())
    data = json.loads(encoded)
    assert list(data["summary"].keys()) == sorted(data["summary"].keys())


def test_report_event_type_counts_keys_alphabetical() -> None:
    encoded = encode_report_to_bytes(
        _summary(event_type_counts={"takeoff": 1, "armed": 1, "landed": 1})
    )
    data = json.loads(encoded)
    keys = list(data["summary"]["event_type_counts"].keys())
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Determinism (Test 8: byte-identical generation)
# ---------------------------------------------------------------------------


def test_encode_report_to_bytes_is_byte_identical_for_same_input() -> None:
    s = _summary()
    a = encode_report_to_bytes(s)
    b = encode_report_to_bytes(s)
    c = encode_report_to_bytes(s)
    assert a == b == c


def test_generate_run_report_writes_same_bytes_as_encoder(tmp_path: Path) -> None:
    s = _summary()
    p = tmp_path / "report.json"
    generate_run_report(s, p)
    assert p.read_bytes() == encode_report_to_bytes(s)


def test_generate_run_report_overwrites_existing(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_bytes(b"old contents")
    generate_run_report(_summary(), p)
    assert p.read_bytes() != b"old contents"


# ---------------------------------------------------------------------------
# Format details — indent, UTF-8, trailing newline
# ---------------------------------------------------------------------------


def test_report_uses_indent_2() -> None:
    encoded = encode_report_to_bytes(_summary()).decode("utf-8")
    # `indent=2` produces "  " before each key at the second level
    assert '\n  "schema_version"' in encoded or '\n  "summary"' in encoded


def test_report_has_trailing_newline() -> None:
    encoded = encode_report_to_bytes(_summary())
    assert encoded.endswith(b"\n")


def test_report_is_utf8() -> None:
    encoded = encode_report_to_bytes(_summary())
    # Decoding as UTF-8 must succeed
    encoded.decode("utf-8")


def test_report_handles_non_ascii_run_id() -> None:
    """ensure_ascii=False keeps unicode; no \\uXXXX escapes."""
    encoded = encode_report_to_bytes(_summary(run_id="ñame-with-ünicode"))
    text = encoded.decode("utf-8")
    assert "ñame-with-ünicode" in text


# ---------------------------------------------------------------------------
# Roundtrip (Test 15)
# ---------------------------------------------------------------------------


def test_report_roundtrips_via_json_loads(tmp_path: Path) -> None:
    """Write a report, read it back as JSON, verify field values match."""
    s = _summary(event_count=42, healthy_sensor_count=3)
    p = tmp_path / "report.json"
    generate_run_report(s, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["summary"]["event_count"] == 42
    assert data["summary"]["healthy_sensor_count"] == 3
    assert data["summary"]["run_id"] == "test-run"
    assert data["schema_version"] == REPORT_SCHEMA_VERSION


def test_report_roundtrips_preserve_histogram_contents(tmp_path: Path) -> None:
    histogram = {"armed": 5, "landed": 5, "takeoff": 10}
    s = _summary(event_type_counts=histogram)
    p = tmp_path / "report.json"
    generate_run_report(s, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["summary"]["event_type_counts"] == histogram


def test_report_roundtrips_preserve_optional_none(tmp_path: Path) -> None:
    s = _summary(first_timestamp_ns=None, last_timestamp_ns=None, duration_ns=None)
    p = tmp_path / "report.json"
    generate_run_report(s, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["summary"]["first_timestamp_ns"] is None
    assert data["summary"]["last_timestamp_ns"] is None
    assert data["summary"]["duration_ns"] is None


# ---------------------------------------------------------------------------
# Re-encoding the same report twice => byte-identical
# ---------------------------------------------------------------------------


def test_report_re_encoded_byte_identical(tmp_path: Path) -> None:
    s = _summary()
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    generate_run_report(s, a)
    generate_run_report(s, b)
    assert a.read_bytes() == b.read_bytes()
