# Replication Package for Project Ghost v0.2.5

This document describes the replication package archived at
**Zenodo (DOI: 10.5281/zenodo.XXXXXXX)** that accompanies the
paper *Epistemic Safety Contracts as a Property Class for
Autonomous Agents*, currently under submission at TOSEM.

The replication package is **independent** of the live GitHub
repository: a reviewer can verify every paper claim from the
Zenodo tarball alone, without needing the GitHub URL to resolve.
The package contains a frozen snapshot of the source tree at
the v0.2.5 tag.

## Package contents

```
project-ghost-v0.2.5/
├── INSTALL.md              # Toolchain install (Python, Java, Lean)
├── REPRODUCE.md            # End-to-end reproduction (R1-R7)
├── AUDIT.md                # Claim-to-artefact mapping table
├── REPLICATION_PACKAGE.md  # This file
├── CITATION.cff            # Citation metadata
├── LICENSE                 # Apache-2.0
├── README.md               # Project overview
├── pyproject.toml          # Python package definition
├── src/project_ghost/      # Verifier implementations
│   ├── properties/
│   │   ├── baud.py         # BAUD-v1 verifier
│   │   ├── erur.py         # ERUR-v1 verifier
│   │   ├── erur_v2.py      # ERUR-v2 verifier (policy-parametric)
│   │   ├── md.py           # MD-v1 verifier
│   │   ├── rlb.py          # RLB-v1 verifier
│   │   ├── fpb.py          # FPB-v1 verifier (observational)
│   │   ├── fpb_v2.py       # FPB-v2 verifier (statistical: Hoeffding + Clopper-Pearson)
│   │   ├── contract.py     # EpistemicSafetyContract Protocol (ADR-0045)
│   │   └── framework.py    # Registry of 7 shipped contracts
│   ├── adapters/           # PX4 ULog adapter + discrimination experiment
│   ├── core/               # Closed-loop pipeline components
│   └── ...
├── tests/                  # ~1700 tests
├── docs/
│   ├── adr/                # 17 ADRs (0031-0045 + candidates)
│   ├── proofs/
│   │   ├── BaudErur.tla    # TLA+: BAUD/ERUR/MD/partition
│   │   ├── Rlb.tla         # TLA+: RLB-v1 at W=4 + sweep configs W=8, 16
│   │   ├── Fpb.tla         # TLA+: FPB-v1 counter automaton
│   │   ├── Rlb_unbounded.tla       # TLAPS outline with discharge guidance
│   │   ├── Rlb_unbounded_handproof.md  # Rigorous hand proof
│   │   └── Lean/
│   │       ├── Sanity.lean
│   │       ├── PartitionTheorem.lean   # NO sorry
│   │       └── RlbUnbounded.lean       # 1 sorry (Lemma 4)
│   └── paper/
│       ├── arxiv/main.tex            # arXiv-class manuscript
│       ├── arxiv-short/main.tex      # Short variant
│       ├── tosem/main.tex            # acmart-class TOSEM submission
│       ├── project_ghost_v0_2.md     # English long-version (Markdown)
│       ├── es/...                    # Spanish version
│       ├── zh/...                    # Chinese version
│       └── submission/               # Cover letter, checklist, venue comparison
└── .github/workflows/      # CI pipeline definitions
```

## What is **not** included

- `tla2tools.jar` (downloaded automatically by INSTALL.md §3).
- The Lean 4 toolchain (installed by INSTALL.md §4).
- Hardware logs (the project deliberately does not run on real
  hardware as of v0.2.5; see paper §9 limitations).
- External dependencies (`numpy`, `pyulog`, `scipy`); pulled by
  `pip install` per INSTALL.md §1.

## Reproducibility guarantees

Following the [ACM Artifact Review and Badging](https://www.acm.org/publications/policies/artifact-review-and-badging)
framework v1.1:

| Badge | Granted? | Evidence |
|---|:---:|---|
| **Artifact Available** | ✅ | Zenodo DOI, GitHub URL |
| **Artifact Evaluated -- Functional** | ✅ | REPRODUCE.md R1 runs the full test suite (~1700 tests) |
| **Artifact Evaluated -- Reusable** | ✅ | Pure-function verifier surface, ADR-0045 framework Protocol |
| **Results Reproduced** | ✅ | REPRODUCE.md R2-R6 reproduce every figure, table, and quantitative claim |

## Step-by-step verification

1. Download the Zenodo tarball.
2. Follow `INSTALL.md` for the toolchain (Python 3.11+, Java 17,
   Lean 4 4.31.0 stable, tla2tools.jar v1.8.0).
3. Run `REPRODUCE.md` sections R1 through R7 in order. Each
   section gives a single shell command and the expected output.
4. (Optional but recommended) Open `AUDIT.md` and spot-check that
   each paper claim's referenced artefact compiles or passes.

Total reproduction time on a modern laptop: **~10 minutes** for
R1-R6 (R7 is instant; R5.2 cross-machine MCAP byte-equality
requires CI access on two machines).

## Paper-vs-code drift detection

The replication package is the **frozen** view of the source at
the paper's submission. The live GitHub repository continues
to evolve after submission. If a reviewer wants to verify a
claim against the *current* code (not the frozen v0.2.5 tag),
they should:

1. Clone `https://github.com/JFHelvetius/ghost`.
2. Check out the appropriate tag (the paper version, or
   `main` for current).
3. Cross-check against the relevant `AUDIT.md` row.

If the audit reveals a paper claim that is no longer accurate at
some later commit, please open an issue at
`https://github.com/JFHelvetius/ghost/issues` so the paper can
be updated.

## Submission of this package to Zenodo

The package is created by the maintainer at the v0.2.5 tag with:

```bash
git checkout v0.2.5
git archive --format=tar.gz --prefix=project-ghost-v0.2.5/ HEAD > project-ghost-v0.2.5.tar.gz
# Upload to Zenodo via the web UI or the zenodo-cli;
# attach .zenodo.json from the repo root as the metadata payload.
```

DOI assignment is by Zenodo on accept; the placeholder
`10.5281/zenodo.XXXXXXX` in `CITATION.cff` is replaced with
the assigned DOI before the camera-ready version of the paper.

## Contact

For questions about reproducibility or this package, contact
the author at `jfhelvetius@gmail.com` or open an issue at
`https://github.com/JFHelvetius/ghost/issues`.
