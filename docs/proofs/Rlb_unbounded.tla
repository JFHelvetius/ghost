--------------------------- MODULE Rlb_unbounded ---------------------------
(****************************************************************************)
(* TLAPS proof skeleton for the unbounded version of RLB-v1               *)
(* (paper §6.3; Action C roadmap).                                          *)
(*                                                                          *)
(* The bounded TLC verification in ``Rlb.tla`` proves INV_RLB over a fixed   *)
(* (W=4, MAX_DRIFT=4) state space. This module sketches the path to a full *)
(* TLAPS theorem proving the bound for any W, M, K in Nat — promoting the   *)
(* claim from "exhaustive over a finite abstract model" to "proved for any *)
(* finite parameterisation".                                                *)
(*                                                                          *)
(* TLAPS = TLA+ Proof System (https://tla.msr-inria.inria.fr/tlaps/).        *)
(* TLAPS proofs are checked by a combination of SMT solvers (Zenon,         *)
(* Isabelle, CVC4, Z3); the resulting certificate is independent of the     *)
(* model-checking bounds used by TLC.                                        *)
(*                                                                          *)
(* STATUS: This module is a PROOF OUTLINE, not a verified proof. The        *)
(* THEOREM statements compile under TLAPS, but the BY tactics are           *)
(* placeholders (``OMITTED`` or ``PROOF OMITTED``) that a future            *)
(* contributor would discharge. See ``docs/proofs/TLAPS_roadmap.md`` for    *)
(* the install + verification workflow.                                     *)
(****************************************************************************)

EXTENDS Naturals, FiniteSets, Sequences, TLAPS

CONSTANTS W      \* sliding-window size, Nat, > 0

ASSUME W_pos == W \in Nat /\ W > 0

(* --------- abstract verdict + window state (mirror of Rlb.tla) ----------- *)

DIRTY == "dirty"
CLEAN == "clean"
Verdicts == {DIRTY, CLEAN}

CountDirty(h) == Cardinality({i \in DOMAIN h : h[i] = DIRTY})

WindowUpdate(h, o) ==
    IF Len(h) < W
    THEN Append(h, o)
    ELSE Append(Tail(h), o)

(****************************************************************************)
(* Lemma 1: CountDirty is non-negative and bounded by Len(h).               *)
(****************************************************************************)

LEMMA CountDirty_bounded ==
    \A h \in Seq(Verdicts) :
        0 <= CountDirty(h) /\ CountDirty(h) <= Len(h)
PROOF OMITTED  \* discharge by induction on Len(h)

(****************************************************************************)
(* Lemma 2: WindowUpdate preserves Len(h) <= W.                            *)
(****************************************************************************)

LEMMA WindowUpdate_bounded ==
    \A h \in Seq(Verdicts), o \in Verdicts :
        Len(WindowUpdate(h, o)) <= W
PROOF OMITTED  \* case split on Len(h) < W vs Len(h) = W

(****************************************************************************)
(* Lemma 3: After N consecutive DIRTY arrivals starting from an empty       *)
(* window, the window contains min(N, W) dirty entries.                    *)
(****************************************************************************)

\* Inductive type: a function rep : Nat -> Seq(Verdicts) where
\* rep(0) = <<>> and rep(n+1) = WindowUpdate(rep(n), DIRTY).
RECURSIVE DirtyAcc(_)
DirtyAcc(n) ==
    IF n = 0 THEN <<>>
    ELSE WindowUpdate(DirtyAcc(n - 1), DIRTY)

LEMMA DirtyAcc_count ==
    \A n \in Nat :
        CountDirty(DirtyAcc(n)) =
            IF n <= W THEN n ELSE W
PROOF OMITTED  \* induction on n with the W boundary as the inductive split

(****************************************************************************)
(* Lemma 4: After accumulation phase (N <= W DIRTY) followed by k CLEAN     *)
(* outcomes with k < W, the window contains min(N, W - k) dirty entries.   *)
(****************************************************************************)

RECURSIVE CleanAfterDirty(_, _)
CleanAfterDirty(N, k) ==
    IF k = 0 THEN DirtyAcc(N)
    ELSE WindowUpdate(CleanAfterDirty(N, k - 1), CLEAN)

LEMMA CleanAfterDirty_count ==
    \A N, k \in Nat :
        (N <= W /\ k <= W) =>
            CountDirty(CleanAfterDirty(N, k)) =
                IF k <= W - N THEN N
                ELSE IF k <= W THEN N - (k - (W - N))
                ELSE 0
PROOF OMITTED  \* induction on k, using WindowUpdate_bounded + DirtyAcc_count

(****************************************************************************)
(* RLB-v1 (UNBOUNDED): for N <= W consecutive DIRTY outcomes followed   *)
(* by clean outcomes, the dirty-run length L = peak + W - 1, where         *)
(* peak = N.                                                                *)
(*                                                                          *)
(* Statement in terms of CleanAfterDirty:                                  *)
(*                                                                          *)
(*   For any N in 1..W, the smallest k such that                            *)
(*   CountDirty(CleanAfterDirty(N, k)) = 0 equals W + N - N = W + (N - N) = ?*)
(*                                                                          *)
(* Refinement of the statement: with peak = N, the dirty-run length is the *)
(* number of cycles where CountDirty > 0. From the accumulation + flush     *)
(* phases of CleanAfterDirty:                                              *)
(*                                                                          *)
(*   - cycles 1..N: count goes 1, 2, ..., N (all dirty)                    *)
(*   - cycles N+1..W: count stays at N (window not yet full, all dirty)    *)
(*   - cycles W+1..W+N-1: count goes N-1, N-2, ..., 1 (all dirty)          *)
(*   - cycle W+N: count = 0 (clean — recovery transition)                  *)
(*                                                                          *)
(* Total dirty cycles = W + N - 1 = peak + W - 1.                         *)
(****************************************************************************)

THEOREM Theorem1_unbounded ==
    \A N \in 1..W :
        \E L \in Nat :
            /\ L = W + N - 1
            /\ CountDirty(CleanAfterDirty(N, L - N)) > 0
            /\ CountDirty(CleanAfterDirty(N, L - N + 1)) = 0
PROOF OMITTED  \* compose CleanAfterDirty_count with arithmetic; ~50 BY steps

================================================================================
