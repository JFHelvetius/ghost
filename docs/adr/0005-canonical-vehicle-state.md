# ADR-0005 — Canonical Vehicle State

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

The "vehicle state" is the system's most-read object: control needs it, estimation produces it, mission consults it, telemetry logs it, replay reconstructs it. If its shape is discovered late or changes often, the whole system suffers.

Decisions about frame conventions and orientation representation are **especially expensive to revert**. Switching from ENU to NED after six months means reviewing every rotation matrix, every filter sign, every plot, and all documentation. Switching from Hamilton to JPL quaternion produces silent bugs for months.

Project Ghost additionally requires that the state object can carry **uncertainty** alongside the value, per ADR-0009. The canonical state must accommodate covariance, validity, and confidence without breaking when future estimators introduce richer uncertainty representations.

## Decision

Project Ghost freezes a canonical `VehicleState` with the following binding conventions:

### Frame and unit conventions

| Aspect | Decision |
|---|---|
| World frame | **ENU** (East-North-Up); z=0 at scene ground |
| Body frame | **FLU** (Forward-Left-Up) |
| Quaternion | **Hamilton, w-first** `[w, x, y, z]`; compatible with `scipy.spatial.transform.Rotation` |
| Units | Strict SI. No feet, no miles, no knots, no pounds |
| Angles | Radians in structures; degrees only in config/UI |
| Precision | `float64` for pose, velocities, covariances, biases; `float32` acceptable only in image/depth buffers |

### Structure

`VehicleState` (frozen dataclass) composed of:

- `stamp_sim_ns: int` and `stamp_wall_ns: int`
- `nav: NavigationState` with `pose` (pos ENU + quat), `twist_world`, `twist_body`, `accel_body`, `imu_biases`, `covariance_15x15: np.ndarray | None`, plus an `uncertainty: NavUncertainty` envelope (see `docs/specs/uncertainty.md`)
- `sensors: SensorHealthMap` (status per `SensorId`)
- `flight: FlightStatus` (armed, mode, battery, error_flags)
- `mission: MissionStatus` (mode, current goal, progress)
- `schema_version: int = 1`

### Evolution rules

- `VehicleState` is **frozen**. Each cycle produces a new object.
- **Array hardening.** All `np.ndarray` fields inside `VehicleState` and its children are set to `flags.writeable=False` at construction time. This converts the "treat as immutable" convention into a runtime guarantee: any attempt to mutate raises `ValueError`. Producers may construct arrays mutably and seal them at the dataclass boundary.
- Adding fields: allowed; increments `schema_version` and adds an entry to the schema changelog.
- Removing fields: forbidden. They are marked optional/`None` during deprecation for at least one major release.
- **State holds no raw sensor data.** It is the output of the estimator. Images and raw samples travel on bus channels.
- Conversion to/from external conventions (PX4 NED/FRD, JPL quaternion, ROS frames) happens **in the boundary adapter**, never scattered.

## Consequences

**Positive:**

- A single structure across all layers. No internal translations.
- Compatible with most of the Python scientific ecosystem (ENU/FLU is ROS REP-103; Hamilton w-first is scipy).
- Frozen + sealed arrays = no accidental in-place mutation, including by tests that pass state into estimators.
- Versioned = trivial to serialize and replay.

**Negative:**

- Integrating PX4 (NED/FRD) requires adapters. They are isolated but must be maintained.
- scipy's `Rotation.from_quat()` is x,y,z,w; our convention is w,x,y,z. The boundary helper must always be used.
- `float64` in covariances + full state at 50 Hz produces non-trivial telemetry bandwidth.
- Sealing arrays forces producers to be explicit; in-place updates inside an estimator must happen on a private mutable buffer before sealing into a new state object.

## Alternatives considered

**A. NED/FRD (PX4 / classical aeronautical).** Seriously considered. Rejected because most Python dependencies (matplotlib 3D, Open3D, ROS REP-103, scipy) assume ENU. Adopting NED would force constant conversions in visualization and in every external library.

**B. JPL quaternion (x,y,z,w).** Rejected: scipy uses Hamilton internally; using JPL forces constant reorderings and produces sign bugs. Although JPL is more common in classical aerospace, in scientific Python Hamilton w-first is the path of least resistance.

**C. 3x3 rotation matrices as primary representation.** Rejected: 9 floats vs 4, no gain; more expensive to propagate in filters; renormalization and orthogonality maintenance is costly.

**D. Euler angles as primary.** Rejected: singularities (gimbal lock), ambiguity of convention (XYZ, ZYX, ...), worse numerical behavior in estimation.

**E. Mutable shared state with copy under lock.** Rejected: introduces complex concurrency, breaks deterministic replay, multiplies bugs. Frozen + new-on-update is simpler and fast enough in Python.

**F. `float32` for everything to reduce bandwidth.** Rejected: covariances lose precision quickly in long filters; the telemetry saving does not offset the numerical cost.

**G. Skip array sealing, rely on documentation.** Rejected: experience shows the in-place mutation bug will appear within months. The five-line cost of sealing buys runtime safety.
