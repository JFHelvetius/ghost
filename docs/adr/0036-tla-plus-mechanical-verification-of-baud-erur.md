# ADR-0036 — TLA+ Mechanical Verification of BAUD-v1 / ERUR-v1 / Partition

## Status

Accepted (2026-06-10). TLC verification confirmed green in CI on the
[``tla-plus`` job](https://github.com/JFHelvetius/ghost/actions/workflows/ci.yml)
of commit `aa6c804` and every commit after. All five invariants
(``INV_BAUD``, ``INV_ERUR``, ``INV_PARTITION``,
``INV_NO_INVENTED_CONFIDENCE``, ``INV_HISTORY_BOUND``) hold over the
full reachable state space of the abstract model at the bounded
constants ``M=2, K=1, W=3``.

## Context

ADRs 0031..0035 establish a property set verified by:

- **Pure-function verifiers** that walk a captured MCAP byte by byte
  and assert per-cycle postconditions hold whenever preconditions do.
- **Hypothesis-based property tests** that generate 200+ synthetic
  inputs per property and check the verifier returns ``holds``.
- **Inline self-evidence** in every reference closed-loop smoke.
- **Self-enforcing CI** that blocks merges when any property
  violates.

This is genuinely strong evidence — strong enough that the project
ships a CLI third parties can use to verify their own MCAPs. But it
shares a structural limitation with all property-based testing: it
proves the property holds on *the inputs the test generator
sampled*. It does not prove it holds *on all inputs*.

The next rung up the ladder of credibility is **mechanical
verification**: state precisely the property in a formalism that a
tool can check exhaustively over a finite abstract model. Two
options dominate this rung:

1. **Theorem proving** (Lean, Coq, Isabelle) — prove the property
   over the unbounded mathematical model. Extremely strong but
   labour-intensive; a real BAUD proof in Lean would be weeks of
   work.
2. **Explicit-state model checking** (TLA+ with TLC, Spin) — check
   the property exhaustively over a small bounded abstract model.
   Weaker than theorem proving (the abstract model is small) but
   tractable (hours, not weeks) and complementary to property
   tests.

ADR-0036 picks option 2 with TLA+ / TLC. The argument is leverage:
the property set is already heavily exercised at full scale by
property tests. What is missing is **exhaustive coverage of a small
abstract model**, which closes the corner cases that random sampling
might miss.

## Decision

### 1. Scope of the formal artifact

Three things, contained in `docs/proofs/BaudErur.tla` and verified
by `tlc BaudErur.tla -config BaudErur.cfg`:

- **`INV_BAUD`** — for every reachable state, BAUD-v1's precondition
  implies its postconditions on adjusted level, decision kind, and
  actuator safety.
- **`INV_ERUR`** — for every reachable state, ERUR-v1's precondition
  implies its postconditions on adjusted level (KNOWN) and decision
  kind (PROCEED).
- **`INV_PARTITION`** — for every reachable state where raw is KNOWN,
  exactly one of `BAUDPrecondition` and `ERURPrecondition` holds.
  This is the structural witness that the pair is bidirectional and
  complete with no overlap (matching the
  `test_smoke_baud_and_erur_partition_the_cycle_space` integration
  test, but proved over the abstract model rather than observed on
  one trace).

### 2. Abstract model

The TLA+ spec models the closed loop as a state machine with one
transition per cycle:

- **State variables**: the calibration history (bounded sequence of
  outcomes with at most W entries), the raw assessment level, and
  the derived adjusted level + decision kind + actuator safety
  flag.
- **Transitions**: each cycle, a non-deterministic outcome arrives
  (dirty or clean, modelling the BAUD-relevant binary partition of
  the four verdict bands), the sliding window absorbs it, and the
  calibrator + decision + actuation policies run deterministically.
- **Raw level**: also non-deterministic per cycle, so the model
  exercises every combination of `(history, raw_level)` reachable
  in the bounded state space.

The reference calibrator (`MahalanobisDowngradePolicy`), decision
policy (`UncertaintyAwareReferencePolicy`), and actuator safety
classifier are implemented as TLA+ definitions that mirror the
Python source line-for-line.

### 3. Bounds

For TLC to enumerate the state space in seconds rather than days, the
spec is run with deliberately small bounds:

| Constant | Reference value | Spec value | Why this bound is sufficient |
|---|---|---|---|
| `M` (min_outcomes) | 4 | 2 | The boundary cases of the precondition are exhausted at any positive M; small M reduces state space |
| `K` (downgrade_threshold) | 2 | 1 | Same |
| `W` (max_history) | 32 | 3 | The window mechanism's correctness is captured by any W ≥ M; small W is sufficient |

These bounds **prove the properties on the abstract model with these
constants**. To extend the claim to the production constants (M=4,
K=2, W=32), the verifier-plus-tests already provide that evidence at
production scale; TLA+ fills in the *small but exhaustive* corner.

### 4. What this DOES and DOES NOT claim

**Does claim:**

- The property statements as written in ADR-0031, ADR-0032 are logically
  consistent with the reference policy semantics.
- The BAUD + ERUR partition is structurally complete on the abstract
  model.
- No combination of (history, raw_level) in the bounded state space
  violates any of the three invariants.

**Does NOT claim:**

- That the Python implementation faithfully mirrors the TLA+ model.
  The bridge is by inspection — a single human (and review) reading
  both. Future work could extract the spec from the Python source
  automatically.
- That the bounded constants prove the unbounded case. TLC is
  exhaustive over the *finite* state space defined by the
  constants. Behaviour at larger M/K/W is covered by the property
  tests, not the TLA+ proof.
- That non-reference calibration policies satisfy the invariants.
  Each non-reference policy would need its own spec or proof.

### 5. Integration

- `docs/proofs/BaudErur.tla` — the specification.
- `docs/proofs/BaudErur.cfg` — TLC configuration with the three
  invariants and the bounded constants.
- `docs/proofs/README.md` — instructions to run TLC locally
  (requires Java 17+ and `tla2tools.jar`).
- `docs/properties/proofs.md` — docs-site page explaining what TLA+
  adds and the honest scope.
- README updated to mention the formal artifact alongside the
  existing verifier + tests.

### 6. Future ADRs that build on this

- **ADR-0037 (potential)**: TLA+ specs for MD-v1, RLB-v1, FPB-v1.
- **ADR-0038 (potential)**: CI job that runs TLC on every push,
  blocking merges that break any invariant. Requires Java + TLA
  tools installed in the runner.
- **ADR-0039 (potential)**: TLAPS proof of the unbounded version of
  the partition theorem — replacing TLC's "exhaustive over bounded
  state space" with "proved for any finite W, M, K".

## Consequences

### Positive

- **A second, independent layer of evidence.** Property tests cover
  large random samples at production scale; TLA+ covers the full
  abstract state space at small bounds. The two are *complementary
  failure detectors*.
- **A citable artifact in a recognised formal-methods notation.**
  TLA+ specs are publishable and have a tradition in distributed
  systems and concurrent algorithms; bringing one to autonomy
  safety is the kind of artifact that makes the project legible to
  formal methods researchers.
- **The partition theorem proved.** The integration test asserts
  `BAUD + ERUR == total` on one trace; the TLA+ spec proves it on
  *every* reachable state of the abstract model. Qualitatively
  stronger.

### Negative / costs

- **The model is small.** TLC at M=2, K=1, W=3 is not the production
  configuration. The argument that this is sufficient relies on
  the property tests already covering the production scale.
- **Manual bridge between TLA+ and Python.** A future divergence
  between the two without anyone noticing would silently weaken
  the claim. Mitigation: every change to the reference calibrator
  or decision policy should be reviewed against the TLA+ spec, and
  any structural change should re-run TLC.
- **TLA+ requires Java.** Running the verification locally requires
  installing Java 17+ and `tla2tools.jar` (~ 5 MB download). CI
  integration is a follow-up ADR.

## Alternatives considered

1. **Lean / Coq proof.** Higher credibility (theorem proving over
   unbounded models) but multi-week investment. Rejected for
   ADR-0036 in favour of the cheaper-but-still-strong TLA+ artifact.
   A Lean proof remains a future candidate.
2. **No formal artifact at all.** The property tests are already
   strong evidence and adopters might be satisfied. Rejected
   because the project's identity has been "make the property set
   the citable contribution"; adding a TLA+ layer continues that
   trajectory.
3. **Hand-written proof in a PDF.** A natural-language proof in an
   appendix would also strengthen the claim, but it cannot be
   mechanically re-checked when the policies change. TLA+ is
   re-runnable.

## Implementation roadmap

| Paso | Entregable | Status |
|---|---|---|
| 1 | Este ADR | done at acceptance |
| 2 | `docs/proofs/BaudErur.tla` + `BaudErur.cfg` | 1 sesión |
| 3 | `docs/proofs/README.md` + `docs/properties/proofs.md` | 1 sesión |
| 4 | Run TLC locally + record verification output | post-spec |
| 5 | Lift ADR a Accepted con la salida de TLC | tras pasos 2-4 |
| 6 | CI integration (future, ADR-0038 candidate) | future |

## References

- Lamport, L. *Specifying Systems* (the TLA+ book), Addison-Wesley
  2002.
- ADRs 0031..0035 — the property set being verified.
- `src/project_ghost/core/feedback/reference_policy.py` —
  `MahalanobisDowngradePolicy` (TLA+ mirrors `adjust()` line-by-line).
- `src/project_ghost/core/decisions/reference_policy.py` —
  `UncertaintyAwareReferencePolicy` (TLA+ mirrors the
  level-to-decision mapping).
