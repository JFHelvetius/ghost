# ADR-0002 — Deterministic Simulation

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

Without determinism in simulation, three things become impossible:

1. **Debugging.** A bug that appears in 1 of 50 runs is nearly impossible to isolate if runs are not reproducible.
2. **Comparative benchmarks.** Comparing two estimator versions requires both to see exactly the same input.
3. **Honest CI.** Regression tests need stable trajectories; loose tolerances hide real regressions.

The two main sources of non-determinism in Python projects are:

- **Time:** mixing wall clock and sim clock, accumulating `float` seconds, calling `time.time()` from inside the backend.
- **Randomness:** using global `random` or `np.random`, threads consuming RNG in non-guaranteed order, seeds not propagated.

## Decision

Project Ghost freezes the following determinism rules:

1. **Integer nanoseconds for time.** All timestamps are `int` (ns). Use of `float` for time arithmetic or storage is forbidden. Conversions to `float` seconds are allowed only for visualization.
2. **Single clock in simulation.** The `core.SimClock` is the exclusive source of time inside simulation. Calling `time.time()`, `time.monotonic()`, or `datetime.now()` inside a sim backend is a contract violation, detected by a custom linter.
3. **Fixed physics steps.** The backend simulates with a constant `step_ns` declared in the `ScenarioSpec`. No variable steps.
4. **Injected randomness.** A single `RandomSource` root derived from `ScenarioSpec.seed`. Each consumer (IMU noise, camera dropout, disturbances) requests a `child("label")` deterministic with respect to the root. Global `random.random()`, `np.random.rand()`, and similar are forbidden; detected by a linter.
5. **Total order of messages.** Every publish carries `(stamp_sim_ns, sequence)` where `sequence` is a global atomic counter. Delivery to subscribers respects this order, regardless of subscription order.
6. **Bit-equality regression tests.** For each canonical scenario, two runs with the same seed must produce an identical hash of the MCAP `/groundtruth/pose` channel.

## Consequences

**Positive:**

- Reproducible bugs. Any observed behavior in a run can be recreated exactly.
- Perfect replay. An MCAP can be re-injected and produces the same estimator/planner decisions.
- CI can use strict tolerances (exact equality where applicable, small ε where float operations are unavoidable).

**Negative:**

- Extra discipline for contributors: RNGs must be requested rather than reaching for `np.random`.
- Some backends do not guarantee determinism (Gazebo with async physics). Documented as "non-deterministic" and forbidden for benchmarks.
- The custom linter requires maintenance.
- Multithreading becomes complicated: execution order must be dictated by the `SimClock` scheduler, not by the OS. In Phase 1 threads are avoided on hot paths.

## Alternatives considered

**A. Soft determinism with statistical tolerances.** Rejected: hides regressions, complicates debugging, and multiplies test costs.

**B. Wall clock with a global numpy seed.** Rejected: not reproducible across machines or Python versions, and breaks replay.

**C. Accept non-determinism and compensate with multiple runs.** Rejected: impossible to debug rare bugs; multiplies CI cost; hides software defects under statistical variance.

**D. Float64 seconds for time.** Rejected: after 4 hours of sim at 1 kHz, resolution drops to microseconds through accumulation; after days, it can drop to milliseconds. Unacceptable.
