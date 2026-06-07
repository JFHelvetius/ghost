"""Tests de `NoisyGroundTruthConfig` — validación por constructor.

Cubre:

- Construcción válida con los defaults del helper.
- Rechazo de stds negativos / NaN / Inf / tipos incorrectos.
- Rechazo de covarianza con forma incorrecta / dtype incorrecto /
  no simétrica / no PSD / con NaN.
- Validación del label (`startswith("/")`).
- Sellado de la covarianza tras construcción (caller no debe mutar).
- Frozen dataclass: no se puede reasignar campos.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import numpy as np
import pytest

from project_ghost.estimation import NoisyGroundTruthConfig
from tests.estimation.conftest import (
    make_config,
    make_declared_cov,
)


def test_valid_config_constructs() -> None:
    cfg = make_config()
    assert cfg.position_noise_std_m == 0.05
    assert cfg.orientation_noise_std_rad == 0.01
    assert cfg.linear_velocity_noise_std_mps == 0.02
    assert cfg.angular_velocity_noise_std_rps == 0.005
    assert cfg.accel_body_noise_std_mps2 == 0.1
    assert cfg.declared_covariance_15x15.shape == (15, 15)
    assert cfg.random_source_label == "/estimation/noisy_gt"


def test_zero_stds_are_valid() -> None:
    """std == 0 es válido — significa "no agregar ruido a este campo"."""
    cfg = make_config(
        position_noise_std_m=0.0,
        orientation_noise_std_rad=0.0,
        linear_velocity_noise_std_mps=0.0,
        angular_velocity_noise_std_rps=0.0,
        accel_body_noise_std_mps2=0.0,
    )
    assert cfg.position_noise_std_m == 0.0


@pytest.mark.parametrize(
    "field",
    [
        "position_noise_std_m",
        "orientation_noise_std_rad",
        "linear_velocity_noise_std_mps",
        "angular_velocity_noise_std_rps",
        "accel_body_noise_std_mps2",
    ],
)
def test_negative_std_rejected(field: str) -> None:
    overrides: dict[str, Any] = {field: -0.1}
    with pytest.raises(ValueError, match=field):
        make_config(**overrides)


@pytest.mark.parametrize(
    "field",
    [
        "position_noise_std_m",
        "orientation_noise_std_rad",
        "linear_velocity_noise_std_mps",
        "angular_velocity_noise_std_rps",
        "accel_body_noise_std_mps2",
    ],
)
def test_nan_std_rejected(field: str) -> None:
    overrides: dict[str, Any] = {field: float("nan")}
    with pytest.raises(ValueError, match="finito"):
        make_config(**overrides)


def test_inf_std_rejected() -> None:
    with pytest.raises(ValueError, match="finito"):
        make_config(position_noise_std_m=float("inf"))


def test_non_numeric_std_rejected() -> None:
    with pytest.raises(TypeError, match="numérico"):
        NoisyGroundTruthConfig(
            position_noise_std_m="0.1",  # type: ignore[arg-type]
            orientation_noise_std_rad=0.01,
            linear_velocity_noise_std_mps=0.02,
            angular_velocity_noise_std_rps=0.005,
            accel_body_noise_std_mps2=0.1,
            declared_covariance_15x15=make_declared_cov(),
        )


def test_covariance_wrong_shape_rejected() -> None:
    bad = np.eye(10, dtype=np.float64)
    with pytest.raises(TypeError, match="shape"):
        make_config(declared_covariance_15x15=bad)


def test_covariance_wrong_dtype_rejected() -> None:
    bad = np.eye(15, dtype=np.float32)
    with pytest.raises(TypeError, match="float64"):
        make_config(declared_covariance_15x15=bad)


def test_covariance_not_ndarray_rejected() -> None:
    with pytest.raises(TypeError, match=r"np\.ndarray"):
        make_config(
            declared_covariance_15x15=[[0.0] * 15] * 15  # type: ignore[arg-type]
        )


def test_covariance_with_nan_rejected() -> None:
    bad = np.eye(15, dtype=np.float64)
    bad[0, 0] = float("nan")
    with pytest.raises(ValueError, match="NaN o Inf"):
        make_config(declared_covariance_15x15=bad)


def test_covariance_asymmetric_rejected() -> None:
    bad = np.eye(15, dtype=np.float64)
    bad[0, 1] = 0.5
    bad[1, 0] = 0.0
    with pytest.raises(ValueError, match="simétrica"):
        make_config(declared_covariance_15x15=bad)


def test_covariance_not_psd_rejected() -> None:
    bad = -np.eye(15, dtype=np.float64)
    with pytest.raises(ValueError, match="PSD"):
        make_config(declared_covariance_15x15=bad)


def test_label_without_leading_slash_rejected() -> None:
    with pytest.raises(ValueError, match="'/'"):
        make_config(random_source_label="estimation/noisy_gt")


def test_label_non_string_rejected() -> None:
    with pytest.raises(TypeError, match="str"):
        make_config(random_source_label=42)  # type: ignore[arg-type]


def test_covariance_sealed_after_construction() -> None:
    """Tras construir el config, la cov queda read-only para evitar
    mutación caller que invalidaría la creencia declarada."""
    cov = make_declared_cov()
    cfg = make_config(declared_covariance_15x15=cov)
    assert cfg.declared_covariance_15x15.flags.writeable is False
    with pytest.raises(ValueError, match="read-only"):
        cfg.declared_covariance_15x15[0, 0] = 99.0


def test_config_is_frozen() -> None:
    cfg = make_config()
    with pytest.raises(FrozenInstanceError):
        cfg.position_noise_std_m = 0.5  # type: ignore[misc]
