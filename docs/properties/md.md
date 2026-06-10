# MD-v1 — Monotonic Degradation

!!! abstract "Citation"
    [ADR-0033](../adr/0033-monotonic-degradation-property-v1.md) ·
    Accepted 2026-06-09 ·
    Verifier: `project_ghost.properties.verify_md`

## What it claims

The reference calibration policy **never invents confidence**. The
adjusted overall level is always at least as conservative as the raw
overall level in the lattice `KNOWN < UNCERTAIN < UNKNOWN`.

## Formal statement

For every cycle `t` with a `CalibratedSelfAssessment` record:

```
level_num(C_t.adjusted_overall_level)
    >=
level_num(raw_t.overall_level)
```

with the numerification `KNOWN=0, UNCERTAIN=1, UNKNOWN=2` (higher
number = less confident). The reference calibrator can therefore
*passthrough* (adj == raw) or *downgrade* (adj > raw), but never
*upgrade* (adj < raw).

## Why it matters

The calibration adjustment contract ([ADR-0026](../adr/0026-closed-loop-feedback-v1.md))
deliberately admits upgrades — some future policies could legitimately
use evidence to upgrade the confidence level. But the *reference*
policy is downgrade-only by construction.

Without MD-v1 stated as an explicit citable property, BAUD + ERUR + RLB
+ FPB could not rule out the possibility that the calibrator
*invented* confidence somewhere in the loop. MD pins it down.

## Verifying any MCAP

```bash
ghost verify-properties --mcap your-run.mcap
```

Or programmatically:

```python
from project_ghost.properties import verify_md
report = verify_md("your-run.mcap")
assert report.holds
print(f"{report.cycles_precondition_held}/{report.cycles_total} cycles")
```

## Example output

On the reference 10-cycle smoke:

```
MD-v1: HOLDS  (10/10 cycles evaluated)
```

MD is the only property whose `cycles_precondition_held` always equals
`cycles_total` — it is **unconditional** and applies to every cycle.

## The 3×3 transition matrix

The reference policy can produce 6 of the 9 cells in the
raw × adjusted matrix:

|  | adj=KNOWN | adj=UNCERTAIN | adj=UNKNOWN |
|---|---|---|---|
| raw=KNOWN | ✓ passthrough | ✓ downgrade | ✗ impossible (would skip a step) |
| raw=UNCERTAIN | ✗ upgrade (forbidden) | ✓ passthrough | ✓ downgrade |
| raw=UNKNOWN | ✗ upgrade | ✗ upgrade | ✓ idempotent |

MD-v1 forbids the three cells marked `✗ upgrade`. The Hypothesis
property test (`test_md_v1_holds_across_all_raw_levels`) sweeps all
three raw levels × the full `(M, K, history)` parameter space to witness
the property across every reachable input.

## Scope

MD-v1 **does** establish:

- An unconditional structural witness on every cycle
- That the reference policy is a "no invented confidence" policy

MD-v1 **does not** establish:

- That the *contract* forbids upgrades (it doesn't — see ADR-0026)
- That a custom calibration policy satisfies MD (each custom policy
  would need its own variant)
- Anything about decision or actuation (MD lives in the calibration
  layer only)

## See also

- [Full ADR-0033](../adr/0033-monotonic-degradation-property-v1.md)
- [Source: `src/project_ghost/properties/md.py`](https://github.com/JFHelvetius/ghost/blob/main/src/project_ghost/properties/md.py)
- Sister properties: [BAUD-v1](baud.md), [ERUR-v1](erur.md), [RLB-v1](rlb.md), [FPB-v1](fpb.md)
