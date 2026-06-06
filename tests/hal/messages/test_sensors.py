"""Tests de `hal.messages.sensors` (T2.a.1).

Cubre: enums, estructuras compartidas, validación de arrays/shape/dtype,
sealing post-construcción, validación de invariantes específicos por
payload.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.hal.messages import (
    AltimeterPayload,
    CameraIntrinsics,
    DepthImagePayload,
    GpsFix,
    GpsPayload,
    IMUPayload,
    RGBImagePayload,
    SensorHealth,
    SensorMeta,
    SensorSample,
    SensorSpec,
)

# ---------------------------------------------------------------------------
# Fixtures helper
# ---------------------------------------------------------------------------


def _meta() -> SensorMeta:
    return SensorMeta(
        frame_id="body",
        calibration_id=None,
        extensions=MappingProxyType({}),
    )


def _intrinsics(w: int = 4, h: int = 3) -> CameraIntrinsics:
    return CameraIntrinsics(
        width=w,
        height=h,
        fx=100.0,
        fy=100.0,
        cx=w / 2,
        cy=h / 2,
        distortion_model="none",
        distortion_coeffs=np.zeros(0, dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def test_sensor_health_total_ordering() -> None:
    assert SensorHealth.OK < SensorHealth.DEGRADED
    assert SensorHealth.DEGRADED < SensorHealth.FAULTY
    assert SensorHealth.FAULTY < SensorHealth.OFFLINE


def test_sensor_health_values_match_spec() -> None:
    assert SensorHealth.OK.value == 0
    assert SensorHealth.DEGRADED.value == 1
    assert SensorHealth.FAULTY.value == 2
    assert SensorHealth.OFFLINE.value == 3


def test_gps_fix_total_ordering() -> None:
    assert GpsFix.NO_FIX < GpsFix.FIX_2D
    assert GpsFix.FIX_2D < GpsFix.FIX_3D
    assert GpsFix.FIX_3D < GpsFix.RTK


# ---------------------------------------------------------------------------
# SensorMeta
# ---------------------------------------------------------------------------


def test_sensor_meta_valid_construction() -> None:
    m = _meta()
    assert m.frame_id == "body"
    assert m.calibration_id is None


def test_sensor_meta_rejects_empty_frame_id() -> None:
    with pytest.raises(ValueError, match="frame_id"):
        SensorMeta(frame_id="", calibration_id=None, extensions=MappingProxyType({}))


def test_sensor_meta_is_frozen() -> None:
    m = _meta()
    with pytest.raises(FrozenInstanceError):
        m.frame_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SensorSample
# ---------------------------------------------------------------------------


def _sample(**overrides: object) -> SensorSample[str]:
    defaults: dict[str, object] = {
        "sensor_id": "imu0",
        "seq": 0,
        "stamp_sensor_ns": 1_000,
        "stamp_sim_ns": 1_000,
        "stamp_wall_ns": 2_000,
        "health": SensorHealth.OK,
        "payload": "test-payload",
        "meta": _meta(),
    }
    defaults.update(overrides)
    return SensorSample(**defaults)  # type: ignore[arg-type]


def test_sensor_sample_valid_construction() -> None:
    s = _sample()
    assert s.sensor_id == "imu0"
    assert s.health == SensorHealth.OK
    assert s.payload == "test-payload"
    assert s.schema_version == 1


def test_sensor_sample_rejects_empty_sensor_id() -> None:
    with pytest.raises(ValueError, match="sensor_id"):
        _sample(sensor_id="")


def test_sensor_sample_rejects_negative_seq() -> None:
    with pytest.raises(ValueError, match="seq"):
        _sample(seq=-1)


def test_sensor_sample_rejects_negative_stamps() -> None:
    for key in ("stamp_sensor_ns", "stamp_sim_ns", "stamp_wall_ns"):
        with pytest.raises(ValueError, match=key):
            _sample(**{key: -1})


def test_sensor_sample_zero_stamps_allowed() -> None:
    s = _sample(stamp_sensor_ns=0, stamp_sim_ns=0, stamp_wall_ns=0)
    assert s.stamp_sim_ns == 0


def test_sensor_sample_rejects_schema_version_below_one() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        _sample(schema_version=0)


def test_sensor_sample_is_frozen() -> None:
    s = _sample()
    with pytest.raises(FrozenInstanceError):
        s.sensor_id = "x"  # type: ignore[misc]


def test_sensor_sample_generic_carries_typed_payload() -> None:
    """Comprueba que SensorSample[T] sostiene payload del tipo declarado."""
    imu_payload = IMUPayload(
        accel_mps2=np.zeros(3, dtype=np.float64),
        gyro_rps=np.zeros(3, dtype=np.float64),
        temperature_c=25.0,
    )
    sample: SensorSample[IMUPayload] = SensorSample(
        sensor_id="imu0",
        seq=0,
        stamp_sensor_ns=0,
        stamp_sim_ns=0,
        stamp_wall_ns=0,
        health=SensorHealth.OK,
        payload=imu_payload,
        meta=_meta(),
    )
    assert sample.payload is imu_payload


# ---------------------------------------------------------------------------
# SensorSpec
# ---------------------------------------------------------------------------


def _spec(**overrides: object) -> SensorSpec:
    defaults: dict[str, object] = {
        "sensor_id": "imu0",
        "payload_type": "imu",
        "nominal_rate_hz": 200.0,
        "frame_id": "body",
        "noise_model": None,
        "latency_ns": 0,
    }
    defaults.update(overrides)
    return SensorSpec(**defaults)  # type: ignore[arg-type]


def test_sensor_spec_valid_construction() -> None:
    s = _spec()
    assert s.sensor_id == "imu0"
    assert s.nominal_rate_hz == 200.0
    assert s.noise_model is None


def test_sensor_spec_rejects_nonpositive_rate() -> None:
    with pytest.raises(ValueError, match="nominal_rate_hz"):
        _spec(nominal_rate_hz=0.0)
    with pytest.raises(ValueError, match="nominal_rate_hz"):
        _spec(nominal_rate_hz=-1.0)


def test_sensor_spec_rejects_negative_latency() -> None:
    with pytest.raises(ValueError, match="latency_ns"):
        _spec(latency_ns=-1)


def test_sensor_spec_rejects_empty_strings() -> None:
    for field, value in (
        ("sensor_id", ""),
        ("payload_type", ""),
        ("frame_id", ""),
    ):
        with pytest.raises(ValueError, match=field):
            _spec(**{field: value})


# ---------------------------------------------------------------------------
# IMUPayload
# ---------------------------------------------------------------------------


def test_imu_payload_valid_construction() -> None:
    payload = IMUPayload(
        accel_mps2=np.array([0.1, 0.2, 9.81], dtype=np.float64),
        gyro_rps=np.array([0.0, 0.0, 0.1], dtype=np.float64),
        temperature_c=25.5,
    )
    assert payload.temperature_c == 25.5


def test_imu_payload_temperature_optional() -> None:
    payload = IMUPayload(
        accel_mps2=np.zeros(3, dtype=np.float64),
        gyro_rps=np.zeros(3, dtype=np.float64),
        temperature_c=None,
    )
    assert payload.temperature_c is None


def test_imu_payload_rejects_wrong_shape() -> None:
    with pytest.raises(TypeError, match="accel_mps2"):
        IMUPayload(
            accel_mps2=np.zeros(4, dtype=np.float64),
            gyro_rps=np.zeros(3, dtype=np.float64),
            temperature_c=None,
        )


def test_imu_payload_rejects_wrong_dtype() -> None:
    with pytest.raises(TypeError, match="dtype"):
        IMUPayload(
            accel_mps2=np.zeros(3, dtype=np.float32),
            gyro_rps=np.zeros(3, dtype=np.float64),
            temperature_c=None,
        )


def test_imu_payload_rejects_nan() -> None:
    with pytest.raises(ValueError, match="NaN"):
        IMUPayload(
            accel_mps2=np.array([0.0, np.nan, 0.0], dtype=np.float64),
            gyro_rps=np.zeros(3, dtype=np.float64),
            temperature_c=None,
        )


def test_imu_payload_arrays_are_sealed() -> None:
    accel = np.array([0.0, 0.0, 9.81], dtype=np.float64)
    gyro = np.zeros(3, dtype=np.float64)
    payload = IMUPayload(accel_mps2=accel, gyro_rps=gyro, temperature_c=None)
    assert not payload.accel_mps2.flags.writeable
    assert not payload.gyro_rps.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        payload.accel_mps2[0] = 1.0


# ---------------------------------------------------------------------------
# CameraIntrinsics
# ---------------------------------------------------------------------------


def test_camera_intrinsics_valid_construction_none_distortion() -> None:
    intr = _intrinsics()
    assert intr.width == 4
    assert intr.distortion_coeffs.shape == (0,)


def test_camera_intrinsics_valid_plumb_bob_5_coeffs() -> None:
    intr = CameraIntrinsics(
        width=640,
        height=480,
        fx=500.0,
        fy=500.0,
        cx=320.0,
        cy=240.0,
        distortion_model="plumb_bob",
        distortion_coeffs=np.zeros(5, dtype=np.float64),
    )
    assert intr.distortion_coeffs.shape == (5,)


def test_camera_intrinsics_valid_equidistant_4_coeffs() -> None:
    intr = CameraIntrinsics(
        width=640,
        height=480,
        fx=500.0,
        fy=500.0,
        cx=320.0,
        cy=240.0,
        distortion_model="equidistant",
        distortion_coeffs=np.zeros(4, dtype=np.float64),
    )
    assert intr.distortion_coeffs.shape == (4,)


def test_camera_intrinsics_rejects_wrong_coeffs_length() -> None:
    with pytest.raises(TypeError, match="distortion_coeffs"):
        CameraIntrinsics(
            width=640,
            height=480,
            fx=500.0,
            fy=500.0,
            cx=320.0,
            cy=240.0,
            distortion_model="plumb_bob",
            distortion_coeffs=np.zeros(3, dtype=np.float64),  # esperado 5
        )


def test_camera_intrinsics_rejects_invalid_distortion_model() -> None:
    with pytest.raises(ValueError, match="distortion_model"):
        CameraIntrinsics(
            width=640,
            height=480,
            fx=500.0,
            fy=500.0,
            cx=320.0,
            cy=240.0,
            distortion_model="fisheye",  # type: ignore[arg-type]
            distortion_coeffs=np.zeros(5, dtype=np.float64),
        )


def test_camera_intrinsics_rejects_nonpositive_dimensions() -> None:
    with pytest.raises(ValueError, match="width"):
        CameraIntrinsics(
            width=0,
            height=480,
            fx=500.0,
            fy=500.0,
            cx=0.0,
            cy=240.0,
            distortion_model="none",
            distortion_coeffs=np.zeros(0, dtype=np.float64),
        )


def test_camera_intrinsics_rejects_nonpositive_focal() -> None:
    with pytest.raises(ValueError, match="fx"):
        CameraIntrinsics(
            width=640,
            height=480,
            fx=0.0,
            fy=500.0,
            cx=320.0,
            cy=240.0,
            distortion_model="none",
            distortion_coeffs=np.zeros(0, dtype=np.float64),
        )


# ---------------------------------------------------------------------------
# RGBImagePayload
# ---------------------------------------------------------------------------


def test_rgb_image_payload_valid() -> None:
    intr = _intrinsics(w=4, h=3)
    img = np.zeros((3, 4, 3), dtype=np.uint8)
    payload = RGBImagePayload(
        image=img, intrinsics=intr, exposure_ns=1_000_000, encoding="rgb8"
    )
    assert payload.image.shape == (3, 4, 3)


def test_rgb_image_payload_rejects_wrong_channels() -> None:
    intr = _intrinsics()
    with pytest.raises(TypeError, match="3 canales"):
        RGBImagePayload(
            image=np.zeros((3, 4, 4), dtype=np.uint8),
            intrinsics=intr,
            exposure_ns=0,
            encoding="rgb8",
        )


def test_rgb_image_payload_rejects_wrong_dtype() -> None:
    intr = _intrinsics()
    with pytest.raises(TypeError, match="dtype"):
        RGBImagePayload(
            image=np.zeros((3, 4, 3), dtype=np.float32),
            intrinsics=intr,
            exposure_ns=0,
            encoding="rgb8",
        )


def test_rgb_image_payload_rejects_mismatched_intrinsics_resolution() -> None:
    intr = _intrinsics(w=640, h=480)
    with pytest.raises(ValueError, match="no coincide"):
        RGBImagePayload(
            image=np.zeros((3, 4, 3), dtype=np.uint8),
            intrinsics=intr,
            exposure_ns=0,
            encoding="rgb8",
        )


def test_rgb_image_payload_rejects_negative_exposure() -> None:
    intr = _intrinsics()
    with pytest.raises(ValueError, match="exposure_ns"):
        RGBImagePayload(
            image=np.zeros((3, 4, 3), dtype=np.uint8),
            intrinsics=intr,
            exposure_ns=-1,
            encoding="rgb8",
        )


def test_rgb_image_payload_image_is_sealed() -> None:
    intr = _intrinsics()
    img = np.zeros((3, 4, 3), dtype=np.uint8)
    payload = RGBImagePayload(
        image=img, intrinsics=intr, exposure_ns=0, encoding="rgb8"
    )
    assert not payload.image.flags.writeable


# ---------------------------------------------------------------------------
# DepthImagePayload
# ---------------------------------------------------------------------------


def test_depth_image_payload_valid() -> None:
    intr = _intrinsics(w=4, h=3)
    depth = np.full((3, 4), 1.5, dtype=np.float32)
    payload = DepthImagePayload(
        depth_m=depth, intrinsics=intr, min_range_m=0.1, max_range_m=10.0
    )
    assert payload.min_range_m == 0.1


def test_depth_image_payload_allows_nan() -> None:
    """NaN explícitamente permitido per sensors.md §3.3."""
    intr = _intrinsics(w=2, h=2)
    depth = np.array([[1.0, np.nan], [np.nan, 2.0]], dtype=np.float32)
    payload = DepthImagePayload(
        depth_m=depth, intrinsics=intr, min_range_m=0.1, max_range_m=10.0
    )
    assert np.isnan(payload.depth_m).sum() == 2


def test_depth_image_payload_rejects_wrong_dtype() -> None:
    intr = _intrinsics()
    with pytest.raises(TypeError, match="dtype"):
        DepthImagePayload(
            depth_m=np.zeros((3, 4), dtype=np.float64),
            intrinsics=intr,
            min_range_m=0.1,
            max_range_m=10.0,
        )


def test_depth_image_payload_rejects_negative_min_range() -> None:
    intr = _intrinsics()
    with pytest.raises(ValueError, match="min_range_m"):
        DepthImagePayload(
            depth_m=np.zeros((3, 4), dtype=np.float32),
            intrinsics=intr,
            min_range_m=-0.1,
            max_range_m=10.0,
        )


def test_depth_image_payload_rejects_max_less_than_min() -> None:
    intr = _intrinsics()
    with pytest.raises(ValueError, match="max_range_m"):
        DepthImagePayload(
            depth_m=np.zeros((3, 4), dtype=np.float32),
            intrinsics=intr,
            min_range_m=5.0,
            max_range_m=2.0,
        )


def test_depth_image_payload_is_sealed() -> None:
    intr = _intrinsics()
    depth = np.zeros((3, 4), dtype=np.float32)
    payload = DepthImagePayload(
        depth_m=depth, intrinsics=intr, min_range_m=0.1, max_range_m=10.0
    )
    assert not payload.depth_m.flags.writeable


# ---------------------------------------------------------------------------
# GpsPayload
# ---------------------------------------------------------------------------


def test_gps_payload_valid() -> None:
    payload = GpsPayload(
        lat_deg=19.4326,
        lon_deg=-99.1332,
        alt_m=2240.0,
        enu_local_m=np.zeros(3, dtype=np.float64),
        fix_type=GpsFix.FIX_3D,
        hacc_m=2.0,
        vacc_m=4.0,
    )
    assert payload.fix_type == GpsFix.FIX_3D


def test_gps_payload_rejects_out_of_range_lat() -> None:
    with pytest.raises(ValueError, match="lat_deg"):
        GpsPayload(
            lat_deg=91.0,
            lon_deg=0.0,
            alt_m=0.0,
            enu_local_m=np.zeros(3, dtype=np.float64),
            fix_type=GpsFix.NO_FIX,
            hacc_m=0.0,
            vacc_m=0.0,
        )


def test_gps_payload_rejects_out_of_range_lon() -> None:
    with pytest.raises(ValueError, match="lon_deg"):
        GpsPayload(
            lat_deg=0.0,
            lon_deg=181.0,
            alt_m=0.0,
            enu_local_m=np.zeros(3, dtype=np.float64),
            fix_type=GpsFix.NO_FIX,
            hacc_m=0.0,
            vacc_m=0.0,
        )


def test_gps_payload_rejects_negative_accuracy() -> None:
    for field in ("hacc_m", "vacc_m"):
        kwargs: dict[str, object] = {
            "lat_deg": 0.0,
            "lon_deg": 0.0,
            "alt_m": 0.0,
            "enu_local_m": np.zeros(3, dtype=np.float64),
            "fix_type": GpsFix.NO_FIX,
            "hacc_m": 0.0,
            "vacc_m": 0.0,
        }
        kwargs[field] = -1.0
        with pytest.raises(ValueError, match=field):
            GpsPayload(**kwargs)  # type: ignore[arg-type]


def test_gps_payload_enu_is_sealed() -> None:
    enu = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    payload = GpsPayload(
        lat_deg=0.0,
        lon_deg=0.0,
        alt_m=0.0,
        enu_local_m=enu,
        fix_type=GpsFix.FIX_2D,
        hacc_m=0.0,
        vacc_m=0.0,
    )
    assert not payload.enu_local_m.flags.writeable


# ---------------------------------------------------------------------------
# AltimeterPayload
# ---------------------------------------------------------------------------


def test_altimeter_payload_valid() -> None:
    payload = AltimeterPayload(altitude_m=10.5, reference="AGL", variance_m2=0.01)
    assert payload.reference == "AGL"


def test_altimeter_payload_rejects_invalid_reference() -> None:
    with pytest.raises(ValueError, match="reference"):
        AltimeterPayload(
            altitude_m=0.0, reference="ELLIPSOIDAL", variance_m2=0.01  # type: ignore[arg-type]
        )


def test_altimeter_payload_rejects_negative_variance() -> None:
    with pytest.raises(ValueError, match="variance_m2"):
        AltimeterPayload(altitude_m=0.0, reference="LOCAL", variance_m2=-1.0)


def test_altimeter_payload_allows_negative_altitude() -> None:
    """Altímetro AGL puede reportar valores negativos si vehículo bajo
    referencia (e.g. cañón). Solo la varianza tiene piso."""
    payload = AltimeterPayload(altitude_m=-5.0, reference="LOCAL", variance_m2=0.5)
    assert payload.altitude_m == -5.0
