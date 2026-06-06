# Project Ghost

A research-grade autonomy platform for drones, built around a single core idea:

> **Autonomy under uncertainty.** The system must know when it knows, know when it does not know, and alter its behavior accordingly.

The end goal is autonomous navigation in unknown environments **without GPS**, based on vision and IMU, evolving from simulation to real hardware. The system treats uncertainty as a first-class engineering object: measured, propagated, visualized, tested, and reasoned about — never hidden behind heuristics.

> **Status:** Phase 0 — foundations. Architectural documentation frozen; Phase 1 implementation pending.

## Why

Most open-source drone autonomy projects fall into one of two extremes: academic demos that break when the simulator changes, or GPS-dependent stacks that are useless indoors. Project Ghost is built to survive five years of evolution and to run on real hardware at the end of the road, without rewriting the higher layers. More importantly, it is built to be honest about what it does not know — to fail gracefully, to explain itself, and to remain useful under degraded perception.

## Principles

- **Sim-first, hardware-eventual.** Same code in sim and on hardware; the backend changes, not the cognitive layers.
- **HAL before features.** No SLAM or control until the HAL contract is frozen and validated.
- **Absolute determinism in simulation.** Same seed + same scenario = same trajectory, bit for bit.
- **Obsessive telemetry.** Every bus message is persisted to MCAP.
- **Explicit math, no black boxes.** Filters, optimization, and control are implemented in legible form. ML only as an opt-in complement.
- **Uncertainty as a first-class object.** Every estimate carries value + covariance + confidence + validity + timestamp + source.
- **Open source, Apache 2.0, closed models forbidden.**

## Current status

| Phase | Content | Status |
|---|---|---|
| 0 | Foundations: architecture, ADRs, specs | In progress |
| 1 | PyBullet simulator + telemetry + manual control + replay | Pending |
| 2 | Stabilization (PID cascade) | Pending |
| 3 | State estimation (EKF + VO) | Pending |
| 4 | SLAM | Pending |
| 5 | Planning (A*, MPC) | Pending |
| 6 | Autonomous navigation | Pending |
| 7 | End-to-end mission (exploration) | Pending |
| 8+ | HIL and real hardware | Pending |

A parallel research track tackles uncertainty-aware autonomy across phases U1–U6 (see [research track](docs/roadmaps/research_track_uncertainty.md)).

## Supported backends

Project Ghost officially supports three backends through its lifetime:

- **PyBullet** — fast iteration, deterministic, used in Phases 1–3.
- **Gazebo + PX4 SITL** — high-fidelity simulation, MAVLink path, used from Phase 4.
- **Real hardware** — Pixhawk + Linux companion computer, used from Phase 9+.

Other simulators (Isaac Sim, AirSim, Webots) are possible community backends; they are not core commitments.

## Documentation

- [Architecture](docs/architecture.md)
- [ADRs](docs/adr/) — architectural decisions, including ADR-0009 *Autonomy Under Uncertainty*
- [Specs](docs/specs/) — detailed contracts (HAL, sensors, actuators, state, clock, telemetry, events) and uncertainty/mission/perception specs
- [Reviews](docs/reviews/) — adversarial reviews of the architecture and of the uncertainty design
- [Phase 1 plan](docs/roadmaps/phase1.md) and [Research track U1–U6](docs/roadmaps/research_track_uncertainty.md)

## Quickstart (Phase 1, when implemented)

```bash
git clone <repo>
cd project-ghost
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[sim,telemetry,dev]"
python -m project_ghost.run --config configs/phase1/manual_pybullet.yaml
```

## Layout

```
project-ghost/
├── docs/                       Documentation, ADRs, specs, roadmaps
├── src/project_ghost/          Source
│   ├── core/                   Base types, clock, RandomSource, config
│   ├── hal/                    HAL Protocols and messages
│   ├── state/                  Canonical VehicleState, transforms
│   ├── events/                 Event bus
│   ├── telemetry/              Telemetry bus, sinks (MCAP, Rerun)
│   ├── simulation/             Simulation backends (PyBullet in Phase 1)
│   ├── sensors/                Generic providers
│   └── actuators/              Generic sinks, safety envelope, mixer
├── tests/                      Unit, integration, conformance, scenario
├── scripts/                    Auxiliary CLIs
└── .github/workflows/          CI
```

## Contributing

Phase 0 is closed-circle work; no formal external contribution flow yet. Issues with questions or criticism are welcome. Before proposing major changes, read `docs/architecture.md` and the active ADRs.

## License

[Apache License 2.0](LICENSE). No additional clauses.
