# Cover Letter: Project Ghost — Epistemic Safety Contracts for Autonomous Agents

**Target venue:** ACM Transactions on Software Engineering and
Methodology (TOSEM) — Regular Paper category.

**Alternate venues (in order of preference):** IEEE Transactions
on Software Engineering (TSE), CAV (Computer Aided Verification),
FMCAD (Formal Methods in Computer-Aided Design).

**Manuscript:** *Project Ghost: Epistemic Safety Contracts as a
Property Class for Autonomous Agents.* J.M. Mateos. v0.2.5
(rounds 23–29, January 2026).

---

Dear Editor,

We respectfully submit the manuscript *Project Ghost: Epistemic
Safety Contracts as a Property Class for Autonomous Agents* for
consideration as a Regular Paper in TOSEM.

## What we contribute

The paper introduces **epistemic safety contracts** as a
property class distinct from (a) STL-style predicates over
external signals and (b) POMDP-style belief monitoring. An
epistemic safety contract is a triple `(P, Q, V)` where `P`
and `Q` are predicates over the *agent's own posture under
uncertainty* (drift detected, belief calibrated, recovery
bounded), and `V` is a pure-function verifier over a
content-addressed run.

Our four main contributions are:

1. **The property class itself.** We argue that contracts over
   epistemic posture answer questions the existing classes do not:
   "did the agent degrade conservatively when its own confidence
   was suspect?", "did it return to acting when evidence was
   restored?", "is its recovery latency bounded?". The property
   class is formalised in v0.2.5 as a Python `Protocol`
   (`EpistemicSafetyContract`) plus a registry of seven shipped
   contracts (BAUD-v1, ERUR-v1, ERUR-v2, MD-v1, RLB-v1, FPB-v1,
   FPB-v2).

2. **Seven concrete contracts plus their verifiers and proofs.**
   Each contract is stated in a binding ADR (immutable once
   accepted), verified by a pure function over a captured MCAP,
   and tested by a Hypothesis property test. Five of the seven
   are additionally mechanically proven: the BAUD/ERUR
   partition theorem and Lemmas 1–3 of unbounded RLB-v1 in Lean
   4 (no `mathlib`, axioms restricted to `propext` and
   `Quot.sound`); BAUD, ERUR, MD, RLB at bounded `W` in TLC;
   RLB-v1 at `W ∈ {4, 8, 16}` via a parametric TLC sweep;
   FPB-v1 counter well-formedness in TLC. The remaining gap —
   Lemma 4 of unbounded RLB-v1 — ships as a documented `sorry`
   in Lean and is reduced to a single load-bearing inductive
   step (ADR-0044 candidate).

3. **A mechanical bridge between the Python verifier and the
   TLA+ specification.** Until v0.2.5 the paper acknowledged a
   "Python ↔ TLA+ bridge by inspection" caveat. ADR-0043 closes
   this for RLB-v1 with a Hypothesis-checked test that
   re-implements both semantics independently from their
   respective sources and asserts they agree on every trace
   Hypothesis can synthesise within bounds. The template
   extends to the other six contracts (ADR-0046 candidate).

4. **An end-to-end discrimination experiment on real PX4
   telemetry.** Six bug categories from the synthetic violation
   matrix are exercised on three structurally distinct PX4
   SITL ULogs. With independent simulator GT enabled
   automatically when `vehicle_*_groundtruth` topics are
   present (ADR-0037, v0.2.5), the discrimination matrix is
   18/18 green; 15/18 cells isolate the violation to the
   expected property. The single non-isolated row is a true
   co-violation between BAUD-v1 and MD-v1 (inflated-confidence
   calibrator).

## Why now

The intersection of autonomous systems, runtime verification,
and formal methods has produced excellent work on each of the
three sides (STL/MITL monitoring; POMDP belief verification;
TLA+/TLAPS-style proofs). What is missing is a property class
that captures **how an agent ought to relate to its own
uncertainty** — the class our paper introduces and instantiates
with a working implementation, a content-addressed run format,
seven verifiers, mechanical proofs, and a real-telemetry
experiment.

## Why this venue

TOSEM publishes work that combines methodological contributions
(here: the property class) with engineering substance (here: the
implementation, the seven verifiers, the mechanical proofs, the
ADR-driven design discipline). Recent issues have featured
papers on STL monitoring, runtime verification frameworks, and
formal verification of robotic systems; our paper sits at the
intersection of these tracks. TSE, CAV, and FMCAD are
alternates we will consider in that order.

## Reproducibility

The full code, paper sources, ADRs, mechanical proofs, and
reproducibility scripts are public at
[github.com/JFHelvetius/ghost](https://github.com/JFHelvetius/ghost)
under the Apache-2.0 license. Three top-level documents make the
artefact navigable:

- [`INSTALL.md`](https://github.com/JFHelvetius/ghost/blob/main/INSTALL.md) —
  fresh-install guide for Python, Java, Lean, and tla2tools.
- [`REPRODUCE.md`](https://github.com/JFHelvetius/ghost/blob/main/REPRODUCE.md) —
  end-to-end reproduction of every paper claim
  (R1–R7, ~10 minutes total on a modern laptop).
- [`AUDIT.md`](https://github.com/JFHelvetius/ghost/blob/main/AUDIT.md) —
  the claim-to-artefact mapping table: every paper claim is
  matched to its grounding test, ADR, proof, or experiment.

CI exercises the full test suite (~1700 tests) plus the TLA+
specs on every push, across a 4-element Linux/Windows × Python
3.11/3.12 matrix. The Lean proofs are exercised locally; a
`lean-proofs` CI job is the natural follow-up.

## Suggested reviewers

We respectfully suggest the following reviewers as having the
right intersection of expertise (runtime verification, formal
methods for autonomy, mechanical theorem proving):

1. (To be completed by the author.)

We have no conflicts of interest to disclose.

## Statement of novelty

This work has not been published or submitted for publication
elsewhere. An earlier preprint of the v0.2.3 results is available
at [arxiv.org/abs/TBD](https://arxiv.org/abs/TBD) and is
super-seded by v0.2.5 (this submission).

## Acknowledgments

We thank the early reviewers (anonymised) for feedback on the
v0.2.0–v0.2.4 iterations. The Lean 4 proof effort benefited from
the standard library's `omega` tactic; the TLA+ specs build on
the long tradition of TLC model checking; the discrimination
experiment uses public PX4 test ULogs (BSD-3, PX4/pyulog).

We are grateful to the editor and reviewers for their time and
hope the paper meets the bar.

Sincerely,

J.M. Mateos
*Evergreen Botánica*
jfhelvetius@gmail.com
[github.com/JFHelvetius](https://github.com/JFHelvetius)
