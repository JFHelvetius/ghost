# ADR-0029 — Trajectory Controller Reference v1

## Status

Accepted

## Context

`KillOnlyActuationPolicy` (ADR-0023) is a floor: it translates only
`ENGAGE_KILL` into a `DirectMotorCommand`; every other decision kind
produces `actuator_command=None`. This is deliberate — the ADR-0023
scope is the *contract shape*, not a real controller.

The closed-loop smoke (ADR-0028) surfaces the gap: 4 `PROCEED` cycles
produce directives with `actuator_command=None`. The pipeline is wired
end-to-end but `PROCEED` decisions are behaviorally inert: the system
decides to proceed but emits nothing.

A minimal reference is needed that:

1. Proves the `AttitudeCommand` type round-trips through the pipeline.
2. Shows that `PROCEED` decisions can produce commands.
3. Remains composable — real attitude controllers override this by
   implementing `ActuationPolicy` with the same shape.

## Decision

Introduce `AttitudeHoldReferencePolicy` in `core.actuation`. Mapping:

| `decision.kind` | `actuator_command` | `reason` |
|---|---|---|
| `PROCEED` | `AttitudeCommand(identity, proceed_thrust)` | `attitude_hold_proceed` |
| `HOLD` | `AttitudeCommand(identity, hold_thrust)` | `attitude_hold_hold` |
| `ENGAGE_KILL` | `DirectMotorCommand([0,0,0,0])` | `kill_zero_throttle` |
| any other | `None` | `no_command_for_<kind>` |

Parameters: `proceed_thrust: float` (default `0.5`) and
`hold_thrust: float` (default `0.5`), both in `[0.0, 1.0]`. Identity
quaternion `[1, 0, 0, 0]` (no rotation from NED body frame); this is
the minimal attitude target that satisfies the `AttitudeCommand` contract.

Update the closed-loop smoke (ADR-0028) to use
`AttitudeHoldReferencePolicy` in place of `KillOnlyActuationPolicy`.
This makes the 4 `PROCEED` directives produce `AttitudeCommand`
instances rather than `None`.

Policy ID: `attitude_hold_v1`.

## Consequences

- `PROCEED` and `HOLD` decisions now produce commands in the pipeline.
  `AttitudeCommand` records flow through the `/actuations` MCAP channel.
- `KillOnlyActuationPolicy` is not removed — it remains valid as a
  safety floor. Operators choose between them; the smoke uses the
  attitude hold reference to exercise the full type set.
- No trajectory planning, no belief-dependency, no PD/PID gains. This
  reference emits a fixed attitude target regardless of the current
  belief. Real attitude controllers compose over the same
  `ActuationPolicy` Protocol.

## Alternatives considered

- **Extend KillOnlyActuationPolicy** — rejected; separation of concerns.
  Kill-only is a valid safety floor. Adding attitude commands there
  would conflate two distinct roles.
- **VelocityCommand / PositionCommand** — rejected for this reference.
  Attitude is the lowest-level command type that is universally
  meaningful; velocity/position commands require a flight controller
  loop to translate down to motors. Attitude is closer to the hardware
  boundary and thus more appropriate for a minimal reference.
- **Parameterize by belief** — deferred. A real controller reads the
  belief to compute a trajectory-tracking attitude command. This
  reference ignores the belief intentionally, as a composable layer
  beneath trajectory planning.
