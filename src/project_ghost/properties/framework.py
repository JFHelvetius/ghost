"""ADR-0045 -- Framework registry: the seven shipped Epistemic Safety Contracts.

This module is the single point of truth for "which properties does
Project Ghost ship?". The list lives here, not in the paper, not in
the per-property ADRs, not in CI configuration. Tools that want to
enumerate the shipped properties (audit dashboards, CI matrices,
external integrations) read from here.

Each registration ships:

- ``property_version``: the string identifier
  (e.g. ``"BAUD-v1"``). Must round-trip with the corresponding
  verifier report's ``property_version`` field.
- ``scope``: the :class:`ScopeStatement` lifted from the
  property's ADR.
- ``verifier``: the public ``verify_*`` callable from the
  property's module.

Adding the eighth property requires only adding one
``register_contract(...)`` call below; the framework guarantees
the recipe is consistent.
"""

from __future__ import annotations

from project_ghost.properties.baud import BAUD_PROPERTY_VERSION, verify_baud
from project_ghost.properties.contract import (
    ContractRecord,
    ScopeStatement,
    list_contracts,
    register_contract,
)
from project_ghost.properties.erur import ERUR_PROPERTY_VERSION, verify_erur
from project_ghost.properties.erur_v2 import (
    ERUR_V2_PROPERTY_VERSION,
    verify_erur_v2,
)
from project_ghost.properties.fpb import FPB_PROPERTY_VERSION, verify_fpb
from project_ghost.properties.fpb_v2 import (
    FPB_V2_PROPERTY_VERSION,
    verify_fpb_v2,
)
from project_ghost.properties.md import MD_PROPERTY_VERSION, verify_md
from project_ghost.properties.rlb import RLB_PROPERTY_VERSION, verify_rlb

# ---------------------------------------------------------------------------
# Scope statements (lifted from each property's ADR).
# ---------------------------------------------------------------------------

_BAUD_V1_SCOPE = ScopeStatement(
    claims=(
        "Whenever the calibration history's drift precondition fires "
        "(>= K outcomes beyond 3-sigma or worse within the last W cycles, "
        "and >= M cycles observed), the calibrator downgrades the assessment "
        "level, the decision policy emits a non-PROCEED kind, and the "
        "actuator command's reason set is contained in the safe-reason set.",
        "All three postconditions hold deterministically per cycle given "
        "the captured MCAP; verification is a pure function over the MCAP.",
    ),
    does_not_claim=(
        "BAUD-v1 does not assert anything about cycles where the "
        "precondition does not fire (a no-drift cycle may PROCEED).",
        "BAUD-v1 does not bound the false-positive rate of its "
        "precondition; that is the scope of FPB-v1 / FPB-v2.",
        "BAUD-v1 is conditional on the reference calibration + decision + "
        "actuation policies; alternative policies need their own contracts.",
    ),
    dependencies=(),
)

_ERUR_V1_SCOPE = ScopeStatement(
    claims=(
        "Whenever the drift precondition does NOT fire and the raw "
        "assessment is KNOWN, the adjusted level remains KNOWN and the "
        "decision kind is PROCEED.",
        "The De Morgan complement of BAUD-v1's drift conjunction; "
        "together with BAUD-v1 forms the partition theorem on the "
        "raw = KNOWN slice of the state space.",
    ),
    does_not_claim=(
        "ERUR-v1 does not claim anything when the raw assessment is "
        "UNCERTAIN or UNKNOWN; the decision policy is free to choose.",
        "ERUR-v1 is conditional on the reference Mahalanobis downgrade "
        "policy; alternative drift detectors need ERUR-v2.",
    ),
    dependencies=("BAUD-v1",),
)

_ERUR_V2_SCOPE = ScopeStatement(
    claims=(
        "Same postcondition as ERUR-v1 (adjusted = KNOWN, decision = "
        "PROCEED), but parameterised over an arbitrary "
        "DriftPreconditionProvider Protocol implementation rather than "
        "the Mahalanobis-specific predicate.",
        "Lifts the property from a single-policy contract to a "
        "policy-family contract: any calibration policy that implements "
        "the Protocol gets a verifier without bespoke work.",
    ),
    does_not_claim=(
        "ERUR-v2 does not validate that the supplied policy's "
        "precondition is correct; that is the implementer's "
        "responsibility (and a Hypothesis test target).",
        "ERUR-v2 does not subsume ERUR-v1: the v1 verifier remains "
        "shipped for callers using the Mahalanobis reference path.",
    ),
    dependencies=("BAUD-v1",),
)

_MD_V1_SCOPE = ScopeStatement(
    claims=(
        "Under the reference Mahalanobis calibration policy, the adjusted "
        "level is never more confident than the raw level. Confidence "
        "levels are ordered KNOWN < UNCERTAIN < UNKNOWN.",
        "Structural (not drift-conditional) -- holds on every cycle regardless of history shape.",
    ),
    does_not_claim=(
        "MD-v1 does not specify when downgrades occur; only that upgrades are prohibited.",
        "MD-v1 is conditional on the reference calibrator; an "
        "alternative calibrator with multi-step downgrades or "
        "confidence-inflation behaviour needs its own contract.",
    ),
    dependencies=(),
)

_RLB_V1_SCOPE = ScopeStatement(
    claims=(
        "For any consecutive-drift interval of N <= W DIRTY outcomes "
        "followed by CLEAN outcomes, the recovery latency satisfies "
        "L <= peak + W - 1 where peak = N and W is the calibrator's "
        "max_history. Proved by structural induction in the hand proof "
        "and Lean 4 (Lemma 4 pending) and exhaustively in TLC at "
        "W in {4, 8, 16}.",
        "The bound is tight: the smoke harness exhibits L = peak + W - 1 with peak = 7 and W = 32.",
    ),
    does_not_claim=(
        "RLB-v1 does not apply to mixed dirty/clean traces -- only to "
        "the consecutive-drift-then-clean trace family. Mixed traces "
        "are out of scope by construction.",
        "RLB-v1's unbounded statement is mechanically verified in TLC "
        "at three scales and via Lean 4 reduced to a single sorry "
        "(Lemma 4); the SMT-checked TLAPS proof remains future work.",
    ),
    dependencies=("BAUD-v1",),
)

_FPB_V1_SCOPE = ScopeStatement(
    claims=(
        "Reports the empirical fire fraction of BAUD-v1's precondition "
        "over the captured MCAP (cycles where precondition fires divided "
        "by cycles with calibrated self-assessment).",
        "Compares the empirical fraction against a caller-supplied "
        "max_fire_fraction; HOLDS iff observed <= bound.",
    ),
    does_not_claim=(
        "FPB-v1 does not estimate the underlying firing probability; "
        "it is a point estimate, statistically meaningless on small "
        "samples. For a statistical bound use FPB-v2.",
        "FPB-v1 does not adjust for multiple-testing across parameter sweeps.",
        "FPB-v1 does not distinguish true positives from false "
        "positives -- the verifier cannot tell from the MCAP alone.",
    ),
    dependencies=("BAUD-v1",),
)

_FPB_V2_SCOPE = ScopeStatement(
    claims=(
        "Computes a one-sided confidence upper bound on the TRUE firing "
        "probability under one of two closed-form estimators: Hoeffding "
        "(distribution-free, stdlib-only) or Clopper-Pearson (exact "
        "binomial, requires SciPy). HOLDS iff upper bound <= "
        "max_fire_probability.",
        "Small-sample correctness: a tight regression gate on n = 10 "
        "cycles correctly fails to certify; a release with n = 10 000 "
        "earns a tight gate.",
    ),
    does_not_claim=(
        "FPB-v2 does not validate the iid Bernoulli assumption "
        "Clopper-Pearson invokes; the verifier trusts the caller's "
        "model choice.",
        "FPB-v2 does not adjust for multiple-testing.",
        "FPB-v2 reports only a one-sided upper bound; Wilson-score "
        "and two-sided variants are deferred amendments.",
    ),
    dependencies=("BAUD-v1",),
)


# ---------------------------------------------------------------------------
# Registrations.
# ---------------------------------------------------------------------------

BAUD_V1 = register_contract(
    ContractRecord(
        property_version=BAUD_PROPERTY_VERSION,
        scope=_BAUD_V1_SCOPE,
        verifier=verify_baud,
    )
)

ERUR_V1 = register_contract(
    ContractRecord(
        property_version=ERUR_PROPERTY_VERSION,
        scope=_ERUR_V1_SCOPE,
        verifier=verify_erur,
    )
)

ERUR_V2 = register_contract(
    ContractRecord(
        property_version=ERUR_V2_PROPERTY_VERSION,
        scope=_ERUR_V2_SCOPE,
        verifier=verify_erur_v2,
    )
)

MD_V1 = register_contract(
    ContractRecord(
        property_version=MD_PROPERTY_VERSION,
        scope=_MD_V1_SCOPE,
        verifier=verify_md,
    )
)

RLB_V1 = register_contract(
    ContractRecord(
        property_version=RLB_PROPERTY_VERSION,
        scope=_RLB_V1_SCOPE,
        verifier=verify_rlb,
    )
)

FPB_V1 = register_contract(
    ContractRecord(
        property_version=FPB_PROPERTY_VERSION,
        scope=_FPB_V1_SCOPE,
        verifier=verify_fpb,
    )
)

FPB_V2 = register_contract(
    ContractRecord(
        property_version=FPB_V2_PROPERTY_VERSION,
        scope=_FPB_V2_SCOPE,
        verifier=verify_fpb_v2,
    )
)


def shipped_contracts() -> tuple[ContractRecord, ...]:
    """Return all v0.2.5-shipped contracts in version order.

    Wraps :func:`list_contracts` for callers that want a stable
    entry point (the underlying registry is also a candidate
    point of failure if a future contributor breaks its
    semantics)."""
    return list_contracts()


__all__ = [
    "BAUD_V1",
    "ERUR_V1",
    "ERUR_V2",
    "FPB_V1",
    "FPB_V2",
    "MD_V1",
    "RLB_V1",
    "shipped_contracts",
]
