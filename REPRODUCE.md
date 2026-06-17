# Reproducing every paper claim from scratch

This document is the end-to-end reproduction guide a third party
follows after a fresh clone. Each section reproduces one
load-bearing claim of the paper, with a single shell command and
the expected output.

Companion documents:

- [INSTALL.md](INSTALL.md) — environment setup (Python, Java, Lean).
- [AUDIT.md](AUDIT.md) — the claim-to-artefact mapping table.
- [README.md](README.md) — overview.

Before starting, ensure you have followed [INSTALL.md](INSTALL.md)
and the following variables resolve in your shell:

- `$VENV/bin/python` (or `$VENV\Scripts\python.exe` on Windows)
  — the Project Ghost virtualenv.
- `$JAVA` — Java 17 binary (for TLC).
- `$LEAN` — Lean 4 binary (for the mechanical proofs).
- `tla2tools.jar` at the repo root.

All commands exit non-zero on failure. Expected runtime is given
per section.

---

## R1. Full test suite

```bash
$VENV/bin/python -m pytest -q
```

**Expected:** ~1700 tests pass; exit code 0.
**Expected runtime:** ~3-5 minutes on a modern laptop.

This is the umbrella reproduction. Every other section below
re-executes a *subset* of these tests; if R1 passes, every
property-level claim of the paper is mechanically substantiated
at this commit.

---

## R2. The seven shipped properties (paper §3)

```bash
$VENV/bin/python -m pytest tests/properties/ -q
```

**Expected:** 124 tests pass; exit code 0.
**Expected runtime:** ~15 seconds.

Covers the seven properties (BAUD-v1, ERUR-v1, ERUR-v2, MD-v1,
RLB-v1, FPB-v1, FPB-v2), the Python↔TLA+ bridge conformance
test, and the eight framework-level invariants on the property
registry (ADR-0045).

---

## R3. The discrimination experiment (paper §8.8)

### R3.1 Single-ULog discrimination on the bundled PX4 ULog (§8.8)

```bash
$VENV/bin/python -m pytest tests/adapters/test_real_ulog_discrimination.py -q
```

**Expected:** 6 tests pass; exit code 0.
**Expected runtime:** ~30 seconds.

The verifier flips the expected property on every one of the six
buggy categories from §8.8's verdict table.

### R3.2 Three-ULog corpus matrix (§8.8.1)

```bash
$VENV/bin/python docs/paper/scripts/run_multi_ulog_corpus.py
```

**Expected stdout (key lines):**

```
Corpus              : 3 ULogs
Detection matrix    : 6 categories x 3 ULogs
all_discriminate    : True
all_isolated        : False
JSON artefact       : docs/paper/outputs/multi_ulog_discrimination/matrix.json
```

**Expected exit code:** 0.
**Expected runtime:** ~60 seconds.

Produces a self-describing JSON at
`docs/paper/outputs/multi_ulog_discrimination/matrix.json` with
the per-ULog detection and isolation matrices plus the
`groundtruth_source` field per ULog (so the auditor can confirm
which rows used independent SITL GT vs the circular EKF2
fallback).

### R3.3 Independent SITL GT closes stationary ULog (§8.8.2)

```bash
$VENV/bin/python -m pytest tests/adapters/test_real_ulog_smoke_gt_source.py -q
```

**Expected:** 6 tests pass; exit code 0.
**Expected runtime:** ~30 seconds.

Asserts the A/B comparison of `EKF2_FALLBACK` vs `SITL_SIMULATOR`
on `sample_logging_tagged.ulg`: the SITL GT lifts the FPB fire
fraction from 0.00 to 0.86, closing the v0.2.4 vacuous-HOLDS
gap.

---

## R4. The mechanical proofs

### R4.1 TLA+ specs (BaudErur, Rlb, Fpb)

The CI workflow downloads `tla2tools.jar` and runs:

```bash
$JAVA -cp tla2tools.jar tlc2.TLC -config docs/proofs/BaudErur.cfg \
    -workers auto -metadir /tmp/tlc-baud-erur docs/proofs/BaudErur.tla
$JAVA -cp tla2tools.jar tlc2.TLC -config docs/proofs/Rlb.cfg \
    -workers auto -metadir /tmp/tlc-rlb docs/proofs/Rlb.tla
$JAVA -cp tla2tools.jar tlc2.TLC -config docs/proofs/Fpb.cfg \
    -workers auto -metadir /tmp/tlc-fpb docs/proofs/Fpb.tla
```

(On Windows, replace `/tmp/...` with `$env:TEMP\...`.)

**Expected:** TLC reports `Model checking completed. No error has been found.` for each.
**Expected runtime:** ~5 seconds per spec.

### R4.2 RLB-v1 parametric TLC sweep (§6.3, ADR-0038)

```bash
$VENV/bin/python docs/paper/scripts/run_rlb_tlc_sweep.py
```

**Expected stdout (key lines):**

```
Running TLC W=4 (config Rlb.cfg)...
  W=4: states_generated=29 distinct=25 INV_RLB=HOLDS (~1s)
Running TLC W=8 (config Rlb_W8.cfg)...
  W=8: states_generated=89 distinct=81 INV_RLB=HOLDS (~1s)
Running TLC W=16 (config Rlb_W16.cfg)...
  W=16: states_generated=305 distinct=289 INV_RLB=HOLDS (~1s)

all_W_INV_RLB_holds : True
```

**Expected exit code:** 0.
**Expected runtime:** ~10 seconds total.

Emits `docs/paper/outputs/rlb_tlc_sweep/sweep.json` with per-W
metrics.

### R4.3 Lean 4: partition theorem (no `sorry`)

```bash
$LEAN docs/proofs/Lean/PartitionTheorem.lean
```

**Expected stdout (last lines):**

```
inv_partition : ∀ (h : List Verdict) (raw : Level) (M K : Nat),
  raw = known → (baudPrecondition h M K ↔ ¬erurPrecondition h raw M K)
partition_exactly_one : ∀ (h : List Verdict) (M K : Nat),
  baudPrecondition h M K ∨ erurPrecondition h known M K
'inv_partition' depends on axioms: [propext, Quot.sound]
'partition_exactly_one' depends on axioms: [propext, Quot.sound]
```

**Expected exit code:** 0.
**Expected runtime:** ~5 seconds.

The two `depends on axioms` lines confirm both theorems are
fully discharged by standard Lean axioms (no `sorryAx`).

### R4.4 Lean 4: unbounded RLB-v1 (1 `sorry`)

```bash
$LEAN docs/proofs/Lean/RlbUnbounded.lean
```

**Expected stdout (last lines):**

```
'countDirty_bounded' depends on axioms: [propext, Quot.sound]
'windowUpdate_length_bounded' depends on axioms: [propext, Quot.sound]
'dirtyAcc_length' depends on axioms: [propext, Quot.sound]
'dirtyAcc_all_dirty' depends on axioms: [propext, Quot.sound]
'countDirty_of_all_dirty' depends on axioms: [propext, Quot.sound]
'dirtyAcc_count' depends on axioms: [propext, Quot.sound]
warning: declaration uses 'sorry'
'cleanAfterDirty_count_pending' depends on axioms: [sorryAx]
'rlb_unbounded' depends on axioms: [propext, sorryAx, Quot.sound]
```

**Expected exit code:** 0 (Lean does not fail on `sorry`,
only warns).
**Expected runtime:** ~30 seconds.

The 6 lemmas with axiom set `[propext, Quot.sound]` are fully
discharged. The 1 `sorry` placeholder
(`cleanAfterDirty_count_pending`, Lemma 4) is the only
remaining gap, transitively inherited by `rlb_unbounded` (the
Theorem 1 statement). See ADR-0042 and ADR-0044 (candidate).

---

## R5. Determinism (paper §8.9)

### R5.1 Same-machine MCAP byte-equality

```bash
$VENV/bin/python -m pytest tests/adapters/test_real_ulog_smoke.py -q
```

**Expected:** ~10 tests pass; exit code 0.
**Expected runtime:** ~30 seconds.

Includes a `test_mcap_deterministic`-style test that runs the
real-ULog pipeline twice and asserts byte-equality of the
produced MCAPs.

### R5.2 Cross-machine MCAP byte-equality

```bash
# Trigger CI on a fresh commit and inspect the
# determinism-cross-machine-assert job artefact.
```

**Expected:** The CI matrix runs the reference smoke on both
`ubuntu-latest` and `windows-latest`; each runner uploads the
SHA-256 of its produced MCAP and the property-report JSON;
the aggregator step `diff`s the two and fails on any
disagreement. The auditor can inspect the published artefacts
on any green commit on `main`.

This is the only artefact in this guide that requires CI access
to verify; everything else is local.

---

## R6. Inspecting the property class formally (ADR-0045)

```bash
$VENV/bin/python -c "
from project_ghost.properties.framework import shipped_contracts
for c in shipped_contracts():
    print(f'{c.property_version:<10} verifier={c.verifier.__name__}')
"
```

**Expected output:**

```
BAUD-v1    verifier=verify_baud
ERUR-v1    verifier=verify_erur
ERUR-v2    verifier=verify_erur_v2
FPB-v1     verifier=verify_fpb
FPB-v2     verifier=verify_fpb_v2
MD-v1      verifier=verify_md
RLB-v1     verifier=verify_rlb
```

Seven contracts, in version-string order. ADR-0045's
"single point of truth" claim is satisfied iff this is the
exact set the paper §3 table lists.

---

## R7. License & dependency posture

```bash
# License check
$VENV/bin/python -c "import project_ghost; print(project_ghost.__doc__)"

# Dependency audit
$VENV/bin/python -m pip list --format json | grep -E 'mcap|numpy|pyulog|scipy'
```

**Expected (license):** the package docstring mentions the
Apache-2.0 license (matching the [LICENSE](LICENSE) file).
**Expected (dependencies):** the base install ships
`mcap`, `numpy`, and (under the `adapters` extra) `pyulog`. SciPy
is gated behind `ConfidenceMethod.CLOPPER_PEARSON`; the base
install is stdlib-only modulo the listed extras.

---

## Total reproduction time

A clean run of R1 through R6 takes approximately **10 minutes**
on a modern laptop. R7 is instant. R5.2 requires CI access.

If any step above fails on a fresh clone at the commit you
tested against, please open an issue at
https://github.com/JFHelvetius/ghost/issues with the exact
command, the exit code, the stderr, and your environment.
