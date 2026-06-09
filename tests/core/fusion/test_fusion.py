"""Tests del contrato de sensor-to-belief fusion (ADR-0028).

Cubre:

- ``FusionInput.__post_init__`` invariantes: tipos, stamps, cold start.
- ``FusionResult.__post_init__`` invariantes: tipos, sha256 format,
  taxonomy, schema_version.
- ``compute_fusion_input_sha256`` determinismo cross-call y formato hex.
- ``LinearMotionOracleFusionPolicy`` construcción, validación,
  ``fuse()`` outputs (posición lineal, stamps, sha256 match, policy_id).
- ``NullFusionResultSink`` descarta sin error.
- ``RecordingFusionResultSink`` acumula en orden.
- ``fuse_and_publish`` orquestación + return value.
- Protocol structural compliance (``SensorFusionPolicy``,
  ``FusionResultSink``).
- Determinismo: mismo input → mismo result encode byte-equal.
"""

from __future__ import annotations

import numpy as np
import pytest

from project_ghost.core.fusion import (
    FUSION_PROTOCOL_VERSION,
    FusionInput,
    FusionResult,
    FusionResultSink,
    LinearMotionOracleFusionPolicy,
    NullFusionResultSink,
    RecordingFusionResultSink,
    SensorFusionPolicy,
    compute_fusion_input_sha256,
    fuse_and_publish,
)
from project_ghost.telemetry import encode_to_bytes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ZERO3 = np.zeros(3, dtype=np.float64)
_ONE3 = np.ones(3, dtype=np.float64)


def _make_oracle(
    *,
    velocity: np.ndarray | None = None,
    initial_pos: np.ndarray | None = None,
    start_ns: int = 0,
    cov: float = 1.0,
) -> LinearMotionOracleFusionPolicy:
    return LinearMotionOracleFusionPolicy(
        initial_position_enu_m=(
            initial_pos if initial_pos is not None else _ZERO3.copy()
        ),
        velocity_world_mps=(
            velocity if velocity is not None else _ZERO3.copy()
        ),
        start_stamp_sim_ns=start_ns,
        covariance_diag=cov,
    )


def _make_input(
    *,
    target_ns: int = 1000,
    prior_ns: int | None = None,
    samples: tuple = (),  # type: ignore[type-arg]
) -> FusionInput:
    return FusionInput(
        sensor_samples=samples,
        prior_belief_stamp_sim_ns=prior_ns,
        target_stamp_sim_ns=target_ns,
    )


# ---------------------------------------------------------------------------
# FusionInput validation
# ---------------------------------------------------------------------------


def test_fusion_input_cold_start_prior_is_none() -> None:
    fi = _make_input(target_ns=0, prior_ns=None)
    assert fi.prior_belief_stamp_sim_ns is None


def test_fusion_input_prior_must_be_less_than_target() -> None:
    fi = _make_input(target_ns=1000, prior_ns=999)
    assert fi.prior_belief_stamp_sim_ns == 999


def test_fusion_input_rejects_prior_equal_to_target() -> None:
    with pytest.raises(ValueError, match="prior_belief_stamp_sim_ns"):
        _make_input(target_ns=1000, prior_ns=1000)


def test_fusion_input_rejects_prior_greater_than_target() -> None:
    with pytest.raises(ValueError, match="prior_belief_stamp_sim_ns"):
        _make_input(target_ns=1000, prior_ns=1001)


def test_fusion_input_rejects_negative_target_stamp() -> None:
    with pytest.raises(ValueError, match="target_stamp_sim_ns"):
        FusionInput(
            sensor_samples=(),
            prior_belief_stamp_sim_ns=None,
            target_stamp_sim_ns=-1,
        )


def test_fusion_input_rejects_negative_prior_stamp() -> None:
    with pytest.raises(ValueError, match="prior_belief_stamp_sim_ns"):
        FusionInput(
            sensor_samples=(),
            prior_belief_stamp_sim_ns=-1,
            target_stamp_sim_ns=0,
        )


def test_fusion_input_rejects_wrong_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        FusionInput(
            sensor_samples=(),
            prior_belief_stamp_sim_ns=None,
            target_stamp_sim_ns=0,
            schema_version=99,
        )


def test_fusion_input_rejects_non_tuple_samples() -> None:
    with pytest.raises(TypeError, match="sensor_samples"):
        FusionInput(
            sensor_samples=[],  # type: ignore[arg-type]
            prior_belief_stamp_sim_ns=None,
            target_stamp_sim_ns=0,
        )


def test_fusion_input_schema_version_default() -> None:
    fi = _make_input()
    assert fi.schema_version == FUSION_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# FusionResult validation
# ---------------------------------------------------------------------------


def _make_valid_result(stamp_ns: int = 1000) -> FusionResult:
    oracle = _make_oracle(start_ns=0, cov=0.5)
    fi = _make_input(target_ns=stamp_ns)
    return oracle.fuse(fi)


def test_fusion_result_rejects_wrong_schema_version() -> None:
    r = _make_valid_result()
    with pytest.raises(ValueError, match="schema_version"):
        FusionResult(
            belief=r.belief,
            fusion_input_sha256=r.fusion_input_sha256,
            fusion_policy_id=r.fusion_policy_id,
            schema_version=99,
        )


def test_fusion_result_rejects_invalid_sha256_length() -> None:
    r = _make_valid_result()
    with pytest.raises(ValueError, match="fusion_input_sha256"):
        FusionResult(
            belief=r.belief,
            fusion_input_sha256="abc",
            fusion_policy_id=r.fusion_policy_id,
        )


def test_fusion_result_rejects_uppercase_hex_sha256() -> None:
    r = _make_valid_result()
    bad_hash = "A" * 64
    with pytest.raises(ValueError, match="fusion_input_sha256"):
        FusionResult(
            belief=r.belief,
            fusion_input_sha256=bad_hash,
            fusion_policy_id=r.fusion_policy_id,
        )


def test_fusion_result_rejects_invalid_policy_id_taxonomy() -> None:
    r = _make_valid_result()
    with pytest.raises(ValueError, match="fusion_policy_id"):
        FusionResult(
            belief=r.belief,
            fusion_input_sha256=r.fusion_input_sha256,
            fusion_policy_id="Invalid-Policy!",
        )


def test_fusion_result_rejects_non_vehicle_state_belief() -> None:
    r = _make_valid_result()
    with pytest.raises(TypeError, match="belief"):
        FusionResult(
            belief="not a VehicleState",  # type: ignore[arg-type]
            fusion_input_sha256=r.fusion_input_sha256,
            fusion_policy_id=r.fusion_policy_id,
        )


# ---------------------------------------------------------------------------
# compute_fusion_input_sha256
# ---------------------------------------------------------------------------


def test_sha256_is_64_hex_chars() -> None:
    fi = _make_input()
    h = compute_fusion_input_sha256(fi)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_sha256_is_deterministic_same_call() -> None:
    fi = _make_input(target_ns=5000, prior_ns=4000)
    h1 = compute_fusion_input_sha256(fi)
    h2 = compute_fusion_input_sha256(fi)
    assert h1 == h2


def test_sha256_differs_for_different_inputs() -> None:
    fi_a = _make_input(target_ns=1000)
    fi_b = _make_input(target_ns=2000)
    assert compute_fusion_input_sha256(fi_a) != compute_fusion_input_sha256(fi_b)


# ---------------------------------------------------------------------------
# LinearMotionOracleFusionPolicy construction
# ---------------------------------------------------------------------------


def test_oracle_rejects_non_array_initial_position() -> None:
    with pytest.raises(ValueError, match="initial_position_enu_m"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=[0.0, 0.0, 0.0],  # type: ignore[arg-type]
            velocity_world_mps=_ZERO3.copy(),
            start_stamp_sim_ns=0,
            covariance_diag=1.0,
        )


def test_oracle_rejects_wrong_shape_initial_position() -> None:
    with pytest.raises(ValueError, match="initial_position_enu_m"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=np.zeros(2, dtype=np.float64),
            velocity_world_mps=_ZERO3.copy(),
            start_stamp_sim_ns=0,
            covariance_diag=1.0,
        )


def test_oracle_rejects_wrong_dtype_initial_position() -> None:
    with pytest.raises(ValueError, match="initial_position_enu_m"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=np.zeros(3, dtype=np.float32),
            velocity_world_mps=_ZERO3.copy(),
            start_stamp_sim_ns=0,
            covariance_diag=1.0,
        )


def test_oracle_rejects_wrong_shape_velocity() -> None:
    with pytest.raises(ValueError, match="velocity_world_mps"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=_ZERO3.copy(),
            velocity_world_mps=np.zeros(4, dtype=np.float64),
            start_stamp_sim_ns=0,
            covariance_diag=1.0,
        )


def test_oracle_rejects_negative_start_stamp() -> None:
    with pytest.raises(ValueError, match="start_stamp_sim_ns"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=_ZERO3.copy(),
            velocity_world_mps=_ZERO3.copy(),
            start_stamp_sim_ns=-1,
            covariance_diag=1.0,
        )


def test_oracle_rejects_zero_covariance() -> None:
    with pytest.raises(ValueError, match="covariance_diag"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=_ZERO3.copy(),
            velocity_world_mps=_ZERO3.copy(),
            start_stamp_sim_ns=0,
            covariance_diag=0.0,
        )


def test_oracle_rejects_negative_covariance() -> None:
    with pytest.raises(ValueError, match="covariance_diag"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=_ZERO3.copy(),
            velocity_world_mps=_ZERO3.copy(),
            start_stamp_sim_ns=0,
            covariance_diag=-1.0,
        )


def test_oracle_rejects_inf_covariance() -> None:
    with pytest.raises(ValueError, match="covariance_diag"):
        LinearMotionOracleFusionPolicy(
            initial_position_enu_m=_ZERO3.copy(),
            velocity_world_mps=_ZERO3.copy(),
            start_stamp_sim_ns=0,
            covariance_diag=float("inf"),
        )


# ---------------------------------------------------------------------------
# LinearMotionOracleFusionPolicy.fuse() — outputs
# ---------------------------------------------------------------------------


def test_oracle_fuse_stamp_matches_target() -> None:
    oracle = _make_oracle()
    fi = _make_input(target_ns=500_000_000)
    result = oracle.fuse(fi)
    assert result.belief.stamp_sim_ns == 500_000_000


def test_oracle_fuse_at_t0_position_equals_initial() -> None:
    pos0 = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    oracle = _make_oracle(initial_pos=pos0.copy(), start_ns=0)
    fi = _make_input(target_ns=0)
    result = oracle.fuse(fi)
    np.testing.assert_array_equal(
        result.belief.nav.pose.position_enu_m, pos0
    )


def test_oracle_fuse_linear_propagation() -> None:
    vel = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    oracle = _make_oracle(velocity=vel, start_ns=0)
    fi = _make_input(target_ns=2_000_000_000)  # 2 s
    result = oracle.fuse(fi)
    np.testing.assert_allclose(
        result.belief.nav.pose.position_enu_m,
        np.array([2.0, 0.0, 0.0], dtype=np.float64),
    )


def test_oracle_fuse_position_at_start_plus_velocity() -> None:
    pos0 = np.array([10.0, 0.0, 0.0], dtype=np.float64)
    vel = np.array([5.0, 0.0, 0.0], dtype=np.float64)
    oracle = _make_oracle(initial_pos=pos0.copy(), velocity=vel, start_ns=0)
    fi = _make_input(target_ns=1_000_000_000)  # 1 s
    result = oracle.fuse(fi)
    np.testing.assert_allclose(
        result.belief.nav.pose.position_enu_m,
        np.array([15.0, 0.0, 0.0], dtype=np.float64),
    )


def test_oracle_fuse_orientation_is_identity_quaternion() -> None:
    oracle = _make_oracle()
    fi = _make_input(target_ns=1000)
    result = oracle.fuse(fi)
    np.testing.assert_array_equal(
        result.belief.nav.pose.orientation_q,
        np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
    )


def test_oracle_fuse_covariance_is_diagonal() -> None:
    cov = 0.25
    oracle = _make_oracle(cov=cov)
    fi = _make_input(target_ns=1000)
    result = oracle.fuse(fi)
    C = result.belief.nav.covariance_15x15
    assert C is not None
    np.testing.assert_allclose(np.diag(C), np.full(15, cov))
    off = C.copy()
    np.fill_diagonal(off, 0.0)
    np.testing.assert_array_equal(off, np.zeros((15, 15)))


def test_oracle_fuse_sha256_matches_input_hash() -> None:
    oracle = _make_oracle()
    fi = _make_input(target_ns=1000)
    result = oracle.fuse(fi)
    expected = compute_fusion_input_sha256(fi)
    assert result.fusion_input_sha256 == expected


def test_oracle_fuse_policy_id_in_result() -> None:
    oracle = _make_oracle(cov=1e-4)
    fi = _make_input(target_ns=1000)
    result = oracle.fuse(fi)
    assert result.fusion_policy_id == oracle.fusion_policy_id


def test_oracle_fusion_policy_id_includes_base() -> None:
    oracle = _make_oracle(cov=1.0)
    assert oracle.fusion_policy_id.startswith("linear_motion_oracle_v1")


def test_oracle_two_instances_different_cov_have_different_policy_ids() -> None:
    o1 = _make_oracle(cov=0.1)
    o2 = _make_oracle(cov=0.5)
    assert o1.fusion_policy_id != o2.fusion_policy_id


def test_oracle_fuse_is_pure_same_result_for_same_input() -> None:
    oracle = _make_oracle(velocity=np.array([1.0, 2.0, 3.0], dtype=np.float64))
    fi = _make_input(target_ns=500_000_000)
    r1 = oracle.fuse(fi)
    r2 = oracle.fuse(fi)
    assert encode_to_bytes(r1) == encode_to_bytes(r2)


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------


def test_null_sink_publish_does_not_raise() -> None:
    sink = NullFusionResultSink()
    result = _make_valid_result()
    sink.publish(result)


def test_recording_sink_accumulates_in_order() -> None:
    sink = RecordingFusionResultSink()
    oracle = _make_oracle()
    r1 = oracle.fuse(_make_input(target_ns=1000))
    r2 = oracle.fuse(_make_input(target_ns=2000, prior_ns=1000))
    sink.publish(r1)
    sink.publish(r2)
    assert len(sink.records) == 2
    assert sink.records[0] is r1
    assert sink.records[1] is r2


def test_recording_sink_clear_empties_records() -> None:
    sink = RecordingFusionResultSink()
    oracle = _make_oracle()
    sink.publish(oracle.fuse(_make_input(target_ns=1000)))
    sink.clear()
    assert len(sink.records) == 0


def test_recording_sink_records_is_tuple() -> None:
    sink = RecordingFusionResultSink()
    assert isinstance(sink.records, tuple)


# ---------------------------------------------------------------------------
# fuse_and_publish
# ---------------------------------------------------------------------------


def test_fuse_and_publish_returns_result() -> None:
    oracle = _make_oracle()
    sink = NullFusionResultSink()
    fi = _make_input(target_ns=1000)
    result = fuse_and_publish(oracle, fi, sink)
    assert isinstance(result, FusionResult)


def test_fuse_and_publish_publishes_to_sink() -> None:
    oracle = _make_oracle()
    sink = RecordingFusionResultSink()
    fi = _make_input(target_ns=1000)
    returned = fuse_and_publish(oracle, fi, sink)
    assert len(sink.records) == 1
    assert sink.records[0] is returned


def test_fuse_and_publish_result_stamp_matches_input_target() -> None:
    oracle = _make_oracle()
    sink = RecordingFusionResultSink()
    fi = _make_input(target_ns=42_000_000)
    result = fuse_and_publish(oracle, fi, sink)
    assert result.belief.stamp_sim_ns == 42_000_000


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_oracle_satisfies_sensor_fusion_policy_protocol() -> None:
    oracle = _make_oracle()
    assert isinstance(oracle, SensorFusionPolicy)


def test_null_sink_satisfies_fusion_result_sink_protocol() -> None:
    assert isinstance(NullFusionResultSink(), FusionResultSink)


def test_recording_sink_satisfies_fusion_result_sink_protocol() -> None:
    assert isinstance(RecordingFusionResultSink(), FusionResultSink)


# ---------------------------------------------------------------------------
# Determinism: 5x cross-call byte-identical
# ---------------------------------------------------------------------------


def test_fusion_result_encode_is_byte_deterministic_5x() -> None:
    oracle = _make_oracle(
        velocity=np.array([2.0, -1.0, 0.5], dtype=np.float64),
        initial_pos=np.array([100.0, 200.0, 300.0], dtype=np.float64),
        start_ns=0,
        cov=1e-3,
    )
    fi = _make_input(target_ns=1_500_000_000, prior_ns=None)

    blobs = [encode_to_bytes(oracle.fuse(fi)) for _ in range(5)]
    assert all(b == blobs[0] for b in blobs)
