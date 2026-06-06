# ADR-0000 — Vision

- **Status:** Accepted
- **Date:** 2026-06-03
- **Deciders:** Project lead

## Context

Many drone autonomy projects exist. Most fall into one of three buckets:

1. **Academic demos** that die at the first simulator change or first contact with real hardware.
2. **Closed commercial systems** (DJI, Skydio) impractical for open research.
3. **GPS-dependent stacks** (PX4 + GPS + camera) that collapse in GPS-denied settings.

We need to fix **what Project Ghost is and is not**, because without this decision every other choice gets contaminated: simulator selection, estimator architecture, allowed dependencies, even the contents of the HAL.

The declared mission is autonomous navigation **without GPS** in unknown environments, based on vision + IMU, starting in simulation and evolving to real hardware, all open source and at near-zero cost. The project also commits to treating uncertainty as a first-class engineering object (see ADR-0009).

## Decision

Project Ghost commits to the following binding axioms:

1. **Vision-inertial first.** The navigation estimator is built on camera + IMU. Any other sensor (GPS, magnetometer, LiDAR) may exist in the API but **does not feed** the main estimator. Its use is restricted to evaluation, monitoring, or optional redundancy.
2. **Sim-first, hardware-eventual.** The system is developed and validated in simulation. Real hardware is a medium-term goal (Phase 8+), not a Phase 1 requirement.
3. **Open source with a permissive license.** Apache 2.0. No closed components or private weight models.
4. **Explicit math.** Filters, optimization, control, and planning are implemented in legible form. ML acts as an optional complement, never as a substitute for classical reasoning.
5. **Near-zero cost.** The stack must run on a modest laptop. Hardware target ~150 USD.
6. **Five-year shelf life.** Every decision is evaluated by its maintenance cost over five years.
7. **Uncertainty as a first-class object.** No subsystem produces a value without an associated uncertainty representation (see ADR-0009).

## Consequences

**Positive:**

- Clear focus: any feature that does not contribute to GPS-denied vision-inertial autonomy is out of scope.
- Differentiation: few open-source projects pursue GPS-denied rigorously, and fewer treat uncertainty as a research object.
- Reuse: the HAL and canonical state are useful for other projects.

**Negative:**

- Higher initial engineering effort: VIO/SLAM is harder than a PID + GPS loop.
- Recurring temptation to "just use GPS for now" during debugging. Must be actively resisted.
- Small initial community: few contributors with expertise in visual estimation.

## Alternatives considered

**A. Conventional GPS-aided autopilot.** Rejected: contradicts the core mission. If that were the goal, PX4 and ArduPilot already solve it.

**B. LiDAR-first SLAM.** Rejected on cost (cheap LiDAR ~300 USD minimum) and because it closes the door on micro platforms. Vision-only preserves form factor and price.

**C. End-to-end reinforcement learning system.** Rejected: black boxes, not interpretable, require massive training, hostile to verification, do not transfer to hardware without an enormous gap.

**D. ROS 2 stack from day one.** Rejected: barrier of entry on Windows, complicates deterministic replay, and adds a heavy dependency before it is needed. ROS 2 will enter as an optional adapter from Phase 4.

**E. Accept GPS as estimator input "because it is available in sim".** Rejected explicitly: breaks the mission. GPS exists in the API only for groundtruth evaluation, never as a navigation input.
