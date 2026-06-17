# ADR-0046 — Bridge conformance extension to BAUD/ERUR/MD/FPB

## Status

Accepted (v0.2.5 round 32).

Extends ADR-0043's RLB-v1 bridge conformance template to the
remaining four foundational contracts: BAUD-v1, ERUR-v1, MD-v1, and
FPB-v1. ERUR-v2 and FPB-v2 are documented as **out of scope** with
reasons (see §"Scope" below).

## Context

ADR-0043 (v0.2.5 round 28) closed paper §9's previously-open caveat
*"Python ↔ TLA+ bridge by inspection"* with a Hypothesis-checked
mechanical conformance test for RLB-v1. The template:

- A pure Python re-implementation of the TLA+ state machine,
  written from `Rlb.tla` without sharing code with the verifier.
- A pure Python re-implementation of the verifier core, written
  from `properties/rlb.py` without sharing code with the TLA+
  re-implementation.
- A Hypothesis property test asserts the two agree on `INV_RLB`
  for every trace within bounds.

The ADR-0043 follow-up identified extending the template to the
other six contracts as ADR-0046. Round 32 closes it for the four
foundational ones; ERUR-v2 and FPB-v2 are documented out of scope.

## Decision

### 1. New test file

[`tests/properties/test_python_tla_bridge_full.py`](../../tests/properties/test_python_tla_bridge_full.py)
ships seven Hypothesis property tests (~1700 random traces total
per run, executes in under 2 seconds):

- `test_baud_precondition_python_and_tla_agree`: BAUD-v1
  precondition fires under both implementations for the same
  traces. 200 examples.
- `test_erur_precondition_python_and_tla_agree`: ERUR-v1
  precondition fires under both implementations. 200 examples.
- `test_partition_holds_under_known_raw`: BAUD ⊕ ERUR partition
  holds at the conformance layer when `raw = KNOWN`. 300 examples.
  (Note: the abstract partition theorem is already mechanically
  proven in Lean 4 via `PartitionTheorem.lean`; this test pins
  that the Python implementations of both preconditions
  respect the same partition.)
- `test_md_calibrate_python_and_tla_agree`: the reference
  Mahalanobis calibrator produces the same adjusted level under
  both implementations. 300 examples.
- `test_md_invariant_no_inflation`: MD-v1's
  `LevelNum(adjusted) >= LevelNum(raw)` holds at the conformance
  layer for every reachable state. 300 examples.
- `test_fpb_python_and_tla_agree`: FPB-v1's
  `cycles_fires * bound_denom <= max_fire_numer * cycles_total`
  matches the verifier's
  `fire_fraction <= max_fire_fraction` semantics. 300 examples.
- `test_all_five_properties_have_a_bridge_test`: framework-level
  sanity check that no future contract is added without a bridge
  test or a documented out-of-scope justification.

### 2. The two-re-implementation discipline

Each property has two re-implementations in the test file:

- `_tla_<prop>`: written from the TLA+ spec
  (`BaudErur.tla` for BAUD/ERUR/MD; `Fpb.tla` for FPB).
- `_pyver_<prop>`: written from the verifier source
  (`properties/<prop>.py`).

The two are kept syntactically distinct (no shared helpers
beyond `_count_dirty` and `_window_update`, which encode shared
TLA+ definitions). A future divergence between the verifier and
the TLA+ spec is caught by Hypothesis at test time.

### 3. Sanity-check enforcement

The `test_all_five_properties_have_a_bridge_test` test cross-checks
the registered contracts against the bridge-test inventory. If a
future contributor adds the eighth contract and forgets to either
extend a bridge test or document the omission, this test fails.

## Scope — what this ADR claims and does NOT claim

**This ADR claims (v0.2.5 round 32):**

- BAUD-v1, ERUR-v1, MD-v1, FPB-v1 each have a mechanical Python
  ↔ TLA+ bridge conformance test.
- The partition theorem is pinned at the conformance layer
  (independent of Lean 4's abstract proof).
- The MD-v1 no-inflation invariant is pinned at the conformance
  layer.
- The framework registry is sanity-checked against the bridge
  inventory.

**This ADR does NOT claim (out of scope):**

- **ERUR-v2 bridge.** ERUR-v2 is parametric over a
  `DriftPreconditionProvider` Protocol; conformance there would
  require re-implementing each policy's predicate from its
  source. ERUR-v1 covers the Mahalanobis-specific path. A future
  ADR may add per-policy ERUR-v2 bridges.
- **FPB-v2 bridge.** FPB-v2's statistical bound is already
  pinned by `test_fpb_v2_property.py` (10 Hypothesis properties
  on the closed-form math: P1 sound, P2 Hoeffding dominates CP,
  P3 monotone in p_hat, P4 decreasing in n, P5 convergence,
  P6 small-sample correctness). Duplicating that here would add
  no new evidence.
- **End-to-end production-pipeline bridge.** The MCAP I/O around
  the verifier core, the closed-loop pipeline that produces
  MCAPs, and the discrimination experiment are tested
  separately (ADR-0030 replay determinism, paper §8.2 violation
  matrix, paper §8.8 discrimination experiment). This ADR
  closes the *verifier-core ↔ TLA+ spec* bridge, not the
  *production-pipeline ↔ property* bridge.

## Verification plan

The seven Hypothesis property tests run on every push as part of
`tests/properties/`. CI executes them on Ubuntu + Windows with
Python 3.11 + 3.12. Test runtime is well under 2 seconds on a
modern laptop.

A future divergence between the verifier core and the TLA+ spec
fails one of the seven tests before the divergence ships. The
sanity-check test catches a future contributor adding the eighth
contract without a bridge.

## What this ADR does NOT close

- **ERUR-v2 bridge** (see §Scope; deferred).
- **FPB-v2 bridge** (see §Scope; redundant with existing
  `test_fpb_v2_property.py`).
- **The end-to-end pipeline bridge** (out of ADR-0046's scope;
  covered by ADR-0030 + paper §8.2 + paper §8.8).

## Alternatives considered

1. **Ship a bridge for all 7 contracts including ERUR-v2 and
   FPB-v2.** Considered; rejected because ERUR-v2's parameterisation
   would force per-policy bridges (potentially many) and FPB-v2's
   closed-form math is already pinned in `test_fpb_v2_property.py`.
   Documenting them as out of scope is cleaner and avoids
   duplicating test coverage.
2. **Ship a single mega-bridge test that runs all properties at
   once on a shared trace.** Rejected: per-property tests give
   per-property failure messages and isolate divergences quickly.
3. **Defer the extension to a post-paper release.** Rejected: the
   paper §9 limitation explicitly listed "bridge for the other
   six contracts open under ADR-0046"; closing it before TOSEM
   submission improves the limitation disclosure and shows the
   framework is operationally complete.

## References

- ADR-0043 (RLB-v1 bridge, the template):
  [`docs/adr/0043-python-tla-bridge-conformance.md`](0043-python-tla-bridge-conformance.md)
- ADR-0036 (TLA+ mechanical verification of BAUD/ERUR):
  [`docs/adr/0036-tla-plus-mechanical-verification-of-baud-erur.md`](0036-tla-plus-mechanical-verification-of-baud-erur.md)
- ADR-0042 (Lean 4 mechanical proofs):
  [`docs/adr/0042-lean4-mechanical-proofs.md`](0042-lean4-mechanical-proofs.md)
- ADR-0045 (Epistemic Safety Contract framework + registry):
  [`docs/adr/0045-epistemic-safety-contract-framework.md`](0045-epistemic-safety-contract-framework.md)
- Test file:
  [`tests/properties/test_python_tla_bridge_full.py`](../../tests/properties/test_python_tla_bridge_full.py)
- RLB-v1 bridge:
  [`tests/properties/test_python_tla_bridge.py`](../../tests/properties/test_python_tla_bridge.py)
- Paper §9 (limitations), §10 (future work).
