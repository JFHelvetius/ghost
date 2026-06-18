# Cover Letter — Project Ghost

**Target journal:** ACM Transactions on Software Engineering and
Methodology (TOSEM) — Regular Paper.

**Alternative venues (in order of preference):** IEEE Transactions
on Software Engineering (TSE), CAV (Computer Aided Verification),
FMCAD (Formal Methods in Computer-Aided Design).

**Manuscript:** *Epistemic Safety Contracts as a Property Class for
Autonomous Agents: A Formalised Framework with Mechanical Proofs
and a Real-Telemetry Discrimination Experiment.*
Javier Menéndez Mateos. v0.2.5 (rounds 23–34, January–June 2026).

---

Dear Editor,

I respectfully submit the manuscript **Epistemic Safety Contracts
as a Property Class for Autonomous Agents** for evaluation as a
Regular Paper at TOSEM.

## What we contribute

The paper introduces **epistemic safety contracts** as a property
class distinct from (a) STL-style predicates over external signals
and (b) POMDP-style Bayesian belief monitoring. An epistemic safety
contract is a triple `(P, Q, V)` where `P` and `Q` are predicates
over the **agent's own posture under uncertainty** (detected drift,
calibrated belief, bounded recovery), and `V` is a pure-function
verifier over a content-addressed execution trace.

The paper makes **four principal contributions**:

1. **The property class itself.** We argue that contracts over the
   epistemic posture answer questions the existing classes do not
   answer: *"did the agent degrade conservatively when it doubted
   its own confidence?"*, *"did it re-engage when the evidence was
   restored?"*, *"is its recovery latency bounded?"* The class is
   formalised in v0.2.5 as a Python `Protocol`
   (`EpistemicSafetyContract`) plus a registry of the seven shipped
   contracts (BAUD-v1, ERUR-v1, ERUR-v2, MD-v1, RLB-v1, FPB-v1,
   FPB-v2).

2. **Seven concrete contracts with their verifiers and proofs.**
   Each contract is stated in a binding ADR (immutable once
   accepted), verified by a pure function over a captured MCAP,
   and exercised by a Hypothesis property test. Five of the seven
   ship additional mechanical evidence: the BAUD/ERUR partition
   theorem and Lemmas 1–3 of unbounded RLB-v1 in Lean 4 (no
   `mathlib`, axioms limited to `propext` and `Quot.sound`); BAUD,
   ERUR, MD, RLB at bounded `W` in TLC; RLB-v1 in
   `W ∈ {4, 8, 16}` via a parametric TLC sweep; FPB-v1's counter
   automaton in TLC. The remaining gap — Lemma 4 of unbounded
   RLB-v1 — is shipped as a documented `sorry` in Lean and is
   mechanically reduced to a single load-bearing inductive step
   (ADR-0044 candidate).

3. **A mechanical bridge between the Python verifier and the TLA+
   specification.** Until v0.2.5 the paper acknowledged a *"Python
   ↔ TLA+ bridge by inspection"* caveat. ADR-0043 + ADR-0046 close
   this for 5 of the 7 contracts via a Hypothesis-checked test
   that re-implements both semantics independently from their
   respective sources and requires them to agree on every trace
   Hypothesis can synthesise within the bounds. The remaining two
   contracts (ERUR-v2 and FPB-v2) are documented as out of scope
   with explicit reasons.

4. **An end-to-end discrimination experiment on real PX4
   telemetry.** Six bug categories from the synthetic violation
   matrix are exercised on three structurally distinct PX4 SITL
   ULogs. With independent simulator GT auto-activated when
   `vehicle_*_groundtruth` topics are present (ADR-0037, v0.2.5),
   the discrimination matrix is 18/18 green; 15/18 cells isolate
   the violation to the expected property. The single
   non-isolated row is a real co-violation between BAUD-v1 and
   MD-v1 (a calibrator that inflates confidence).

## Why now

The intersection of autonomous systems, runtime verification, and
formal methods has produced excellent work on each of the three
sides (STL/MITL monitoring; POMDP belief verification;
TLA+/TLAPS-style proofs). What is missing is a property class that
captures **how an agent should relate to its own uncertainty** —
the class our paper introduces and instantiates with an
operational implementation, a content-addressed execution format,
seven verifiers, mechanical proofs, and an experiment on real
telemetry.

## Why this journal

TOSEM publishes work that combines methodological contributions
(here: the property class) with engineering substance (here: the
implementation, the seven verifiers, the mechanical proofs, the
ADR-driven design discipline). Recent issues have included papers
on STL monitoring, runtime verification frameworks, and formal
verification of robotic systems; our paper sits at the
intersection of these three axes. TSE, CAV, and FMCAD are
alternatives we would consider in that order.

## Reproducibility

The complete code, paper sources, ADRs, mechanical proofs, and
reproducibility scripts are publicly available at
[github.com/JFHelvetius/ghost](https://github.com/JFHelvetius/ghost)
under the Apache-2.0 license. Three top-level documents make the
artifact navigable:

- [`INSTALL.md`](https://github.com/JFHelvetius/ghost/blob/main/INSTALL.md) —
  from-scratch install guide for Python, Java, Lean, and tla2tools.
- [`REPRODUCE.md`](https://github.com/JFHelvetius/ghost/blob/main/REPRODUCE.md) —
  end-to-end reproduction of each claim of the paper (R1–R7, ~10
  minutes total on a modern laptop).
- [`AUDIT.md`](https://github.com/JFHelvetius/ghost/blob/main/AUDIT.md) —
  the claim-to-artifact mapping table: each claim of the paper
  paired with its underlying test, ADR, proof, or experiment.

CI runs the full test suite (~1785 tests) plus the TLA+ specs on
every push, across a Linux/Windows × Python 3.11/3.12 matrix. The
Lean proofs run locally; a `lean-proofs` CI job is the natural
next step.

The v0.2.5 release is published on PyPI
(`pip install project-ghost==0.2.5`) with sigstore attestations
via OIDC trusted publishing, and on GitHub as a tagged release
with the source distribution and the platform wheel as assets.

## AI tool use (disclosure)

This paper was prepared with the assistance of Anthropic Claude AI
as a coding pair-programmer and editorial reviewer. **The
conceptual contributions, the formal property definitions, the
seven epistemic safety contracts, the experimental design, the
reproducibility approach, and all final decisions are the
author's.** AI assistance was used for code generation under
supervision, for drafting technical prose in English, and for
translating the long-form paper to Spanish and Chinese. All
theorems, claims, citations, and bibliographic references were
independently verified by the author against their primary sources
before submission. The author takes full responsibility for the
content of this paper.

## Novelty Statement

This work has not been published nor submitted for publication to
any other journal. We declare no conflicts of interest.

<!-- TO COMPLETE BEFORE SUBMISSION TO TOSEM:
     After publishing the preprint on arXiv, add the sentence:
     "A preprint of the v0.2.5 results is available at
     arxiv.org/abs/XXXX.XXXXX and corresponds to this
     submission."
     Replace XXXX.XXXXX with the actual arXiv ID. -->
[_TODO: add line with arXiv ID once the preprint is published._]

## Acknowledgements

The idea behind this work emerged during the development of
Ghost. What began as a project centred on simulation and
reproducible verification gradually evolved toward a more
fundamental question: not only whether an agent acts correctly,
but how it should behave when it stops trusting its own beliefs
about the environment. That question led to the definition of the
epistemic safety contracts proposed in this paper.

The project was developed over multiple cycles of implementation,
experimentation, and conceptual revision. As the work progressed,
it became clear that many safety-relevant properties described not
only the state of the environment but also the agent's
relationship with its own uncertainty. This shift in perspective
ultimately became the central contribution of the work.

I thank the editor and reviewers for their time and hope the
paper meets the quality bar.

Sincerely,

Javier Menéndez Mateos
*Independent*
jfhelvetius@gmail.com
[github.com/JFHelvetius](https://github.com/JFHelvetius)
