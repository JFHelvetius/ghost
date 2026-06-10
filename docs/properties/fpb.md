# FPB-v1 — False Positive Bound observer

!!! abstract "Citation"
    [ADR-0035](../adr/0035-false-positive-bound-property-v1.md) ·
    Accepted 2026-06-09 ·
    Verifier: `project_ghost.properties.verify_fpb`

## What it claims

The empirical fraction of cycles where BAUD-v1's precondition fires
is **observable and bounded** by a caller-configurable
`max_fire_fraction`. The fifth property of the set and the only
**quantitative observational** one.

## Formal statement

For an execution with parameters `(M, K)` and a caller-supplied
`max_fire_fraction ∈ [0, 1]`:

```
fire_fraction(E) <= max_fire_fraction
```

where:

```
fire_fraction(E) = cycles_baud_fires(E) / cycles_total(E)
```

and `cycles_baud_fires` is the count of cycles where BAUD's
precondition is met. Default `max_fire_fraction = 1.0` makes the
verifier a **pure observer** that always holds.

## Why it's "observer-shaped"

Unlike BAUD/ERUR/MD/RLB (all hard pass/fail), FPB-v1 is a *measuring
stick*. The honest framing: the *statistical* false-positive bound
(under Gaussian noise with declared covariance) requires Monte Carlo
infrastructure that is currently out of scope. FPB-v1 delivers the
**empirical** fire-rate observation that:

- Surfaces an explicit float metric in the report
- Lets the caller pin a regression bound via `max_fire_fraction`
- Defaults to non-failing observer mode for normal CI use

A future FPB-v2 with Monte Carlo machinery would tighten this into a
true statistical claim.

## Verifying any MCAP

```bash
# Default: pure observer, never fails
ghost verify-properties --mcap your-run.mcap

# Regression gate: fail if fire fraction exceeds 0.5
ghost verify-properties --mcap your-run.mcap --max-fire-fraction 0.5
```

Or programmatically:

```python
from project_ghost.properties import verify_fpb
report = verify_fpb("your-run.mcap", max_fire_fraction=0.5)
assert report.holds
print(f"Observed: {report.fire_fraction:.2f}")
```

## Example output

On the reference 10-cycle smoke:

```
FPB-v1: HOLDS  (fire_fraction=0.60, 6/10 cycles evaluated)
```

The smoke baseline is `fire_fraction = 0.60` (BAUD fires in 6 of 10
cycles). With default `max_fire_fraction=1.0` this holds trivially;
with `max_fire_fraction=0.5` it would violate.

## Use as a regression gate

The integration test pins the exact observed fraction:

```python
def test_smoke_carries_inline_fpb_verification(tmp_path):
    summary = run_closed_loop_smoke(tmp_path / "smoke.mcap", n_cycles=10)
    assert summary.fpb_report.fire_fraction == 0.6  # <- pinned baseline
```

If a future refactor of the calibration policy changes its
sensitivity, this test surfaces the change in a single line of CI
output. The maintainer either:

- Accepts the change (update the pinned value)
- Treats it as a regression (fix the policy)

Either way, the change is **visible**, not silent.

## Scope

FPB-v1 **does** establish:

- The exact empirical fire fraction over the MCAP
- A pass/fail comparison against a caller-supplied bound

FPB-v1 **does not** establish:

- Any statistical claim under a probabilistic noise model
- That the observed fires are *false* positives (the verifier cannot
  distinguish from the MCAP alone)
- A target value for `max_fire_fraction` (that is policy-dependent
  and operator-supplied)

## See also

- [Full ADR-0035](../adr/0035-false-positive-bound-property-v1.md)
- [Source: `src/project_ghost/properties/fpb.py`](https://github.com/JFHelvetius/ghost/blob/main/src/project_ghost/properties/fpb.py)
- Sister properties: [BAUD-v1](baud.md), [ERUR-v1](erur.md), [MD-v1](md.md), [RLB-v1](rlb.md)
