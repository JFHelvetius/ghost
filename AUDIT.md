# External Audit Guide for Project Ghost v0.2.5

This document is the **single page** an external auditor needs to
verify every claim the paper makes. Each row maps a **paper
claim** to the **artefact** that grounds it and the **command**
that re-executes the artefact from scratch.

Audit philosophy:

- **No claim is trusted.** Each one cites an artefact (test, ADR,
  Lean proof, TLC model, MCAP, JSON) that an auditor can execute.
- **Reproducibility is the contract.** Every command in this
  document runs offline from a fresh clone given the
  documented environment (see [INSTALL.md](INSTALL.md)).
- **The mapping is exhaustive.** If a paper claim is not in the
  table below, it is either (a) a non-load-bearing remark or
  (b) a documentation bug we want flagged.

Conventions:

- Commands assume a Bash-or-PowerShell shell at the repo root.
- ``$JAVA`` and ``$LEAN`` resolve to the Java 17 and Lean 4
  binaries documented in [INSTALL.md](INSTALL.md).
- ``$VENV`` is the Python virtualenv activated per
  [INSTALL.md](INSTALL.md).
- All commands exit non-zero on failure; CI runs them on every
  push.

---

## A. Property semantics & verification

The paper's seven properties (paper §3) are each grounded in one
ADR, one verifier function, one Hypothesis property test, and
one mechanical proof (TLA+, Lean 4, or both). Each row is
auditable independently.

| Claim (paper §) | Property | ADR | Verifier surface | Property test | Mechanical proof |
|---|---|---|---|---|---|
| BAUD-v1 holds on the smoke MCAP | BAUD-v1 | [0031](docs/adr/0031-bounded-action-under-drift-property-v1.md) | `verify_baud(mcap_path, *, min_outcomes=4, downgrade_threshold=2)` | `tests/properties/test_baud_property.py` | `docs/proofs/BaudErur.tla` `INV_BAUD` |
| ERUR-v1 holds on the smoke MCAP | ERUR-v1 | [0032](docs/adr/0032-eventual-reactivation-under-recovery-property-v1.md) | `verify_erur(mcap_path, ...)` | `tests/properties/test_erur_property.py` | `BaudErur.tla` `INV_ERUR` |
| ERUR-v2 is policy-parametric | ERUR-v2 | [0040](docs/adr/) (paper §10) | `verify_erur_v2(mcap_path, *, drift_predicates)` | `tests/properties/test_erur_v2_property.py` | -- (Protocol contract) |
| MD-v1 holds for the reference calibrator | MD-v1 | [0033](docs/adr/0033-monotonic-degradation-property-v1.md) | `verify_md(mcap_path)` | `tests/properties/test_md_property.py` | `BaudErur.tla` `INV_NO_INVENTED_CONFIDENCE` |
| RLB-v1 holds at bounded W | RLB-v1 (bounded) | [0034](docs/adr/0034-recovery-latency-bound-property-v1.md) | `verify_rlb(mcap_path, *, max_history=32)` | `tests/properties/test_rlb_property.py` | `Rlb.tla` `INV_RLB` |
| RLB-v1 holds at W=4,8,16 (paper §6.3) | RLB-v1 (sweep) | [0038](docs/adr/0038-rlb-unbounded-verification.md) | `docs/paper/scripts/run_rlb_tlc_sweep.py` | -- | `Rlb_W{4,8,16}.cfg` |
| RLB-v1 lemmas 1-3 + Theorem 1 statement | RLB-v1 (Lean) | [0042](docs/adr/0042-lean4-mechanical-proofs.md) | -- | -- | `docs/proofs/Lean/RlbUnbounded.lean` |
| Partition theorem BAUD ⊕ ERUR | partition | [0036](docs/adr/0036-tla-plus-mechanical-verification-of-baud-erur.md) | -- | -- | `docs/proofs/Lean/PartitionTheorem.lean` (no `sorry`); `BaudErur.tla` `INV_PARTITION` |
| FPB-v1 reports the empirical fire rate | FPB-v1 | [0035](docs/adr/0035-false-positive-bound-property-v1.md) | `verify_fpb(mcap_path, ...)` | `tests/properties/test_fpb_property.py` | `Fpb.tla` `INV_FPB_*` |
| FPB-v2 reports a statistical upper bound | FPB-v2 | [0039](docs/adr/0039-false-positive-bound-property-v2.md) | `verify_fpb_v2(mcap_path, *, method=...)` | `tests/properties/test_fpb_v2_property.py` | -- (closed-form math, 10 Hypothesis properties) |
| Python verifier core ⇔ TLA+ semantics agree | bridge | [0043](docs/adr/0043-python-tla-bridge-conformance.md) | -- | `tests/properties/test_python_tla_bridge.py` | conformance via Hypothesis |
| Property class is a Protocol with 7 registrations | framework | [0045](docs/adr/0045-epistemic-safety-contract-framework.md) | `project_ghost.properties.framework.shipped_contracts()` | `tests/properties/test_framework_invariants.py` | 8 framework invariants |

### Re-executing every property verifier

```bash
$VENV/bin/python -m pytest tests/properties/ -q
```

Expected exit code: 0. Expected ~124 tests pass; if any of the
above-named test files report failures, the corresponding paper
claim is regressed and the auditor should flag it.

---

## B. The discrimination experiment (paper §8.8, §8.8.1, §8.8.2)

The discrimination matrix is the load-bearing experiment of §8.
The auditor can re-run it end-to-end against the bundled PX4
ULogs.

| Claim | Artefact | Reproducing command |
|---|---|---|
| §8.8 verdict delta on `sample.ulg` | `tests/adapters/test_real_ulog_discrimination.py` | `$VENV/bin/python -m pytest tests/adapters/test_real_ulog_discrimination.py -q` |
| §8.8.1 corpus matrix N×6 = 18 cells | `docs/paper/scripts/run_multi_ulog_corpus.py` | `$VENV/bin/python docs/paper/scripts/run_multi_ulog_corpus.py` |
| §8.8.2 SITL GT closes stationary ULog gap | `tests/adapters/test_real_ulog_smoke_gt_source.py` | `$VENV/bin/python -m pytest tests/adapters/test_real_ulog_smoke_gt_source.py -q` |

The corpus matrix script (above) emits a self-describing JSON at
`docs/paper/outputs/multi_ulog_discrimination/matrix.json` with
per-ULog `groundtruth_source` (`"sitl_simulator"` or
`"ekf2_fallback"`) so the auditor can confirm which rows used
independent GT vs the circular fallback.

Expected matrix shape:

- `sample.ulg`: 6/6 categories discriminate, 5/6 isolate
  (ekf2_fallback)
- `sample_appended.ulg`: 6/6 categories discriminate, 5/6
  isolate (ekf2_fallback)
- `sample_logging_tagged.ulg`: 6/6 categories discriminate, 5/6
  isolate (sitl_simulator)

`all_discriminate=True`. If any cell regresses, the §8.8 claim
is invalid for that ULog and the paper must be updated before
merging.

---

## C. Formal mechanical proofs

| Claim | Tool | File | Reproducing command |
|---|---|---|---|
| BaudErur invariants hold (M=2, K=1, W=3) | TLC | `docs/proofs/BaudErur.tla` + `.cfg` | `cd docs/proofs && $JAVA -cp ../../tla2tools.jar tlc2.TLC -config BaudErur.cfg BaudErur` |
| RLB-v1 holds at W=4, 8, 16 | TLC | `Rlb.tla` + `Rlb_W{4,8,16}.cfg` | `$VENV/bin/python docs/paper/scripts/run_rlb_tlc_sweep.py` |
| FPB counter well-formedness | TLC | `Fpb.tla` + `.cfg` | `cd docs/proofs && $JAVA -cp ../../tla2tools.jar tlc2.TLC -config Fpb.cfg Fpb` |
| Partition theorem fully mechanized | Lean 4 | `docs/proofs/Lean/PartitionTheorem.lean` | `$LEAN docs/proofs/Lean/PartitionTheorem.lean` |
| RLB-v1 unbounded: 9 lemmas + Theorem 1 statement | Lean 4 | `docs/proofs/Lean/RlbUnbounded.lean` | `$LEAN docs/proofs/Lean/RlbUnbounded.lean` |

### How to read the Lean proof axiom set

After running `$LEAN <file>`, the output ends with `'<theorem>'
depends on axioms: [...]`. Auditor expectations:

- **`[propext, Quot.sound]`**: the theorem is fully discharged
  by standard Lean axioms. **No `sorryAx`**, no human trust
  beyond the axioms.
- **`[propext, sorryAx, Quot.sound]`**: the theorem is reduced
  to a `sorry` placeholder that has not been discharged. The
  paper documents this as a known gap (Lemma 4 of unbounded
  RLB-v1, ADR-0042).

If a theorem listed in this document as fully discharged shows
`sorryAx` in its axiom set, the paper claim is regressed.

---

## D. Determinism & cross-machine equivalence (paper §8.9)

| Claim | Artefact | Reproducing command |
|---|---|---|
| Same-machine MCAP bit-equality | `tests/adapters/test_real_ulog_smoke.py::test_mcap_deterministic` | `$VENV/bin/python -m pytest tests/adapters/test_real_ulog_smoke.py -q` |
| Cross-machine MCAP bit-equality | `.github/workflows/ci.yml` `determinism-cross-machine-assert` | -- (executes on every CI push) |

The CI job is the only artefact in this table the auditor cannot
fully re-execute locally without two distinct machines. Pinning
evidence: the JSON artefacts uploaded by the CI matrix on the
`main` branch carry per-runner SHA-256 of the produced MCAP and
the property-report JSON.

---

## E. Reproducibility surface

| Claim | Artefact | Verification |
|---|---|---|
| Full pipeline runs from `pip install` | `setup.py` / `pyproject.toml` | See [INSTALL.md](INSTALL.md) §"Fresh Python install" |
| Verifier is pure function over MCAP | `src/project_ghost/properties/*.py` | Inspection + tests/properties pass |
| MCAP is content-addressed | every `*VerificationReport.mcap_sha256` field | `sha256sum <mcap_path>` matches the report's field |
| ADRs are immutable | `docs/adr/` git log | `git log --follow docs/adr/<file>.md` |
| Per-property ADRs are complete | 7 ADRs (0031-0035, 0039, 0040) + 5 mech ADRs (0036, 0038, 0042, 0043, 0045) + 4 candidate (0037, 0041, 0044, 0046) | Direct enumeration in `docs/adr/` |

---

## F. Honest gaps the paper acknowledges (§9 limitations)

The auditor is encouraged to spot-check that each limitation the
paper §9 lists has a corresponding entry below. If the paper
claims a limitation but the limitation is not reflected in the
code, that is a paper-vs-code drift the auditor should flag.

| Paper §9 limitation | Code surface |
|---|---|
| "Sim, not hardware" | No `src/project_ghost/hal/` impl; `pyulog` adapter only |
| "Reference policies only" | `src/project_ghost/core/feedback/reference_policy.py` is the only `*Reference*Policy` |
| "Bounded TLC, near-full unbounded coverage" | `Rlb_W16.cfg` largest TLC config; `RlbUnbounded.lean` has 1 `sorry` |
| "Python ↔ TLA+ bridge mechanically closed (ADR-0043)" | `tests/properties/test_python_tla_bridge.py` runs on every push |
| "Statistical FPB shipped, scope narrow" | `verify_fpb_v2` ships; ADR-0039 documents what's open |
| "Vacuous holds on stationary ULogs (closed for SITL)" | ADR-0037 partially addressed; `_groundtruth` topics auto-detected |

---

## How to flag a paper-vs-code regression

If, while auditing, you find:

- A paper claim with **no artefact** in the table above → likely
  a documentation bug; please open an issue at
  https://github.com/JFHelvetius/ghost/issues with the section
  number and the unsubstantiated claim.
- An artefact that **fails to reproduce** → please attach the
  command output and the exact commit SHA you tested against.
- A discrepancy between **the paper's claim and the artefact's
  output** → the most valuable kind of finding; please be as
  precise as possible (which claim, which output, which line).

We track audit findings publicly to keep the verification surface
honest.

---

## Repository state at v0.2.5

```
SHA at this round: (see git log)
Verifier surface count: 7 (BAUD/ERUR-v1/ERUR-v2/MD/RLB/FPB-v1/FPB-v2)
ADR count: 17 (0031-0045 + candidates)
Lean files: 3 (Sanity, PartitionTheorem, RlbUnbounded)
TLA+ files: 4 (BaudErur, Rlb, Rlb_unbounded, Fpb)
Property tests: ~124
Adapter tests: ~42
Discrimination matrix: 6×3 = 18 cells, 18/18 detection
Total Hypothesis property runs per CI push: thousands
```
