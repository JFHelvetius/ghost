# ADR-0042 — Mechanical proofs in Lean 4 (partition theorem + partial RLB-v1 unbounded)

## Status

Accepted (v0.2.5).

Advances ADR-0038 from "partial discharge" toward full closure by
shipping mechanically-checked Lean 4 proofs for:

- The full **partition theorem** (`INV_PARTITION` from
  [`BaudErur.tla`](../proofs/BaudErur.tla)): both directions of
  the BAUD ⊕ ERUR exclusivity, plus the exhaustiveness corollary
  `partition_exactly_one`.
- **Partial** unbounded RLB-v1: Lemmas 1–3 of the hand proof
  (`countDirty_bounded`, `windowUpdate_length_bounded`,
  `dirtyAcc_count`) plus three more auxiliary lemmas
  (`dirtyAcc_length`, `dirtyAcc_all_dirty`,
  `cleanAfterDirty_length`) and the **Theorem 1 statement**
  itself, mechanically reduced to a single remaining lemma
  (`cleanAfterDirty_count_pending`, the load-bearing Lemma 4) that
  ships as a documented `sorry` placeholder.

## Context

ADR-0038 (v0.2.5 round 27) shipped the **triple-evidence**
package for unbounded RLB-v1: TLC parametric sweep, hand proof,
and a refined TLAPS outline. The outline had every lemma as
`PROOF OMITTED`, awaiting a future contributor with TLAPS
installed.

TLAPS is Linux/macOS only. WSL2 is "experimental" per the
upstream docs and requires a reboot to install. Within the v0.2.5
session, the pragmatic alternative was a different mechanizer
that installs natively on Windows. **Lean 4** met the criterion:

- Native Windows install via `elan` (no reboot, no WSL2).
- Standard library is sufficient for the proofs we need
  (`List`, `Nat`, `omega`); no mathlib dependency.
- Axioms used are limited to `propext` and `Quot.sound` (the
  same axioms TLAPS proofs rely on through Zenon / Isabelle).
- The proof certificate is independent of TLAPS, satisfying the
  paper's "mechanical evidence" claim by a different (and
  arguably stronger, since type-theoretic) route.

The two artefacts ADR-0042 ships are not a *replacement* for
the TLAPS outline; they are an **independent** discharge of the
same statements in a different proof system. A future contributor
with TLAPS installed can still execute the
[`Rlb_unbounded.tla`](../proofs/Rlb_unbounded.tla) outline; the
Lean files give an independent witness in the meantime.

## Decision

### 1. Lean 4 proof artefacts

Two new files under [`docs/proofs/Lean/`](../proofs/Lean/):

- [`PartitionTheorem.lean`](../proofs/Lean/PartitionTheorem.lean)
  — full mechanical proof of `INV_PARTITION`. Two theorems:
  - `inv_partition`: BAUD ⊕ ERUR exclusivity given `raw = known`.
  - `partition_exactly_one`: exhaustiveness corollary
    (BAUD ∨ ERUR holds under `raw = known`).

  Both axioms-set: `[propext, Quot.sound]` (i.e. standard;
  **no `sorryAx`**).

- [`RlbUnbounded.lean`](../proofs/Lean/RlbUnbounded.lean)
  — Lemmas 1–3 of the hand proof + auxiliaries + Theorem 1
  statement. Six fully mechanized lemmas:
  - `countDirty_bounded`, `countDirty_nonneg` (Lemma 1).
  - `windowUpdate_length_bounded` (Lemma 2).
  - `dirtyAcc_length`, `dirtyAcc_all_dirty`,
    `countDirty_of_all_dirty`, `dirtyAcc_count` (Lemma 3 +
    auxiliaries).
  - `cleanAfterDirty_length`, `countDirty_append_clean`,
    `countDirty_tail_of_dirty_head`,
    `countDirty_tail_of_clean_head` (auxiliaries for Lemma 4).

  Plus the **Theorem 1 statement** (`rlb_unbounded`), mechanically
  reduced to `cleanAfterDirty_count_pending` (the only remaining
  `sorry`). When Lemma 4 is discharged, the theorem closes
  automatically.

  Six lemmas + Theorem 1 statement: full axiom set
  `[propext, Quot.sound]` for the mechanized ones; Lemma 4 and
  Theorem 1's discharge inherit `sorryAx` until Lemma 4 lands.

### 2. Sanity check

[`Sanity.lean`](../proofs/Lean/Sanity.lean) is a 4-line file that
proves `1 + 1 = 2` and `add_comm_nat`. It is the canary that the
Lean 4 install is reproducible: any future contributor can run
`lean Sanity.lean` to verify the toolchain before tackling the
main proofs.

### 3. Toolchain pin

- Lean 4 version: 4.31.0 (the stable channel as of v0.2.5).
- Install procedure: PowerShell `elan-init.ps1` with
  `-NoPrompt $true -NoModifyPath $true -DefaultToolchain
  "leanprover/lean4:stable"`.
- The pinning prevents the proofs from breaking under a future
  Lean 4 breaking change.

### 4. Scope — what this ADR closes and does NOT close

**This ADR claims (v0.2.5):**

- The partition theorem (BAUD ⊕ ERUR) is mechanically verified
  in Lean 4 with no `sorry`. This was an open follow-up under
  ADR-0036 and the paper §10 future-work item "TLAPS proof of
  the partition theorem"; Lean 4 closes it via the same
  type-theoretic route.
- Lemmas 1–3 + auxiliaries of unbounded RLB-v1 are mechanically
  verified in Lean 4 with no `sorry`. The Theorem 1 statement is
  mechanically reduced to Lemma 4.

**This ADR does NOT close:**

- **Lemma 4** (`cleanAfterDirty_count_pending`). The load-bearing
  recovery-phase count formula remains as a `sorry` placeholder.
  The accompanying comment in the Lean file documents the
  proof strategy and explains the remaining work (auxiliary
  "DIRTYs precede CLEANs in window" invariant). Discharging
  Lemma 4 is the natural ADR-0044 follow-up.
- The TLAPS outline (`Rlb_unbounded.tla`). It remains as the
  *bridge document* — a future contributor with TLAPS can still
  use it to obtain a TLAPS-mechanical proof; the Lean 4 proof
  is an alternative discharge route.
- The unbounded version of any other property (BAUD/ERUR/MD/FPB).
  ADR-0042 covers RLB-v1 unbounded specifically; extensions are
  follow-ups.

## Why Lean 4 (and not Coq, Isabelle, Agda)

Decision rationale:

- **Lean 4 installs natively on Windows via elan.** No reboot,
  no WSL2. Single PowerShell invocation reproduces the install.
- **Standard library suffices for these proofs.** No mathlib
  dependency means no large download, no version drift, no
  `import Mathlib.*` fragility. The proofs use only `List`,
  `Nat`, `omega`, and structural induction.
- **Axioms minimal and well-known.** `propext` and `Quot.sound`
  are the same axioms TLAPS proofs effectively rely on (via
  Zenon / Isabelle). No additional axiom commitments.
- **`omega` tactic closes arithmetic obligations cheaply.** The
  inductive structure of the lemmas matches the tactic's
  strengths.
- **Type theory is at least as expressive as set theory** for
  these statements. The mechanical certificate is comparable in
  strength to a TLAPS one.

Alternatives considered:

- **Coq.** Installs on Windows but `omega`-equivalent (`lia`) is
  less ergonomic in the standard library; mathlib equivalent is
  larger. Comparable strength, slightly heavier tooling.
- **Isabelle/HOL.** Reasonable but the proof style (Isar) is
  unfamiliar to most paper readers. Adds a learning curve to
  the audit surface.
- **Agda.** Type-theoretic like Lean but the install story is
  rockier on Windows and the standard library is sparser. Not
  the right fit.

## Verification plan

- The two Lean files are checked offline by `lean
  PartitionTheorem.lean` and `lean RlbUnbounded.lean`. Exit 0
  with `propext, Quot.sound` axioms (plus `sorryAx` for the
  documented placeholder) is the success criterion.
- A future follow-up integrates these checks into CI as a new
  `lean-proofs` job (currently the CI matrix is Python + TLC
  only). Deferred to keep the v0.2.5 round focused.

## Alternatives considered

1. **Install TLAPS via WSL2 in this session.** Rejected: WSL2
   install requires a reboot. The pragmatic alternative is Lean
   4, which installs natively on Windows.
2. **Ship only the partition theorem in Lean 4.** Considered:
   would have been a smaller and cleaner round. Rejected: the
   v0.2.5 RLB-v1 partial mechanization is itself a substantial
   improvement over the ADR-0038 round-27 status (where every
   lemma was `PROOF OMITTED`); shipping it incrementally pulls
   the §9 limitation closer to closure faster.
3. **Use Mathlib.** Considered for `List.IsPrefix` and other
   structural reasoning that would have shortened Lemma 4.
   Rejected for v0.2.5: mathlib install adds a `lake build`
   step and an external dependency that complicates
   reproducibility. The proofs that *do* land use only the Lean
   4 standard library; Lemma 4 stays as a `sorry` rather than
   take on the dependency, which is the honest trade-off.
4. **Skip mechanical proofs; rely on the hand proof.**
   Rejected: the hand proof is auditable but not SMT-checked;
   shipping the mechanical Lean 4 proof for the parts that *do*
   close strengthens the paper's "verifiable contracts" claim.

## References

- Partition theorem proof:
  [`docs/proofs/Lean/PartitionTheorem.lean`](../proofs/Lean/PartitionTheorem.lean)
- RLB-v1 unbounded proof (partial):
  [`docs/proofs/Lean/RlbUnbounded.lean`](../proofs/Lean/RlbUnbounded.lean)
- Sanity check: [`docs/proofs/Lean/Sanity.lean`](../proofs/Lean/Sanity.lean)
- Hand proof (the script for the Lean proofs):
  [`docs/proofs/Rlb_unbounded_handproof.md`](../proofs/Rlb_unbounded_handproof.md)
- TLAPS outline (the alternative route, still open):
  [`docs/proofs/Rlb_unbounded.tla`](../proofs/Rlb_unbounded.tla)
- TLA+ bounded TLC ADR:
  [`docs/adr/0036-tla-plus-mechanical-verification-of-baud-erur.md`](0036-tla-plus-mechanical-verification-of-baud-erur.md)
- ADR-0038 (triple evidence):
  [`docs/adr/0038-rlb-unbounded-verification.md`](0038-rlb-unbounded-verification.md)
- Paper §6.2 (partition theorem), §6.3 (RLB-v1 unbounded), §9 (limitations), §10 (future work)
