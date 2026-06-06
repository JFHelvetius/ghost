# ADR-0008 — Perception Failure Modes and Uncertainty Propagation

- **Status:** Accepted
- **Date:** 2026-06-04

## Context

ADR-0000 commits Project Ghost to GPS-denied vision-inertial autonomy. ADR-0001 freezes the HAL contract, ADR-0005 freezes the canonical `VehicleState`, and ADR-0006 freezes the event bus. None of these documents specifies what the system does when perception **fails or degrades** — when the camera sees a textureless wall, the IMU saturates, the scene goes dark, or VIO loses tracking.

The architecture red-team review (`docs/reviews/architecture_red_team_review.md`, §2.6) calls this out bluntly: *"GPS-denied vision-only is hard. Without features, VO fails. Without loop closure, drift accumulates. The current design does not specify graceful degradation. Without an ADR on perception failure modes, the vision-only promise is marketing."*

There are two intertwined problems:

1. **Failure modes are nameless.** The codebase will accumulate ad-hoc checks (`if num_features < 10: ...`) scattered across perception, estimation, and control. Each developer invents thresholds. Behavior under degradation becomes emergent and untestable.
2. **Uncertainty is implicit.** ADR-0005 mentions a `covariance_15x15` slot on `NavigationState` but does not bind a contract for *who fills it, how it propagates, and what consumers may assume*. Without a uniform contract, a covariance produced by VO will be incommensurable with one produced by EKF, and downstream code will silently treat valid and stale estimates as equivalent.

This ADR closes both gaps for the lifetime of the project. It is a precondition for ADR-0009 (*Autonomy Under Uncertainty*), which builds the behavioral policy on top of this substrate.

## Decision

Project Ghost adopts a **typed catalog of perception failure modes**, a **uniform uncertainty envelope** carried by every perceptual estimate, and **quantitative entry criteria** for each mode. These are frozen contracts; modules may not invent private equivalents.

### 1. Uncertainty envelope (the `Estimate[T]` contract)

Every perceptual or estimation output that crosses a module boundary is wrapped in an `Estimate[T]` with the following fields:

| Field | Type | Meaning |
|---|---|---|
| `value` | `T` | The estimate itself (pose, depth, feature track, etc.) |
| `covariance` | `np.ndarray \| None` | Second-moment uncertainty in the same basis as `value`. `None` is only legal when `source.kind == "groundtruth"`. |
| `confidence` | `float \| None` | Scalar in `[0, 1]`; semantic is producer-defined and documented in `docs/specs/uncertainty.md`. Optional. |
| `validity` | `Validity` enum | `VALID`, `DEGRADED`, `STALE`, `INVALID`. See §2. |
| `stamp_sim_ns` | `int` | When the estimate was *produced*, not consumed. |
| `source` | `EstimateSource` | Producer identity (`module_id`, `kind`, `schema_version`). |

The envelope is itself a frozen dataclass. Arrays inside `value` and `covariance` are sealed with `flags.writeable=False` at construction, consistent with ADR-0005.

**Composition rule.** When a consumer combines two `Estimate[T]` (e.g. EKF update), it MUST emit a new `Estimate[T]` whose `validity` is the *most restrictive* of the inputs, and whose `covariance` accounts for both. There is no silent upgrade from `DEGRADED` to `VALID`.

### 2. Validity ladder

`Validity` is a totally-ordered enum:

```
VALID > DEGRADED > STALE > INVALID
```

| Value | Meaning | Consumers may |
|---|---|---|
| `VALID` | Inside published nominal envelope. | Use directly for control and mission decisions. |
| `DEGRADED` | Producer detected reduced quality but output is still informative. Covariance MUST reflect the degradation (inflated, not nominal). | Use for state estimation. Mission logic MUST consult the mode (see §3) before acting. |
| `STALE` | Estimate is older than its `max_age_ns` budget. Value is held; covariance is inflated by a documented growth model. | Use only for dead reckoning. Control loops MUST switch to fallback gains. |
| `INVALID` | Producer cannot supply a meaningful estimate. | MUST NOT use the value. Consumers fall through to last-known + dead reckoning, or trigger a perception failure mode (§3). |

Validity is never derived implicitly from "looks reasonable" heuristics on the consumer side. The producer is authoritative.

### 3. Perception failure mode catalog

The system recognizes a closed set of perception failure modes. Each has a stable `PerceptionMode` identifier, a quantitative entry criterion, and a corresponding behavioral response (defined in ADR-0009; this ADR only fixes the catalog and the criteria).

| Mode | Entry criterion | Exit criterion |
|---|---|---|
| `NOMINAL` | Default. All perceptual `Estimate.validity == VALID` for ≥ `nominal_hold_ms` (default 200 ms). | — |
| `LOW_TEXTURE` | VO feature count < `min_features` (default 30) for ≥ `low_texture_window_ms` (default 500 ms), OR mean feature-track length < `min_track_length` (default 5 frames). | Feature count ≥ `min_features × 1.5` for `nominal_hold_ms`. |
| `LOW_LIGHT` | Mean luminance < `min_luminance` (default 0.05 normalized) OR camera AGC saturated at max gain for ≥ `low_light_window_ms` (default 1000 ms). | Luminance ≥ `min_luminance × 2.0` for `nominal_hold_ms`. |
| `IMU_SATURATION` | Any IMU axis at `imu_saturation_threshold` (default 90 % of full scale) for ≥ `imu_saturation_window_ms` (default 50 ms). | All axes < `imu_saturation_threshold × 0.7` for `nominal_hold_ms`. |
| `VIO_LOST` | EKF innovation gate fails for ≥ `innovation_fail_count` consecutive updates (default 5), OR no VO update received for `vio_timeout_ms` (default 200 ms). | New VIO `Estimate.validity == VALID` accepted by the gate for `nominal_hold_ms`. |
| `MAP_AMBIGUOUS` | Loop-closure candidate score within `loop_closure_ambiguity_margin` (default 0.1) of the second-best for ≥ `ambiguity_window_ms` (default 500 ms). | Best candidate clears the second-best by `margin × 2`. |
| `PERCEPTION_DEAD` | All of `LOW_TEXTURE`, `LOW_LIGHT`, `VIO_LOST` simultaneously, OR every perceptual producer reports `validity == INVALID`. | All producers report `VALID` for `nominal_hold_ms × 2`. |

All thresholds live in `docs/specs/uncertainty.md` and `configs/perception/*.yaml`; they are tunable per scenario but the **names of the modes are frozen**.

### 4. Mode transitions are events

Every transition between perception modes is published as an `Event` on the bus (per ADR-0006) with severity ≥ `WARN`. Transitions are logged to telemetry. This guarantees that any incident in simulation or hardware leaves a trace in MCAP that can be replayed (per ADR-0003).

### 5. Estimator obligations

State estimators (Phase 3 onwards) MUST:

- Tag every output `NavigationState` with the highest-restrictive `validity` among their inputs over the last `validity_window_ms`.
- Inflate `covariance_15x15` whenever any input is `DEGRADED` or `STALE`, using the inflation models documented in `docs/specs/uncertainty.md`. No silent fallback to nominal covariance.
- Publish a `PERCEPTION_MODE_CHANGED` event on every transition.

### 6. What this ADR does **not** decide

- **Behavioral response per mode** (hover, slow ascent, blind RTL, kill) — that is ADR-0009.
- **Concrete VO/SLAM algorithm choice** — that is a Phase 4 decision.
- **Exact covariance inflation models** — those live in `docs/specs/uncertainty.md` and may evolve without an ADR, as long as the contract above holds.
- **ML-based perception failure detection** — explicitly out of scope. ML may be an opt-in consumer of the catalog, never a replacement.

## Consequences

**Positive.**

- A single, named vocabulary for perception failure across the codebase. Code review can reject ad-hoc thresholds.
- Telemetry and replay carry mode transitions automatically, so any flight incident is reproducible.
- ADR-0009 can be a thin behavioral policy on top of a stable mechanism layer.
- `Estimate[T]` makes covariance presence a type-level concern. A consumer that forgets to check `validity` is visible in review.
- Backends that lack ground truth (Gazebo, hardware) are not penalized: `Estimate.covariance == None` is illegal there by construction.

**Negative.**

- `Estimate[T]` wrapping adds boilerplate at every module boundary. Mitigated by helpers in `core.uncertainty`.
- The catalog is closed. Adding a new mode requires a new ADR (or an explicit "this ADR supersedes 0008" if the change is structural). This is deliberate — silent expansion of failure-mode taxonomies is exactly how SLAM stacks rot.
- Thresholds need empirical tuning per scenario. Default values above are starting points, not promises.
- Estimators must implement covariance inflation explicitly; this is non-trivial work in Phase 3.

## Alternatives considered

**A. Implicit confidence scalars only.** Producers emit a single `confidence ∈ [0, 1]`; consumers decide what to do. Rejected: opacifies what "0.4 confidence" means across modules; covariance information is lost; mission code accumulates magic numbers.

**B. Per-module ad-hoc failure flags.** Each consumer invents its own checks. Rejected: this is the status quo we are escaping. It produces untestable behavior under degradation.

**C. Continuous "health score" instead of discrete modes.** Single scalar per perception channel. Rejected: control and mission code want to dispatch on a few qualitative states, not threshold-on-a-float. A continuous score can still exist *inside* a mode (for fine-grained covariance inflation), but the boundary contract is discrete.

**D. Learned failure detector (anomaly model).** A model classifies perception quality. Rejected as the *primary* mechanism: not interpretable, not deterministic, not auditable, breaks replay. May be added later as an opt-in producer whose output flows through the same `Estimate` envelope.

**E. Defer the decision to ADR-0009.** Reject the split; put modes and behavior in one document. Rejected: mechanism (this ADR) and policy (ADR-0009) have different change rates. The catalog is structural and should not be coupled to behavioral debates.

**F. `Optional[T]` instead of `Estimate[T]`.** Use Python's standard option type and rely on documentation for uncertainty. Rejected: option type collapses `STALE` and `INVALID` into `None`; covariance has nowhere to live; producers cannot communicate degradation without losing the value.
