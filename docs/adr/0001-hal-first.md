# ADR-0001 — HAL First

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

The natural temptation in an autonomy project is to begin with the visible parts: control, estimation, SLAM. This produces systems that work well in one simulator and break when changing to another or to real hardware. Coupling to the concrete simulator contaminates every layer and surfaces late, when fixing it is expensive.

Project Ghost officially supports three backends across its lifetime: PyBullet, Gazebo+PX4 SITL, and real hardware. Other simulators (Isaac Sim, AirSim, Webots) are possible community backends but not core commitments. Any premature coupling to one of them compromises the others.

## Decision

Before implementing **any** functionality in the upper layers (control, estimation, SLAM, planning, mission), the Hardware Abstraction Layer is completed and validated:

1. The Protocols are defined (`SimulationBackend`, `RuntimeBackend`, `SensorProvider`, `ActuatorSink`).
2. The typed dataclasses for messages are defined (`SensorSample`, `ActuatorCommand`, `CommandAck`, etc.).
3. A **conformance test suite** is built (`tests/hal_conformance/`) that any new backend must pass.
4. At least one backend is implemented (PyBullet in Phase 1) and tested against the conformance suite.
5. The `ghost.hal` package imports **no** simulator or hardware-specific library. Validated in CI with `import-linter`.

Only then is development of upper layers authorized.

## Consequences

**Positive:**

- Upper layers are developed against stable, testable contracts using mocks.
- Adding a new backend is isolated work: implement the Protocols + pass the conformance suite. No changes to perception, estimation, control, etc.
- Migration to real hardware reduces to implementing `RuntimeBackend` + a MAVLink adapter. Reduces the risk of the "sim-to-real valley of death".

**Negative:**

- Phase 1 spends weeks on infrastructure before seeing a drone fly autonomously. For a personal project, this is psychologically costly.
- Some backend-specific optimizations (e.g. direct access to Isaac Sim GPU buffers) require extension mechanisms (`Capabilities`, an `extensions` field), which add complexity.

## Alternatives considered

**A. Start with PyBullet directly, abstract when it hurts.** Rejected based on industry experience: retroactive abstraction is always more expensive than anticipated abstraction in systems with multiple expected backends. And if it is postponed, it almost never happens.

**B. Adopt the PX4 HAL (uORB).** Rejected: uORB is C/C++, tied to NuttX, not idiomatic in Python. Its learning curve and maintenance overflow the project scope.

**C. Use the ROS 2 HAL (topics + msgs).** Seriously considered. Rejected for Phase 1 because it drags the entire ROS 2 stack (heavy install on Windows, hostile to determinism, complicates replay). It will be considered as an **optional adapter** from Phase 4 to interop with ecosystem tools.

**D. Do not abstract, lock to a single simulator forever.** Rejected: contradicts the explicit goal of sim-to-sim and sim-to-hardware portability.
