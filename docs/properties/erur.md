# ERUR-v1 — Eventual Reactivation Under Recovery

!!! abstract "Citation"
    [ADR-0032](../adr/0032-eventual-reactivation-under-recovery-property-v1.md) ·
    Accepted 2026-06-09 ·
    Verifier: `project_ghost.properties.verify_erur`

## What it claims

When the calibration history does **not** trigger a downgrade and the
raw self-assessment is KNOWN, **the agent emits PROCEED** in that same
cycle. The symmetric counterpart of [BAUD-v1](baud.md).

## Formal statement

For an execution under the same reference policy pair as BAUD-v1, if
at cycle `t`:

```
( H_t.outcomes_considered < M
  OR H_t.count_beyond_3_std + H_t.count_beyond_5_std < K )
AND  raw_t.overall_level == KNOWN
```

(the **drift-clean** condition AND raw is KNOWN), then in that same
cycle:

1. `C_t.adjusted_overall_level == KNOWN`
2. `A_t.decision.kind == PROCEED`

## Why it matters

Without ERUR, BAUD alone is satisfied vacuously by a degenerate
"always emit HOLD" policy. ERUR is the **inverse symmetry** — the
witness that the reference calibrator actually *reactivates* when
conditions allow, rather than staying stuck in a defensive posture.

Together with BAUD, ERUR partitions the entire space of conditional
per-cycle behaviour with no overlap.

## Verifying any MCAP

```bash
ghost verify-properties --mcap your-run.mcap
```

Or programmatically:

```python
from project_ghost.properties import verify_erur
report = verify_erur("your-run.mcap")
assert report.holds
```

## Example output

On the reference 10-cycle smoke with sustained 5 m/s drift:

```
ERUR-v1: HOLDS  (M=4, K=2, 4/10 cycles evaluated)
```

The precondition fires on cycles 1–4 (before enough drift outcomes
have accumulated to trigger a downgrade). For each of those 4 cycles
ERUR asserts that the recorded adjusted level is KNOWN and the
decision is PROCEED.

## The partition with BAUD

| Cycle range | BAUD applies | ERUR applies |
|---|---|---|
| 1–4 (drift-clean) | no | **yes** |
| 5–10 (drift-detected) | **yes** | no |

`BAUD.cycles_precondition_held + ERUR.cycles_precondition_held ==
cycles_total` is enforced as an integration test
(`test_smoke_baud_and_erur_partition_the_cycle_space`).

## Bug found during implementation

The original `drift_clean` predicate was `count_beyond_3+5 < K`. A
two-cycle band where `count >= K` but `outcomes_considered < M`
remained uncovered by both BAUD and ERUR. Tightened to the literal De
Morgan negation of BAUD's precondition. Full narrative in
[ADR-0032](../adr/0032-eventual-reactivation-under-recovery-property-v1.md).

## Scope

ERUR-v1 **does** establish:

- A computable per-cycle precondition (the inverse of BAUD's)
- Two postconditions evaluated against MCAP records
- Structural complementarity with BAUD

ERUR-v1 **does not** establish:

- Reactivation latency bounds (that's [RLB-v1](rlb.md))
- Behaviour when raw assessment is not KNOWN (those cycles fall
  outside ERUR's precondition)
- Coverage of non-reference policy pairs

## See also

- [Full ADR-0032](../adr/0032-eventual-reactivation-under-recovery-property-v1.md)
- [Source: `src/project_ghost/properties/erur.py`](https://github.com/JFHelvetius/ghost/blob/main/src/project_ghost/properties/erur.py)
- Sister properties: [BAUD-v1](baud.md), [MD-v1](md.md), [RLB-v1](rlb.md), [FPB-v1](fpb.md)
