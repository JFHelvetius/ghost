# arXiv submission package

This directory contains the LaTeX source ready for arXiv submission
and as the starting point for RV 2026 / FMAS 2026 workshop versions.

## Files

| File | Purpose |
|---|---|
| [`main.tex`](main.tex) | Paper source (article class, ~600 lines, self-contained) |
| [`refs.bib`](refs.bib) | BibTeX bibliography (18 entries) |
| `main.pdf` | Generated locally; not committed |

The Markdown extended version lives at
[`../project_ghost_v0_2.md`](../project_ghost_v0_2.md) and is the
authoritative narrative source. The LaTeX is a faithful condensed
rendering suitable for venue submission.

## Building locally

Requires TeX Live or MiKTeX with `pdflatex` + `bibtex`.

```bash
cd docs/paper/arxiv/
pdflatex main
bibtex main
pdflatex main
pdflatex main
```

Output: `main.pdf` (~12 pages).

## arXiv submission checklist

### 1. Account and credentials

- Sign in at <https://arxiv.org/user/login>.
- If you do not already have a moderator endorsement, you will need
  one for first-time submission in **cs.SE** or **cs.LO**. Endorsement
  is per-archive; once you have it for one, you can cross-list to the
  others. See <https://arxiv.org/help/endorsement>.

### 2. Upload bundle

arXiv accepts either a single PDF (simpler) or a tarball with the
LaTeX source (preferred — arXiv extracts metadata, indexes the
abstract, and renders the references correctly).

**Preferred: source tarball.**

```bash
cd docs/paper/arxiv/
tar czf project_ghost_v0_2_arxiv.tar.gz main.tex refs.bib main.bbl
```

(Include `main.bbl` so arXiv does not have to re-run `bibtex`.)

Upload at <https://arxiv.org/submit>. arXiv will compile your source
server-side and show you the rendered preview. Iterate until it
looks correct.

### 3. Categories

Primary and secondary classifications for the submission form:

- **Primary:** `cs.SE` — Software Engineering. The paper is
  fundamentally about a build-and-ship pattern with reproducibility
  as the headline.
- **Secondary 1:** `cs.LO` — Logic in Computer Science. RLB-v1
  + the TLA+/TLC mechanisation belong here.
- **Secondary 2:** `cs.RO` — Robotics. The application domain.

MSC classification: `68N30` (Mathematical aspects of software
engineering), `68V20` (Formal methods).

ACM Computing Classification System (optional, free-text):
`Software and its engineering → Software verification and validation`;
`Computing methodologies → Robotics`.

### 4. Title, abstract, and metadata

- **Title:** `Epistemic Contracts for Autonomous Systems: A Verifiable Pattern for Safety Claims Under Uncertainty`
- **Authors:** `Javier Menéndez Mateos` (single author).
- **Comments line** (free text, displayed under the abstract):
  ```
  12 pages, 2 tables. Code, MCAPs, TLA+ specs, and TLC verification
  output reproducible from https://github.com/JFHelvetius/ghost
  (release v0.2.0) and from pip install project-ghost==0.2.0.
  ```
- **Abstract:** copy verbatim from the `\begin{abstract}` block in
  `main.tex` (arXiv accepts plain text; strip the LaTeX commands).
- **Report-no, journal-ref, DOI:** leave empty for v0.2.0 preprint.
  Update on resubmission after a workshop accepts the paper.
- **License:** the source is Apache-2.0; on arXiv select
  `arXiv.org perpetual, non-exclusive license to distribute` (the
  default — does not transfer copyright). The CC-BY option is also
  appropriate if you prefer it.

### 5. After submission

- arXiv assigns a paper ID of the form `arXiv:2606.NNNNN` (the
  prefix is YYMM).
- Once accepted, update the project repository:
  - `CITATION.cff`: add the arXiv ID and DOI under `identifiers`.
  - `README.md`: add a "Cite this work" badge linking to the arXiv
    abstract page.
  - This `README.md`: record the arXiv ID and submission date here.
- arXiv DOIs become routable via `https://arxiv.org/abs/<id>` and via
  `https://doi.org/10.48550/arXiv.<id>`.

## RV 2026 (Runtime Verification) submission

The same `main.tex` is reusable as the basis for an RV 2026 tool
paper or regular paper submission. RV typically uses Springer LNCS.

1. Download the LNCS class files:
   <https://www.springer.com/gp/computer-science/lncs/conference-proceedings-guidelines>.
2. Replace the top of `main.tex`:
   ```latex
   \documentclass[runningheads]{llncs}
   ```
   Remove the `\usepackage{geometry}` line (LNCS sets its own
   margins).
3. Replace the author block with the LNCS form:
   ```latex
   \author{Javier Menéndez Mateos\inst{1}}
   \institute{Independent\\\email{jfhelvetius@gmail.com}}
   ```
4. Adjust page count to the venue limit (RV regular ~16, tool ~6).
   The current paper at ~12 pages fits regular comfortably; for a
   tool paper, trim §1.2 + §9 and condense §6's proof.
5. Submit via the RV 2026 EasyChair URL when the CFP opens
   (typically March–July).

## FMAS 2026 (Formal Methods for Autonomous Systems)

FMAS uses EPTCS or LNCS depending on the year. Check the CFP at
<https://fmasworkshop.github.io/FMAS2026/>. The current `main.tex`
adapts directly; FMAS tends to weight the autonomy-domain framing
higher than RV does, so consider expanding §1's motivation
paragraph for FMAS submission.

## Versioning

This package corresponds to **Project Ghost v0.2.0**, released
2026-06-10. Update version + date in `main.tex` (\\date and
abstract) when bumping for resubmission.
