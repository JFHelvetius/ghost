# ADR-0010 — Revised Perception Mode Catalog and Parameter Coupling Discipline

- **Status:** Accepted
- **Date:** 2026-06-04
- **Relationship to prior ADRs:** Amends ADR-0008 §3 (Mode catalog) and §6 (Out-of-scope). The rest of ADR-0008 (`Estimate[T]`, `Validity`, composition rules, telemetry obligations, estimator obligations) remains in force unchanged.

## Context

The uncertainty red-team review (`docs/reviews/uncertainty_red_team_review.md`) raised two structural problems with ADR-0008 that cannot be resolved by tuning or documentation alone:

1. **The closed catalog of seven `PerceptionMode` values has at least one obvious gap.** Mechanical vibration at high throttle degrades both IMU and camera simultaneously without saturating either, producing motion blur and feature instability that fall through the cracks of `LOW_TEXTURE` and `IMU_SATURATION`. The review labelled this `MOTION_AGGRESSIVE`. Several other candidates (`DUST`, `WATER_DROP_ON_LENS`, `HORIZON_GLARE`) were raised but as discutibles. ADR-0008 explicitly froze the catalog and required an ADR for any change. This is that ADR.
2. **ADR-0008 (mechanism) and ADR-0009 (policy) are not as decoupled as they appear.** Changing a threshold in ADR-0008 (e.g. `min_features`, `min_luminance`) silently shifts the qualitative behavior produced by ADR-0009 (e.g. `slow_ascend_mps`, `low_texture_max_speed_mps`), because the policy values are calibrated against the entry criteria of the mode. The review called for a list of "coupled parameters" that must be reviewed jointly. Without this discipline, the first threshold adjustment after Phase 1 will break the policy invisibly.

These two issues bundle naturally because both are catalog-and-tuning hygiene: one adds a mode, the other constrains how the mode's parameters move over time. Splitting them across ADRs would create cross-references for no benefit.

## Decision

### 1. New mode: `MOTION_AGGRESSIVE`

The catalog is extended by one mode. The closed catalog is now eight modes (the seven of ADR-0008 plus this one).

| Mode | Entry criterion | Exit criterion |
|---|---|---|
| `MOTION_AGGRESSIVE` | Commanded body rates exceed `aggressive_rate_threshold_rps` (default 3.0 rad/s on any body axis) **or** measured body acceleration exceeds `aggressive_accel_threshold_mps2` (default 12 m/s², excluding gravity), sustained for ≥ `aggressive_window_ms` (default 200 ms) **and** at least one perception producer reports degradation in the same window. | All commanded rates and measured acceleration below 70 % of the entry thresholds for `nominal_hold_ms × 2` (default 400 ms), and no degradation reports from any perception producer in the same window. |

Behavioral mapping (extends ADR-0009 §2):

| Mode | Active tier | Behavior |
|---|---|---|
| `MOTION_AGGRESSIVE` | T2 | Cap commanded body rates to `aggressive_rate_threshold_rps × 0.6`. Cap commanded acceleration to `aggressive_accel_threshold_mps2 × 0.6`. Continue mission with reduced envelope. If perception does not recover within `aggressive_recovery_timeout_ms` (default 2000), downgrade to `LOW_TEXTURE` behavior. |

`MOTION_AGGRESSIVE` does not override pilot input directly — capping is applied through the actuator mixer with explicit telemetry of the cap (`PILOT_COMMAND_CLIPPED` event). Pilot override semantics are governed by ADR-0011.

### 2. Considered-and-rejected modes (appendix)

The following candidates were considered and **not** added to the catalog. Each rejection is documented so that future readers can revisit with new evidence.

| Candidate | Rejection reason |
|---|---|
| `DUST` | Hardware-only failure mode with no sim equivalent. Deferred: if observed during U6 with measurable frequency, open ADR-0014 to add. Until then, manifests as `LOW_TEXTURE` with elevated entry threshold; this loss of granularity is acceptable for Phases 1–8. |
| `WATER_DROP_ON_LENS` | Hardware-only and intermittent. Deferred to U6 evaluation. Until then, manifests as transient `LOW_TEXTURE` or `VIO_LOST` depending on coverage; behaviorally indistinguishable from those modes. |
| `HORIZON_GLARE` | Subsumed under a revised `LOW_LIGHT` criterion that includes "AGC saturated at *minimum* gain ≥ `low_light_window_ms`" as well as the maximum-gain saturation already covered in `uncertainty.md` §7. The criterion update is documented in `uncertainty.md`. |
| `THERMAL_SHIMMER` (hot environment optical artifact) | Out-of-scope for declared environments. Project Ghost does not commit to operation in environments where thermal shimmer is dominant. Documented as risk in red team review §3.x. |
| `EM_INTERFERENCE` (compass and IMU disturbance) | Project Ghost does not consume magnetometer, so compass interference does not apply. Strong EM affecting IMU is captured by existing `IMU_SATURATION` thresholds. |
| `MULTIPATH_VIO` (specular surfaces causing reflective feature mismatches) | Subsumed under `MAP_AMBIGUOUS`, which already covers loop-closure ambiguity. Single-frame multipath without map effect is below current detection sensitivity; revisit if U5 dataset shows it as a dominant failure mode. |

These rejections are not immutable — they are dispositions at this point in time. Adding any to the catalog later requires an ADR superseding or extending this one.

### 3. Parameter coupling discipline

The following pairs of parameters span ADR-0008 (mechanism via `docs/specs/uncertainty.md` §7) and ADR-0009 (policy via §2). Adjusting either side of a coupled pair without explicit review of the other side is forbidden.

| Mechanism parameter (entry criterion) | Coupled policy parameter (behavior) | Why coupled |
|---|---|---|
| `low_texture.min_features` | `low_texture_max_speed_mps` | Aggressive speed at the boundary of texture loss accelerates tracking failure; the cap must keep the per-frame displacement below the feature reacquisition window. |
| `low_light.min_luminance` | `low_light.slow_ascend_mps`, `low_light.recovery_altitude_m` | Lower luminance threshold means we enter the mode in darker scenes; ascent must be slower (more conservative) when entry implies less light overall. |
| `imu_saturation.saturation_threshold_frac` | `imu_recovery_hold_ms`, `imu_kill_threshold_ms` | Lower saturation threshold means more frequent transient entries; recovery and kill timers must lengthen to avoid spurious kills. |
| `vio_lost.vio_timeout_ms`, `vio_lost.innovation_fail_count` | `dr_hover_window_ms`, `dr_abort_covariance_pos_m` | A faster declaration of VIO loss must be followed by a tighter dead-reckoning budget; otherwise the system drifts further before aborting. |
| `map_ambiguous.ambiguity_margin` | Replan policy on map ambiguity (mission.md §5) | A tighter ambiguity margin produces more frequent replans; budget for replanning frequency must be re-examined. |
| `perception_dead` entry (all-`INVALID`) | `dead_descent_mps`, `kill_altitude_m` | Wider conditions for `PERCEPTION_DEAD` entry must be paired with more conservative descent and kill behaviors. |
| `motion_aggressive.aggressive_rate_threshold_rps` | `aggressive_rate_threshold_rps × 0.6` cap | Cap factor is defined relative to entry threshold; changing one must explicitly re-validate the other. |
| `nominal_hold_ms` | All "for `nominal_hold_ms × N`" timers in policy | The base unit propagates everywhere; changes ripple. |

Discipline:

- A PR that modifies a mechanism parameter MUST update or explicitly justify the coupled policy parameter in the same PR.
- The change description in `runs/<run_id>/manifest.yaml` includes a `coupling_check` field that is set automatically by tooling (to be implemented in U1) and asserts the coupling was evaluated.
- Any ADR that revises one side of a coupled pair MUST cross-reference and confirm the disposition of the other side.

This is not a runtime check; it is a review-time and tooling-time check. Runtime cannot detect "the operator forgot to adjust the coupled value".

### 4. What this ADR does **not** decide

- **It does not relax the catalog's closedness.** New modes still require a superseding or amending ADR.
- **It does not enumerate every possible coupling forever.** New parameters introduced by future ADRs must be examined for coupling and the table above updated by the same ADR.
- **It does not change tier definitions, validity semantics, `Estimate[T]`, or composition rules from ADR-0008.**
- **It does not redefine T0 invariants from ADR-0009 §4.**

## Consequences

**Positive.**

- The single most-likely missing mode is now in the catalog before U1 starts, preventing a Phase 3 scramble.
- The considered-and-rejected appendix gives future contributors a head start when they observe a candidate failure mode: they can check this table before opening an ADR.
- Coupled parameters are visible. Reviewers can reject ad-hoc threshold changes that ignore the coupling.
- The discipline does not constrain implementation; it constrains review. Cost is small, expected value of caught mistakes is high.

**Negative.**

- The catalog grows from seven to eight modes. Every consumer (detector, estimator, mission planner) must handle one more case. Mitigated: all are dispatched through the `PerceptionMode` enum, so the cost is mechanical.
- The coupling table is opinionated and partial. Couplings outside the table may exist and go unnoticed. Mitigated: red-team passes against future ADRs explicitly check for new couplings.
- Tooling for `coupling_check` in manifest is new work for U1.

## Alternatives considered

**A. Add `MOTION_AGGRESSIVE` as a sub-state of `LOW_TEXTURE`.** Reuse the existing mode and parameterize it. Rejected: behaviorally distinct (cap maneuver vs. cap speed), entry criterion is command-driven not measurement-driven, mixing them would muddy the catalog's principle that names map to single mechanisms.

**B. Add all four candidates (MOTION_AGGRESSIVE, DUST, WATER_DROP, HORIZON_GLARE) now.** Rejected: only `MOTION_AGGRESSIVE` has clear sim coverage and a clear behavioral response. The others would be added blind, calibrated against nothing, and risk catalog inflation. Hardware data from U6 is the right gate.

**C. Document coupling as a "best practice" in the spec without ADR-level commitment.** Rejected: the review correctly identified that the mechanism/policy decoupling claim was a structural assertion of ADR-0008+ADR-0009. Walking it back requires the same level of formality.

**D. Replace the closed catalog with an open extensible registry.** Rejected: open extensibility is exactly the failure mode the architecture review §2.7 warned about in other contexts. Discrete, named, ADR-gated modes survive contact with the codebase; open registries do not.

**E. Defer the catalog revision to a "Phase 1.5 cleanup".** Rejected: every spec and roadmap downstream of ADR-0008 references the catalog. Revising it after U1 lands means rewriting U2/U3 entry criteria and any code that switches on the enum. Cost grows monotonically with delay.
