# RLB-v1 — Recovery Latency Bound

!!! abstract "Citation"
    [ADR-0034](../adr/0034-recovery-latency-bound-property-v1.md) ·
    Accepted 2026-06-09 ·
    Verifier: `project_ghost.properties.verify_rlb`

## What it claims

For every observed transition from a "dirty" calibration history
window to a "fully clean" one, the length of the preceding dirty run
is bounded by `peak + W - 1`, where `peak` is the maximum
over-threshold count observed during the run and `W` is the
calibration history window size.

The first **multi-cycle** and **quantitative** property of the set.

## Formal statement

For every recovery transition at cycle `t` (a clean cycle whose
predecessor is dirty):

```
L(t) <= peak(t) + W - 1
```

where:

- `L(t)` is the number of consecutive dirty cycles immediately
  preceding `t`
- `peak(t)` is the maximum value of `H_s.count_beyond_3_std +
  H_s.count_beyond_5_std` for any `s` in the dirty run
- `W` is the window size used by `build_calibration_history`

## Why the bound is `peak + W - 1`

A sliding window of size `W` expels at most **one outcome per cycle**.
If `N` consecutive over-threshold outcomes ever enter the buffer, the
buffer accumulates `peak = min(N, W)` dirty outcomes. From that point,
each new within-1σ outcome expels one dirty one. To flush all `peak`
dirty outcomes takes `peak` more cycles. Total dirty run length:

```
L(t) = accumulation_phase + flush_phase - 1
     = N + peak - 1
     <= peak + W - 1     (because N <= W in steady state)
```

If `L(t)` ever exceeds `peak + W - 1`, the builder is no longer
expelling one outcome per cycle — a structural bug in the windowing.

## Why it matters

ERUR-v1 says *when* the agent reactivates (the moment drift-clean
fires), but does not say *how long* it takes for drift-clean to fire
after the last over-threshold outcome enters the window. RLB-v1
fills that gap with a quantitative upper bound parameterised by `W`.

## Verifying any MCAP

```bash
ghost verify-properties --mcap your-run.mcap
# RLB defaults to W=32 (the reference smoke value)

# Verify with a custom window size:
ghost verify-properties --mcap your-run.mcap --max-history 64
```

Or programmatically:

```python
from project_ghost.properties import verify_rlb
report = verify_rlb("your-run.mcap", max_history=32)
assert report.holds
```

## Example output

On the reference 10-cycle smoke with sustained drift (no recovery):

```
RLB-v1: HOLDS  (W=32, 0/10 cycles evaluated)
```

RLB applies **vacuously** to the smoke — there is no recovery
transition to verify. The strong coverage lives in the Hypothesis
property test which generates synthetic drift-then-recovery scenarios
of varying lengths.

## Bug found during implementation

The original bound was `L(t) <= W`. A property test with 32 dirty
cycles followed by 37 clean cycles surfaced `L(t) = 63 > 32` — a
genuine counterexample. The bound was corrected to `peak + W - 1` and
the ADR amended in-place. Full narrative in
[ADR-0034](../adr/0034-recovery-latency-bound-property-v1.md).

## Scope

RLB-v1 **does** establish:

- A quantitative upper bound on recovery latency
- Verification of every recovery transition observed in the MCAP

RLB-v1 **does not** establish:

- That the bound is tight (it is worst-case)
- Behaviour when outcomes never recover (the property applies
  vacuously)
- Independence from `W` (the parameter must be passed correctly to
  the verifier)

## See also

- [Full ADR-0034](../adr/0034-recovery-latency-bound-property-v1.md)
- [Source: `src/project_ghost/properties/rlb.py`](https://github.com/JFHelvetius/ghost/blob/main/src/project_ghost/properties/rlb.py)
- Sister properties: [BAUD-v1](baud.md), [ERUR-v1](erur.md), [MD-v1](md.md), [FPB-v1](fpb.md)
