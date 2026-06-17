# Changelog

All notable changes to Project Ghost are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.5] - 2026-06-17

Paper-grade release backing the v0.2.5 manuscript submission
(arXiv preprint + ACM TOSEM regular paper). Aggregates rounds
23–34 of the pre-publication audit: framework formalisation,
property-class additions (ERUR-v2, FPB-v2), the Python↔TLA+
mechanical bridge, the trilingual dashboard, and a bibliography
fully independently verified by the author.

### Added

- **Epistemic Safety Contract framework** (ADR-0045,
  [`src/project_ghost/properties/contract.py`](src/project_ghost/properties/contract.py),
  [`src/project_ghost/properties/framework.py`](src/project_ghost/properties/framework.py)):
  a Python `Protocol` (`EpistemicSafetyContract`) + registry of
  the seven shipped contracts. Adding the eighth property requires
  one `register_contract(...)` call; the framework guarantees the
  recipe is consistent (non-empty scope, dangling-dependency check,
  Protocol conformance, idempotent re-registration).
- **ERUR-v2** (ADR-0040, parameterised drift-precondition variant)
  and **FPB-v2** (ADR-0039, statistical fire-fraction bound with
  Hoeffding + Clopper-Pearson estimators).
- **Python↔TLA+ mechanical bridge** (ADR-0043 + ADR-0046,
  [`tests/properties/test_python_tla_bridge.py`](tests/properties/test_python_tla_bridge.py),
  [`tests/properties/test_python_tla_bridge_full.py`](tests/properties/test_python_tla_bridge_full.py)):
  Hypothesis-checked conformance for 5 of 7 contracts. Closes the
  previously-open "Python ↔ TLA+ bridge by inspection" caveat.
- **Lean 4 partition theorem** discharged, no `sorry`. RLB-v1
  unbounded reduced to a single load-bearing lemma 4 (`sorry`
  documented).
- **Real-telemetry §8.8 discrimination experiment** over three
  structurally distinct PX4 SITL ULogs with independent simulator
  ground-truth (ADR-0037). Discrimination matrix is 18/18 green;
  15/18 cells isolate violations to the expected property.
- **Trilingual dashboard** (EN/ES/中文, 120-key parity) with stable
  tab identity across language switches and content-addressed
  inspect surface.

### Fixed

- Bibliography (round 32–34): removed 1 fabricated entry, 1
  unsubstantiated entry, and 5 entries that could not be
  exhaustively verified before submission. All remaining entries
  independently verified by the author against their primary
  source. `0 bibtex warnings`, `0 undefined references`,
  `0 orphan citations`.
- `pyproject.toml` and `src/project_ghost/__init__.py` bumped to
  `0.2.5` to match the paper.
- Dashboard tab identity (`st.tabs`): stable ASCII labels prevent
  the active tab from resetting on language switch.

## [0.2.2] - 2026-06-12

Excellence pass: six follow-up workstreams (D/F/A/B/E/C) that
strengthen the paper-grade evidence around the property set, the
reproducibility primitive, and the comparison with prior work.

### Added

- **Violation matrix** (Action D,
  [`closed_loop_smoke_violated.py` extended to `violation_matrix.py`](src/project_ghost/examples/violation_matrix.py)):
  systematic taxonomy of six bug categories, one mini-smoke per
  category, each engineered to break exactly one component of the
  closed loop. All six categories produce the expected violation
  on the unmodified verifier. Captured to
  [`docs/paper/outputs/violation_matrix.md`](docs/paper/outputs/violation_matrix.md).
  Demonstrates contribution C3's detection capacity is systematic,
  not anecdotal (paper §8.2).
- **Two alternative calibration policies** (Action F,
  [`src/project_ghost/core/feedback/alternative_policies.py`](src/project_ghost/core/feedback/alternative_policies.py)):
  - `EWMADowngradePolicy(alpha, min_outcomes, threshold)` — EWMA over
    dirty indicator.
  - `PerAxisHysteresisDowngradePolicy(min_outcomes, upper, lower)` —
    per-axis Mahalanobis with hysteresis.

  Both satisfy the `CalibrationAdjustmentPolicy` Protocol and
  MD-v1 by construction. 22 dedicated tests in
  [`tests/core/feedback/test_alternative_policies.py`](tests/core/feedback/test_alternative_policies.py).
  Policy-comparison script
  [`docs/paper/scripts/compare_policies.py`](docs/paper/scripts/compare_policies.py)
  runs the closed-loop smoke under all three policies; the
  verifier is policy-agnostic in code but ERUR violates on the
  alternative policies when verified with the reference's
  `(M=4, K=2)`, revealing that BAUD/ERUR are parameter-specific
  even though the verifier itself generalises (paper §8.4).
- **Three realistic-shape scenarios** (Action B,
  [`src/project_ghost/examples/realistic_scenarios.py`](src/project_ghost/examples/realistic_scenarios.py)):
  `gps_denial`, `slow_biased_drift`, `cascading_failure`. All
  five properties hold under the reference policy on each. Honest
  scope: shape-realistic, not flight-data-real. Roadmap for PX4
  ULog / ROSBag / EuRoC MAV integration documented at
  [`docs/paper/venues/dataset_integration.md`](docs/paper/venues/dataset_integration.md)
  as a future ADR-0037 (paper §8.5).
- **Quantitative benchmark vs RTAMT** (Action E,
  [`docs/paper/scripts/benchmark_vs_rtamt.py`](docs/paper/scripts/benchmark_vs_rtamt.py)):
  head-to-head wall-clock + verdict comparison on the reference
  50-cycle smoke. Ghost (BAUD-v1 exact): HOLDS, 23 ms. RTAMT
  (STL approximation): VIOLATED, 0.15 ms. Verdict difference is
  informative — STL cannot express K-of-M-in-W as a single
  formula. Output captured to
  [`docs/paper/outputs/benchmark_vs_rtamt.json`](docs/paper/outputs/benchmark_vs_rtamt.json).
  Paper §8.6 documents the honest three-point reading.
- **TLAPS proof outline** for RLB-v1 unbounded (Action C,
  [`docs/proofs/Rlb_unbounded.tla`](docs/proofs/Rlb_unbounded.tla)):
  TLA+ module that compiles under TLAPS, declares the four
  supporting lemmas with `PROOF OMITTED` placeholders, and the
  main theorem as the composition target. Discharge plan
  documented at
  [`docs/proofs/TLAPS_roadmap.md`](docs/proofs/TLAPS_roadmap.md)
  (install steps, lemma-by-lemma proof sketches, estimated 5-10
  days for a TLAPS-fluent contributor). Lifting the outline to a
  verified proof is candidate ADR-0038.
- **Pre-submission outreach emails** (Action A,
  [`docs/paper/venues/outreach_emails.md`](docs/paper/venues/outreach_emails.md)):
  four short individual emails drafted for Bartocci (MoonLight),
  Niković (RTAMT), Ferrando (ROSMonitoring), Falcone (RV
  Lectures co-editor) with venue-specific questions and explicit
  do-not-do reminders to avoid academic faux pas.

### Changed

- New `rtamt>=0.3.5` is a paper-script dependency only
  (`docs/paper/scripts/benchmark_vs_rtamt.py`); not a runtime
  dependency of `project_ghost` itself.
- Suite expanded from 1665 to 1687 tests (22 new in
  `test_alternative_policies.py`).

### Notes

- The pyproject `version` bumps to `0.2.2`; `CITATION.cff` and
  release tag synchronise to the same. The publishable wheel via
  OIDC trusted publishing is the artifact pinned by the new tag.

## [0.2.1] - 2026-06-11

Paper-readiness pass: artifacts in support of the v0.2.x academic
write-up at [`docs/paper/project_ghost_v0_2.md`](docs/paper/project_ghost_v0_2.md),
the LaTeX arXiv source at [`docs/paper/arxiv/main.tex`](docs/paper/arxiv/main.tex),
and a second TLA+ specification mechanically verifying RLB-v1
(the tight recovery latency bound `L ≤ peak + W − 1`).

### Added

- **TLA+ `Rlb.tla` specification** mechanically verifying RLB-v1
  ([`docs/proofs/Rlb.tla`](docs/proofs/Rlb.tla),
  [`docs/proofs/Rlb.cfg`](docs/proofs/Rlb.cfg)). Mirrors the
  verifier algorithm of
  [`src/project_ghost/properties/rlb.py`](src/project_ghost/properties/rlb.py)
  and checks three invariants over the full reachable state space
  (`W=4, MAX_DIRTY_RUN=12`): `INV_RLB` (the formal recovery latency
  bound `L ≤ peak + W − 1`), `INV_PEAK_BOUNDED`, and
  `INV_WINDOW_BOUND`. CI-enforced on every push alongside
  `BaudErur.tla`.
- **Violation showcase**
  ([`closed_loop_smoke_violated.py`](src/project_ghost/examples/closed_loop_smoke_violated.py)):
  a smoke that swaps the reference calibrator for
  `_BuggyPassthroughCalibrator` (never downgrades), proving the
  property verifier detects the bug — `BAUD-v1: VIOLATED`,
  `violation_count: 12` (6 cycles × 2 postconditions), exit code 1.
  Companion artifact for paper §8.2 demonstrating detection capacity
  of the reproducibility primitive (contribution C3).
- **Cross-machine determinism CI jobs**
  (`determinism-cross-machine` + `determinism-cross-machine-assert`
  in [`ci.yml`](.github/workflows/ci.yml)): the reference smoke runs
  on a `{ubuntu-latest, windows-latest}` matrix, each runner
  publishes the SHA-256 of its MCAP and property-report JSON, and
  the aggregator step `diff`s the two files. Any disagreement fails
  the build, operationalising paper §8.4.
- **Parametric metrics script**
  ([`docs/paper/scripts/measure_metrics.py`](docs/paper/scripts/measure_metrics.py)):
  reproducibly measures verifier runtime, MCAP size, smoke runtime,
  and HOLDS verdict across 3 calibrator parameterisations
  `(M=4,K=2), (M=3,K=1), (M=5,K=3)` × 3 trace lengths `n ∈ {10, 50, 200}`.
  Writes results to
  [`docs/paper/outputs/metrics.json`](docs/paper/outputs/metrics.json).
  All 9 combinations report all 5 properties HOLDS.
- **Paper draft** at
  [`docs/paper/project_ghost_v0_2.md`](docs/paper/project_ghost_v0_2.md)
  with:
  - 4 contributions formulated as C1–C4: tight recovery latency
    bound (RLB-v1), mechanically verified partition theorem,
    reproducibility primitive with demonstrated detection capacity,
    end-to-end safety citation pattern.
  - **§6 RLB-v1 with rigorous proof by sliding-window trace**
    (accumulation → saturation → flush → recovery) and two
    corollaries on the operational regime and structural sanity.
  - §2 Related work with 10 prior tools cited (RTAMT, MoonLight,
    ROSMonitoring, ROSRV, Shielding, CBF Toolbox, Conformal
    prediction, Timed Automata SC, Rizaldi survey) and §2.3
    9-dimension comparison matrix.
  - §8 Evaluation with violation-showcase JSON output and the
    9-run parametric policy table.
  - 18 references (vs. 7 in the initial draft).
- **arXiv submission package** at
  [`docs/paper/arxiv/`](docs/paper/arxiv/):
  - [`main.tex`](docs/paper/arxiv/main.tex) — self-contained
    LaTeX source (~600 lines, `article` class, compiles with
    pdflatex + bibtex).
  - [`refs.bib`](docs/paper/arxiv/refs.bib) — BibTeX bibliography
    (21 entries).
  - [`README.md`](docs/paper/arxiv/README.md) — submission
    instructions for arXiv (categories: cs.SE primary, cs.LO +
    cs.RO secondary; MSC 68N30, 68V20), plus adaptation notes for
    RV 2026 and FMAS 2026 workshop versions.
- Per-file ruff ignore for [`docs/paper/scripts/`](docs/paper/scripts/)
  to permit `M`, `K` math notation matching the ADRs and the
  Unicode `×` matching the paper's table captions.

### Notes

- Suite remains 1665 tests passing, ruff + mypy strict + deptry
  clean after the additions. The new smoke, script, and TLA+ spec
  are wired into the same lint / type / TLC infrastructure as the
  rest of the repo.

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

[Unreleased]: https://github.com/JFHelvetius/ghost/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/JFHelvetius/ghost/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/JFHelvetius/ghost/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/JFHelvetius/ghost/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/JFHelvetius/ghost/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/JFHelvetius/ghost/releases/tag/v0.1.0
