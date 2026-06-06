"""Tests de `NavUncertainty` (uncertainty.md §2)."""

from __future__ import annotations

import numpy as np
import pytest

from project_ghost.core.uncertainty import NavUncertainty, Validity


def _good_sigma() -> np.ndarray:
    return np.array([0.1, 0.1, 0.1], dtype=np.float64)


def test_nav_uncertainty_constructs_and_seals() -> None:
    nu = NavUncertainty(
        validity=Validity.VALID,
        pos_sigma_m=_good_sigma(),
        vel_sigma_mps=_good_sigma(),
        att_sigma_rad=_good_sigma(),
        horizon_ns=1_000_000,
        age_ns=0,
    )
    for arr in (nu.pos_sigma_m, nu.vel_sigma_mps, nu.att_sigma_rad):
        assert arr.shape == (3,)
        assert arr.dtype == np.float64
        assert not arr.flags.writeable


def test_nav_uncertainty_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match="pos_sigma_m"):
        NavUncertainty(
            validity=Validity.VALID,
            pos_sigma_m=np.array([0.1, 0.1]),
            vel_sigma_mps=_good_sigma(),
            att_sigma_rad=_good_sigma(),
            horizon_ns=1,
            age_ns=0,
        )


def test_nav_uncertainty_rejects_negative_sigma() -> None:
    with pytest.raises(ValueError, match="pos_sigma_m"):
        NavUncertainty(
            validity=Validity.VALID,
            pos_sigma_m=np.array([0.1, -0.1, 0.1]),
            vel_sigma_mps=_good_sigma(),
            att_sigma_rad=_good_sigma(),
            horizon_ns=1,
            age_ns=0,
        )


def test_nav_uncertainty_rejects_negative_horizon_or_age() -> None:
    with pytest.raises(ValueError, match="horizon_ns"):
        NavUncertainty(
            validity=Validity.VALID,
            pos_sigma_m=_good_sigma(),
            vel_sigma_mps=_good_sigma(),
            att_sigma_rad=_good_sigma(),
            horizon_ns=-1,
            age_ns=0,
        )
    with pytest.raises(ValueError, match="age_ns"):
        NavUncertainty(
            validity=Validity.VALID,
            pos_sigma_m=_good_sigma(),
            vel_sigma_mps=_good_sigma(),
            att_sigma_rad=_good_sigma(),
            horizon_ns=0,
            age_ns=-1,
        )
