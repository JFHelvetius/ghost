"""Tests de `telemetry.serialization`.

Cubre:

- Encoder total para todos los tipos soportados.
- Determinismo byte-a-byte de `encode_to_bytes`.
- Round-trip a través de `from_json_dict` con re-ejecución de
  `__post_init__` (cualquier invariante violada produce error).
- Rechazo loud de tipos no soportados.
"""

from __future__ import annotations

import json
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.events import Event, EventSeverity, EventType
from project_ghost.hal.messages import (
    IMUPayload,
    SensorHealth,
    SensorMeta,
    SensorSample,
)
from project_ghost.telemetry import (
    encode_to_bytes,
    from_json_dict,
    make_sensor_sample_decoder,
    to_json_safe,
)
from project_ghost.telemetry.serialization import (
    _NDARRAY_DATA_KEY,
    _NDARRAY_DTYPE_KEY,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _event() -> Event:
    return Event(
        type=EventType.MISSION_START,
        severity=EventSeverity.INFO,
        source="mission.fsm",
        stamp_sim_ns=1_000,
        stamp_wall_ns=2_000,
        sequence=5,
        payload=MappingProxyType({"goal_idx": 3, "label": "alpha"}),
        correlation_id="mission-xyz",
    )


def _imu_sample() -> SensorSample[IMUPayload]:
    return SensorSample[IMUPayload](
        sensor_id="imu0",
        seq=42,
        stamp_sensor_ns=1_000,
        stamp_sim_ns=1_000,
        stamp_wall_ns=2_000,
        health=SensorHealth.OK,
        payload=IMUPayload(
            accel_mps2=np.array([0.1, 0.2, 9.81], dtype=np.float64),
            gyro_rps=np.array([0.0, 0.0, 0.05], dtype=np.float64),
            temperature_c=25.5,
        ),
        meta=SensorMeta(
            frame_id="body",
            calibration_id="cal-01",
            extensions=MappingProxyType({"vendor": "fake"}),
        ),
    )


# ---------------------------------------------------------------------------
# to_json_safe — encoder cases
# ---------------------------------------------------------------------------


def test_to_json_safe_primitives() -> None:
    assert to_json_safe(None) is None
    assert to_json_safe(True) is True
    assert to_json_safe(42) == 42
    assert to_json_safe(3.14) == 3.14
    assert to_json_safe("hello") == "hello"


def test_to_json_safe_int_enum_emits_int() -> None:
    assert to_json_safe(EventSeverity.WARN) == 30
    assert isinstance(to_json_safe(EventSeverity.WARN), int)
    # The encoded value must NOT be an enum instance (which would break
    # json.dumps roundtrip equivalence).
    assert type(to_json_safe(EventSeverity.WARN)) is int


def test_to_json_safe_str_enum_emits_str() -> None:
    assert to_json_safe(EventType.MISSION_START) == "mission_start"
    assert type(to_json_safe(EventType.MISSION_START)) is str


def test_to_json_safe_ndarray_round_trips_via_dtype_marker() -> None:
    arr = np.array([1.0, 2.5, 3.0], dtype=np.float64)
    encoded = to_json_safe(arr)
    assert encoded == {
        _NDARRAY_DTYPE_KEY: "float64",
        _NDARRAY_DATA_KEY: [1.0, 2.5, 3.0],
    }


def test_to_json_safe_ndarray_preserves_dtype() -> None:
    for dtype in (np.float32, np.float64, np.int32, np.int64, np.uint8):
        arr = np.array([1, 2, 3], dtype=dtype)
        encoded = to_json_safe(arr)
        assert encoded[_NDARRAY_DTYPE_KEY] == str(np.dtype(dtype))


def test_to_json_safe_tuple_becomes_list() -> None:
    assert to_json_safe((1, 2, 3)) == [1, 2, 3]
    assert to_json_safe(("a", "b")) == ["a", "b"]


def test_to_json_safe_mapping_proxy() -> None:
    mp = MappingProxyType({"x": 1, "y": "z"})
    assert to_json_safe(mp) == {"x": 1, "y": "z"}


def test_to_json_safe_nested_dataclass_event() -> None:
    encoded = to_json_safe(_event())
    assert encoded["type"] == "mission_start"
    assert encoded["severity"] == 20
    assert encoded["source"] == "mission.fsm"
    assert encoded["payload"] == {"goal_idx": 3, "label": "alpha"}


def test_to_json_safe_rejects_unsupported_type() -> None:
    class _Custom:
        pass

    with pytest.raises(TypeError, match="tipo no soportado"):
        to_json_safe(_Custom())


def test_to_json_safe_rejects_callable() -> None:
    with pytest.raises(TypeError, match="tipo no soportado"):
        to_json_safe(lambda x: x)


def test_to_json_safe_numpy_scalar_types() -> None:
    """Bare numpy scalars (not wrapped in arrays) serialize cleanly via
    json.dumps. ``np.float64`` is a subclass of Python ``float`` so it
    hits the primitive fast-path; ``np.float32`` does not and goes
    through the dedicated branch."""
    # Either branch works — both produce JSON-encodable values.
    assert to_json_safe(np.float64(1.5)) == 1.5
    assert to_json_safe(np.float32(1.5)) == pytest.approx(1.5)
    assert to_json_safe(np.int64(7)) == 7
    assert to_json_safe(np.int32(7)) == 7


def test_to_json_safe_generic_enum_fallback() -> None:
    """Enums that are neither IntEnum nor StrEnum fall through to
    `.value` — defensive path for any future enum types."""
    import enum as _enum

    class Color(_enum.Enum):
        RED = "red"

    assert to_json_safe(Color.RED) == "red"


def test_decode_dataclass_rejects_non_dataclass() -> None:
    from project_ghost.telemetry.serialization import _decode_dataclass

    with pytest.raises(TypeError, match="not a dataclass"):
        _decode_dataclass(int, {"x": 1})


def test_decode_ndarray_rejects_non_mapping() -> None:
    from project_ghost.telemetry.serialization import _decode_ndarray

    with pytest.raises(TypeError, match="mapping"):
        _decode_ndarray([1, 2, 3])


def test_decode_ndarray_rejects_missing_keys() -> None:
    from project_ghost.telemetry.serialization import _decode_ndarray

    with pytest.raises(TypeError, match="missing required keys"):
        _decode_ndarray({_NDARRAY_DTYPE_KEY: "float64"})  # missing data


def test_round_trip_literal_field_survives() -> None:
    """Literal types are passed through; decoder does not re-evaluate
    them against the Literal set (constructor already validates)."""
    from project_ghost.state.messages import Twist

    twist = Twist(
        linear_mps=np.array([1.0, 2.0, 3.0], dtype=np.float64),
        angular_rps=np.array([0.0, 0.0, 0.1], dtype=np.float64),
        frame="world",
    )
    decoded = from_json_dict(Twist, json.loads(encode_to_bytes(twist)))
    assert decoded.frame == "world"


# ---------------------------------------------------------------------------
# Byte-level determinism (T4 review requirement)
# ---------------------------------------------------------------------------


def test_encode_to_bytes_is_byte_deterministic_event() -> None:
    """encode(x); encode(x); encode(x) → identical bytes (T4 review)."""
    ev = _event()
    a = encode_to_bytes(ev)
    b = encode_to_bytes(ev)
    c = encode_to_bytes(ev)
    assert a == b == c


def test_encode_to_bytes_is_byte_deterministic_sensor_sample() -> None:
    sample = _imu_sample()
    a = encode_to_bytes(sample)
    b = encode_to_bytes(sample)
    assert a == b


def test_encode_to_bytes_is_byte_deterministic_with_ndarray() -> None:
    arr = np.array([1.0, 2.5, -0.3, 1e-10], dtype=np.float64)
    a = encode_to_bytes(arr)
    b = encode_to_bytes(arr)
    assert a == b


def test_encode_to_bytes_independent_of_dict_insertion_order() -> None:
    """sort_keys=True must make insertion order irrelevant."""
    d1 = {"b": 1, "a": 2, "c": 3}
    d2 = {"a": 2, "c": 3, "b": 1}
    assert encode_to_bytes(d1) == encode_to_bytes(d2)


def test_encode_to_bytes_uses_compact_separators() -> None:
    """No incidental whitespace in encoded JSON (determinism + file size)."""
    encoded = encode_to_bytes({"a": 1, "b": 2})
    assert encoded == b'{"a":1,"b":2}'


# ---------------------------------------------------------------------------
# Round-trip — from_json_dict re-triggers __post_init__
# ---------------------------------------------------------------------------


def test_round_trip_event() -> None:
    original = _event()
    encoded = encode_to_bytes(original)
    decoded = from_json_dict(Event, json.loads(encoded))
    assert decoded == original


def test_round_trip_sensor_sample_imu() -> None:
    """SensorSample is generic; use make_sensor_sample_decoder for the
    concrete payload type rather than the unparameterized from_json_dict."""
    original = _imu_sample()
    decoder = make_sensor_sample_decoder(IMUPayload)
    decoded = decoder(json.loads(encode_to_bytes(original)))
    # Equality on frozen dataclasses with ndarrays is brittle (numpy ==
    # returns array, not bool). Compare per attribute.
    assert decoded.sensor_id == original.sensor_id
    assert decoded.seq == original.seq
    assert decoded.health == original.health
    np.testing.assert_array_equal(decoded.payload.accel_mps2, original.payload.accel_mps2)
    np.testing.assert_array_equal(decoded.payload.gyro_rps, original.payload.gyro_rps)
    assert decoded.payload.temperature_c == original.payload.temperature_c


def test_round_trip_preserves_ndarray_dtype() -> None:
    sample = _imu_sample()
    decoder = make_sensor_sample_decoder(IMUPayload)
    decoded = decoder(json.loads(encode_to_bytes(sample)))
    assert decoded.payload.accel_mps2.dtype == np.float64


def test_round_trip_triggers_post_init_validation() -> None:
    """If a captured file is corrupted to a non-unit quaternion (or any
    other invariant breaker), decoding should fail loudly — replay is
    an active correctness check, not a silent loader."""
    from project_ghost.state.messages import Pose

    bad_dict = {
        "position_enu_m": {
            _NDARRAY_DTYPE_KEY: "float64",
            _NDARRAY_DATA_KEY: [0.0, 0.0, 0.0],
        },
        "orientation_q": {
            _NDARRAY_DTYPE_KEY: "float64",
            _NDARRAY_DATA_KEY: [2.0, 0.0, 0.0, 0.0],  # not unit
        },
    }
    with pytest.raises(ValueError, match="unit"):
        from_json_dict(Pose, bad_dict)


def test_round_trip_optional_field_none() -> None:
    """`correlation_id` is Optional — None must survive round-trip."""
    ev = Event(
        type=EventType.KILL,
        severity=EventSeverity.CRITICAL,
        source="test",
        stamp_sim_ns=0,
        stamp_wall_ns=0,
        sequence=0,
        payload=MappingProxyType({}),
        correlation_id=None,
    )
    decoded = from_json_dict(Event, json.loads(encode_to_bytes(ev)))
    assert decoded.correlation_id is None


def test_round_trip_tuple_field_reconstructed() -> None:
    """JSON has no tuple — decoder must restore tuples for typed fields."""
    from project_ghost.hal.messages import Capabilities

    caps = Capabilities(
        hal_version=1,
        sensor_ids=("imu0", "cam_front"),
        actuator_levels=(),
        has_ground_truth=True,
        synchronous_step=True,
        deterministic=True,
        supports_replay=False,
        extensions=MappingProxyType({}),
    )
    decoded = from_json_dict(Capabilities, json.loads(encode_to_bytes(caps)))
    assert isinstance(decoded.sensor_ids, tuple)
    assert decoded.sensor_ids == ("imu0", "cam_front")
    assert isinstance(decoded.actuator_levels, tuple)


def test_round_trip_init_false_field_uses_default() -> None:
    """Fields with init=False (e.g. ActuatorCommand.level) must not be
    passed to the constructor by the decoder."""
    from project_ghost.hal.messages import ActuatorLevel, DirectMotorCommand

    cmd = DirectMotorCommand(throttle=np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64))
    decoded = from_json_dict(DirectMotorCommand, json.loads(encode_to_bytes(cmd)))
    assert decoded.level == ActuatorLevel.DIRECT_MOTOR
    np.testing.assert_array_equal(decoded.throttle, cmd.throttle)
