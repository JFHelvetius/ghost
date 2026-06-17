# ADR-0043 — Python ↔ TLA+ bridge by mechanical conformance

## Status

Accepted (v0.2.5).

Closes paper section 9's previously-open caveat *"Python ↔ TLA+
bridge by inspection"* with a mechanical Hypothesis-checked test.

## Context

Paper section 9 has carried, since v0.2.0, an honest caveat:

> **Python ↔ TLA+ bridge by inspection.** A future divergence
> between the Python policy and the TLA+ definition could silently
> weaken the claim. Mitigation: review and re-run TLC on every
> change to the reference calibrator or decision policy.

The mitigation is real but workflow-bound. Human review can miss
a sign flip in a sliding-window count, or a transposition between
`peak + W − 1` and `peak − W + 1`. Re-running TLC catches
abstract-model divergences but not Python-code divergences — TLC
operates on the TLA+ spec, not on the Python verifier.

What is *not* needed is mechanical-theorem-proving the Python
implementation. That is a different problem (program verification
of a Python codebase, currently a research frontier). What *is*
tractable is **mechanical conformance**: re-implement the TLA+
semantics in Python, re-implement the verifier-core semantics in
Python from scratch (not via shared code), and assert
Hypothesis-generated traces produce the same verdict under both.

If the production verifier's logic ever drifts from the TLA+ spec,
one or both re-implementations will diverge from each other on
some trace Hypothesis generates, and the test fails. The bridge
becomes mechanically self-policing on every push.

This ADR records that approach for RLB-v1; the same template
applies to the other four properties as a follow-up.

## Decision

### 1. Conformance test surface

`tests/properties/test_python_tla_bridge.py` ships two pure
Python functions, written from the respective sources without
sharing code:

- `_tla_semantics_invariant_holds(outcomes, W)` — re-implements
  the `Rlb.tla` state machine literally
  (window, dirty_run, peak_in_run, phase, CountDirty, WindowUpdate,
  AccumulateDirty/EndDrift/RecoverClean, INV_RLB). Written from
  the TLA+ spec, not from the verifier.
- `_python_verifier_invariant_holds(counts, W)` — re-implements
  the core loop of `verify_rlb` (`rlb.py` lines ~225-252)
  without MCAP I/O. Written from the Python verifier, not from
  the TLA+ spec.

A third helper, `_outcomes_to_counts`, applies `CountDirty(window)`
after each `WindowUpdate(outcome)` to translate an outcome
sequence into the count sequence the verifier consumes. This
function is the only shared bridge step between the two
re-implementations; both consume the same `(window, count)`
mapping and the verdicts are independently asserted on the same
ground truth.

### 2. Hypothesis-generated trace coverage

The test ships three Hypothesis property tests plus four
parametrised paper-example cases:

- `test_python_and_tla_agree_on_accumulating_then_clean`
  (300 examples): sweeps `W ∈ [1, 16]`, `N ∈ [0, 16]`,
  `k ∈ [0, 32]` of the consecutive-drift-then-clean trace
  family that RLB-v1 is stated over. Covers transient
  (`N ≤ W`), saturated (`N = W`), and over-saturated
  (`N > W`) regimes.
- `test_python_and_tla_agree_on_arbitrary_mixed_traces`
  (300 examples): generates arbitrary `{DIRTY, CLEAN}`
  sequences. The stronger property: agreement on traces RLB-v1
  is *not* stated over (mixed dirty/clean episodes), where the
  bound legitimately may not apply. Both semantics handle
  these without crashing; the test pins they *report the same
  verdict*.
- `test_python_and_tla_agree_on_paper_examples` (4 cases):
  pinned regression checks on the concrete `(W, N, k)` tuples
  the paper section 6.3 walks through, so a reviewer can trace
  the math by hand and confirm both semantics agree.

The two property tests together generate ~600 Hypothesis traces
per run. The test suite runs in under one second; CI executes it
on every push.

### 3. Scope — what this ADR claims and does NOT claim

**This ADR claims (v0.2.5):**

- The Python verifier core and the TLA+ Rlb.tla state machine
  agree on the `INV_RLB` verdict for every trace Hypothesis can
  synthesise within the documented bounds (`W ≤ 16`, trace length
  ≤ 40).
- The agreement is mechanically self-policing. A future refactor
  of either the verifier core or the TLA+ spec that drifts from
  the other will fail the test before the divergence ships.

**This ADR does NOT claim:**

- The bridge from the *production verifier* (the MCAP I/O path
  around the core) to the verifier core itself. The MCAP I/O is
  mechanically verified separately by replay-determinism tests
  under ADR-0030.
- The bridge from the *production producer* (the closed-loop
  pipeline) to the property semantics. That is the section 8.2
  discrimination matrix's job — and is itself mechanically
  exercised on real PX4 ULogs by ADR-0037 / paper section 8.8.
- A bridge for the other four properties (BAUD, ERUR, MD, FPB).
  This ADR ships the *template*; extending it is a follow-up
  per-property task. The test file is structured to make the
  extension obvious (one function pair per property).

## Verification plan

The conformance test is the verification. It is fast (< 1 s),
runs on every push as part of the `tests/properties/` suite, and
catches any future divergence between the two artefacts.

A future follow-up extends the template to BAUD-v1, ERUR-v1,
MD-v1, and FPB-v1/v2. The BaudErur.tla spec already defines the
state machine for the first three; FPB-v1/v2 use a simpler
counter automaton that should be straightforward to re-implement.

## What this ADR does NOT close

- **The other four bridges.** ADR-0043 ships the RLB-v1 bridge
  as proof of concept; BAUD/ERUR/MD/FPB extensions are tracked
  as follow-up ADRs.
- **The bridge from the production pipeline to the abstract
  trace family.** The TLA+ trace family is a clean abstraction
  of what the production pipeline emits; the abstraction itself
  is a design decision. A future tighter bridge would re-derive
  the trace family from the production telemetry channels.

## Alternatives considered

1. **Mechanical theorem proving the Python verifier.** Out of
   scope: there is no widely-adopted Python proof system. Pivot
   options (port verifier to a verified language; use Z3/Lean
   bindings) are research projects, not paper artefacts.
2. **Property tests on a single re-implementation.** Rejected:
   that pattern proves the verifier matches itself. The
   conformance approach pins the verifier against the *spec* by
   writing each side independently from its source artefact.
3. **Continue with the "by inspection" caveat.** Rejected: the
   caveat had been open for two rounds and was the highest-
   value, lowest-effort gap in section 9. Closing it with the
   conformance test ships in this ADR.
4. **Generate the verifier core from the TLA+ spec.** Considered:
   could eliminate the duplication. Rejected for v0.2.5: code
   generation is its own engineering project, and the two
   re-implementations are small (< 40 lines each). The
   conformance test catches drift between them; that is what we
   need.

## References

- Test surface:
  [`tests/properties/test_python_tla_bridge.py`](../../tests/properties/test_python_tla_bridge.py)
- Verifier under test:
  [`src/project_ghost/properties/rlb.py`](../../src/project_ghost/properties/rlb.py)
- TLA+ spec under test:
  [`docs/proofs/Rlb.tla`](../proofs/Rlb.tla)
- Bounded TLC ADR: [`docs/adr/0036-tla-plus-mechanical-verification-of-baud-erur.md`](0036-tla-plus-mechanical-verification-of-baud-erur.md)
- Unbounded RLB-v1 evidence ADR:
  [`docs/adr/0038-rlb-unbounded-verification.md`](0038-rlb-unbounded-verification.md)
- Paper §9 (the caveat this ADR closes)
