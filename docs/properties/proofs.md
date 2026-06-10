# Mechanical verification (TLA+)

!!! abstract "Citation"
    [ADR-0036](../adr/0036-tla-plus-mechanical-verification-of-baud-erur.md) ·
    Proposed 2026-06-09 ·
    Specs: [`docs/proofs/BaudErur.tla`](https://github.com/JFHelvetius/ghost/blob/main/docs/proofs/BaudErur.tla)

The property set is verified by three complementary layers:

| Layer | Tool | Scope | Strength |
|---|---|---|---|
| **Executable verifiers** | `ghost verify-properties` | One specific MCAP | Per-trace |
| **Property tests** | Hypothesis | Random samples at production scale | Probabilistic |
| **Mechanical verification** | TLA+ / TLC | Full state space at small bounds | Exhaustive |

This page covers the third layer.

## What TLA+ adds

The Python verifiers prove the property holds on **a specific captured
MCAP**. The Hypothesis property tests prove it holds on **the inputs
the test generator sampled**. Neither proves the property holds on
*all* possible inputs.

TLA+ with the TLC model checker closes that gap on a *bounded abstract
model*. With M=2, K=1, W=3, TLC enumerates the entire reachable state
space (low hundreds of states) and verifies all five invariants
exhaustively. No random sampling — every state is visited.

## The five invariants

[`BaudErur.tla`](https://github.com/JFHelvetius/ghost/blob/main/docs/proofs/BaudErur.tla)
defines and checks:

1. **INV_BAUD** — formal statement of [BAUD-v1](baud.md)'s precondition →
   postconditions implication.
2. **INV_ERUR** — formal statement of [ERUR-v1](erur.md)'s precondition →
   postconditions implication.
3. **INV_PARTITION** — the BAUD + ERUR partition theorem, proved over
   the full abstract state space. Promotes
   `test_smoke_baud_and_erur_partition_the_cycle_space` from
   "observed on one trace" to "proven on the model".
4. **INV_NO_INVENTED_CONFIDENCE** — bonus formal statement of
   [MD-v1](md.md): the reference calibrator's adjusted level is always
   ≥ raw level in the lattice.
5. **INV_HISTORY_BOUND** — safety net on the sliding-window model:
   `Len(history) <= W` always. If this ever violates, the
   WindowUpdate definition is wrong and so is RLB-v1's structural
   assumption.

## Running TLC

Requires Java 17+ and `tla2tools.jar`:

```bash
java -cp /path/to/tla2tools.jar tlc2.TLC \
    -config docs/proofs/BaudErur.cfg \
    docs/proofs/BaudErur.tla
```

Expected output: `Model checking completed. No error has been found.`

See [the proofs README](https://github.com/JFHelvetius/ghost/blob/main/docs/proofs/README.md)
for full instructions.

## Honest scope

The TLA+ artifact does NOT establish:

- **That the Python implementation faithfully mirrors the TLA+ model.**
  The bridge between the two is by code inspection only — a single
  reviewer reading `src/project_ghost/core/feedback/reference_policy.py`
  and the `Calibrate` definition in `BaudErur.tla` and confirming they
  encode the same semantics. Future work could extract the TLA+ spec
  from the Python source automatically.
- **That the bounded constants prove the unbounded case.** TLC is
  exhaustive over the *finite* state space defined by `M=2, K=1, W=3`.
  Behaviour at production constants (M=4, K=2, W=32) is covered by the
  property tests and CLI verifier, not the TLA+ proof.
- **That non-reference calibration policies satisfy the invariants.**
  Each non-reference policy would need its own spec.

See [ADR-0036](../adr/0036-tla-plus-mechanical-verification-of-baud-erur.md)
for the full framing.

## Why TLA+ specifically, not Lean/Coq

The decision is in [ADR-0036 §Alternatives](../adr/0036-tla-plus-mechanical-verification-of-baud-erur.md).
Summary: TLA+ delivers exhaustive model-checking at bounded scale in a
few hours of work; Lean or Coq deliver unbounded theorem proofs at
multi-week investment. The project's identity has been "make the
property set citable end-to-end"; TLA+ continues that trajectory
cost-effectively. A Lean proof remains a future candidate (potential
ADR-0039).

## Future work

- **ADR-0037 candidate**: TLA+ specs for RLB-v1 and FPB-v1 in their
  own modules.
- **ADR-0038 candidate**: CI job that runs TLC on every push, blocking
  merges that break any invariant.
- **ADR-0039 candidate**: TLAPS proof of the partition theorem for
  unbounded W, M, K — replacing TLC's "exhaustive over bounded state
  space" with "proved for any finite W, M, K".
