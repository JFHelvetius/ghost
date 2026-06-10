# Project Ghost

!!! quote ""
    **Autonomy under uncertainty.** The system must know when it knows,
    know when it does not know, and alter its behaviour accordingly.

A research-grade autonomy platform for drones built around a single
core idea — and the only open-source robotics codebase that ships a
**formal property set you can verify in one shell command**.

---

## The headline claim

```bash
$ ghost verify-properties --mcap path/to/run.mcap
BAUD-v1: HOLDS  (M=4, K=2, 6/10 cycles evaluated)
ERUR-v1: HOLDS  (M=4, K=2, 4/10 cycles evaluated)
MD-v1:   HOLDS  (10/10 cycles evaluated)
RLB-v1:  HOLDS  (W=32, 0/10 cycles evaluated)
FPB-v1:  HOLDS  (fire_fraction=0.60, 6/10 cycles evaluated)
```

Five properties, five citable claims, exit code `0` iff every
property holds. Each verifier is a pure function over the MCAP — no
replay, no simulation, no trust in the producer.

## Try it without installing anything

[:material-play-circle: Open the live dashboard](https://project-ghost.streamlit.app/){ .md-button .md-button--primary }
[:material-package-variant: Install from PyPI](https://pypi.org/project/project-ghost/){ .md-button }

The hosted dashboard runs the same reference closed-loop smoke and
shows the five property veredictos inline. Same code that
`pip install project-ghost` ships locally.

## The five properties

<div class="grid cards" markdown>

-   :material-shield-alert:{ .lg .middle } **[BAUD-v1](properties/baud.md)**

    Bounded Action Under Drift

    ---

    When prediction error signals drift, the agent emits no
    non-conservative actuator command.

-   :material-restart:{ .lg .middle } **[ERUR-v1](properties/erur.md)**

    Eventual Reactivation Under Recovery

    ---

    When drift is absent and belief is KNOWN, the agent reactivates
    PROCEED.

-   :material-arrow-down-bold:{ .lg .middle } **[MD-v1](properties/md.md)**

    Monotonic Degradation

    ---

    The calibration policy never invents confidence —
    `adjusted >= raw` in the lattice.

-   :material-timer-sand:{ .lg .middle } **[RLB-v1](properties/rlb.md)**

    Recovery Latency Bound

    ---

    Dirty-run length is bounded by `peak + W - 1` where W is the
    calibration history window.

-   :material-chart-line:{ .lg .middle } **[FPB-v1](properties/fpb.md)**

    False Positive Bound observer

    ---

    Empirical BAUD fire rate exposed and bounded for regression
    gating.

</div>

[See the full overview →](properties/index.md)

## Honest framing

The individual ideas Ghost relies on — uncertainty calibration,
action gating on confidence, fault detection and isolation,
calibrated probabilistic predictions — are well-established robotics
research, much of it decades old. **The contribution of Project
Ghost is not new theory.** It is the specific opinionated combination,
end-to-end, with byte-exact replay verification and a CLI-grade
external surface that third parties can use against any captured run
without trusting the producer.

In other words: a *carefully built reference of a pattern that is
discussed more often than it is implemented*.

## Architecture in one diagram

```mermaid
graph LR
    F[Fusion<br/>ADR-0028] --> A[Assessment<br/>ADR-0020]
    A --> C[Calibration<br/>ADR-0026]
    C --> D[Decision<br/>ADR-0021/0027]
    D --> E[Actuation<br/>ADR-0023/0029]
    E --> P[Forward Prediction<br/>ADR-0024]
    P --> O[Divergence<br/>ADR-0025]
    O -.feedback.-> C
    C -. BAUD/ERUR .-> D
    C -. MD .-> C
    O -. RLB/FPB .-> O

    classDef baud fill:#fef3c7,stroke:#b45309
    classDef erur fill:#d1fae5,stroke:#0f766e
    classDef md fill:#e0e7ff,stroke:#3730a3
    classDef rlb fill:#fce7f3,stroke:#a21caf
    classDef fpb fill:#e0f2fe,stroke:#0369a1
```

## Get started

- :material-rocket: **[Quick start](#try-it-without-installing-anything)** — the live dashboard or `pip install project-ghost`
- :material-book-open: **[Architecture](architecture.md)** — system-level overview
- :material-shield-check: **[Properties overview](properties/index.md)** — the five formal claims
- :material-file-document: **[ADRs](adr/README.md)** — 36 architectural decisions
- :material-format-list-bulleted: **[Specs](specs/README.md)** — frozen component contracts

## Status

- **36 ADRs accepted** (ADR-0000 .. ADR-0035) including the property
  set ADR-0031..0035
- **1653 tests passing**, ruff + mypy strict clean
- **Self-enforcing CI**: every push verifies the property set against
  the reference smoke MCAP
- **PyPI-released** via [OIDC trusted publishing](https://docs.pypi.org/trusted-publishers/)
  on tag push — no API tokens stored anywhere

## License

[Apache License 2.0](https://github.com/JFHelvetius/ghost/blob/main/LICENSE).
No additional clauses.
