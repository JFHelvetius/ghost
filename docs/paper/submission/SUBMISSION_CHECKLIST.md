# Pre-submission checklist for Project Ghost v0.2.5

This document is the **gate** the paper must pass before
submission to a journal venue. Every item below is binary
(done / not done); the auditor (typically the lead author plus
one external reader) walks the list end-to-end and signs off.

The companion documents are:

- [COVER_LETTER.md](COVER_LETTER.md) — the cover letter draft.
- [VENUE_COMPARISON.md](VENUE_COMPARISON.md) — TOSEM vs TSE vs FMCAD/CAV.
- [`../arxiv/main.tex`](../arxiv/main.tex) — the long paper.
- [`../arxiv-short/main.tex`](../arxiv-short/main.tex) — the short paper.

---

## A. Paper artefacts

| # | Item | State | Notes |
|---|---|---|---|
| A.1 | Long paper compiles to PDF without errors | ☐ | `cd docs/paper/arxiv && pdflatex main.tex` exits 0 |
| A.2 | Short paper compiles to PDF without errors | ☐ | `cd docs/paper/arxiv-short && pdflatex main.tex` exits 0 |
| A.3 | All cross-references (`\ref`) resolve | ☐ | No "??" in compiled PDFs |
| A.4 | Bibliography is complete | ☐ | `bibtex main` reports 0 errors, 0 warnings about missing refs |
| A.5 | All figures render at print resolution | ☐ | No raster figure < 300 dpi |
| A.6 | Tables have captions on the same page as content | ☐ | LaTeX `[h!]` discipline |
| A.7 | All ADRs referenced in the paper exist in `docs/adr/` | ☐ | Cross-check ADR numbers `0031-0045` |
| A.8 | Paper §3 table matches `shipped_contracts()` output | ☐ | 7 rows: BAUD-v1, ERUR-v1, ERUR-v2, MD-v1, RLB-v1, FPB-v1, FPB-v2 |

---

## B. Reproducibility artefacts

| # | Item | State | Notes |
|---|---|---|---|
| B.1 | `REPRODUCE.md` is current | ☐ | Sections R1-R7 reflect current code |
| B.2 | `INSTALL.md` lists all required toolchains | ☐ | Python, Java, Lean, tla2tools.jar |
| B.3 | `AUDIT.md` mapping table is complete | ☐ | Every paper claim has a row |
| B.4 | Every test referenced in `AUDIT.md` exists | ☐ | `pytest --collect-only` succeeds |
| B.5 | Every script referenced in `AUDIT.md` exists | ☐ | Manual cross-check |
| B.6 | `LICENSE` file is present and Apache-2.0 | ☐ | License unchanged from v0.2.0 |
| B.7 | `setup.py` / `pyproject.toml` is buildable | ☐ | `pip install -e .` succeeds |
| B.8 | The paper's "verifier surface" claim matches the public API | ☐ | `python -c "from project_ghost.properties import *"` works |
| B.9 | All MCAPs referenced in §8 are bundled or downloadable | ☐ | `docs/paper/data/sample.ulg`, `corpus/*.ulg` present |

---

## C. Mechanical proofs

| # | Item | State | Notes |
|---|---|---|---|
| C.1 | TLC runs clean on `BaudErur.tla` | ☐ | `Model checking completed. No error has been found.` |
| C.2 | TLC runs clean on `Rlb.tla` (W=4) | ☐ | INV_RLB holds |
| C.3 | TLC runs clean on `Fpb.tla` | ☐ | Counter automaton well-formed |
| C.4 | RLB sweep PASS at W=4, 8, 16 | ☐ | `run_rlb_tlc_sweep.py` exits 0; `all_W_INV_RLB_holds: True` |
| C.5 | Lean proof `PartitionTheorem.lean` compiles | ☐ | `lean PartitionTheorem.lean` exits 0 |
| C.6 | `PartitionTheorem` has **no `sorry`** | ☐ | `'inv_partition' depends on axioms: [propext, Quot.sound]` |
| C.7 | Lean proof `RlbUnbounded.lean` compiles | ☐ | `lean RlbUnbounded.lean` exits 0 |
| C.8 | `RlbUnbounded` has **exactly one `sorry`** | ☐ | `cleanAfterDirty_count_pending` only; documented in ADR-0042 |

---

## D. CI state

| # | Item | State | Notes |
|---|---|---|---|
| D.1 | `main` branch CI is green | ☐ | Check the GitHub Actions badge |
| D.2 | Full test suite passes on Ubuntu | ☐ | CI matrix entry |
| D.3 | Full test suite passes on Windows | ☐ | CI matrix entry |
| D.4 | Determinism cross-machine MCAP byte-equality holds | ☐ | `determinism-cross-machine-assert` job green |
| D.5 | TLA+ specs continuously checked in CI | ☐ | `tla-plus` job green |
| D.6 | Ruff + mypy strict pass | ☐ | `lint` job green |

---

## E. Honest gap disclosure

The paper §9 limitations are not bugs; they are claim-bounding
disclosures. Each must be still-accurate at the time of
submission.

| # | Limitation in §9 | Still accurate? | Notes |
|---|---|---|---|
| E.1 | "Sim, not hardware" | ☐ | No HAL backend shipped; PX4 ULog only |
| E.2 | "Reference policies only" | ☐ | Production verifier targets the reference; ERUR-v2 lifts this for one verifier |
| E.3 | "Bounded TLC, near-full unbounded coverage" | ☐ | Lean has 1 `sorry` on Lemma 4; TLAPS outline still open |
| E.4 | "Python ↔ TLA+ bridge mechanically closed" | ☐ | RLB-v1 only; other six contracts open under ADR-0046 |
| E.5 | "Statistical FPB shipped, scope narrow" | ☐ | Hoeffding + Clopper-Pearson; Wilson, two-sided, multi-test correction open |
| E.6 | "Vacuous holds on stationary ULogs (closed for SITL)" | ☐ | SITL `_groundtruth` topics auto-detected; non-PX4 hardware still open |

If any of these has become *less* accurate (e.g. someone closed
ADR-0046 between rounds), the §9 entry must be updated before
submission.

---

## F. Venue-specific items

For TOSEM (ACM Transactions on Software Engineering and Methodology):

| # | Item | State | Notes |
|---|---|---|---|
| F.1 | LaTeX uses `acmart` class with `\documentclass[acmsmall]{acmart}` | ☐ | Currently uses `article`; needs migration |
| F.2 | Abstract uses structured format (Background / Aims / Method / Results / Conclusions) | ☐ | See §3 of `arxiv/main.tex` |
| F.3 | Threats to validity is a dedicated subsection | ☐ | Currently in §9 |
| F.4 | Related work is comprehensive (≥ 30 cited works) | ☐ | Currently ~20 |
| F.5 | Replication package is on Zenodo with DOI | ☐ | Future step |
| F.6 | Paper word count under venue limit | ☐ | TOSEM: ~12K words for regular submission |

For TSE (IEEE Transactions on Software Engineering):

| # | Item | State | Notes |
|---|---|---|---|
| G.1 | LaTeX uses IEEEtran class | ☐ | Needs migration |
| G.2 | Author affiliations in IEEE format | ☐ | Needs revision |
| G.3 | Reproducibility statement formatted to IEEE style | ☐ | Needs addition |

---

## G. Submission-day items

| # | Item | State | Notes |
|---|---|---|---|
| H.1 | Cover letter complete and proofread | ☐ | See COVER_LETTER.md |
| H.2 | Paper PDF has no "DRAFT" watermarks | ☐ | Check `\setboolean{draft}{false}` or remove `draft` option |
| H.3 | All author email addresses listed | ☐ | Match institutional records |
| H.4 | Anonymization (if double-blind venue) | ☐ | TOSEM/TSE are single-blind; CAV/FMCAD vary |
| H.5 | A version of the paper exists at a permanent URL (arXiv, Zenodo) | ☐ | We recommend arXiv before peer review |
| H.6 | Source code release tag matches paper version | ☐ | Tag `v0.2.5` on `main` at submission time |

---

## H. Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Lead author | J.M. Mateos | | |
| External reader | TBD | | |
| Reproducibility auditor | TBD | | |

Once all rows above are ☑, the paper is ready for submission.
