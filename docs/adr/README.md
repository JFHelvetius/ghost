# Architecture Decision Records

This directory holds the project's **significant architectural decisions**.

## Rules

- An ADR documents **a single decision**.
- ADRs are **immutable** once accepted. Changing a decision requires a new ADR that supersedes the old one.
- Sequential numbering, padded to four digits: `0000-`, `0001-`, ...
- Format: Markdown with mandatory sections `Context`, `Decision`, `Consequences`, `Alternatives considered`, `Status`.

## Possible statuses

- **Proposed** — under discussion.
- **Accepted** — active.
- **Superseded by ADR-NNNN** — replaced.
- **Deprecated** — abandoned without replacement.

## Index

| ID | Title | Status |
|---|---|---|
| [ADR-0000](0000-vision.md) | Vision | Accepted |
| [ADR-0001](0001-hal-first.md) | HAL First | Accepted |
| [ADR-0002](0002-deterministic-simulation.md) | Deterministic Simulation | Accepted |
| [ADR-0003](0003-telemetry-everywhere.md) | Telemetry Everywhere | Accepted |
| [ADR-0004](0004-backend-independence.md) | Backend Independence | Accepted |
| [ADR-0005](0005-canonical-vehicle-state.md) | Canonical Vehicle State | Accepted |
| [ADR-0006](0006-event-driven-core.md) | Event Driven Core | Accepted |
| [ADR-0007](0007-hardware-migration-strategy.md) | Hardware Migration Strategy | Accepted |
| [ADR-0008](0008-perception-failure-modes.md) | Perception Failure Modes and Uncertainty Propagation | Accepted (catalog amended by ADR-0010) |
| [ADR-0009](0009-autonomy-under-uncertainty.md) | Autonomy Under Uncertainty | Accepted (pilot override amended by ADR-0011) |
| [ADR-0010](0010-revised-perception-mode-catalog.md) | Revised Perception Mode Catalog and Parameter Coupling Discipline | Accepted |
| [ADR-0011](0011-t0-safety-vetoes-pilot.md) | T0 Safety Vetoes Over Pilot Input | Accepted |
| [ADR-0012](0012-run-retention-policy.md) | Run Retention Policy | Accepted |
| [ADR-0013](0013-run-analysis-artifacts.md) | Run Analysis Artifacts | Accepted |
| [ADR-0014](0014-behavior-traceability-v1.md) | Behavior Traceability v1 | Accepted |
| [ADR-0015](0015-noisy-ground-truth-estimator.md) | Noisy Ground Truth Estimator | Accepted |
| [ADR-0016](0016-belief-traceability-report-v1.md) | Belief Traceability Report v1 | Accepted |
| [ADR-0017](0017-belief-consistency-analysis-v1.md) | Belief Consistency Analysis v1 | Accepted |
| [ADR-0018](0018-comparative-belief-analysis.md) | Comparative Belief Analysis with Provenance Manifests v1 | Accepted |
| [ADR-0019](0019-belief-calibration-honesty-check-v1.md) | Belief Calibration Honesty Check v1 | Accepted |
| [ADR-0020](0020-belief-self-assessment-v1.md) | Belief Self-Assessment v1 | Accepted |
| [ADR-0021](0021-belief-to-action-contract-layer-v1.md) | Belief-to-Action Contract Layer v1 | Accepted |
| [ADR-0022](0022-decision-trace-verification-v1.md) | Decision Trace and Chain Verification v1 | Accepted |
| [ADR-0023](0023-action-emission-contract-layer-v1.md) | Action Emission Contract Layer v1 | Accepted |
