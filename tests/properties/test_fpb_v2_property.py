"""Hypothesis property tests for ADR-0041 (FPB-v2).

FPB-v2 ships a confidence upper bound on the **true** firing
probability given a sample ``(cycles_fires, cycles_total)``. The
tests pin the mathematical properties any sound estimator must
satisfy plus the relationship between Hoeffding and Clopper-Pearson.

P1 (sound bound): the upper bound is always ``>= p_hat`` and
   ``<= 1.0``.

P2 (Hoeffding dominates Clopper-Pearson): for any ``(k, n)``,
   Hoeffding's bound is at least Clopper-Pearson's; CP is exact
   under the binomial assumption while Hoeffding is distribution-
   free and therefore looser.

P3 (monotone in p_hat): for fixed ``n``, the bound increases as
   ``cycles_fires`` increases.

P4 (decreasing in n): for fixed ``p_hat`` (rational with the same
   numerator-to-denominator ratio), the bound decreases as ``n``
   grows. We pick ``(k, n) -> (2k, 2n)`` to keep ``p_hat`` exact.

P5 (consistency): as ``n`` grows large at fixed ``p_hat``, the
   Hoeffding bound converges to ``p_hat``. We pin a quantitative
   form: at ``n = 10 000``, the gap is below ``0.05``.

P6 (small-sample correctness): on ``n = 0`` the bound is vacuous
   (``1.0``); on ``cycles_fires = 0, n > 0`` the bound is strictly
   below ``1.0``.

These are pure-math properties of the closed-form bounds; they do
not require an MCAP and run in milliseconds. The end-to-end
``verify_fpb_v2`` integration is covered by a separate smoke test
that drives an MCAP through the verifier.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from project_ghost.properties.fpb_v2 import (
    ConfidenceMethod,
    _clopper_pearson_upper_bound,
    _hoeffding_upper_bound,
)

_CONFIDENCE_LEVELS = (0.90, 0.95, 0.99)


@settings(deadline=None)
@given(
    n=st.integers(min_value=1, max_value=100_000),
    k=st.integers(min_value=0),
    level=st.sampled_from(_CONFIDENCE_LEVELS),
)
def test_hoeffding_upper_bound_is_sound(n: int, k: int, level: float) -> None:
    """P1 for Hoeffding: bound in [p_hat, 1.0]."""
    k = min(k, n)
    p_hat = k / n
    ub = _hoeffding_upper_bound(k, n, level)
    assert p_hat - 1e-12 <= ub <= 1.0 + 1e-12, (
        f"Hoeffding ub={ub} not in [p_hat={p_hat}, 1.0] for k={k}, n={n}, level={level}"
    )


@settings(deadline=None)
@given(
    n=st.integers(min_value=1, max_value=10_000),
    k=st.integers(min_value=0),
    level=st.sampled_from(_CONFIDENCE_LEVELS),
)
def test_clopper_pearson_upper_bound_is_sound(n: int, k: int, level: float) -> None:
    """P1 for Clopper-Pearson: bound in [p_hat, 1.0]."""
    k = min(k, n)
    p_hat = k / n
    ub = _clopper_pearson_upper_bound(k, n, level)
    assert p_hat - 1e-9 <= ub <= 1.0 + 1e-9, (
        f"CP ub={ub} not in [p_hat={p_hat}, 1.0] for k={k}, n={n}, level={level}"
    )


@settings(deadline=None)
@given(
    n=st.integers(min_value=2, max_value=10_000),
    k=st.integers(min_value=0),
    level=st.sampled_from(_CONFIDENCE_LEVELS),
)
def test_hoeffding_dominates_clopper_pearson(n: int, k: int, level: float) -> None:
    """P2: Hoeffding bound >= Clopper-Pearson bound.

    Hoeffding is distribution-free and therefore looser than the
    exact binomial CI. If CP ever exceeds Hoeffding, one of the two
    estimators has a bug.
    """
    k = min(k, n)
    h = _hoeffding_upper_bound(k, n, level)
    cp = _clopper_pearson_upper_bound(k, n, level)
    # Allow tiny floating-point slack; binary search in scipy's
    # beta.ppf has ULP-level error vs the closed-form sqrt.
    assert h + 1e-9 >= cp, (
        f"Hoeffding ub={h:.6f} < Clopper-Pearson ub={cp:.6f} at k={k}, n={n}, level={level}"
    )


@settings(deadline=None)
@given(
    n=st.integers(min_value=2, max_value=10_000),
    k1=st.integers(min_value=0),
    k2=st.integers(min_value=0),
    method=st.sampled_from(list(ConfidenceMethod)),
    level=st.sampled_from(_CONFIDENCE_LEVELS),
)
def test_bound_is_monotone_in_p_hat(
    n: int, k1: int, k2: int, method: ConfidenceMethod, level: float
) -> None:
    """P3: for fixed ``n``, ub(k1) <= ub(k2) when k1 <= k2."""
    k1 = min(k1, n)
    k2 = min(k2, n)
    if k1 > k2:
        k1, k2 = k2, k1
    fn = _bound_fn(method)
    ub1 = fn(k1, n, level)
    ub2 = fn(k2, n, level)
    assert ub1 <= ub2 + 1e-9, (
        f"{method.value}: ub({k1},{n})={ub1:.6f} > ub({k2},{n})={ub2:.6f}, "
        "monotonicity in p_hat broken"
    )


@settings(deadline=None)
@given(
    n=st.integers(min_value=1, max_value=5_000),
    k=st.integers(min_value=0),
    method=st.sampled_from(list(ConfidenceMethod)),
    level=st.sampled_from(_CONFIDENCE_LEVELS),
)
def test_bound_is_decreasing_in_n_at_fixed_p_hat(
    n: int, k: int, method: ConfidenceMethod, level: float
) -> None:
    """P4: doubling (k, n) at fixed p_hat must shrink the bound."""
    k = min(k, n)
    fn = _bound_fn(method)
    ub_small = fn(k, n, level)
    ub_big = fn(2 * k, 2 * n, level)
    assert ub_big <= ub_small + 1e-9, (
        f"{method.value}: bound did not shrink under (k,n)->(2k,2n): "
        f"ub({k},{n})={ub_small:.6f} ub({2 * k},{2 * n})={ub_big:.6f}"
    )


@settings(max_examples=20, deadline=None)
@given(
    p_hat_promille=st.integers(min_value=0, max_value=1000),
    method=st.sampled_from(list(ConfidenceMethod)),
)
def test_bound_converges_to_p_hat_at_large_n(p_hat_promille: int, method: ConfidenceMethod) -> None:
    """P5: at n=10000 the bound is within 0.05 of p_hat at level 0.95.

    Distribution-free quantitative consistency check. Hoeffding's
    half-width at level 0.95, n=10000 is sqrt(ln(20)/20000) ~= 0.0387;
    CP is tighter. So 0.05 is a safe pin that catches a structural
    regression without overfitting to the math.
    """
    n = 10_000
    p_hat = p_hat_promille / 1000
    k = round(p_hat * n)
    fn = _bound_fn(method)
    ub = fn(k, n, 0.95)
    gap = ub - (k / n)
    assert gap < 0.05, f"{method.value}: ub-p_hat={gap:.4f} >= 0.05 at n={n}, p_hat={k / n:.4f}"


@pytest.mark.parametrize("method", list(ConfidenceMethod))
def test_zero_sample_is_vacuous(method: ConfidenceMethod) -> None:
    """P6: with n=0 the bound is the vacuous 1.0 (no information)."""
    fn = _bound_fn(method)
    assert fn(0, 0, 0.95) == pytest.approx(1.0)


@pytest.mark.parametrize("method", list(ConfidenceMethod))
def test_zero_fires_with_positive_n_is_strictly_below_one(
    method: ConfidenceMethod,
) -> None:
    """P6 (other half): k=0 with n>0 must give an informative bound."""
    fn = _bound_fn(method)
    ub = fn(0, 50, 0.95)
    assert ub < 1.0, f"{method.value}: ub({0},{50})={ub} should be < 1.0"


def _bound_fn(method: ConfidenceMethod):  # type: ignore[no-untyped-def]
    if method is ConfidenceMethod.HOEFFDING:
        return _hoeffding_upper_bound
    if method is ConfidenceMethod.CLOPPER_PEARSON:
        return _clopper_pearson_upper_bound
    raise ValueError(f"unhandled method: {method}")
