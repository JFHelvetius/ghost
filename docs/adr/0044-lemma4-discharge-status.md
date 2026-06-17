# ADR-0044 — Lemma 4 discharge status (the last `sorry` of unbounded RLB-v1)

## Status

Candidate, **partially advanced** in v0.2.5 round 32.

The `cleanAfterDirty_count_pending` lemma in
[`docs/proofs/Lean/RlbUnbounded.lean`](../proofs/Lean/RlbUnbounded.lean)
ships with **two auxiliary lemmas now fully discharged**
(`cleanAfterDirty_length`, `countDirty_append_clean`,
`countDirty_tail_of_dirty_head`, `countDirty_tail_of_clean_head`) and a
**shape-lemma sketch** documented inline. The remaining `sorry` on the
main count formula is the last leg of the unbounded RLB-v1 mechanical
proof; round 32 advances it but does not close it.

The full discharge is targeted at the next round (or a future
contributor with a Lean 4 + mathlib environment) per the path
described in §"Why the round-32 attempt did not close it" below.

## Context

ADR-0042 (v0.2.5 round 28) shipped Lean 4 mechanical proofs for the
partition theorem (fully discharged, no `sorry`) and for 9 lemmas
plus the Theorem 1 statement of unbounded RLB-v1, with the
remaining work — the load-bearing
**`cleanAfterDirty_count`** lemma (Lemma 4 of the hand proof) —
shipped as a documented `sorry` placeholder.

ADR-0044 was named at the same round as the natural follow-up. Round
32 (this round) attempts the discharge and **partially advances**
it.

## What v0.2.5 round 32 advances

### 1. Two new auxiliary lemmas discharged

[`docs/proofs/Lean/RlbUnbounded.lean`](../proofs/Lean/RlbUnbounded.lean)
now ships **four new mechanically verified auxiliaries** with axiom
set `{propext, Quot.sound}` (no `sorry`):

- `cleanAfterDirty_length`: the recovery-phase length grows from
  `N` to saturation at `W`.
- `countDirty_append_clean`: appending CLEAN preserves count.
- `countDirty_tail_of_dirty_head`: tail-pop on a DIRTY head drops
  the count by 1.
- `countDirty_tail_of_clean_head`: tail-pop on a CLEAN head
  preserves the count.

These are the four building blocks the Lemma 4 induction step
needs. Round 32 ships them as standalone discharged lemmas; the
final composition is the remaining work.

### 2. Shape-lemma sketch documented inline

The Lean file's inline comments describe the structural invariant
the Lemma 4 induction needs (`cleanAfterDirty(N, W, k)` has the
form `replicate r dirty ++ replicate s clean` for explicit `r, s`
depending on `k`'s region). A future contributor lifts the
sketch to a real `theorem cleanAfterDirty_shape` and the count
formula falls out by `simp [countDirty_append]`.

### 3. The discharge remains a `sorry`

The main formula
`countDirty (cleanAfterDirty N W k) = if k ≤ W - N then N else N - (k - (W - N))`
ships as a documented `sorry` placeholder. The transitively-induced
`sorryAx` axiom appears in `rlb_unbounded` (Theorem 1 statement).

## Why the round-32 attempt did not close it

A round-32 attempt at the shape lemma uncovered the following
technical constraint:

The shape lemma's discharge requires reasoning about
**structural prefixes** of lists (the DIRTYs-precede-CLEANs
invariant). The Lean 4 standard library has list operations
(`List.append`, `List.tail`, `List.replicate`) but does **not**
ship `List.IsPrefix` / `List.IsSuffix` in core. Those live in
**`mathlib`**.

Project Ghost's Lean 4 proofs deliberately do **not** depend on
`mathlib` (ADR-0042 §"Why Lean 4 (and not Coq, Isabelle, Agda)"
documents the rationale: standalone install, no external lake
dependency, axiom commitment is `{propext, Quot.sound}` only).
Bringing in `mathlib` would add a heavy build dependency, change
the install story, and broaden the axiom commitment.

The round-32 attempt explored several routes:

1. **Direct induction by region splits** (without the shape
   lemma). The proof obligations grow quadratically in case
   complexity; `omega` closes the arithmetic but the list-shape
   side goals do not discharge without an explicit invariant.
2. **Inline `replicate` shape via existentials**. The
   `∃ r s, list = replicate r dirty ++ replicate s clean ∧ ...`
   form discharges in core Lean, but the induction step requires
   the auxiliary "DIRTYs precede CLEANs" reasoning, which without
   `List.IsPrefix` produces verbose case analyses on
   `replicate (r+1) dirty = dirty :: replicate r dirty`.
3. **Encoding the shape via length + count alone** (without
   explicit replicate). Possible in principle, requires
   re-deriving DIRTY-first ordering from the recursion;
   tractable but verbose.

Round 32 ships paths 2 and 3 as **future-contributor scaffolding**
in the Lean file's inline comments. A contributor with mathlib
available can close the discharge in path 1 in an hour; without
mathlib, path 3 is the recommended route, estimated at 2-3 days
of Lean development.

## Decision

Round 32 **advances ADR-0044 without closing it**. The four new
auxiliary lemmas are shipped as standalone proofs; the shape
lemma is documented in inline comments; the main `sorry` remains.

A future round (or contributor) closes Lemma 4 via either:

- **(A)** Add `mathlib` as an opt-in dependency, lift the
  `List.IsPrefix` reasoning, discharge in ~1h.
- **(B)** Stay mathlib-free, work through path 3 (length + count
  encoding), ~2-3 days.
- **(C)** Discharge in TLAPS instead (the `Rlb_unbounded.tla`
  outline at `docs/proofs/Rlb_unbounded.tla` is the canonical
  TLAPS path; ADR-0038 follow-up). This requires Linux/macOS for
  the TLAPS install.

The choice between (A), (B), (C) is a future decision; round 32
does not pre-commit.

## Scope — what this ADR claims and does NOT claim

**This ADR claims (v0.2.5 round 32):**

- Four new auxiliary lemmas are mechanically verified in Lean 4
  with axiom set `{propext, Quot.sound}`.
- The Lemma 4 discharge path is documented in inline comments
  with three viable routes.
- The remaining `sorry` is scoped: it is *only*
  `cleanAfterDirty_count_pending`; the rest of the unbounded
  RLB-v1 file is fully discharged.

**This ADR does NOT claim:**

- That Lemma 4 is mechanically proven. It is not. The `sorry`
  remains.
- That round 32 chose a path. It did not; (A), (B), (C) all
  remain open.
- That the v0.2.5 unbounded RLB-v1 result is complete. The TLC
  parametric sweep (ADR-0038) gives empirical evidence at
  `W ∈ {4, 8, 16}`, the hand proof is rigorous, and the Lean 4
  proof is 9/10 lemmas + Theorem 1 statement + 4 new auxiliaries;
  the 10th lemma still needs work.

## Verification plan

Once any of (A), (B), or (C) lands:

1. Replace the `sorry` in `cleanAfterDirty_count_pending` with a
   real proof.
2. Re-run `lean RlbUnbounded.lean` and confirm the
   `#print axioms` of `rlb_unbounded` reports only
   `{propext, Quot.sound}` (no `sorryAx`).
3. Update [ADR-0042](0042-lean4-mechanical-proofs.md) §"This ADR
   does NOT close" to remove the Lemma 4 entry.
4. Update paper §9 limitations: remove the
   "1 `sorry` remaining" disclosure.
5. Update [ADR-0038](0038-rlb-unbounded-verification.md) §"What
   this ADR does NOT close" to remove the Lemma 4 entry.

## What this ADR does NOT close

- **The Lemma 4 discharge itself.** Round 32 advances; future
  rounds close.
- **The TLAPS leg.** Independent of Lean 4. The
  `Rlb_unbounded.tla` outline remains for contributors who
  prefer the TLA+ ecosystem.

## Alternatives considered

1. **Discharge Lemma 4 in round 32 using core Lean only,
   accepting verbosity.** Attempted; the 30-minute timebox was
   insufficient. Documented as path (B).
2. **Adopt `mathlib` for path (A).** Considered; rejected for
   v0.2.5 to keep ADR-0042's "no mathlib" promise. Future round
   may revisit.
3. **Skip Lean 4, finish in TLAPS.** Considered; documented as
   path (C). Requires Linux/macOS; defers to a contributor with
   the right environment.
4. **Ship without auxiliaries.** Rejected: the four new auxiliary
   lemmas are useful in their own right and reduce the surface
   area of the remaining `sorry`. Shipping them is a positive
   round-32 contribution.

## References

- ADR-0042 (Lean 4 mechanical proofs):
  [`docs/adr/0042-lean4-mechanical-proofs.md`](0042-lean4-mechanical-proofs.md)
- ADR-0038 (unbounded RLB-v1 evidence package):
  [`docs/adr/0038-rlb-unbounded-verification.md`](0038-rlb-unbounded-verification.md)
- Hand proof:
  [`docs/proofs/Rlb_unbounded_handproof.md`](../proofs/Rlb_unbounded_handproof.md)
- TLAPS outline:
  [`docs/proofs/Rlb_unbounded.tla`](../proofs/Rlb_unbounded.tla)
- Lean 4 file:
  [`docs/proofs/Lean/RlbUnbounded.lean`](../proofs/Lean/RlbUnbounded.lean)
- Paper §6.3 (the bound), §9 (limitations), §10 (future work).
