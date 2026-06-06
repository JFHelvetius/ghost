# ADR-0004 — Backend Independence

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

ADR-0001 establishes that the HAL is built first. ADR-0004 complements it: defines **how** we ensure the upper layers never couple to a concrete backend.

Without mechanical rules, coupling sneaks in: an `import pybullet` "just for this function", a type-cast on an internal simulator object, a backend-specific optimization through a global variable. After a year, "swap the backend" implies massive rewriting.

## Decision

Three binding mechanisms:

1. **Hard import rules.**
   - `ghost.hal` imports only `numpy`, `typing`, `dataclasses`, `core`. Importing simulators, ROS, MAVSDK, OpenCV, or Torch is forbidden.
   - Each backend lives in `ghost.simulation.<name>/` with isolated dependencies. `ghost.simulation.pybullet` does not import `ghost.simulation.gazebo_px4` and vice versa.
   - Cognitive layers (`perception`, `estimation`, `slam`, `mapping`, `planning`, `control`, `mission`) import only `core`, `hal`, `state`, `events`, `telemetry`, and their own deps. They **never** import `simulation.<name>`.
   - Validated in CI with `import-linter` or `deptry`.

2. **Capability discovery.**
   - Each backend exposes a `Capabilities` object declaring: available sensors, supported actuator levels, groundtruth availability, synchronous-step support, replay support.
   - The rest of the system queries `capabilities` before assuming. Example: if `caps.synchronous_step is False`, the harness adjusts the test mode.
   - Capabilities are part of the HAL contract and versioned with `HAL_PROTOCOL_VERSION`.

3. **Conformance test suite.**
   - `tests/hal_conformance/` contains tests parametrized per backend.
   - Any new backend must pass the **full** suite to be considered valid.
   - Includes: determinism of `reset(seed)`, monotonicity of `clock.now_ns()`, no cross-mutation of samples, correct rejection of invalid commands, valid ack of correct commands, recovery after `shutdown()` and a new `reset()`.

For backend-specific extensions (e.g. GPU buffer access in Isaac Sim if a future community backend is added), the mechanism is:

- The reserved `extensions: Mapping[str, Any]` field in messages.
- A specific capabilities flag (`caps.has_gpu_buffers`).
- The consumer is responsible for handling the absence of the feature.

**Scope of "supported".** Only PyBullet, Gazebo+PX4 SITL, and the hardware backend are officially supported. Other simulators are welcome as community contributions but are not part of the core maintenance commitment.

## Consequences

**Positive:**

- Adding a backend = new subpackage + passing conformance. Zero risk of breaking other backends.
- CI detects coupling before merge, not weeks later.
- Migration to real hardware reuses the same mechanism: new backend, conformance + specific safety tests.

**Negative:**

- Some backend-specific optimizations require the `extensions` escape hatch, which adds conditional code in consumers.
- The conformance suite has to be maintained: each new HAL feature must add a corresponding test.
- Some verbosity in initialization code (consult capabilities before using features).

## Alternatives considered

**A. Discipline without enforcement.** Rejected: entropy always wins. Without a linter, couplings come back.

**B. Dependency injection without Protocols.** Rejected: loses type checking. With `typing.Protocol`, static checking is gained without forced inheritance.

**C. Adapter pattern with an abstract base class.** Considered. Rejected in favor of Protocols, which allow duck typing and lightweight mock testing without forced inheritance.

**D. A single "abstract" backend on top of Gym/Gymnasium.** Rejected: Gym is an API for RL, not for multi-sensor robotic autonomy. It would force the system to conform to a model it does not fit.
