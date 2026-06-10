"""Tests de `state.transforms` (T2.a.5).

Estrategia:

- **Anchor vectors**: para cada función, casos con resultado conocido a
  mano (identidad, rotación 90° por cada eje, vectores base de frame).
- **Round-trip**: forward∘inverse y inverse∘forward son identidad bit-exacta.
- **Determinismo**: invocaciones repetidas con el mismo input producen
  el mismo output bit a bit (ADR-0002).
- **Frontera**: validación de shape, dtype, finitud y unit-norm para
  quaternions.

Las transforms son fundación; no se testean comportamientos de robot ni
demos — solo que la matemática sea correcta y determinística.
"""

from __future__ import annotations

import numpy as np
import pytest

from project_ghost.state.transforms import (
    R_body_to_world,
    R_world_to_body,
    enu_to_ned,
    flu_to_frd,
    frd_to_flu,
    ned_to_enu,
    quat_hamilton_to_scipy,
    quat_scipy_to_hamilton,
)

# ---------------------------------------------------------------------------
# Constantes — quaternions de prueba canónicos (Hamilton w-first)
# ---------------------------------------------------------------------------

_Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
# Rotación 90° alrededor de Z (yaw positivo)
_Q_YAW_90 = np.array([np.sqrt(2.0) / 2.0, 0.0, 0.0, np.sqrt(2.0) / 2.0], dtype=np.float64)
# Rotación 90° alrededor de X
_Q_ROLL_90 = np.array([np.sqrt(2.0) / 2.0, np.sqrt(2.0) / 2.0, 0.0, 0.0], dtype=np.float64)
# Rotación 90° alrededor de Y
_Q_PITCH_90 = np.array([np.sqrt(2.0) / 2.0, 0.0, np.sqrt(2.0) / 2.0, 0.0], dtype=np.float64)


# ---------------------------------------------------------------------------
# Helpers de aserción
# ---------------------------------------------------------------------------


def _assert_arr_equal_bitwise(actual: np.ndarray, expected: np.ndarray) -> None:
    """Igualdad bit-a-bit para chequear determinismo (no `allclose`)."""
    assert actual.shape == expected.shape
    assert actual.dtype == expected.dtype
    assert np.array_equal(actual, expected), f"actual={actual}, expected={expected}"


# ---------------------------------------------------------------------------
# quat_hamilton_to_scipy / quat_scipy_to_hamilton
# ---------------------------------------------------------------------------


def test_hamilton_to_scipy_permutes_correctly() -> None:
    q_h = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64) / np.linalg.norm(
        np.array([1.0, 2.0, 3.0, 4.0])
    )
    q_s = quat_hamilton_to_scipy(q_h)
    # Hamilton [w,x,y,z] -> scipy [x,y,z,w]
    assert q_s[0] == q_h[1]
    assert q_s[1] == q_h[2]
    assert q_s[2] == q_h[3]
    assert q_s[3] == q_h[0]


def test_scipy_to_hamilton_is_inverse() -> None:
    q_h = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    q_s = quat_hamilton_to_scipy(q_h)
    q_h_back = quat_scipy_to_hamilton(q_s)
    _assert_arr_equal_bitwise(q_h_back, q_h)


def test_hamilton_to_scipy_identity_preserves_shape_and_norm() -> None:
    q_s = quat_hamilton_to_scipy(_Q_IDENTITY)
    assert q_s.shape == (4,)
    assert float(np.linalg.norm(q_s)) == pytest.approx(1.0)


def test_quat_returns_are_sealed() -> None:
    out = quat_hamilton_to_scipy(_Q_IDENTITY)
    assert not out.flags.writeable


def test_quat_rejects_wrong_shape() -> None:
    with pytest.raises(TypeError, match="shape"):
        quat_hamilton_to_scipy(np.array([1.0, 0.0, 0.0], dtype=np.float64))


def test_quat_rejects_non_unit() -> None:
    with pytest.raises(ValueError, match="unit"):
        quat_hamilton_to_scipy(np.array([1.0, 1.0, 0.0, 0.0], dtype=np.float64))


def test_quat_rejects_nan() -> None:
    with pytest.raises(ValueError, match="NaN"):
        quat_hamilton_to_scipy(np.array([np.nan, 0.0, 0.0, 0.0], dtype=np.float64))


def test_quat_rejects_wrong_dtype() -> None:
    with pytest.raises(TypeError, match="dtype"):
        quat_hamilton_to_scipy(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))


# ---------------------------------------------------------------------------
# R_body_to_world — anchor vectors
# ---------------------------------------------------------------------------


def test_R_body_to_world_identity_is_identity_matrix() -> None:
    r = R_body_to_world(_Q_IDENTITY)
    np.testing.assert_allclose(r, np.eye(3, dtype=np.float64), atol=1e-15)


def test_R_body_to_world_yaw_90_maps_x_to_y() -> None:
    """Yaw 90° (rotación alrededor de Z) en body→world envía body-x → world-y."""
    r = R_body_to_world(_Q_YAW_90)
    v_body_x = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    v_world = r @ v_body_x
    np.testing.assert_allclose(v_world, np.array([0.0, 1.0, 0.0]), atol=1e-15)


def test_R_body_to_world_roll_90_maps_y_to_z() -> None:
    """Roll 90° (rotación alrededor de X) envía body-y → world-z."""
    r = R_body_to_world(_Q_ROLL_90)
    v_body_y = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    v_world = r @ v_body_y
    np.testing.assert_allclose(v_world, np.array([0.0, 0.0, 1.0]), atol=1e-15)


def test_R_body_to_world_pitch_90_maps_z_to_x() -> None:
    """Pitch 90° (rotación alrededor de Y) envía body-z → world-x."""
    r = R_body_to_world(_Q_PITCH_90)
    v_body_z = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    v_world = r @ v_body_z
    np.testing.assert_allclose(v_world, np.array([1.0, 0.0, 0.0]), atol=1e-15)


def test_R_body_to_world_is_orthogonal() -> None:
    """Una matriz de rotación es ortogonal: R @ R^T = I."""
    for q in (_Q_IDENTITY, _Q_YAW_90, _Q_ROLL_90, _Q_PITCH_90):
        r = R_body_to_world(q)
        np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-15)


def test_R_body_to_world_has_determinant_one() -> None:
    """Rotaciones propias (sin reflexión) tienen det = 1."""
    for q in (_Q_IDENTITY, _Q_YAW_90, _Q_ROLL_90, _Q_PITCH_90):
        r = R_body_to_world(q)
        assert float(np.linalg.det(r)) == pytest.approx(1.0, abs=1e-12)


def test_R_body_to_world_returns_sealed_array() -> None:
    r = R_body_to_world(_Q_IDENTITY)
    assert not r.flags.writeable


def test_R_body_to_world_is_deterministic_bitwise() -> None:
    """Determinismo bit-a-bit ante invocaciones repetidas (ADR-0002)."""
    r1 = R_body_to_world(_Q_YAW_90.copy())
    r2 = R_body_to_world(_Q_YAW_90.copy())
    _assert_arr_equal_bitwise(r1, r2)


def test_R_body_to_world_rejects_non_unit_quaternion() -> None:
    with pytest.raises(ValueError, match="unit"):
        R_body_to_world(np.array([2.0, 0.0, 0.0, 0.0], dtype=np.float64))


# ---------------------------------------------------------------------------
# R_world_to_body
# ---------------------------------------------------------------------------


def test_R_world_to_body_is_transpose_of_R_body_to_world() -> None:
    for q in (_Q_IDENTITY, _Q_YAW_90, _Q_ROLL_90, _Q_PITCH_90):
        r_fwd = R_body_to_world(q)
        r_inv = R_world_to_body(q)
        np.testing.assert_allclose(r_inv, r_fwd.T, atol=1e-15)


def test_R_world_to_body_inverts_R_body_to_world() -> None:
    """R_world_to_body(q) @ R_body_to_world(q) = I."""
    for q in (_Q_IDENTITY, _Q_YAW_90, _Q_ROLL_90, _Q_PITCH_90):
        composed = R_world_to_body(q) @ R_body_to_world(q)
        np.testing.assert_allclose(composed, np.eye(3), atol=1e-15)


def test_R_world_to_body_returns_sealed_array() -> None:
    r = R_world_to_body(_Q_YAW_90)
    assert not r.flags.writeable


# ---------------------------------------------------------------------------
# ENU <-> NED
# ---------------------------------------------------------------------------


def test_enu_to_ned_anchor() -> None:
    """`[E, N, U]` -> `[N, E, -U]`."""
    v_enu = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    v_ned = enu_to_ned(v_enu)
    np.testing.assert_array_equal(v_ned, np.array([2.0, 1.0, -3.0]))


def test_ned_to_enu_anchor() -> None:
    """`[N, E, D]` -> `[E, N, -D]`."""
    v_ned = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    v_enu = ned_to_enu(v_ned)
    np.testing.assert_array_equal(v_enu, np.array([2.0, 1.0, -3.0]))


def test_enu_ned_round_trip_is_identity_bitwise() -> None:
    for v in (
        np.array([0.0, 0.0, 0.0], dtype=np.float64),
        np.array([1.0, 2.0, 3.0], dtype=np.float64),
        np.array([-1.5, 2.7, -0.3], dtype=np.float64),
    ):
        back = ned_to_enu(enu_to_ned(v))
        _assert_arr_equal_bitwise(back, v)


def test_enu_to_ned_returns_sealed() -> None:
    out = enu_to_ned(np.zeros(3, dtype=np.float64))
    assert not out.flags.writeable


def test_enu_to_ned_rejects_wrong_shape() -> None:
    with pytest.raises(TypeError, match="shape"):
        enu_to_ned(np.zeros(4, dtype=np.float64))


def test_enu_to_ned_rejects_nan() -> None:
    with pytest.raises(ValueError, match="NaN"):
        enu_to_ned(np.array([0.0, np.nan, 0.0], dtype=np.float64))


def test_enu_to_ned_rejects_wrong_dtype() -> None:
    with pytest.raises(TypeError, match="dtype"):
        enu_to_ned(np.zeros(3, dtype=np.float32))


# ---------------------------------------------------------------------------
# FLU <-> FRD
# ---------------------------------------------------------------------------


def test_flu_to_frd_anchor() -> None:
    """`[F, L, U]` -> `[F, -L, -U]`. Forward intacto."""
    v_flu = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    v_frd = flu_to_frd(v_flu)
    np.testing.assert_array_equal(v_frd, np.array([1.0, -2.0, -3.0]))


def test_frd_to_flu_anchor() -> None:
    v_frd = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    v_flu = frd_to_flu(v_frd)
    np.testing.assert_array_equal(v_flu, np.array([1.0, -2.0, -3.0]))


def test_flu_frd_round_trip_is_identity_bitwise() -> None:
    for v in (
        np.array([0.0, 0.0, 0.0], dtype=np.float64),
        np.array([1.0, 2.0, 3.0], dtype=np.float64),
        np.array([-1.5, 2.7, -0.3], dtype=np.float64),
    ):
        back = frd_to_flu(flu_to_frd(v))
        _assert_arr_equal_bitwise(back, v)


def test_flu_to_frd_returns_sealed() -> None:
    out = flu_to_frd(np.zeros(3, dtype=np.float64))
    assert not out.flags.writeable


def test_flu_to_frd_rejects_invalid_inputs() -> None:
    with pytest.raises(TypeError, match="shape"):
        flu_to_frd(np.zeros(2, dtype=np.float64))
    with pytest.raises(ValueError, match="NaN"):
        flu_to_frd(np.array([0.0, np.inf, 0.0], dtype=np.float64))


# ---------------------------------------------------------------------------
# Determinismo end-to-end
# ---------------------------------------------------------------------------


def test_all_transforms_are_deterministic_bitwise_under_repeated_calls() -> None:
    """ADR-0002: misma input -> mismo output, bit a bit, en cualquier momento."""
    q = _Q_YAW_90.copy()
    v = np.array([1.5, -2.7, 0.3], dtype=np.float64)

    _assert_arr_equal_bitwise(quat_hamilton_to_scipy(q.copy()), quat_hamilton_to_scipy(q.copy()))
    _assert_arr_equal_bitwise(R_body_to_world(q.copy()), R_body_to_world(q.copy()))
    _assert_arr_equal_bitwise(R_world_to_body(q.copy()), R_world_to_body(q.copy()))
    _assert_arr_equal_bitwise(enu_to_ned(v.copy()), enu_to_ned(v.copy()))
    _assert_arr_equal_bitwise(ned_to_enu(v.copy()), ned_to_enu(v.copy()))
    _assert_arr_equal_bitwise(flu_to_frd(v.copy()), flu_to_frd(v.copy()))
    _assert_arr_equal_bitwise(frd_to_flu(v.copy()), frd_to_flu(v.copy()))


# ---------------------------------------------------------------------------
# Inputs no mutados — el caller mantiene la propiedad de su array
# ---------------------------------------------------------------------------


def test_transforms_do_not_mutate_input_arrays() -> None:
    """Las transforms son puras: el array que entra no cambia."""
    q = _Q_YAW_90.copy()
    q_before = q.copy()
    R_body_to_world(q)
    R_world_to_body(q)
    quat_hamilton_to_scipy(q)
    quat_scipy_to_hamilton(q)
    _assert_arr_equal_bitwise(q, q_before)

    v = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    v_before = v.copy()
    enu_to_ned(v)
    ned_to_enu(v)
    flu_to_frd(v)
    frd_to_flu(v)
    _assert_arr_equal_bitwise(v, v_before)
