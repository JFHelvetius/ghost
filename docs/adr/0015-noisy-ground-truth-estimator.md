# ADR-0015 — Noisy Ground Truth Estimator

## Status
Accepted (2026-06-07).

## Context

ADR-0005 froze `VehicleState` with an optional `covariance_15x15`.
ADR-0009 introduced the **truth ≠ belief** principle as a non-negotiable
honesty obligation. T2.a.6 (`vehicle_state_from_ground_truth`) honored
that principle by publishing `covariance_15x15 = None`: ground truth is
not a belief with quantified uncertainty, it is the simulator's oracle.

The next milestone in the autonomy-under-uncertainty axis is to produce
a `VehicleState` that **is** a belief — that is, an artifact for which
`covariance_15x15 is not None` and whose pose differs, deterministically
and reproducibly, from the simulator's truth.

This ADR commits to one specific, deliberately limited mechanism for
producing such an artifact:

> A **caller-declared perturbation** of `GroundTruth` by deterministic
> Gaussian noise, packaged as a `VehicleState` whose `covariance_15x15`
> is a **caller-declared parameter**, NOT a quantity inferred from data.

That is **all** the system does. The exclusions listed below are not
extension hooks — they are explicit non-goals.

The honest framing matters more than the mechanism: an estimator that
pretends to estimate when it is in fact perturbing ground truth would
undermine every claim Project Ghost makes about uncertainty modeling.
The naming (`NoisyGroundTruthEstimator`) and the documentation here
make the perturbation-of-truth nature unambiguous.

## Decision

Add `project_ghost.estimation` package with:

1. **`NoisyGroundTruthConfig`** — frozen dataclass capturing the
   parameters of the perturbation:
   - `position_noise_std_m` (float ≥ 0): per-axis std dev of additive
     Gaussian noise on ENU position.
   - `orientation_noise_std_rad` (float ≥ 0): per-axis std dev of the
     small-angle tangent perturbation applied to the unit quaternion.
   - `linear_velocity_noise_std_mps` (float ≥ 0): per-axis std dev of
     additive Gaussian noise on world-frame linear velocity.
   - `angular_velocity_noise_std_rps` (float ≥ 0): per-axis std dev of
     additive Gaussian noise on body-frame angular velocity.
   - `accel_body_noise_std_mps2` (float ≥ 0): per-axis std dev of
     additive Gaussian noise on body-frame linear acceleration.
   - `declared_covariance_15x15` (`np.ndarray`, shape (15, 15),
     float64): the **caller-declared** belief covariance attached to
     every emitted `VehicleState`. Validated symmetric (tol 1e-9) and
     PSD (eps 1e-12), same tolerances as
     `NavigationState._validate_covariance`. NOT derived from the noise
     stds; the caller chooses what belief to publish.
   - `random_source_label` (str, default `"/estimation/noisy_gt"`):
     label used to derive the dedicated child `RandomSource` per
     ADR-0002.

2. **`NoisyGroundTruthEstimator`** — class with:
   - `__init__(*, config, random_source)`: holds the config and derives
     a single child `RandomSource` once at construction via
     `random_source.child(config.random_source_label)`. The child is
     reused for every `estimate()` call; the parent is never read again
     after construction.
   - `estimate(*, gt, sensors_health, flight, mission, stamp_wall_ns)
     -> VehicleState`: applies the perturbations to `gt` and returns a
     `VehicleState` whose `nav.covariance_15x15` is a fresh copy of
     `config.declared_covariance_15x15`.

3. **Perturbation model.**

   Position, world-linear-velocity, body-angular-velocity and
   body-acceleration receive **independent additive zero-mean Gaussian
   noise** with the per-axis std devs from the config.

   Orientation receives a **small-angle tangent perturbation**:
   sample `δθ ∈ R³` with per-axis std `orientation_noise_std_rad`,
   form `δq = [1, δθ_x/2, δθ_y/2, δθ_z/2]`, compose with the GT
   quaternion via Hamilton multiplication (`q' = δq ⊗ q`), and
   renormalize. Adequate for small std devs (the regime in which the
   small-angle approximation is meaningful); the unit-norm tolerance
   of `state.messages.Pose` (1e-3) is the operational ceiling.

4. **Twist self-consistency.**

   The emitted `VehicleState` follows the same body↔world conversion
   pattern as `vehicle_state_from_ground_truth`, but uses the
   **noisy quaternion** (not the GT quaternion) for `R_body_to_world`
   and `R_world_to_body`. This keeps `twist_world` and `twist_body`
   self-consistent under the published pose. The published belief is
   internally coherent — coherent with itself, NOT with truth.

5. **IMU biases.** Set to zero. The same honesty argument from T2.a.6
   applies: this estimator does not estimate biases; it perturbs truth.
   Reporting zero biases here is the explicit refusal to fabricate a
   belief that was never computed.

6. **Determinism.**

   For identical
   `(config, parent_random_source_seed, parent_random_source_label,
   sequence of estimate() inputs)`,
   the byte representation of every emitted `VehicleState` is
   identical. This is preserved by the hierarchical SHA-256 child
   derivation in `core.clock.random_source` (ADR-0002).

## Inputs

- `gt: GroundTruth` from `hal.messages.runtime`.
- `sensors_health: SensorHealthMap`, `flight: FlightStatus`,
  `mission: MissionStatus`: discrete state that this estimator does
  NOT perturb; copied through.
- `stamp_wall_ns: int`: passed through unchanged to the resulting
  `VehicleState`. The estimator does NOT read any clock.
- Construction-time: `NoisyGroundTruthConfig` + parent `RandomSource`.

## Outputs

- A `VehicleState` with:
  - `stamp_sim_ns = gt.stamp_sim_ns`
  - `stamp_wall_ns = stamp_wall_ns` (caller-provided)
  - `nav.pose`: perturbed
  - `nav.twist_world`, `nav.twist_body`: built from perturbed velocities
    and the perturbed orientation
  - `nav.accel_body_mps2`: perturbed
  - `nav.imu_biases`: zero
  - `nav.covariance_15x15`: fresh copy of
    `config.declared_covariance_15x15`
  - `sensors`, `flight`, `mission`: copied through unchanged.

## Limits

- The published covariance is a **declared parameter**, not a function
  of the noise stds, not a function of the observed innovation, not a
  function of motion. It expresses what the caller has chosen to claim
  as their belief.
- The orientation perturbation uses the small-angle quaternion
  approximation. For std devs beyond a few tenths of a radian the
  approximation breaks down and the published pose may fail
  `Pose._validate_unit_quaternion` even after renormalization. Callers
  are responsible for choosing stds compatible with their declared
  covariance.
- The estimator has **no state between calls**. Each `estimate()`
  call draws from the same child `RandomSource`; perturbations across
  calls are independent in distribution but determined by the call
  sequence.
- No motion model. No measurement model. No innovation. No gating.
  No recursive update.

## Determinism

For identical
`(config, parent.seed, parent.label, sequence of (gt, sensors_health,
flight, mission, stamp_wall_ns) tuples)`
within a fixed `(CPython, numpy)`:

- Every emitted `VehicleState` is field-by-field equal.
- The JSON-encoded byte representation (via
  `telemetry.serialization.encode_to_bytes`) is byte-identical.

The estimator:

- Reads no clock.
- Performs no I/O.
- Holds no thread-local state.
- Derives its `numpy.random.Generator` exactly once at construction.

## Exclusions (explicit non-goals)

The following are NOT implemented and are NOT extension points
sanctioned by this ADR. Any introduction of these would require a new
ADR explaining why the perturbation stance was insufficient and what
the new artifact's honest framing would be:

- **Bayesian estimation** — no prior/posterior update.
- **Kalman / EKF / UKF** — no motion model, no measurement model, no
  Jacobians, no innovation.
- **Particle filters / smoothers** — no resampling, no MCMC.
- **Covariance propagation** — `declared_covariance_15x15` is constant
  across calls.
- **Covariance derivation from noise stds** — the declared covariance
  is a caller parameter, not `diag(stds**2)` blown up to 15×15.
- **Innovation-based bias estimation** — biases are zero, by design.
- **Outlier rejection / chi-square gating**.
- **Multi-sensor fusion**.
- **State augmentation** — the 15-dim layout is fixed by
  `NavigationState`.
- **Online tuning of stds or covariance**.

## "Noisy ground truth is not estimation"

This module produces a `VehicleState` that **looks like a belief**: it
has `covariance_15x15 is not None` and a perturbed pose. It is NOT a
belief in the epistemic sense:

- The published covariance does not bound the published error in any
  meaningful statistical sense — it is whatever the caller declared.
- The published pose is not a posterior estimate — it is truth plus
  noise the caller asked for.
- Iterating the estimator does not improve its output — each call is
  i.i.d. given the call sequence.

The module exists to **exercise the downstream consumers of
non-trivial covariance** (planners, T2 reactive behaviors, telemetry
panels, traceability over belief). It is a test fixture in production
shape, not a stand-in for a real estimator.

When a real estimator lands — Kalman, factor graph, or otherwise — it
will live in a separate module (`project_ghost.estimation.{whatever}`)
and this one will remain available specifically for fixture and
ablation use.

## Consequences

**Positive.**

- Project Ghost gains its first deliberate producer of belief.
  Downstream consumers can be exercised against
  `covariance_15x15 is not None` without waiting on real estimation.
- The honest framing (perturbation of truth, declared covariance)
  prevents the project from drifting into the trap of pretending a
  Gaussian noise generator is an estimator.
- The estimator composes cleanly with the existing
  `RandomSource` hierarchy: a single child label keeps replay
  deterministic.
- The declared-covariance choice forces every caller to **state their
  belief explicitly**. There is no default; you cannot accidentally
  publish an unjustified small covariance.

**Negative.**

- Tutorial / demo code that wires this estimator into the runtime
  loop will look superficially like real estimation. The ADR's
  "not estimation" clause must be cited whenever this comes up in
  review or documentation.
- The closed exclusion list creates friction for future variants
  (e.g. a heteroscedastic noise model parameterized by motion). Each
  variant requires a new ADR. Justified because silent extension into
  inference territory is exactly what this ADR exists to prevent.

## Alternatives Considered

1. **Derive covariance from noise stds** (`Σ = diag(stds**2)` blown up
   to 15×15 with appropriate cross-terms). Rejected: pretends to
   compute belief from a noise model that has no relationship to the
   physics; trades the explicit declared parameter for a hidden
   computation that callers cannot inspect.
2. **Make it a `_from_ground_truth` variant in `state.aggregator`**.
   Rejected: `vehicle_state_from_ground_truth` publishes truth
   (`covariance_15x15 = None`). Mixing it with a belief publisher in
   the same module dilutes the truth/belief boundary that ADR-0009 is
   built on.
3. **Use a real (toy) Kalman filter for the same VehicleState output**.
   Rejected: requires a motion model and a measurement model that
   would either be honest about their toy nature (and so just as
   limited as this module) or claim more than they deliver. The
   perturbation stance is more honest for the test-fixture role.
4. **Sample covariance from a distribution per call** (so each
   `VehicleState` has a different published covariance). Rejected:
   adds a second axis of caller-opaque randomness without changing
   the artifact's role; declared-and-constant is sufficient.

## Backward compatibility

Zero impact. New package, new public symbols, no existing module
modified. `vehicle_state_from_ground_truth` continues to publish
`covariance_15x15 = None`; the new estimator is an opt-in alternative
chosen by the caller wiring the runtime loop.
