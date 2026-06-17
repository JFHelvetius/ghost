/-
Mechanical proof of the BAUD ⊕ ERUR partition theorem
(paper §6.2, ADR-0036, INV_PARTITION in `BaudErur.tla`).

This Lean 4 proof closes one of the two TLAPS placeholders the
v0.2.5 round left open. The partition theorem is the simpler of
the two and was the natural first mechanization to attempt
without TLAPS (Lean 4 installs natively on Windows; TLAPS does
not).

The statement is independent of W, M, K — it relies only on the
literal complementarity of `BAUDPrecondition` and
`ERURPrecondition` under `raw_level = KNOWN`. The proof is a
single case split that Lean's `omega` tactic closes.
-/

-- Outcomes of a single cycle in the abstract trace family.
inductive Verdict where
  | dirty
  | clean
  deriving DecidableEq, Repr

open Verdict

-- Confidence levels in the assessment lattice.
inductive Level where
  | known
  | uncertain
  | unknown
  deriving DecidableEq, Repr

open Level

/-- `CountDirty(h) := |{i ∈ DOMAIN h : h[i] = DIRTY}|`. Mirrors
the TLA+ definition literally. -/
def countDirty : List Verdict → Nat
  | [] => 0
  | dirty :: rest => 1 + countDirty rest
  | clean :: rest => countDirty rest

/-- `BAUDPrecondition(h)` from `BaudErur.tla`. -/
def baudPrecondition (h : List Verdict) (M K : Nat) : Prop :=
  h.length ≥ M ∧ countDirty h ≥ K

/-- `DriftClean(h)` from `BaudErur.tla`: literal De Morgan
negation of the BAUD drift conjunction. -/
def driftClean (h : List Verdict) (M K : Nat) : Prop :=
  h.length < M ∨ countDirty h < K

/-- `ERURPrecondition(h, raw)` from `BaudErur.tla`. -/
def erurPrecondition (h : List Verdict) (raw : Level) (M K : Nat) : Prop :=
  driftClean h M K ∧ raw = known

/-- INV_PARTITION (the load-bearing theorem of paper §6.2).
When `raw = known`, `BAUDPrecondition` and `ERURPrecondition`
partition the cycle space exactly: each implies the negation of
the other.

This is the formal statement of the integration-test invariant
`test_smoke_baud_and_erur_partition_the_cycle_space`, promoted
from "observed on the smoke trace" to "proven for all reachable
states of the abstract model".
-/
theorem inv_partition
    (h : List Verdict) (raw : Level) (M K : Nat) (h_raw : raw = known) :
    baudPrecondition h M K ↔ ¬ erurPrecondition h raw M K := by
  unfold baudPrecondition erurPrecondition driftClean
  constructor
  · -- BAUD → ¬ERUR
    intro hBaud hErur
    obtain ⟨hM, hK⟩ := hBaud
    obtain ⟨hDrift, _⟩ := hErur
    cases hDrift with
    | inl hLen => omega
    | inr hCount => omega
  · -- ¬ERUR → BAUD
    intro hNotErur
    -- Case split on the two BAUD conjuncts; we show both hold by
    -- contradicting hNotErur in each failure case.
    by_cases hM : h.length ≥ M
    · by_cases hK : countDirty h ≥ K
      · -- Both conjuncts hold: BAUD precondition is met.
        exact ⟨hM, hK⟩
      · -- K fails: drift-clean via the K branch, contradicting hNotErur.
        exfalso
        apply hNotErur
        refine ⟨?_, h_raw⟩
        right
        omega
    · -- M fails: drift-clean via the M branch, contradicting hNotErur.
      exfalso
      apply hNotErur
      refine ⟨?_, h_raw⟩
      left
      omega

/-- Sanity corollary: if `raw = known`, exactly one of
the two preconditions holds. -/
theorem partition_exactly_one
    (h : List Verdict) (M K : Nat) :
    baudPrecondition h M K ∨ erurPrecondition h known M K := by
  unfold baudPrecondition erurPrecondition driftClean
  -- Either both M and K floors are met (BAUD), or one of them is not (ERUR).
  by_cases hM : h.length ≥ M
  · by_cases hK : countDirty h ≥ K
    · left; exact ⟨hM, hK⟩
    · right; refine ⟨?_, rfl⟩
      right; omega
  · right; refine ⟨?_, rfl⟩
    left; omega

#check @inv_partition
#check @partition_exactly_one

#print axioms inv_partition
#print axioms partition_exactly_one
