# Venue comparison for Project Ghost v0.2.5

This document compares four candidate venues for the Project
Ghost paper and ranks them on fit, expected effort, and
expected timeline. The lead author should review this before
running through `SUBMISSION_CHECKLIST.md` to confirm the venue
choice.

## Summary

| Venue | Fit | Time to format | Expected review timeline |
|---|---|---|---|
| **TOSEM** | Best | ~1 week | 4-6 months first round |
| **TSE** | Strong | ~1 week | 4-6 months first round |
| **CAV** | Strong but narrower | ~2 weeks | 3 months (conference) |
| **FMCAD** | Good for proofs section | ~2 weeks | 3 months (conference) |

Recommendation: **TOSEM**, with TSE as the fallback. The
methodological contribution (the property class) and the
engineering substance (seven verifiers, mechanical proofs,
real-telemetry experiment) together fit TOSEM's regular paper
category best.

---

## TOSEM (ACM Transactions on Software Engineering and Methodology)

### Why it fits

- The contribution is methodological + engineering, not pure
  theory or pure systems.
- The property class formalisation (paper §3) is a methods
  contribution; the seven verifiers + Lean / TLA+ proofs are
  the engineering substance.
- Recent TOSEM issues have featured papers on STL monitoring,
  runtime verification, and formal verification of autonomous
  systems.

### Format requirements

- `acmsmall` class. Migration from the current `article` class
  takes ~1 day of work.
- Structured abstract (Background / Aims / Method / Results /
  Conclusions). Currently the paper has an unstructured
  abstract.
- Threats to validity as a dedicated subsection (currently in
  §9 limitations).
- Replication package on Zenodo with DOI. Not yet prepared.
- Word limit: ~12,000 words for regular submission.
- Bibliography style: `ACM-Reference-Format`.

### Review process

- Single-blind by default. The author identity is known to
  reviewers.
- 3 reviewers expected. Major revision is common; expect
  iterations.
- First decision typically 4-6 months.

### Submission link

[mc.manuscriptcentral.com/tosem](https://mc.manuscriptcentral.com/tosem)

### Estimated effort to first submission

1 week. Items:

1. Migrate to `acmart` class (~1 day).
2. Restructure abstract (~2 hours).
3. Split §9 limitations into "Threats to Validity" subsection
   and a separate "Future work" subsection (~2 hours).
4. Expand related work to ~30 cited works (~1-2 days).
5. Build Zenodo replication package (~1 day).
6. Final pass + proofread (~1 day).

---

## TSE (IEEE Transactions on Software Engineering)

### Why it fits

- Similar to TOSEM in scope and quality bar.
- Slightly more emphasis on empirical evaluation; our §8.8.x
  discrimination experiment fits well.
- IEEE template is widely known; many readers have a TSE
  habit.

### Format requirements

- `IEEEtran` class. Migration from `article` is similar effort
  to TOSEM (~1 day).
- Author affiliations in IEEE format.
- Reproducibility statement formatted to IEEE style.
- Word limit: 14 pages double-column for regular paper.
- Bibliography style: IEEE numerical.

### Review process

- Single-blind by default.
- 3 reviewers, similar revision discipline as TOSEM.
- First decision typically 4-6 months.

### Submission link

[mc.manuscriptcentral.com/tse-cs](https://mc.manuscriptcentral.com/tse-cs)

### Estimated effort to first submission

~1 week, comparable to TOSEM. The main difference is the
two-column layout (IEEEtran) vs single-column (acmsmall), which
requires reflow of figures and tables.

---

## CAV (Computer Aided Verification)

### Why it fits

- Recognized formal methods venue.
- Our Lean 4 + TLA+ proofs are a natural fit for CAV's
  audience.

### Why it's narrower

- The systems / engineering content (Python verifier surface,
  discrimination experiment, real ULog adapter) is less
  central to CAV than to TOSEM/TSE. The paper would need to
  emphasize the formal methods side and may need to defer the
  empirical experiment to a companion paper.
- Conference format (12 pages including refs), much tighter
  than TOSEM/TSE journals.

### Format requirements

- Springer LNCS class.
- 12 pages excluding refs is a typical limit; refs do not
  count toward the page count.
- Anonymous submission (double-blind) for CAV.

### Review process

- 4-6 reviewers per paper.
- 3-month decision timeline.
- Acceptance rate ~25-30% historically.

### Submission link

[easychair.org](https://easychair.org) — venue-specific track.

### Estimated effort to first submission

~2 weeks. The page limit forces significant content trimming;
some §8 evaluation content would be cut.

---

## FMCAD (Formal Methods in Computer-Aided Design)

### Why it fits

- The Lean 4 and TLAPS-outline content map naturally to FMCAD's
  topic list.
- Smaller, more intimate community; well-curated reviews.

### Why it's narrower

- Same trimming concerns as CAV (page limit).
- Less emphasis on runtime verification; the paper's RV side
  would need to be downplayed.

### Format requirements

- IEEE conference template.
- ~10-12 pages.

### Review process

- 3-month decision timeline.
- Similar acceptance rate to CAV.

### Submission link

[fmcad.org](https://fmcad.org) — yearly conference; submission
window varies.

### Estimated effort to first submission

~2 weeks. Similar to CAV.

---

## Decision

**Primary target: TOSEM.** The methodological+engineering mix
fits TOSEM's regular paper category. The cover letter at
[COVER_LETTER.md](COVER_LETTER.md) is targeted at TOSEM.

If TOSEM declines after first review, the next iteration is
TSE; the LaTeX delta is moderate (column layout + style).

CAV and FMCAD are kept as options if a focused-on-proofs
version becomes useful (e.g. if a Lemma 4 discharge becomes
available and the proofs side grows). They are not the v0.2.5
target.

---

## Submission timeline (approximate)

| Date (approximate) | Milestone |
|---|---|
| Round 30 (this round) | Submission package complete; cover letter, checklist, AUDIT/REPRODUCE/INSTALL drafted |
| +1 week | Acmart migration; bibliographic expansion; Zenodo package; arXiv preprint |
| +2 weeks | TOSEM submission |
| +6 months | First decision (major revision expected) |
| +12 months | Camera-ready (optimistic) |
