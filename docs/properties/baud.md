# BAUD-v1 — Bounded Action Under Drift

!!! abstract "Citation"
    [ADR-0031](../adr/0031-bounded-action-under-drift-property-v1.md) ·
    Accepted 2026-06-09 ·
    Verifier: `project_ghost.properties.verify_baud`

## What it claims

When the calibration history shows enough recent prediction errors to
trigger the reference calibrator's downgrade condition, **the agent
emits no PROCEED decision and no unsafe actuator command** in that
same cycle.

## Formal statement

For an execution under the reference policy pair
`MahalanobisDowngradePolicy(M, K)` +
`UncertaintyAwareReferencePolicy` +
`AttitudeHoldReferencePolicy`, if at cycle `t` the calibration
history `H_t` satisfies:

```
H_t.outcomes_considered >= M
AND  H_t.count_beyond_3_std + H_t.count_beyond_5_std >= K
```

then in that same cycle `t`:

1. `C_t.adjusted_overall_level != KNOWN`
2. `A_t.decision.kind != PROCEED`
3. If `A_t.actuator_command is not None`, then `A_t.reason` is in
   the closed safe-reason set `S_baud_v1 = {attitude_hold_hold,
   kill_zero_throttle}`

## Why it matters

Without BAUD, an autonomous system can silently emit unsafe motor
commands while its internal model has drifted from reality. BAUD is
the per-cycle structural witness that **detected drift blocks
actuation in the same cycle it is detected** — no buffering, no
hysteresis, no delay window.

## Verifying any MCAP

```bash
ghost verify-properties --mcap your-run.mcap
```

Or programmatically:

```python
from project_ghost.properties import verify_baud
report = verify_baud("your-run.mcap")
assert report.holds
print(report.cycles_precondition_held, "/", report.cycles_total)
```

## Example output

On the reference 10-cycle smoke with the engineered 5 m/s drift:

```
BAUD-v1: HOLDS  (M=4, K=2, 6/10 cycles evaluated)
```

The precondition fires from cycle 5 onwards (after 4 outcomes have
accumulated past the K threshold). For each of those 6 cycles BAUD
asserts the three postconditions hold against the recorded MCAP.

## Bug found during implementation

The original draft of postcondition 3 required `actuator_command is
None` under non-PROCEED decisions. The first smoke test surfaced that
`AttitudeHoldReferencePolicy` (ADR-0029) legitimately emits an
identity-attitude command under HOLD — operationally **safer** than
silence, because an uncommanded vehicle drifts. The postcondition was
tightened to the closed safe-reason whitelist `S_baud_v1`. The full
narrative is in [ADR-0031 §1.1](../adr/0031-bounded-action-under-drift-property-v1.md).

## Scope

BAUD-v1 **does** establish:

- A computable per-cycle precondition
- Three postconditions evaluated against MCAP records
- A byte-exact reproducible verdict

BAUD-v1 **does not** establish:

- Detection latency bounds (depends on the window builder, not BAUD)
- Completeness against real drift (the precondition is sufficient,
  not necessary)
- Coverage of non-reference policy pairs (each pair would need its
  own version)

## See also

- [Full ADR-0031](../adr/0031-bounded-action-under-drift-property-v1.md)
- [Source: `src/project_ghost/properties/baud.py`](https://github.com/JFHelvetius/ghost/blob/main/src/project_ghost/properties/baud.py)
- [Tests: `tests/properties/test_verify_baud_smoke.py` + `test_baud_property.py`](https://github.com/JFHelvetius/ghost/tree/main/tests/properties)
- Sister properties: [ERUR-v1](erur.md), [MD-v1](md.md), [RLB-v1](rlb.md), [FPB-v1](fpb.md)
