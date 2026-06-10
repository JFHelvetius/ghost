# Changelog

All notable changes to Project Ghost are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-06-09

First release published through the automated PyPI workflow
([`.github/workflows/release.yml`](.github/workflows/release.yml)).
Same code shape as v0.1.0, with the addition of the
drift-then-recovery smoke and supporting CI extension.

### Added

- **Drift-then-recovery smoke** (`closed_loop_smoke_with_recovery.py`):
  engineered to fire exactly one RLB-v1 recovery transition with
  `L = peak + W - 1`, hitting the bound exactly and proving it tight.
  50 cycles total (8 drift + 42 recovery). Strong CI witness for
  RLB that the sustained-drift smoke leaves vacuous.
- 12 integration tests pinning the per-property shape and
  cross-property invariants of the recovery smoke
  (`tests/integration/test_closed_loop_smoke_with_recovery.py`).
- CI `verify-properties` job now runs both smokes and uploads
  4 artifacts (2 MCAPs + 2 JSON reports).
- `docs/properties/rlb.md` updated with the recovery-smoke example
  output and bound-tightness narrative.
- Automated PyPI release workflow with OIDC trusted publishing.
- MkDocs Material documentation site
  (https://JFHelvetius.github.io/ghost/).
- `CITATION.cff` for academic citation (renders the GitHub "Cite this
  repository" button).
- `CONTRIBUTING.md` and this `CHANGELOG.md`.

### Changed

- `run_closed_loop_smoke()` now accepts a private `_ground_truth_fn`
  parameter, defaulting to the original `_ground_truth_pose`. Byte
  determinism of the existing sustained-drift smoke is preserved
  exactly.
- Streamlit dashboard now surfaces the 5-property panel in the run
  results.
- README headline rewritten to lead with the property set + live
  dashboard CTA + docs site CTA.

## [0.1.0] - 2026-06-09

First versioned release of Project Ghost. Establishes the formal
safety property set as the project's central contribution.

### Added

- **Five formal safety properties**, each citable, each verifiable
  byte-exact from any captured MCAP:
  - [BAUD-v1](docs/adr/0031-bounded-action-under-drift-property-v1.md) —
    Bounded Action Under Drift. When drift is detected, the agent
    emits no non-conservative actuator command.
  - [ERUR-v1](docs/adr/0032-eventual-reactivation-under-recovery-property-v1.md) —
    Eventual Reactivation Under Recovery. When drift is absent and
    belief is KNOWN, the agent reactivates PROCEED.
  - [MD-v1](docs/adr/0033-monotonic-degradation-property-v1.md) —
    Monotonic Degradation. The calibration policy never invents
    confidence.
  - [RLB-v1](docs/adr/0034-recovery-latency-bound-property-v1.md) —
    Recovery Latency Bound. Dirty-run length is bounded by
    `peak + W - 1`.
  - [FPB-v1](docs/adr/0035-false-positive-bound-property-v1.md) —
    False Positive Bound observer. Empirical BAUD fire rate is
    exposed and bounded for regression gating.
- **Public verifier API** (`project_ghost.properties.*`): `verify_baud`,
  `verify_erur`, `verify_md`, `verify_rlb`, `verify_fpb`, plus the
  matching `BAUDVerificationReport` / `ERURViolation` / etc. dataclasses.
- **CLI subcommand**: `ghost verify-properties --mcap <path>` with
  text and `--json` output, exit code `0` iff all properties hold.
- **Inline self-evidence**: every `SmokeSummary` returned by
  `run_closed_loop_smoke` now carries five property reports
  (`baud_report`, `erur_report`, `md_report`, `rlb_report`, `fpb_report`)
  computed against the just-written MCAP.
- **Self-enforcing CI**: `.github/workflows/ci.yml` `verify-properties`
  job runs the smoke and verifies the property set on every push.
  Property violations block the build.
- ~50 new property tests in `tests/properties/` covering sanity
  (smoke MCAP), Hypothesis-based property tests (200+ examples each
  for BAUD/ERUR/FPB, 80+ for RLB, 300+ for MD), and named
  adversarial scenarios.
- 8-step closed-loop reference smoke
  (`project_ghost.examples.closed_loop_smoke`) wiring fusion →
  self-assessment → calibration feedback → decision → actuation →
  forward prediction → divergence → next cycle, end-to-end in
  <1 second.
- Streamlit dashboard with EN/ES i18n and Plotly charts
  (https://project-ghost.streamlit.app/).
- PyPI-ready packaging with `mcap` as a base dependency so the CLI
  works out of the box after `pip install project-ghost`.

### Properties of note

- v0.1.0 corresponds to ADRs 0000–0035 (36 architectural decisions).
- 1665 tests passing, ruff + mypy strict clean.
- All property reports are deterministic: same MCAP bytes produce
  byte-identical JSON output across machines.

[Unreleased]: https://github.com/JFHelvetius/ghost/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/JFHelvetius/ghost/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/JFHelvetius/ghost/releases/tag/v0.1.0
