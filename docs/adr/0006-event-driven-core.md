# ADR-0006 — Event Driven Core

- **Status:** Accepted
- **Date:** 2026-06-03

## Context

System modules need to communicate. Classical options:

1. **Direct calls.** Simple but coupling. The planner calling `control.set_setpoint()` implies the planner knows control.
2. **ROS 2 (DDS).** Industrial standard. Solves communication but drags heavy dependencies, complicates determinism and replay.
3. **Internal pub/sub bus.** Low coupling, in-process, no network.

We also need to distinguish two traffic types:

- **Periodic:** sensors at 200 Hz, state at 50 Hz, commands at 100 Hz. Continuous flow.
- **Discrete semantic:** takeoff, landing, sensor_fault, collision, mission_start. Low frequency, high meaning, often requiring priority.

Mixing both on the same channel complicates policies (how much to drop, what to block) and obscures semantics.

## Decision

Project Ghost adopts:

1. **In-process pub/sub bus, asyncio-agnostic**, implemented in `ghost.events` and `ghost.telemetry`. No network, no serialization for inter-module communication.
2. **Two conceptual channel families:**
   - **Stream channels** (`/sensors/*`, `/state/*`, `/cmd/*`): periodic, ordered, with per-sink drop policies.
   - **Event channel** (`/events`): `Event` messages with severity, source, payload, and `correlation_id`. Total order guaranteed.
3. **Standard severities.** `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL`. The `CRITICAL` ones (KILL, COLLISION, SAFETY_VIOLATION) deliver synchronously to the safety subscriber before continuing the step.
4. **Ordered delivery by `(stamp_sim_ns, sequence)`.** Sequence is a global atomic counter. Same seed + same scenario → same order, guaranteed.
5. **ROS 2 deferred to Phase 4 as an optional adapter.** When it appears, it will be an additional sink/source translating between the internal bus and ROS topics, without replacing it.
6. **No agent frameworks.** LangChain, LlamaIndex, AutoGen, and similar are not used. Autonomy is a classical FSM/behavior tree, not LLM orchestration. This is reinforced by ADR-0009.

## Consequences

**Positive:**

- Minimal coupling: any module is replaced by another with the same pub/sub interface.
- High testability: each module is tested with a mock bus that captures published messages.
- Determinism preserved: delivery order does not depend on the OS or the Python scheduler.
- Simple replay: read `/events` from the MCAP and re-inject into the bus.

**Negative:**

- Initial cost: implementing the bus, total-order tests, backpressure management.
- Loss of static typing on bus contracts if channel names are bare strings. Mitigated with constants in `core.channels` and type aliases.
- Multithreading is complicated: if subscribers run in different threads, ordered delivery requires (typically) a single dispatcher thread.

## Alternatives considered

**A. ROS 2 from day one.** Rejected. Heavy install on Windows, hostile to determinism (DDS reorders under QoS), complicates replay (rosbag2 works but is tied to ROS). Easier to add later as an adapter than to remove later.

**B. Direct calls + DI.** Considered. Works in small systems; fails when 5–6 modules collaborate. Also prevents trivial replay: reproducing requires reconstructing the entire object graph in order.

**C. ZeroMQ inproc.** Considered. Faster than pure-Python pub/sub but introduces an external dep, serialization (even if optional), and hinders type checking. Unnecessary for in-process traffic.

**D. LLM-in-the-loop agent framework.** Rejected categorically. Latency incompatible with autonomy, not verifiable, contradicts ADR-0000 (explicit math) and ADR-0009 (uncertainty as engineering object).

**E. Topic-based callbacks without total order.** Rejected: loses determinism, introduces sometimes-only reproducible bugs.
