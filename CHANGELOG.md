# Changelog

All notable changes to Project Ghost are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-06-10

Major addition: a fourth layer of evidence for the property set —
mechanical verification by TLA+ / TLC, **proved continuously green in
CI**.

### Added

- **ADR-0036 — TLA+ Mechanical Verification of BAUD-v1 / ERUR-v1 /
  Partition (Accepted)**. The TLA+ specification at
  [`docs/proofs/BaudErur.tla`](docs/proofs/BaudErur.tla) is exhaustively
  model-checked by TLC over the full reachable state space of the
  abstract model (bounded constants `M=2, K=1, W=3`). Five invariants
  hold:
  - `INV_BAUD` — formal statement of BAUD-v1's precondition →
    postconditions implication.
  - `INV_ERUR` — formal statement of ERUR-v1's precondition →
    postconditions implication.
  - `INV_PARTITION` — the BAUD + ERUR partition theorem proven on the
    abstract model (promoted from "observed on smoke trace" to
    "proven everywhere"); the first project claim to make that
    promotion.
  - `INV_NO_INVENTED_CONFIDENCE` — formal statement of MD-v1.
  - `INV_HISTORY_BOUND` — structural sliding-window sanity.
- **CI self-enforcement of TLA+**: `.github/workflows/ci.yml`'s new
  `tla-plus` job downloads `tla2tools.jar`, runs TLC on every push,
  fails the build on any invariant violation, uploads `tlc_output.log`
  as a build artifact.
- **Drift-then-recovery smoke**
  (`closed_loop_smoke_with_recovery.py`): engineered so RLB-v1 fires
  exactly one recovery transition at the bound `L = peak + W - 1`
  (38 = 7 + 32 − 1), proving the bound is tight. Strong RLB witness
  in CI complementing the vacuous sustained-drift smoke.
- 12 integration tests for the recovery smoke pinning the per-property
  shape and cross-property invariants.
- Docs site `proofs/` section with the formal artifacts, plus
  `docs/properties/proofs.md` surfacing TLA+ as the fourth evidence
  layer.

### Changed

- `run_closed_loop_smoke()` accepts a private `_ground_truth_fn`
  parameter. Byte determinism of the sustained-drift smoke is
  preserved exactly by the default.
- README and docs site `index.md` updated to mention the TLA+ proof
  alongside the verifier + property tests.

### Fixed

- Multi-layer CI lint cleanup: 119 files reformatted by `ruff format`,
  31 C408 dict-literal rewrites, plotly added to mypy missing-imports
  override, several real bugs surfaced in the process (covariance
  attribute typo, unused type-ignore comments, untyped streamlit
  decorator).
- `pytest -m conformance` now treats exit code 5 ("no tests
  collected") as success — the conformance marker is reserved for
  HAL backend suites that will be added later.

### Honest scope of the new layer

Read [ADR-0036 §4](docs/adr/0036-tla-plus-mechanical-verification-of-baud-erur.md#4-what-this-does-and-does-not-claim)
for the full framing. Summary of what TLA+ DOES NOT prove:

- That the Python implementation faithfully mirrors the TLA+ model
  (the bridge is by human inspection).
- That the bounded constants prove the unbounded case (TLC is
  exhaustive within bounds; property tests cover production scale).
- Any property of non-reference policy pairs.

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

[Unreleased]: https://github.com/JFHelvetius/ghost/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/JFHelvetius/ghost/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/JFHelvetius/ghost/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/JFHelvetius/ghost/releases/tag/v0.1.0
