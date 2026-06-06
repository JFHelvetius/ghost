# ADR-0003 — Telemetry Everywhere

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

Debugging autonomy without total observability is blind. A failure in SLAM, the planner, or the controller is rarely reproducible from a verbal description; it requires evidence: full state, sensors, commands, and events, in order and with times.

Robotics projects historically pick from three paths:

1. **Text logging (stdout / logging.py).** Useful for errors; useless to reconstruct state and trajectories.
2. **ROS bag.** Standard in ROS, but drags the ROS dependency, partially deprecated format (rosbag1 → mcap), and tools dependent on the ecosystem.
3. **Custom binary.** Fragile across versions, non-standardized, no inspection tools.

We need something useful for: debugging, replay, comparative benchmarks, datasets for optional ML, and external toolchains (Foxglove, plot.ly, pandas). Project Ghost adds a further requirement: the telemetry stream must be amenable to **uncertainty introspection**, i.e. every estimate logged carries its uncertainty.

## Decision

Project Ghost adopts an **obsessive telemetry** policy:

1. **Every bus message is persisted.** Every `SensorSample`, `VehicleState`, `ActuatorCommand`, `CommandAck`, and `Event` that crosses the bus is written to the run log, together with the uncertainty envelope where applicable.
2. **MCAP as primary format.** Open, indexed, multi-channel, supported by Foxglove. One run = one `runs/<run_id>/log.mcap` file.
3. **Versioned Protobuf schemas.** Each message type has a `.proto` in `protos/`. The `schema_version` field allows forward evolution.
4. **Rerun as a secondary live sink.** Not the source of truth: visualization. Active in dev by default, optional in CI.
5. **Per-run manifest** (`manifest.yaml`): seed, config hash, git SHA, world, sim time range, schema versions. A run without a valid manifest is not accepted as an artifact.
6. **Hot loop never blocks on I/O.** Writing runs in a background thread with a queue; sinks declare their drop policy:
   - MCAP: large queue, almost never drops (a drop forces `TELEMETRY_BACKPRESSURE` event).
   - Rerun: drop-oldest with per-channel quota.
   - Console: only severity ≥ WARN.
7. **Compressed images by default** (JPEG 85). Lossless under flag for SLAM datasets or evaluation.

A benchmark spike of the Protobuf write path is mandatory before Phase 1 closes (see `docs/roadmaps/phase1.md`, task T4). If the spike shows Protobuf cannot sustain target rates without excessive GC pressure, an addendum ADR will reopen format selection (Cap'n Proto, MessagePack, or batched Protobuf).

## Consequences

**Positive:**

- Any sim-observed bug can be revived from the log without re-running the simulation.
- Comparative benchmarks become trivial: two runs, two MCAPs, metric diff.
- Foxglove / plot.ly / pandas are immediate: MCAP tooling exists.
- Datasets for optional ML come for free.

**Negative:**

- Disk cost: a 5-minute run with compressed camera weighs ~100–500 MB. Retention policy required.
- Maintaining Protobuf schemas adds friction to dataclass evolution.
- Sink backpressure can degrade visualization on intensive runs.
- Close latency: at the end of the run, the queue must be drained; the harness must wait for flush.

## Alternatives considered

**A. Rerun only, no persistent file.** Rejected: Rerun is not a long-term archive and is not ideal for analytical datasets.

**B. ROS 2 bag (MCAP).** Considered. Rejected because it drags ROS 2 into the project from Phase 1, contradicting ADR-0006. MCAP itself is kept; only the ROS dependency is dropped.

**C. JSON-Lines logs per channel.** Rejected: not binary-readable, no indices, no efficient multi-channel support.

**D. Synchronous logging from the hot loop.** Rejected: introduces jitter and random drops in sensors and controllers. Unacceptable for determinism.

**E. Log only a subset of channels.** Rejected on philosophy: "what is not logged cannot be debugged". Disk cost is bearable; bugs without evidence are not.
