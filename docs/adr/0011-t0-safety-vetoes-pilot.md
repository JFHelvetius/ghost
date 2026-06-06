# ADR-0011 — T0 Safety Vetoes Over Pilot Input

- **Status:** Accepted
- **Date:** 2026-06-04
- **Relationship to prior ADRs:** Amends ADR-0009 §5 (Human override). The rest of ADR-0009 — tier definitions, behavioral mapping per mode, uncertainty-aware planning, T0 safety invariants of §4, and honesty obligations — remains in force unchanged.

## Context

ADR-0009 §5 defined pilot input as a T2-level authority that may be upgraded to T0 by an explicit kill or RTL command. The same section explicitly allowed the pilot to force the vehicle into a worse-quality envelope (for example, demanding an aggressive maneuver under `LOW_TEXTURE`), with the system complying and merely logging a `PILOT_OVERRIDE_DEGRADED` event.

The uncertainty red-team review (§2.7) attacked this as "modeling the pilot the designer would like, not the pilot real systems encounter":

- Under stress, pilots over-correct yaw when they see drift, producing IMU saturation precisely when perception is already degraded.
- Pilots demand "RTL now" when blind RTL is the worst available option because the path home is worse than holding position.
- Pilots ignore visual warnings if the vehicle appears stable.

The review's recommendation was a small, named list of `(PilotIntent × PerceptionMode)` combinations where T0 actively vetoes the pilot. This is not paternalism in general; it is functional safety for combinations where the joint of "what the pilot wants" and "what the system knows about the world" produces a foreseeable accident.

The decision to introduce T0 vetoes over pilot input is **architecturally load-bearing**. It changes the meaning of "human override" from "human is always the higher authority below safety invariants" to "human is the higher authority *except in this named list*". This is a deliberate, narrow change.

## Decision

### 1. Pilot intent vocabulary

Pilot inputs are classified into a small set of `PilotIntent` values for the purpose of T0 evaluation. Classification happens at the input layer (per `docs/specs/sensors.md` and the manual input module in Phase 1) using documented rules:

| `PilotIntent` | Trigger |
|---|---|
| `MANUAL_FLIGHT` | Continuous stick input within nominal envelope. Default for any non-special input. |
| `AGGRESSIVE_MANEUVER` | Stick input requesting body rate above `aggressive_pilot_rate_threshold_rps` (default 2.5 rad/s) **or** sustained at > 80 % of stick travel for > 500 ms. |
| `REQUEST_RTL` | Explicit RTL command from controller, regardless of inputs. |
| `REQUEST_LAND` | Explicit LAND command from controller. |
| `REQUEST_KILL` | Explicit KILL command from controller. |
| `RELEASE_TO_AUTO` | Explicit handoff back to T3. |

Pilot intent classification is a **producer**, not a consumer, of the safety supervisor. It carries the same telemetry and event obligations as any other producer.

### 2. Veto table (the load-bearing decision)

T0 vetoes the pilot **only** for the following combinations. Each row specifies what T0 does instead; T0 may not invent vetoes outside this list without an amending ADR.

| `PilotIntent` | `PerceptionMode` | T0 action | Why |
|---|---|---|---|
| `AGGRESSIVE_MANEUVER` | `VIO_LOST` | Cap rates to `aggressive_rate_threshold_rps × 0.6` (per ADR-0010 §1). Emit `PILOT_VETOED` with reason. | Aggressive maneuver during VIO loss extends dead-reckoning displacement, often past `dr_abort_covariance_pos_m` before the pilot recognizes the problem. The cap is a soft veto; pilot retains directional control. |
| `AGGRESSIVE_MANEUVER` | `IMU_SATURATION` | Cap rates to zero for the residual `imu_recovery_hold_ms`. Pilot inputs deferred, not discarded. | Adding rate command on a saturated IMU compounds estimator divergence. The deferral is short; pilot does not lose authority, just timing. |
| `AGGRESSIVE_MANEUVER` | `PERCEPTION_DEAD` | Reject. Engage controlled descent per ADR-0009 §2. Emit `PILOT_VETOED`. | No perceptual basis for any maneuver. Pilot cannot override what the system cannot see. |
| `REQUEST_RTL` | `PERCEPTION_DEAD` | Reject RTL; engage controlled descent in place. Emit `PILOT_VETOED` with reason "blind_rtl_unsafe". | Blind RTL with covariance growing past `dr_abort_covariance_pos_m` is more dangerous than landing in place. |
| `REQUEST_RTL` | `VIO_LOST` (covariance already past 80 % of `dr_abort_covariance_pos_m`) | Reject RTL; engage `dr_hover_window_ms` first, then re-evaluate. If still past 80 % at end of window, controlled descent. | Same reasoning, gradient form. |
| `REQUEST_RTL` | Geofence excursion expected on home path | Reject. Engage hover and emit `OPERATOR_DECISION_REQUIRED`. | RTL that violates geofence is a safety invariant violation; T0 invariants (ADR-0009 §4) cannot be bypassed by pilot. |
| `RELEASE_TO_AUTO` | any non-`NOMINAL` mode | Reject. T3 cannot be engaged in degraded modes (ADR-0009 §3.5). Emit event explaining mode. | Authority transfer to deliberative layer requires the layer's preconditions. Pilot cannot will them into existence. |

`REQUEST_KILL` and `REQUEST_LAND` are **never vetoed**. T0 prerogative to commit them is preserved as the ultimate pilot authority; the safety supervisor may upgrade them (e.g. switch LAND to KILL on imminent ground contact) but may not refuse.

### 3. Veto telemetry contract

Every veto produces a `PILOT_VETOED` event on the bus with severity `WARN` (or `ERROR` for `PERCEPTION_DEAD` cases). The event carries:

- `intent`: the `PilotIntent` value.
- `mode`: the active `PerceptionMode`.
- `action`: what T0 did instead (one of `cap`, `defer`, `reject`, `replace_with_<x>`).
- `reason`: short cause string from the table above.
- `pilot_input_snapshot`: numeric snapshot of the pilot inputs at the moment of veto.

These events are persisted in MCAP. Any post-incident review of a flight that ended badly starts by enumerating `PILOT_VETOED` events.

### 4. Veto cannot be disabled at runtime

There is no runtime flag, no config option, and no scenario field that disables the table in §2. Hardware deployments may **tighten** the table (add rows) via scenario config or an addition to this ADR; no deployment may remove rows.

Sim deployments may not loosen either; the table is the same in sim and on hardware. This is intentional: incidents that appear in sim with vetoes engaged are exactly the incidents we want surfaced before hardware.

### 5. Out-of-scope

- **General paternalism.** T0 does not refuse pilot input when the table does not name the combination. The default remains: pilot input is T2 authority, recorded honestly via `PILOT_OVERRIDE_DEGRADED` as in ADR-0009 §5.
- **Skill-based gating.** No "pilot certification level" gating. The same vetoes apply to all human inputs.
- **Predictive vetoes.** T0 vetoes on the current `(intent, mode)` pair, not on a forecast that the pilot is about to do something dangerous. Forecast vetoes belong to a future ADR if at all.
- **Mission-level pilot interactions.** Pilot requests for mission changes (waypoint additions, abort) are handled in `mission/` per ADR-0009 §3, not by T0.

## Consequences

**Positive.**

- A specific set of pilot decisions that statistically end flights badly are now blocked or softened by the system, not by the pilot's recovery skill under stress.
- The list is short, named, and ADR-gated. Future engineers can audit it without reading code.
- The default for non-listed combinations remains "pilot has authority", preserving the design philosophy of recording rather than overriding.
- The vetoes are the same in sim and hardware, so simulator runs that exercise pilot overrides under degradation produce identical envelope to flight tests.

**Negative.**

- A pilot who knows the airframe better than the system will, at some point, be vetoed wrongly. The cost is borne by the pilot; the project does not provide an escape hatch by design. Mitigation: vetoes are softer than termination (cap, defer) wherever physically possible; only `PERCEPTION_DEAD` combinations are hard rejections, and there is no good outcome there anyway.
- Adding T0 logic increases the surface where a bug can ground a flight. Mitigation: vetoes are evaluated on a small, named set of inputs with no internal state; the implementation is straightforward and testable.
- Vetoes complicate the pilot UX: the pilot's stick inputs may not produce expected motion. Mitigation: every veto emits an event; pilot HUD (Phase 8+) renders veto state explicitly.

## Alternatives considered

**A. No vetoes; rely on documentation.** Current ADR-0009 §5 stance. Rejected by the review and confirmed here: the costs of pilot-induced crashes during the project's hardware track outweigh the costs of a small, surfaced authority restriction.

**B. Generic "expert mode" toggle that disables all vetoes.** Rejected: defeats the safety purpose, and the population of pilots that need such a toggle is, in this project, exactly the pilot. Self-overrides at 3 a.m. are how incidents happen.

**C. Vetoes as gradients (smooth degradation of pilot authority).** Replace discrete vetoes with continuous attenuation of pilot input as covariance grows. Rejected: harder to predict, harder to test, indistinguishable from "the pilot stick feels mushy", which generates over-correction precisely in the failure regime. Discrete is clearer.

**D. Vetoes driven by a learned policy.** A model predicts when pilot intent will likely cause an incident and vetoes accordingly. Rejected: not interpretable, not auditable, and the data to train it does not exist. The named list is opinionated and reviewable.

**E. Pilot retains absolute authority below T0 invariants of §4.** This is the status quo of ADR-0009 §5. Rejected: §4 invariants are geometric/electrical (geofence, altitude, comms, NaN); they do not cover the perception-state-dependent dangers this ADR addresses.

**F. Wider veto table covering all `(intent × mode)` combinations.** Rejected: the table is opinionated precisely about combinations with foreseeable bad outcomes. Wider lists are paternalism without evidence; this ADR explicitly avoids that posture.
