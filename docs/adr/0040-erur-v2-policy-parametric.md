# ADR-0040: ERUR-v2 — policy-parametric variant of ERUR-v1

- **Status**: Accepted (2026-06-15)
- **Driver**: paper §3 (epistemic safety contracts), §3.X (ERUR-v2),
  §6 (Python↔TLA+ bridge scope)
- **Module**: `src/project_ghost/properties/erur_v2.py`
- **Tests**: `tests/properties/test_erur_v2_property.py`
- **Supersedes / depends on**: ADR-0032 (ERUR-v1), ADR-0045 (framework)
- **Related**: paper §1.2 (C2), §3.X (the ERUR family),
  ADR-0046 (Python↔TLA+ bridge scope decisions)

## Context

ERUR-v1 (ADR-0032) is stated against the reference Mahalanobis
calibration policy: it asserts that whenever the
Mahalanobis-specific drift precondition does NOT fire and the raw
self-assessment is `KNOWN`, the adjusted level remains `KNOWN` and
the decision kind is `PROCEED`. It is the De Morgan complement of
BAUD-v1's drift conjunction over the same Mahalanobis predicate.

The reference implementation is good as a concrete proof of
concept but is a single-policy contract. A user who ships an
alternative calibrator (e.g. EWMA over the dirty indicator,
per-axis hysteresis, or a learned policy) does not get the ERUR-v1
verifier — the precondition the verifier expects is hard-coded to
Mahalanobis. Their downgrade policy needs its own bespoke ERUR
verifier, breaking the recipe.

The framework (ADR-0045) treats the property class as the unit of
reuse; it is incongruent to require a new property number per
policy when the property *semantics* are policy-agnostic. ERUR-v2
makes the policy a parameter of the contract.

## Decision

Introduce `verify_erur_v2(mcap_path, *, precondition_provider)`
where `precondition_provider` conforms to a
`DriftPreconditionProvider` Protocol:

```python
class DriftPreconditionProvider(Protocol):
    def fires(self, history: CalibrationHistory) -> bool: ...
```

The contract's claim is identical to ERUR-v1's postcondition
(adjusted=`KNOWN` and decision=`PROCEED` when the precondition does
not fire and raw=`KNOWN`), but the precondition itself is supplied
by the caller via the Protocol implementation. Ghost ships an
implementation for the reference Mahalanobis policy
(`MahalanobisDriftPredicateProvider`); third parties supply their
own.

The Protocol is runtime-checkable; the verifier validates the
provider's surface at call time and raises a `TypeError` with a
specific message ("supplied object does not implement
DriftPreconditionProvider; expected `fires(history) -> bool`") if
the surface does not match.

## Scope

- Generalises ERUR-v1's statement to a *policy family*, not a single
  policy. ERUR-v1's verifier remains shipped unchanged for callers
  that use the Mahalanobis reference policy.
- Does NOT validate that the supplied policy's precondition is
  correct: the implementer is responsible for ensuring `fires`
  returns the right boolean for their policy. A Hypothesis test on
  the implementer's side is the recommended sanity check.
- Does NOT subsume ERUR-v1. The v1 verifier remains the canonical
  shipped surface; v2 is the parametric extension for alternative
  policies.
- Does NOT cover the Python↔TLA+ bridge for ERUR-v2 (paper §9.2):
  bridging a policy-parametric contract to TLA+ requires
  re-implementing each policy's predicate inside TLA+, which is out
  of scope for the structural conformance harness used by ADR-0046.
  The two ERUR-v2 conformance gaps (over the Mahalanobis policy and
  over the alternatives) are honestly documented in §9.2.

## Honest caveats

- ERUR-v2 reduces to ERUR-v1 when `precondition_provider` is the
  Mahalanobis reference; the test suite exercises this equivalence
  on the bundled reference MCAP.
- A pathological provider (e.g. one that always returns `False`)
  trivially satisfies the postcondition; ERUR-v2 does not detect
  this. The recommended workflow is: the operator pins their
  policy's precondition in their own ADR and supplies a verifier
  that uses it, allowing third-party scrutiny of the
  precondition's correctness independently of ERUR-v2.
- ERUR-v2 is structurally separate from ERUR-v1; an ERUR-v2 verdict
  cannot be mistaken for an ERUR-v1 verdict because the
  `property_version` field of the verifier report is distinct
  (`"ERUR-v2"`).

## Status of evidence

- Hypothesis-checked property test in
  `tests/properties/test_erur_v2_property.py` runs the v2 verifier
  with both the Mahalanobis reference provider and an
  intentionally-pathological provider, asserting expected outcomes
  per the contract's claim.
- The framework registry (ADR-0045) lists ERUR-v2 as a shipped
  contract; the registry's invariants pin its scope statement on
  every CI run.
