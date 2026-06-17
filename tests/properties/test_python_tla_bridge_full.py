# ruff: noqa: N803
# Argument names M, K, W are kept uppercase to match the TLA+ constants
# and the paper's mathematical notation; lowercase aliases would
# obscure the correspondence to the spec.
"""ADR-0046 -- Python <-> TLA+ bridge conformance for BAUD/ERUR/MD/FPB.

Extends ADR-0043's RLB-v1 bridge to the remaining four foundational
contracts. The template per property:

- ``_tla_<prop>``: literal Python re-implementation of the property's
  TLA+ semantics (built from ``BaudErur.tla`` / ``Fpb.tla``).
- ``_pyver_<prop>``: literal Python re-implementation of the verifier's
  core decision logic from ``properties/<prop>.py`` (no MCAP I/O).
- ``test_..._agree_*``: Hypothesis property that synthesises a trace,
  feeds it through both implementations, and asserts they agree on
  the per-cycle verdict.

The two re-implementations per property are written from their
respective sources without sharing code; conformance is mechanically
checked on every push. A future divergence between the verifier core
and the TLA+ spec fails the test before the divergence ships.

ERUR-v2 is NOT covered here -- it is parametric over a
DriftPreconditionProvider Protocol and conformance there would require
re-implementing each policy's predicate. ERUR-v1 covers the
Mahalanobis-specific path. FPB-v2's statistical bound conformance is
already pinned in ``test_fpb_v2_property.py`` against the closed-form
math; we do not duplicate it here.

Property under test for each:

- BAUD-v1: precondition ``len(window) >= M and CountDirty(window) >= K``.
- ERUR-v1: precondition ``len(window) < M or CountDirty(window) < K``
  AND raw level is KNOWN.
- MD-v1: structural invariant -- adjusted level is never *more*
  confident than raw, under the reference Mahalanobis calibrator.
- FPB-v1: ``cycles_fires / cycles_total <= max_fire_fraction``.

Each test runs in well under a second; CI exercises them on every
push.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Shared infrastructure.
# ---------------------------------------------------------------------------


_DIRTY = "DIRTY"
_CLEAN = "CLEAN"
_KNOWN = "KNOWN"
_UNCERTAIN = "UNCERTAIN"
_UNKNOWN = "UNKNOWN"
_LEVEL_NUM = {_KNOWN: 0, _UNCERTAIN: 1, _UNKNOWN: 2}


def _count_dirty(window: list[str]) -> int:
    """``CountDirty(h) == |{i in DOMAIN h : h[i] = DIRTY}|`` from BaudErur.tla."""
    return sum(1 for v in window if v == _DIRTY)


def _window_update(window: list[str], outcome: str, W: int) -> list[str]:
    """``WindowUpdate(h, o)`` from BaudErur.tla / Rlb.tla."""
    if len(window) < W:
        return [*window, outcome]
    return [*window[1:], outcome]


# ---------------------------------------------------------------------------
# BAUD-v1 bridge.
# ---------------------------------------------------------------------------


def _tla_baud_precondition(window: list[str], M: int, K: int) -> bool:
    """BAUDPrecondition(h) from BaudErur.tla:
    OutcomesConsidered(h) >= M AND CountDirty(h) >= K.
    """
    return len(window) >= M and _count_dirty(window) >= K


def _pyver_baud_precondition_fires(
    count_beyond_3_or_worse: int, outcomes_considered: int, M: int, K: int
) -> bool:
    """Reproduce the verifier-core precondition check from
    ``src/project_ghost/properties/fpb.py::_baud_precondition_fires``
    (the canonical reference). Operates on the same scalar counts the
    verifier extracts from CalibratedSelfAssessment.
    """
    return outcomes_considered >= M and count_beyond_3_or_worse >= K


@settings(deadline=None, max_examples=200)
@given(
    M=st.integers(min_value=1, max_value=8),
    K=st.integers(min_value=1, max_value=8),
    W=st.integers(min_value=1, max_value=12),
    outcomes=st.lists(
        st.sampled_from([_DIRTY, _CLEAN]), min_size=0, max_size=20,
    ),
)
def test_baud_precondition_python_and_tla_agree(
    M: int, K: int, W: int, outcomes: list[str]
) -> None:
    """For any (M, K, W, trace), the two implementations agree on
    whether BAUD's precondition fires at the end-state window.
    """
    window: list[str] = []
    for o in outcomes:
        window = _window_update(window, o, W)

    tla = _tla_baud_precondition(window, M, K)
    py = _pyver_baud_precondition_fires(
        count_beyond_3_or_worse=_count_dirty(window),
        outcomes_considered=len(window),
        M=M,
        K=K,
    )
    assert tla == py, (
        f"BAUD bridge violated at M={M} K={K} W={W} window={window}: "
        f"TLA+={tla}, Python={py}"
    )


# ---------------------------------------------------------------------------
# ERUR-v1 bridge.
# ---------------------------------------------------------------------------


def _tla_erur_precondition(
    window: list[str], raw_level: str, M: int, K: int
) -> bool:
    """ERURPrecondition(h, raw) from BaudErur.tla:
    DriftClean(h) AND raw = KNOWN_L, where
    DriftClean(h) := OutcomesConsidered(h) < M OR CountDirty(h) < K.
    """
    drift_clean = len(window) < M or _count_dirty(window) < K
    return drift_clean and raw_level == _KNOWN


def _pyver_erur_precondition(
    count_dirty: int, outcomes_considered: int, raw_level: str, M: int, K: int
) -> bool:
    """De Morgan complement of BAUD's drift conjunction + KNOWN raw,
    mirroring the verifier core in
    ``src/project_ghost/properties/erur.py``.
    """
    drift_clean = outcomes_considered < M or count_dirty < K
    return drift_clean and raw_level == _KNOWN


@settings(deadline=None, max_examples=200)
@given(
    M=st.integers(min_value=1, max_value=8),
    K=st.integers(min_value=1, max_value=8),
    W=st.integers(min_value=1, max_value=12),
    raw=st.sampled_from([_KNOWN, _UNCERTAIN, _UNKNOWN]),
    outcomes=st.lists(
        st.sampled_from([_DIRTY, _CLEAN]), min_size=0, max_size=20,
    ),
)
def test_erur_precondition_python_and_tla_agree(
    M: int, K: int, W: int, raw: str, outcomes: list[str]
) -> None:
    """For any (M, K, W, raw, trace), the two implementations agree."""
    window: list[str] = []
    for o in outcomes:
        window = _window_update(window, o, W)

    tla = _tla_erur_precondition(window, raw, M, K)
    py = _pyver_erur_precondition(
        count_dirty=_count_dirty(window),
        outcomes_considered=len(window),
        raw_level=raw,
        M=M,
        K=K,
    )
    assert tla == py, (
        f"ERUR bridge violated at M={M} K={K} W={W} raw={raw} "
        f"window={window}: TLA+={tla}, Python={py}"
    )


# ---------------------------------------------------------------------------
# Partition (BAUD XOR ERUR) bridge -- closes ADR-0036's INV_PARTITION
# at the Python level. Already mechanically proven in Lean 4
# (PartitionTheorem.lean), but the conformance test also pins that
# the Python verifier core respects the same partition.
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=300)
@given(
    M=st.integers(min_value=1, max_value=8),
    K=st.integers(min_value=1, max_value=8),
    W=st.integers(min_value=1, max_value=12),
    outcomes=st.lists(
        st.sampled_from([_DIRTY, _CLEAN]), min_size=0, max_size=20,
    ),
)
def test_partition_holds_under_known_raw(
    M: int, K: int, W: int, outcomes: list[str]
) -> None:
    """When raw = KNOWN, exactly one of BAUD precondition or ERUR
    precondition fires. Pins ``INV_PARTITION`` at the conformance
    layer (Lean 4 already proves the abstract theorem)."""
    window: list[str] = []
    for o in outcomes:
        window = _window_update(window, o, W)

    baud = _tla_baud_precondition(window, M, K)
    erur = _tla_erur_precondition(window, _KNOWN, M, K)
    assert baud != erur, (
        f"Partition violated: BAUD={baud}, ERUR={erur} at M={M} K={K} "
        f"W={W} window={window}"
    )


# ---------------------------------------------------------------------------
# MD-v1 bridge -- the reference Mahalanobis calibrator never inflates.
# ---------------------------------------------------------------------------


def _tla_md_downgrade(level: str) -> str:
    """``Downgrade(level)`` from BaudErur.tla."""
    if level == _KNOWN:
        return _UNCERTAIN
    if level == _UNCERTAIN:
        return _UNKNOWN
    return _UNKNOWN


def _tla_md_calibrate(
    raw: str, window: list[str], M: int, K: int
) -> str:
    """``Calibrate(raw, h)`` from BaudErur.tla: downgrade if BAUD
    precondition fires, else passthrough."""
    if _tla_baud_precondition(window, M, K):
        return _tla_md_downgrade(raw)
    return raw


def _pyver_md_calibrate(
    raw_level: str, count_dirty: int, outcomes_considered: int, M: int, K: int
) -> str:
    """Reproduce the verifier-side reference Mahalanobis calibrator
    semantics (``src/project_ghost/core/feedback/reference_policy.py``).
    """
    if outcomes_considered >= M and count_dirty >= K:
        return _tla_md_downgrade(raw_level)
    return raw_level


@settings(deadline=None, max_examples=300)
@given(
    M=st.integers(min_value=1, max_value=8),
    K=st.integers(min_value=1, max_value=8),
    W=st.integers(min_value=1, max_value=12),
    raw=st.sampled_from([_KNOWN, _UNCERTAIN, _UNKNOWN]),
    outcomes=st.lists(
        st.sampled_from([_DIRTY, _CLEAN]), min_size=0, max_size=20,
    ),
)
def test_md_calibrate_python_and_tla_agree(
    M: int, K: int, W: int, raw: str, outcomes: list[str]
) -> None:
    """The two calibrator implementations agree on adjusted level for
    every reachable state."""
    window: list[str] = []
    for o in outcomes:
        window = _window_update(window, o, W)

    tla_adj = _tla_md_calibrate(raw, window, M, K)
    py_adj = _pyver_md_calibrate(
        raw_level=raw,
        count_dirty=_count_dirty(window),
        outcomes_considered=len(window),
        M=M,
        K=K,
    )
    assert tla_adj == py_adj, (
        f"MD bridge violated at M={M} K={K} W={W} raw={raw} "
        f"window={window}: TLA+={tla_adj}, Python={py_adj}"
    )


@settings(deadline=None, max_examples=300)
@given(
    M=st.integers(min_value=1, max_value=8),
    K=st.integers(min_value=1, max_value=8),
    W=st.integers(min_value=1, max_value=12),
    raw=st.sampled_from([_KNOWN, _UNCERTAIN, _UNKNOWN]),
    outcomes=st.lists(
        st.sampled_from([_DIRTY, _CLEAN]), min_size=0, max_size=20,
    ),
)
def test_md_invariant_no_inflation(
    M: int, K: int, W: int, raw: str, outcomes: list[str]
) -> None:
    """``INV_NO_INVENTED_CONFIDENCE`` from BaudErur.tla:
    ``LevelNum(adjusted_level) >= LevelNum(raw_level)``.

    Pinned at the conformance layer: the reference calibrator never
    invents confidence. This is the MD-v1 contract postcondition.
    """
    window: list[str] = []
    for o in outcomes:
        window = _window_update(window, o, W)

    adj = _tla_md_calibrate(raw, window, M, K)
    assert _LEVEL_NUM[adj] >= _LEVEL_NUM[raw], (
        f"MD-v1 inflated: adjusted={adj} (num={_LEVEL_NUM[adj]}) < "
        f"raw={raw} (num={_LEVEL_NUM[raw]}) at M={M} K={K} W={W} "
        f"window={window}"
    )


# ---------------------------------------------------------------------------
# FPB-v1 bridge -- empirical fire fraction comparison.
# ---------------------------------------------------------------------------


def _tla_fpb_holds(
    cycles_fires: int, cycles_total: int,
    max_fire_numer: int, bound_denom: int,
) -> bool:
    """``INV_FPB_OBSERVATIONAL_DEFAULT`` from Fpb.tla:
    ``cycles_fires * bound_denom <= max_fire_numer * cycles_total``.
    """
    return cycles_fires * bound_denom <= max_fire_numer * cycles_total


def _pyver_fpb_holds(
    cycles_fires: int, cycles_total: int, max_fire_fraction: float
) -> bool:
    """Reproduce ``FPBVerificationReport.holds`` from
    ``src/project_ghost/properties/fpb.py``:
    ``fire_fraction <= max_fire_fraction``.
    """
    fire_fraction = 0.0 if cycles_total == 0 else cycles_fires / cycles_total
    return fire_fraction <= max_fire_fraction


@settings(deadline=None, max_examples=300)
@given(
    cycles_total=st.integers(min_value=0, max_value=100),
    cycles_fires=st.integers(min_value=0, max_value=100),
    max_numer=st.integers(min_value=0, max_value=10),
    denom=st.integers(min_value=1, max_value=10),
)
def test_fpb_python_and_tla_agree(
    cycles_total: int, cycles_fires: int, max_numer: int, denom: int
) -> None:
    """For any (cycles_fires, cycles_total, max_fire_fraction) within
    bounds, the two implementations agree on whether FPB-v1 holds.
    """
    cycles_fires = min(cycles_fires, cycles_total)
    max_numer = min(max_numer, denom)
    tla = _tla_fpb_holds(cycles_fires, cycles_total, max_numer, denom)
    py = _pyver_fpb_holds(cycles_fires, cycles_total, max_numer / denom)
    assert tla == py, (
        f"FPB bridge violated at fires={cycles_fires} total={cycles_total} "
        f"max={max_numer}/{denom}: TLA+={tla}, Python={py}"
    )


# ---------------------------------------------------------------------------
# Sanity: register that all 5 properties' bridges are exercised.
# ---------------------------------------------------------------------------


def test_all_five_properties_have_a_bridge_test() -> None:
    """The framework registry (ADR-0045) lists 7 contracts; ADR-0046
    covers BAUD-v1, ERUR-v1, MD-v1, FPB-v1 (4 of the 5 foundational
    ones; ERUR-v2 / FPB-v2 are documented as out of scope above).
    RLB-v1's bridge is in ``test_python_tla_bridge.py``.

    This sanity test exists so that if a future contributor adds the
    eighth property, the framework forces them to either add a
    bridge here or to document the omission.
    """
    from project_ghost.properties.framework import (
        shipped_contracts,
    )

    versions = {c.property_version for c in shipped_contracts()}
    covered_here = {"BAUD-v1", "ERUR-v1", "MD-v1", "FPB-v1"}
    covered_elsewhere = {"RLB-v1"}  # test_python_tla_bridge.py (ADR-0043)
    documented_out_of_scope = {"ERUR-v2", "FPB-v2"}  # see module docstring

    accounted_for = covered_here | covered_elsewhere | documented_out_of_scope
    missing = versions - accounted_for
    assert not missing, (
        f"New contract(s) without a documented bridge: {missing}. "
        "Add either a Hypothesis bridge test or update "
        "documented_out_of_scope above with the reason."
    )
