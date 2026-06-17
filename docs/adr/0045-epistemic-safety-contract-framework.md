# ADR-0045 — Epistemic Safety Contract framework

## Status

Accepted (v0.2.5).

Formalises paper §3's property class as a Python ``Protocol``
plus a registry of the seven shipped contracts (BAUD-v1,
ERUR-v1, ERUR-v2, MD-v1, RLB-v1, FPB-v1, FPB-v2). Does **not**
deprecate or replace any per-property ADR (0031-0035, 0039,
0040, 0041); it sits on top of them and makes their shared
recipe machine-checkable.

## Context

The five (now seven) properties Project Ghost ships were each
introduced by an ADR (0031-0035 for the original five, 0040 for
ERUR-v2, 0039/0041 for FPB-v2) with the same structural recipe:

- A **property version string** (e.g. ``"BAUD-v1"``).
- A **scope statement**: what the property claims, what it
  explicitly does NOT claim, and which other properties it
  depends on.
- A **precondition** + **postcondition** pair, stated formally
  in the ADR.
- A **pure-function verifier** that consumes an MCAP and emits
  a typed report.
- A **Hypothesis property test** pinning the verifier's
  invariants.

Until v0.2.5 the recipe was implicit. Every new ADR
re-derived it from the previous ones; a future contributor
adding the eighth property would re-derive it again. The paper
§3 cited "the property class" but had no single class
definition to point at.

v0.2.5 closes that gap. The recipe becomes a Python
``Protocol`` (:class:`EpistemicSafetyContract`) plus a
machine-readable registry of all shipped contracts
(:mod:`project_ghost.properties.framework`). The paper's "five
contracts we ship" rhetorical move is now a concrete enumerable
list. CI, tooling, and external integrations all read from the
same registry.

## Decision

### 1. `EpistemicSafetyContract` Protocol

Defined in
[`src/project_ghost/properties/contract.py`](../../src/project_ghost/properties/contract.py).
A property conforms to this Protocol iff it carries:

- ``property_version: str`` — round-trips with the verifier
  report's ``property_version`` field.
- ``scope: ScopeStatement`` — the "what is claimed / not
  claimed / depends on" block lifted to data.
- ``verifier: Callable[..., VerificationReport]`` — the pure
  function from the property's module.

Conformance is **structural** (Python's runtime-checkable
Protocol), not nominal: no subclassing required, no metaclass,
no decorators. A new contract conforms by being a dataclass with
the right field names and types.

### 2. `ScopeStatement` dataclass

Lifts the "Scope" section every ADR carries to machine-readable
data:

- ``claims: tuple[str, ...]`` — what the property formally
  asserts (non-empty, enforced by ``__post_init__``).
- ``does_not_claim: tuple[str, ...]`` — explicit honest caveats
  (non-empty, enforced).
- ``dependencies: tuple[str, ...]`` — property version strings
  this property's precondition refers to (e.g. FPB-v1's scope
  includes ``"BAUD-v1"``).

Non-empty enforcement on both ``claims`` and ``does_not_claim``
is a load-bearing invariant: it makes it structurally impossible
to register a contract that pretends to be unboundedly strong
(no claim) or unboundedly bold (no caveats).

### 3. Registry of the seven shipped contracts

[`src/project_ghost/properties/framework.py`](../../src/project_ghost/properties/framework.py)
is the **single point of truth** for the question "which
properties does Project Ghost ship?". It contains seven
``register_contract(...)`` calls, one per shipped property; the
scope statements are lifted from each ADR's Scope section.

Registry API:

- ``shipped_contracts() -> tuple[ContractRecord, ...]`` —
  enumerate all contracts in version-string order.
- ``get_contract(version: str) -> ContractRecord`` — look up by
  property version.
- ``register_contract(record)`` — idempotent registration;
  raises on conflicting redefinition (same version, different
  scope or verifier).

### 4. Framework-level invariants

[`tests/properties/test_framework_invariants.py`](../../tests/properties/test_framework_invariants.py)
pins eight invariants (~26 test cases after parametrisation):

- **Completeness**: the registry contains exactly the seven
  expected versions; adding the eighth requires updating both
  ``framework.py`` and the test's expected set.
- **Determinism**: ``list_contracts()`` returns
  version-string-sorted records.
- **Scope non-emptiness**: every contract has at least one
  claim and one does-not-claim bullet.
- **Verifier surface**: every verifier's first positional
  parameter is named ``mcap_path``.
- **Dependency closure**: every dependency string references a
  registered contract.
- **Protocol conformance**: every record satisfies
  ``EpistemicSafetyContract`` per ``isinstance``.
- **Idempotence**: re-importing the framework module does not
  conflict with previously-registered contracts.
- **Version-string uniqueness**: no two contracts share a
  version string.

These pin the framework's *guarantees*, not per-property
assertions. A future regression in any of them fails CI before
the divergence ships.

## Scope — what this ADR claims and does NOT claim

**This ADR claims (v0.2.5):**

- The framework is a Python Protocol + registry that captures
  the recipe every shipped contract follows.
- Adding the eighth contract requires only adding one
  ``register_contract(...)`` call plus a ``ScopeStatement``
  with non-empty claims and does-not-claim tuples.
- The eight framework invariants above are mechanically
  enforced on every push.

**This ADR does NOT claim:**

- That every property in the literature fits this framework.
  The framework captures *Project Ghost's* recipe (epistemic
  safety contracts under the ADR-0036-style precondition +
  postcondition + verifier triad); other property classes
  (STL formulas, MITL formulas, OPL contracts) are out of
  scope.
- That the framework adds new verification *guarantees*. It
  documents and structures what the per-property ADRs already
  guarantee; the property tests and verifiers do the actual
  work.
- That the framework subsumes the per-property ADRs. ADRs
  remain authoritative for their property's semantics; the
  framework lifts the *shared* skeleton.

## Verification plan

The framework's own correctness is verified by
``test_framework_invariants.py``. Per-property verification
continues to be the responsibility of the existing per-property
tests (`test_baud_property.py`, `test_erur_property.py`,
`test_fpb_v2_property.py`, etc.) — unchanged in v0.2.5.

A future amendment (ADR-0046 candidate) integrates the
framework with the bridge conformance template (ADR-0043),
giving every shipped property a mechanical Python↔TLA+ bridge,
not just RLB-v1.

## What this ADR does NOT close

- **Conformance tests for the other six properties.** ADR-0043
  ships the RLB-v1 bridge as proof of concept; extending it to
  BAUD/ERUR/MD/FPB is the ADR-0046 follow-up.
- **TLA+ specs for FPB-v1 and FPB-v2 unbounded.** Out of scope
  for v0.2.5; paper §10 future work item.
- **An external auditor's view of the framework.** v0.2.5 ships
  it; external review would be the natural next round.

## Alternatives considered

1. **Abstract base class instead of Protocol.** Rejected:
   subclassing is heavier and forces every contract to
   inherit; structural conformance via Protocol is lighter and
   matches the existing pattern (the verifier dataclasses are
   not inherited from a common base either).
2. **Decorator-based registration.** Considered:
   ``@register_contract`` on the verifier function. Rejected
   for v0.2.5: the verifier functions are loadable as
   module-level objects without side effects on import; the
   explicit ``register_contract`` call site is easier to
   audit. Decorators may come in a future amendment.
3. **Auto-discovery of contracts.** Considered:
   ``importlib`` walk over ``project_ghost.properties.*``.
   Rejected: implicit registration is fragile under refactor.
   Explicit registration is one extra line per property and
   makes the registry self-documenting.
4. **Skip the framework; keep the recipe implicit.** Rejected:
   the paper §3 rhetorical move ("five contracts we ship") has
   no concrete class to point at without this ADR. Adding the
   class makes the paper's claim machine-checkable.

## References

- Protocol + registry:
  [`src/project_ghost/properties/contract.py`](../../src/project_ghost/properties/contract.py)
- Framework registrations:
  [`src/project_ghost/properties/framework.py`](../../src/project_ghost/properties/framework.py)
- Framework invariant tests:
  [`tests/properties/test_framework_invariants.py`](../../tests/properties/test_framework_invariants.py)
- Per-property ADRs: 0031 (BAUD), 0032 (ERUR), 0033 (MD), 0034
  (RLB), 0035 (FPB), 0039 (FPB-v2), 0040 (ERUR-v2)
- Paper §3 (the property class), §3.5 (FPB-v1/v2 side by
  side), §10 (future work)
