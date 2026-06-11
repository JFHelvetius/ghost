# Formal proofs

This directory hosts mechanically-verifiable formal artefacts that
complement the executable verifiers in `src/project_ghost/properties/`.

Where the Python verifiers prove the property set holds on **a specific
captured MCAP**, and the Hypothesis property tests prove it holds on
**random samples at production scale**, the artefacts here prove it
holds on **the full reachable state space of a small abstract model**.

The three layers are complementary failure detectors: any divergence
between the abstract model, the Python implementation, and the
property statements in the ADRs is surfaced by *some* layer breaking.

## Inventory

| File | Property | Tool | Status |
|---|---|---|---|
| [`BaudErur.tla`](BaudErur.tla) | BAUD-v1, ERUR-v1, Partition, MD-v1 bonus | TLA+ / TLC | Accepted (ADR-0036) |
| [`BaudErur.cfg`](BaudErur.cfg) | TLC config for the above | TLC | — |
| [`Rlb.tla`](Rlb.tla) | RLB-v1 / Theorem 1 (tight recovery latency bound) | TLA+ / TLC | Accepted (paper §6) |
| [`Rlb.cfg`](Rlb.cfg) | TLC config for the above | TLC | — |

## Running TLC locally

### Prerequisites

- Java 17+ (any modern OpenJDK works).
- `tla2tools.jar` from <https://github.com/tlaplus/tlaplus/releases>
  (download the latest `tla2tools.jar`, ~2 MB).

### Invocation

```bash
# From the repo root:
java -cp /path/to/tla2tools.jar tlc2.TLC \
    -config docs/proofs/BaudErur.cfg \
    docs/proofs/BaudErur.tla

java -cp /path/to/tla2tools.jar tlc2.TLC \
    -config docs/proofs/Rlb.cfg \
    docs/proofs/Rlb.tla
```

Expected output on a clean spec:

```
TLC2 Version ...
Computing initial states.
Finished computing initial states: N distinct states generated at ...
Model checking completed. No error has been found.
  Estimates of the probability that TLC did not check all
  reachable states: ...
N states generated, M distinct states found, ...
```

If TLC reports `Invariant ... is violated`, the spec is logically
inconsistent with the property statement — fix the spec, or fix the
ADR. Either way it is a bug.

### Verification scope

The default `BaudErur.cfg` runs with intentionally small bounds
(M=2, K=1, W=3) so TLC completes in seconds rather than days. The
argument that small bounds are sufficient is in
[ADR-0036 §3](../adr/0036-tla-plus-mechanical-verification-of-baud-erur.md#3-bounds).

For larger bounds, edit `BaudErur.cfg` (e.g., `W = 5` increases the
state space ~16×). TLC handles W up to ~6 or 7 in reasonable time;
beyond that the state-space explosion dominates.

## What these proofs DO and DO NOT establish

**Do establish:**

- The property statements in ADRs 0031..0033 are logically consistent
  with the reference policy semantics on the abstract model.
- No combination of (history, raw_level) in the bounded state space
  violates any of the five invariants.
- The BAUD + ERUR partition is structurally exact, not just observed
  on one trace.

**Do not establish:**

- That the Python implementation in `src/project_ghost/` faithfully
  mirrors the TLA+ model. The bridge is by inspection.
- That the bounded constants prove the unbounded case. TLC is
  exhaustive *within the bounds*. Property tests cover production
  scale.
- Any property of non-reference calibration policies.

See [ADR-0036](../adr/0036-tla-plus-mechanical-verification-of-baud-erur.md)
for the full honest framing.

## Future work

- Spec for FPB-v1 (the empirical fire-fraction observer). FPB is
  probabilistic in nature; the TLA+ encoding would need a different
  shape than the structural BAUD/ERUR/RLB invariants.
- TLAPS proof of the unbounded version of the partition theorem
  (any finite `W, M, K`) and of Theorem 1 (RLB).
- Extending the `tla-plus` CI job to run both `BaudErur.tla` and
  `Rlb.tla` on every push.
