# Short / workshop submission version

This directory contains the **short paper** version of the work — the
one that targets FMAS 2026, RV 2026, SAFECOMP workshops, or an
IROS workshop where page limits are 12–15 pages.

## Files

- [`main.tex`](main.tex) — short version, ~12 pages. Body has only
  two tables (comparison matrix, real-telemetry verdict bundle);
  the other five evaluation tables live in Appendix C.
- `refs.bib` — symlink / copy of `../arxiv/refs.bib` at submission
  time (we deliberately do not duplicate it in version control to
  avoid drift).

## Companion documents

- The **technical-report version** at
  [`../arxiv/main.tex`](../arxiv/main.tex) and
  [`../project_ghost_v0_2.md`](../project_ghost_v0_2.md) (Markdown
  canonical) remains the definitive long-form reference for the
  full evaluation, proofs, and discussion. The short version cites
  it explicitly where appendices defer.
- Translations of the technical report at
  [`../es/`](../es/) and [`../zh/`](../zh/) refer to the long
  version's structure. The short version is not translated.

## Strategy

- **arXiv preprint**: submit the technical-report version
  (`docs/paper/arxiv/main.tex`). Reviewers, adopters, and search
  indexes get the full document.
- **Workshop / conference submission**: submit the short version
  (`docs/paper/arxiv-short/main.tex`). Reviewers stay in budget;
  the appendix tables are present for completeness; the body
  reads at FMAS / RV / SAFECOMP length.

## How the short version was derived from the long one

- §1 (Introduction) — kept; the single-claim paragraph leads.
- §2 (Background + Industrial practice) — compressed to one section.
- §3 (The pattern) — the figure plus its caption; that's it.
- §4 (Properties + verifier) — short bullets, no full ADR prose.
- §5 (Mechanical verification) — three specs in one paragraph each;
  Theorem 1 statement only; proof in Appendix B.
- §6 (Real telemetry) — kept; this is the load-bearing section.
- §7 (Limitations) — four bullets.
- §8 (Conclusion) — three sentences, all of them important.

Appendix A: per-tool comparison detail (long-version §2.2 prose).
Appendix B: Theorem 1 proof.
Appendix C: full evaluation tables (long-version §8.2–§8.6).

## What to do before each submission

1. `cd docs/paper/arxiv-short`
2. Copy or symlink `../arxiv/refs.bib`.
3. Replace the appendix-C table stubs with the actual tables from
   the long version (manual port; we deliberately do not auto-sync
   so we can prune to fit budget per venue).
4. Compile: `pdflatex main; bibtex main; pdflatex main; pdflatex main`.
5. Verify page count under the venue's limit. Typical FMAS / RV
   workshop budgets are 12–15 pages.
6. Tag the corresponding release of the repository
   (`v0.x.y-fmas` or similar) so the submission MCAP + verifier are
   pinned by the version the paper cites.

## Why two versions

Workshops cap page counts. Technical reports do not. We follow the
common open-source-research pattern of shipping both: the workshop
gets a tight argument, the community gets the full evidence.
