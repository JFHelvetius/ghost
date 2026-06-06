"""Tests de envejecimiento de estimaciones (uncertainty.md §4)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from project_ghost.core.uncertainty import (
    Estimate,
    EstimateSource,
    Validity,
    age_ns,
    downgrade_by_age,
    make_estimate,
)


def _src() -> EstimateSource:
    return EstimateSource(module_id="test.mod", kind="filter", schema_version=1)


def _make_valid_estimate(stamp_ns: int = 0) -> Estimate[np.ndarray]:
    return make_estimate(
        value=np.zeros(3, dtype=np.float64),
        covariance=np.eye(3, dtype=np.float64),
        validity=Validity.VALID,
        stamp_sim_ns=stamp_ns,
        source=_src(),
    )


# ---------------------------------------------------------------------------
# age_ns
# ---------------------------------------------------------------------------


def test_age_ns_simple() -> None:
    est = _make_valid_estimate(stamp_ns=1_000)
    assert age_ns(est, now_ns=2_500) == 1_500


def test_age_ns_zero_when_simultaneous() -> None:
    est = _make_valid_estimate(stamp_ns=42)
    assert age_ns(est, now_ns=42) == 0


def test_age_ns_negative_when_now_before_stamp() -> None:
    """age_ns no corrige; el caller verá un valor negativo y debe manejarlo."""
    est = _make_valid_estimate(stamp_ns=100)
    assert age_ns(est, now_ns=50) == -50


# ---------------------------------------------------------------------------
# downgrade_by_age — uncertainty.md §4
# ---------------------------------------------------------------------------


def test_downgrade_by_age_no_change_within_max() -> None:
    """age ≤ max_age_ns: sin cambio."""
    est = _make_valid_estimate(stamp_ns=0)
    out = downgrade_by_age(est, now_ns=500, max_age_ns=1000)
    assert out is est  # devolvemos la misma instancia para evitar copia
    assert out.validity == Validity.VALID


def test_downgrade_by_age_to_stale() -> None:
    """max < age ≤ 3·max: STALE."""
    est = _make_valid_estimate(stamp_ns=0)
    out = downgrade_by_age(est, now_ns=2_000, max_age_ns=1_000)
    assert out.validity == Validity.STALE


def test_downgrade_by_age_to_invalid() -> None:
    """age > 3·max_age_ns: INVALID."""
    est = _make_valid_estimate(stamp_ns=0)
    out = downgrade_by_age(est, now_ns=10_000, max_age_ns=1_000)
    assert out.validity == Validity.INVALID


def test_downgrade_by_age_preserves_covariance_and_other_fields() -> None:
    """Solo el validity cambia; cov/stamp/source/value se preservan."""
    est = _make_valid_estimate(stamp_ns=100)
    out = downgrade_by_age(est, now_ns=2_500, max_age_ns=1_000)
    assert out.stamp_sim_ns == est.stamp_sim_ns
    assert out.source == est.source
    assert out.covariance is not None
    np.testing.assert_array_equal(out.covariance, est.covariance)
    np.testing.assert_array_equal(out.value, est.value)


def test_downgrade_by_age_never_upgrades() -> None:
    """Si el validity de entrada ya es peor que el calculado, mantiene el peor."""
    est = make_estimate(
        value=np.zeros(3),
        covariance=np.eye(3),
        validity=Validity.STALE,
        stamp_sim_ns=0,
        source=_src(),
    )
    # age=500 < max=1000 ⇒ regla diría "no cambia"; queda STALE (era STALE).
    out_no_age = downgrade_by_age(est, now_ns=500, max_age_ns=1_000)
    assert out_no_age.validity == Validity.STALE
    # age=10000 > 3*max ⇒ INVALID es peor que STALE; baja.
    out_invalid = downgrade_by_age(est, now_ns=10_000, max_age_ns=1_000)
    assert out_invalid.validity == Validity.INVALID


def test_downgrade_by_age_rejects_non_positive_max() -> None:
    est = _make_valid_estimate(stamp_ns=0)
    with pytest.raises(ValueError, match="max_age_ns"):
        downgrade_by_age(est, now_ns=100, max_age_ns=0)
    with pytest.raises(ValueError, match="max_age_ns"):
        downgrade_by_age(est, now_ns=100, max_age_ns=-1)


def test_downgrade_by_age_rejects_negative_age() -> None:
    """Reloj retrocedió o stamp futuro: no hay magia silenciosa."""
    est = _make_valid_estimate(stamp_ns=1_000)
    with pytest.raises(ValueError, match="age="):
        downgrade_by_age(est, now_ns=500, max_age_ns=1_000)


@given(
    stamp_ns=st.integers(min_value=0, max_value=10**12),
    delta_ns=st.integers(min_value=0, max_value=10**13),
    max_age_ns=st.integers(min_value=1, max_value=10**12),
)
def test_downgrade_by_age_thresholds_property(
    stamp_ns: int, delta_ns: int, max_age_ns: int
) -> None:
    """Propiedad sobre las tres bandas de §4."""
    est = _make_valid_estimate(stamp_ns=stamp_ns)
    now_ns = stamp_ns + delta_ns
    out = downgrade_by_age(est, now_ns=now_ns, max_age_ns=max_age_ns)

    if delta_ns <= max_age_ns:
        assert out.validity == Validity.VALID
    elif delta_ns <= 3 * max_age_ns:
        assert out.validity == Validity.STALE
    else:
        assert out.validity == Validity.INVALID
