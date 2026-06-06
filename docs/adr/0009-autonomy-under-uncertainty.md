# ADR-0009 — Autonomy Under Uncertainty

- **Status:** Accepted
- **Date:** 2026-06-04

## Context

ADR-0008 freezes the **mechanism** layer for perception failure: a typed `Estimate[T]` envelope, a `Validity` ladder, and a closed catalog of `PerceptionMode` values with quantitative entry criteria. It deliberately stops short of saying *what the vehicle should do* in each mode.

ADR-0000 commits the project to a single behavioral principle: *the system must know when it knows, know when it does not know, and alter its behavior accordingly.* The architecture red-team review (§2.6) is sharper: without a documented degradation policy, the GPS-denied autonomy claim is marketing.

A behavioral policy under uncertainty has to resolve, at minimum, four questions:

1. **What does the vehicle do** when it enters each perception mode? (Hover? RTL? Land? Hand to pilot?)
2. **Who has authority** — autonomous controller, pre-recorded recovery routine, human pilot, safety supervisor?
3. **How does the mission layer reason about uncertainty** when planning, not only when reacting?
4. **What invariants are non-negotiable** even under degraded perception (kill switch, no-fly geometry, max altitude)?

These are policy decisions with a different change rate than the mechanism. They will be revisited as the project moves from PyBullet to Gazebo+PX4 to hardware. Putting them in a separate ADR keeps the mechanism stable while the policy evolves.

This ADR fixes the policy for Phases 1–6. Phases 7+ (real hardware) may add stricter rules without breaking this contract; they may not loosen it.

## Decision

Project Ghost adopts a **three-tier autonomy stack** in which perception modes (ADR-0008) map to authority transitions, mission-level uncertainty reasoning is explicit, and a small set of safety invariants is enforced unconditionally.

### 1. Tiered autonomy

| Tier | Name | Authority over actuators | When active |
|---|---|---|---|
| T0 | **Safety supervisor** | Veto on every command; cannot generate motion of its own except `STOP`/`KILL`. | Always. |
| T1 | **Reflex layer** | Closed-loop stabilization, attitude/rate control, dead reckoning hold. Deterministic, no perception input. | Always running; takes command when T2/T3 yield. |
| T2 | **Reactive layer** | Behaviors per perception mode (hover, slow ascend, blind RTL). Consumes `Estimate[T]` but uses no global map. | Engaged in `DEGRADED` modes per §2. |
| T3 | **Deliberative layer** | Mission planning, SLAM consumer, frontier exploration. Trusts `VALID` estimates. | Engaged only in `NOMINAL` mode. |

Authority flows downward when uncertainty rises. T3 yields to T2 when leaving `NOMINAL`. T2 yields to T1 in `PERCEPTION_DEAD`. T0 may pre-empt any tier at any time.

### 2. Behavioral response per perception mode

The mapping below is the canonical policy. Modules implementing reactive behaviors MUST consult this table; deviations require an ADR amendment.

| `PerceptionMode` | Active tier | Behavior |
|---|---|---|
| `NOMINAL` | T3 | Mission plan executes normally. |
| `LOW_TEXTURE` | T2 | Reduce horizontal speed to `low_texture_max_speed_mps` (default 0.5). Continue mission if path is collision-free per last known map; otherwise hover and request replan. |
| `LOW_LIGHT` | T2 | Stop forward motion. Hold position with inflated covariance. Emit `RECOVERY_REQUESTED` event. After `low_light_recovery_timeout_ms` (default 5000), ascend slowly at `slow_ascend_mps` (default 0.3) toward `recovery_altitude_m` (default 2.0 above takeoff) seeking texture. |
| `IMU_SATURATION` | T1 + T0 | T2/T3 suspended for `imu_recovery_hold_ms` (default 200). T1 reduces commanded body rates to zero. T0 inspects: if saturation persists > `imu_kill_threshold_ms` (default 1000), escalate to `KILL`. |
| `VIO_LOST` | T2 | Hover on dead reckoning for `dr_hover_window_ms` (default 3000). If VIO does not recover, attempt blind RTL toward takeoff coordinate using IMU integration with growing covariance. If covariance crosses `dr_abort_covariance`, switch to controlled descent. |
| `MAP_AMBIGUOUS` | T2 | Reject loop closures while ambiguous. Continue VO-only navigation. Do not commit map updates. Replan to revisit a previously confident landmark if available. |
| `PERCEPTION_DEAD` | T1 + T0 | All deliberative and reactive control suspended. T1 commands controlled descent at `dead_descent_mps` (default 0.5). T0 monitors altitude; cuts thrust at `kill_altitude_m` (default 0.3 above takeoff). |

Every mapping above is a **default**. Scenario configs (`configs/missions/*.yaml`) may override numeric thresholds but **may not change the active tier or the qualitative behavior**.

### 3. Uncertainty-aware mission planning (T3)

The deliberative layer treats uncertainty as a planning input, not only a runtime signal.

- Plans are scored against an **expected information gain** term and a **risk** term. The risk term integrates expected `validity` along the planned path, using a forward uncertainty model documented in `docs/specs/mission.md`.
- The planner rejects plans whose worst-case predicted covariance exceeds `mission_max_covariance_norm` over a contiguous segment longer than `mission_max_blind_segment_m` (default 5).
- When uncertainty is unavoidable (e.g. crossing a textureless area is required to reach the goal), the planner inserts an explicit **active perception** sub-goal: slow ascent, yaw scan, or revisit of a known landmark before committing.
- Goals carry an `uncertainty_budget`: the planner records, accepts, and exposes the maximum tolerated covariance for each goal. Mission code may not silently exceed the budget.

These mechanisms exist from Phase 5 onward; Phases 1–4 satisfy the contract trivially (no planner, no mission).

### 4. Safety invariants (T0)

The safety supervisor enforces invariants that **no tier may violate**, regardless of perception state. They are evaluated on every actuator command **before** transmission.

| Invariant | Default | Override |
|---|---|---|
| `max_altitude_m` | 30.0 (sim), 5.0 (hardware) | Scenario config; hardware floor `≤ scenario.max_altitude`. |
| `geofence_polygon` | Scenario-defined | Must be present for any non-`empty_room` scenario. |
| `max_battery_age_s` | 1200 | Hardware-only; ignored in sim. |
| `command_freshness_ms` | 200 | Same as ADR-0001 `command_timeout_ns`. |
| `nan_inf_reject` | Always on | Cannot be disabled. |
| `kill_on_loss_of_comms_ms` | None in sim; 5000 on hardware | Cannot be loosened on hardware. |

Any violation produces a `SAFETY_VIOLATION` event with severity `CRITICAL`, an immediate `STOP` or `KILL` command per a small lookup table, and a persistent telemetry record.

### 5. Human override

When a pilot input channel is present (manual flight, Phase 1; HIL, Phase 8; hardware, Phase 9), pilot input is treated as a **T2-level authority** by default and is upgradable to **T0** by an explicit kill or RTL command.

- Pilot input never re-enables a tier the safety supervisor has disabled.
- Pilot input cannot disarm safety invariants from §4.
- A pilot may force the vehicle into a worse mode (e.g. demand aggressive maneuver under `LOW_TEXTURE`); the system complies but logs a `PILOT_OVERRIDE_DEGRADED` event with the active mode and validity at the time.

### 6. Honesty obligations

This section makes explicit a set of practices that follow from the principle "know when you do not know":

- No estimator may publish `validity == VALID` when its input covariance is missing or its innovation gate is failing. The default in ambiguity is `DEGRADED`.
- No planner may consume an `Estimate` without explicitly reading `validity`. Static analysis (Phase 5 task) will enforce this.
- Every `RECOVERY_REQUESTED` event must specify which producer asked for recovery and why. Anonymous recovery requests are rejected.
- Replays surface mode history as a first-class telemetry channel (`/perception/mode`). Any review of an incident starts there.

## Consequences

**Positive.**

- A single document maps every perception failure mode to a behavior. Reviewers can audit the table directly.
- Authority transitions are explicit and testable. T0 is the only tier with veto power; this is the structural reason hardware deployment will not require rewriting upper layers.
- Mission planning that is honest about uncertainty is now a contract, not an aspiration.
- Safety invariants are centralized; hardware can tighten them without touching reactive or deliberative code.
- The pilot model is realistic about how humans actually interact with semi-autonomous systems: they intervene under stress, often making things worse. The system records this rather than denying it.

**Negative.**

- The table in §2 is opinionated. Some choices (e.g. blind RTL after `VIO_LOST`) will need empirical revision. Each revision is an ADR amendment, which is friction. Justified because silent policy drift is worse.
- Active perception in mission planning (§3) is non-trivial to implement; it is deferred to Phase 5+ but the contract is fixed now.
- The pilot override semantics (§5) constrain UX design: the system cannot offer a "trust me, disable safety" mode. This is intentional.
- Hardware-only invariants (battery age, comms loss kill) create a divergence between sim and hardware behaviors. The divergence is bounded and documented, not hidden.

## Alternatives considered

**A. Single monolithic autonomy layer.** No T1/T2/T3 split; one controller does everything with a state machine inside. Rejected: experience in PX4, ArduPilot, and academic stacks shows that mixing reflex with deliberation makes both untestable. The tiered structure is widely validated.

**B. Behavior trees as the policy language.** Adopt a BT framework (py_trees, BehaviorTree.CPP) for §2. Rejected for Phase 1: introduces a runtime dependency and a debugger surface ahead of need. May be revisited at Phase 5 if the table in §2 outgrows hand-written dispatch. The contract here would survive that change.

**C. Continuous-mode controller (no discrete modes).** Mode-free MPC with uncertainty in the cost function. Rejected: not auditable, not interpretable to a pilot, hard to replay-debug. May coexist with this ADR inside a single mode (e.g. NOMINAL) but does not replace the discrete dispatch.

**D. Pilot as T0.** Promote the human pilot above the safety supervisor. Rejected: real pilots make wrong calls under stress (this is the whole reason for autonomy). Safety supervisor invariants are a property of the airframe and its environment, not of pilot intent.

**E. Defer policy to "when we have hardware".** Phase 0 punts on the policy, builds the mechanism, and writes the ADR in Phase 8. Rejected: every Phase 1–7 design decision that touches actuator commands, mission planning, or estimator output depends on knowing what the policy will be. Deferring leaks ad-hoc policy into every layer.

**F. Learn the policy from data (RL).** A learned controller chooses the response per mode. Rejected as the primary policy: not safe to deploy on hardware, not interpretable, breaks replay determinism. Acceptable as an opt-in sub-policy *within* a mode, when its outputs flow through the same actuator boundary and T0 invariants.
