# Project Ghost

A research-grade autonomy platform for drones, built around a single core idea:

> **Autonomy under uncertainty.** The system must know when it knows, know when it does not know, and alter its behavior accordingly.

The end goal is autonomous navigation in unknown environments **without GPS**, based on vision and IMU, evolving from simulation to real hardware. The system treats uncertainty as a first-class engineering object: measured, propagated, visualized, tested, and reasoned about — never hidden behind heuristics.

> **Status:** Phase 1 implementation in progress. 36 ADRs accepted; closed-loop reference smoke wired end-to-end; **5 formal safety properties** verifiable byte-exact against any captured run.

## The headline claim

Project Ghost is the only open-source robotics codebase (that we know of) that ships a formal property set you can verify in one shell command:

```bash
$ ghost verify-properties --mcap path/to/run.mcap
BAUD-v1: HOLDS  (M=4, K=2, 6/10 cycles evaluated)
ERUR-v1: HOLDS  (M=4, K=2, 4/10 cycles evaluated)
MD-v1:   HOLDS  (10/10 cycles evaluated)
RLB-v1:  HOLDS  (W=32, 0/10 cycles evaluated)
FPB-v1:  HOLDS  (fire_fraction=0.60, 6/10 cycles evaluated)
```

Five properties, five citable claims, exit code `0` iff every property holds. Each verifier is a pure function over the MCAP — no replay, no simulation, no trust in the producer.

### The five properties

| ID | Property | Claim |
|---|---|---|
| **BAUD-v1** | Bounded Action Under Drift ([ADR-0031](docs/adr/0031-bounded-action-under-drift-property-v1.md)) | When prediction error signals drift, the agent emits no non-conservative action |
| **ERUR-v1** | Eventual Reactivation Under Recovery ([ADR-0032](docs/adr/0032-eventual-reactivation-under-recovery-property-v1.md)) | When drift is absent and belief is KNOWN, the agent reactivates PROCEED |
| **MD-v1** | Monotonic Degradation ([ADR-0033](docs/adr/0033-monotonic-degradation-property-v1.md)) | The calibration policy never invents confidence (`adjusted >= raw` in lattice) |
| **RLB-v1** | Recovery Latency Bound ([ADR-0034](docs/adr/0034-recovery-latency-bound-property-v1.md)) | Dirty-run length is bounded by `peak + W - 1` where W is the window size |
| **FPB-v1** | False Positive Bound observer ([ADR-0035](docs/adr/0035-false-positive-bound-property-v1.md)) | Empirical BAUD fire rate is exposed and bounded for regression gating |

The honest part: the individual ideas (uncertainty calibration, action gating on confidence, fault detection) are decades-old robotics research. The contribution of Ghost is not new theory — it's **the specific combination, end-to-end, with byte-exact replay verification and a CLI-grade external surface**. See [ADR-0031 §Context](docs/adr/0031-bounded-action-under-drift-property-v1.md) for the honest framing.

## Try it in 60 seconds

```bash
# Clone, set up, run the 10-cycle closed-loop reference smoke.
git clone https://github.com/JFHelvetius/project-ghost
cd project-ghost
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[telemetry,app,dev]"

# Run the smoke — produces an MCAP at ./closed_loop_smoke.mcap and self-verifies
# the property set inline.
python -m project_ghost.examples.closed_loop_smoke

# Verify the captured MCAP from the shell, as any third party would.
ghost verify-properties --mcap closed_loop_smoke.mcap

# JSON output for CI / external citation:
ghost verify-properties --mcap closed_loop_smoke.mcap --json

# Or use the Streamlit dashboard:
ghost-app
```

Every MCAP produced by `closed_loop_smoke` carries its **own inline property veredicto** in `SmokeSummary.{baud,erur,md,rlb,fpb}_report`. The CLI is the external surface; the inline reports are the self-evidence.

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
| 0 | Foundations: architecture, 36 ADRs, specs | ✅ Done |
| Uncertainty U1–U7 | Self-assessment → action contract → calibration → forward prediction → divergence → closed-loop feedback → replay verification | ✅ Done |
| Property set | BAUD / ERUR / MD / RLB / FPB verifiers + CLI + smoke witnesses | ✅ Done |
| 1 | PyBullet simulator + telemetry + manual control | In progress |
| 2 | Stabilization (PID cascade) | Pending |
| 3 | State estimation (EKF + VO) | Pending |
| 4 | SLAM | Pending |
| 5 | Planning (A*, MPC) | Pending |
| 6 | Autonomous navigation | Pending |
| 7+ | HIL and real hardware | Pending |

**What works today**: the closed-loop reference smoke runs an 8-step
pipeline (fusion → self-assessment → calibration feedback → decision
→ actuation → forward prediction → divergence → next cycle) end-to-end
in <1 second, materialises an MCAP, and verifies five formal safety
properties against it. 1653 tests passing, ruff + mypy strict clean.

A parallel research track tackles uncertainty-aware autonomy across phases U1–U6 (see [research track](docs/roadmaps/research_track_uncertainty.md)).

## Supported backends

Project Ghost officially supports three backends through its lifetime:

- **PyBullet** — fast iteration, deterministic, used in Phases 1–3.
- **Gazebo + PX4 SITL** — high-fidelity simulation, MAVLink path, used from Phase 4.
- **Real hardware** — Pixhawk + Linux companion computer, used from Phase 9+.

Other simulators (Isaac Sim, AirSim, Webots) are possible community backends; they are not core commitments.

## Documentation

- [Architecture](docs/architecture.md)
- [ADRs](docs/adr/) — 36 architectural decisions. Highlights:
  - [ADR-0009](docs/adr/0009-autonomy-under-uncertainty.md) *Autonomy Under Uncertainty* — the founding decision
  - [ADR-0026..0027](docs/adr/) *Closed-Loop Feedback* + *Calibration-Aware Decision Context* — the wiring that makes the property set meaningful
  - [ADR-0030](docs/adr/0030-replay-verification-v1.md) *Replay Verification v1* — byte-exact reproducibility of every channel
  - [ADR-0031..0035](docs/adr/) *Property set* — the five citable safety claims
- [Specs](docs/specs/) — frozen contracts (HAL, sensors, actuators, state, clock, telemetry, events) and uncertainty/mission/perception specs
- [Reviews](docs/reviews/) — adversarial reviews of the architecture and of the uncertainty design
- [Phase 1 plan](docs/roadmaps/phase1.md) and [Research track U1–U6](docs/roadmaps/research_track_uncertainty.md)

## CLI surface

```bash
ghost --help                      # list subcommands
ghost verify-properties --help    # ADR-0031..0035 verifier
ghost analyze-run --help          # RunSummary report
ghost trace-decisions --help      # belief→decision chain verification
ghost-app                         # Streamlit dashboard for interactive runs
```

All subcommands operate on captured MCAPs offline; no network, no
long-running processes, exit codes follow CI conventions (`0` =
success / property holds, `1` = property violated or runtime error,
`2` = argument error).

## Layout

```
project-ghost/
├── docs/
│   ├── adr/                    36 architectural decisions
│   ├── specs/                  Frozen contracts (HAL, sensors, ...)
│   ├── architecture.md         Top-level overview
│   ├── reviews/                Adversarial design reviews
│   └── roadmaps/               Phase + research-track plans
├── src/project_ghost/
│   ├── core/
│   │   ├── fusion/             Belief construction from sensors (ADR-0028)
│   │   ├── uncertainty/        Self-assessment + thresholds (ADR-0020)
│   │   ├── feedback/           Calibration policy + history (ADR-0026)
│   │   ├── decisions/          Decision context + policy (ADR-0021/0027)
│   │   ├── actuation/          Action emission contract (ADR-0023/0029)
│   │   └── prediction/         Forward prediction + divergence (ADR-0024/0025)
│   ├── properties/             5 property verifiers (ADR-0031..0035) ★
│   ├── examples/
│   │   ├── closed_loop_smoke.py    8-step reference pipeline + inline verification
│   │   └── replay_verification.py  Byte-exact downstream replay (ADR-0030)
│   ├── app/                    Streamlit dashboard (ghost-app)
│   ├── telemetry/              MCAP sink + replay reader + adapters
│   ├── analysis/               RunSummary, calibration reports, decision traces
│   ├── traceability/           Behavior + belief traceability reports
│   ├── hal/, sensors/, actuators/, state/, events/, simulation/
│   └── cli.py                  ghost CLI dispatcher
├── tests/
│   ├── properties/             ~50 property tests (sanity + Hypothesis + adversarial)
│   ├── integration/            Closed-loop end-to-end
│   └── [core/, telemetry/, ...]   Unit + contract tests per package
├── scripts/                    Auxiliary CLIs
└── .github/workflows/          CI
```

★ = the externally-citable surface.

## Contributing

Phase 0 is closed-circle work; no formal external contribution flow yet. Issues with questions or criticism are welcome. Before proposing major changes, read `docs/architecture.md` and the active ADRs.

## License

[Apache License 2.0](LICENSE). No additional clauses.
