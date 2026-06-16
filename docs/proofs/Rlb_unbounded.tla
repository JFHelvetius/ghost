--------------------------- MODULE Rlb_unbounded ---------------------------
(****************************************************************************)
(* TLAPS proof outline for the unbounded version of RLB-v1                *)
(* (paper section 6.3; Action C roadmap; ADR-0038).                        *)
(*                                                                          *)
(* The bounded TLC verification in `Rlb.tla` proves INV_RLB over a fixed   *)
(* (W=4, MAX_DRIFT=4) state space. v0.2.5 extends the empirical evidence  *)
(* with a parametric TLC sweep over W in {4, 8, 16} (see                  *)
(* Rlb_sweep.cfg.json + the CI sweep job). This module sketches the TLAPS *)
(* path to the full theorem for any W, M, K in Nat, lifting the claim    *)
(* from "exhaustive over a finite abstract model up to W=16" to "proved   *)
(* for any finite parameterisation".                                       *)
(*                                                                          *)
(* TLAPS = TLA+ Proof System (https://tla.msr-inria.inria.fr/tlaps/).        *)
(* TLAPS proofs are checked by a combination of SMT solvers (Zenon,         *)
(* Isabelle, CVC4, Z3); the resulting certificate is independent of the     *)
(* model-checking bounds used by TLC.                                        *)
(*                                                                          *)
(* STATUS: v0.2.5 ships THREE artefacts for unbounded RLB-v1:             *)
(*                                                                          *)
(*   1. Rlb.tla + the parametric sweep (Rlb_sweep.cfg.json), giving       *)
(*      mechanical TLC verification at W in {4, 8, 16} on every push.    *)
(*                                                                          *)
(*   2. Rlb_unbounded_handproof.md, a rigorous hand proof of the four     *)
(*      lemmas + theorem below. Not SMT-checked; auditable line by line. *)
(*                                                                          *)
(*   3. THIS MODULE, a TLAPS proof outline whose hierarchical BY tactics  *)
(*      are placeholders (`PROOF OMITTED`) that a future contributor with *)
(*      a working TLAPS install would discharge. Per-step discharge       *)
(*      guidance is included inline (the v0.2.5 refinement). See          *)
(*      `docs/proofs/TLAPS_roadmap.md` for the install + verification     *)
(*      workflow.                                                          *)
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
(*                                                                          *)
(* DISCHARGE GUIDANCE: 3 BY steps. CountDirty(h) is the cardinality of a    *)
(* subset of DOMAIN h, and |DOMAIN h| = Len(h). Use the FiniteSets module   *)
(* lemma SubsetCardinality and the Sequences bridge DOMAIN s = 1..Len(s).   *)
(****************************************************************************)

LEMMA CountDirty_bounded ==
    \A h \in Seq(Verdicts) :
        0 <= CountDirty(h) /\ CountDirty(h) <= Len(h)
PROOF OMITTED  \* 3 BY steps; see Rlb_unbounded_handproof.md Lemma 1

(****************************************************************************)
(* Auxiliary: every reachable window has Len <= W.                          *)
(*                                                                          *)
(* This is INV_WINDOW_BOUND from Rlb.tla, proved by inducting on the        *)
(* transition relation. In the standalone unbounded module we hoist it as  *)
(* a separate lemma because the trace family DirtyAcc/CleanAfterDirty      *)
(* needs it independently of the Rlb.tla state-machine framing.            *)
(*                                                                          *)
(* DISCHARGE GUIDANCE: structural induction on the sequence construction.  *)
(* Base: Len(<<>>) = 0 <= W. Step: Append(h, o) length is Len(h) + 1;       *)
(* Append(Tail(h), o) length is Len(h). Use W_pos for the W > 0 case.       *)
(****************************************************************************)

LEMMA WindowUpdate_LengthBounded ==
    \A h \in Seq(Verdicts), o \in Verdicts :
        Len(h) <= W => Len(WindowUpdate(h, o)) <= W
PROOF OMITTED  \* 5 BY steps; see Rlb_unbounded_handproof.md Lemma 2 Case A/B

(****************************************************************************)
(* Lemma 2: WindowUpdate preserves Len(h) <= W.                            *)
(*                                                                          *)
(* DISCHARGE GUIDANCE: composition of WindowUpdate_LengthBounded and the   *)
(* invariant of the construction (DirtyAcc / CleanAfterDirty only build   *)
(* windows of length <= W). A direct corollary; ~3 BY steps.                *)
(****************************************************************************)

LEMMA WindowUpdate_bounded ==
    \A h \in Seq(Verdicts), o \in Verdicts :
        Len(WindowUpdate(h, o)) <= W
PROOF OMITTED  \* 3 BY steps using WindowUpdate_LengthBounded

(****************************************************************************)
(* Auxiliary: when CountDirty(h) = Len(h), every entry of h is DIRTY.       *)
(* Used by Lemma 3's saturation case and Lemma 4's tail-pop argument.       *)
(*                                                                          *)
(* DISCHARGE GUIDANCE: |{i in DOMAIN h : h[i] = DIRTY}| = |DOMAIN h|        *)
(* forces every element to be DIRTY (the alternative is at most Len(h)-1   *)
(* DIRTY entries). 4 BY steps using SubsetEqualCardinalityImpliesEqual.    *)
(****************************************************************************)

LEMMA Saturated_AllDirty ==
    \A h \in Seq(Verdicts) :
        CountDirty(h) = Len(h) =>
            \A i \in DOMAIN h : h[i] = DIRTY
PROOF OMITTED  \* 4 BY steps

(****************************************************************************)
(* Lemma 3: After N consecutive DIRTY arrivals starting from an empty       *)
(* window, the window contains min(N, W) dirty entries.                    *)
(*                                                                          *)
(* DISCHARGE GUIDANCE: induction on N with the W boundary as the case      *)
(* split.                                                                   *)
(*                                                                          *)
(*   <1>1. Base: CountDirty(DirtyAcc(0)) = 0 = min(0, W).                   *)
(*   <1>2. Step: assume the claim for N; show for N+1.                      *)
(*         <2>1. Case A: N < W. Then Len(DirtyAcc(N)) = N < W (auxiliary    *)
(*               LengthIs_n_until_W). WindowUpdate appends a DIRTY,         *)
(*               incrementing both Len and CountDirty by 1.                 *)
(*         <2>2. Case B: N >= W. By Saturated_AllDirty,                     *)
(*               DirtyAcc(N) is all-DIRTY of length W. Tail drops one       *)
(*               DIRTY; Append adds one DIRTY back: count stays at W.       *)
(*         <2>3. QED by <2>1, <2>2.                                         *)
(*   <1>3. QED by <1>1, <1>2 with induction over Nat.                       *)
(*                                                                          *)
(* Estimated effort: ~20 BY lines including the LengthIs_n_until_W         *)
(* auxiliary.                                                                *)
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
PROOF OMITTED  \* ~20 BY steps; see Rlb_unbounded_handproof.md Lemma 3

(****************************************************************************)
(* Auxiliary: at step k of the clean phase, the leftmost entry of the      *)
(* window is DIRTY iff some DIRTY remains.                                  *)
(*                                                                          *)
(* This captures the "DIRTYs precede CLEANs in the window" invariant of    *)
(* CleanAfterDirty, which Lemma 4 needs to argue that Tail drops a DIRTY   *)
(* and not a CLEAN during the recovery phase.                              *)
(*                                                                          *)
(* DISCHARGE GUIDANCE: induction on k. Base k=0: window is DirtyAcc(N),    *)
(* all DIRTY if non-empty. Step: appending CLEAN only adds to the right,   *)
(* preserving the DIRTYs-then-CLEANs shape; Tail (when Len = W) drops the  *)
(* leftmost (a DIRTY while any remain). ~15 BY steps.                       *)
(****************************************************************************)

RECURSIVE CleanAfterDirty(_, _)
CleanAfterDirty(N, k) ==
    IF k = 0 THEN DirtyAcc(N)
    ELSE WindowUpdate(CleanAfterDirty(N, k - 1), CLEAN)

LEMMA OldestEntryIsDirty ==
    \A N \in 1..W, k \in 0..(W - 1) :
        CountDirty(CleanAfterDirty(N, k)) > 0 =>
            CleanAfterDirty(N, k)[1] = DIRTY
PROOF OMITTED  \* ~15 BY steps

(****************************************************************************)
(* Lemma 4: After accumulation phase (N <= W DIRTY) followed by k CLEAN     *)
(* outcomes with k <= W, the window contains min(N, W - k) dirty entries.   *)
(*                                                                          *)
(* DISCHARGE GUIDANCE: induction on k with three sub-cases (matching the   *)
(* three branches of the formula).                                          *)
(*                                                                          *)
(*   <1>1. Base k=0: count = N = min(N, W - 0). BY DirtyAcc_count.         *)
(*   <1>2. Step k+1:                                                        *)
(*         <2>1. Sub-case A: k < W - N.  Append CLEAN to window of length  *)
(*               < W; count preserved at N.                                 *)
(*         <2>2. Sub-case B: W - N <= k < W. Window length = W. Use         *)
(*               OldestEntryIsDirty to argue Tail drops a DIRTY;            *)
(*               Append CLEAN adds zero DIRTY. Count goes from              *)
(*               N - (k - (W - N)) to N - ((k+1) - (W - N)).                *)
(*         <2>3. Sub-case C: k = W. By inductive hypothesis count = 0,     *)
(*               so window is all-CLEAN; appending another CLEAN keeps     *)
(*               it all-CLEAN.                                              *)
(*         <2>4. QED by <2>1, <2>2, <2>3.                                  *)
(*   <1>3. QED by <1>1, <1>2 with induction over Nat.                       *)
(*                                                                          *)
(* This is the load-bearing lemma. Estimated effort: ~50 BY lines           *)
(* including the OldestEntryIsDirty auxiliary.                              *)
(****************************************************************************)

LEMMA CleanAfterDirty_count ==
    \A N, k \in Nat :
        (N <= W /\ N >= 1 /\ k <= W) =>
            CountDirty(CleanAfterDirty(N, k)) =
                IF k <= W - N THEN N
                ELSE IF k <= W THEN N - (k - (W - N))
                ELSE 0
PROOF OMITTED  \* ~50 BY steps; see Rlb_unbounded_handproof.md Lemma 4

(****************************************************************************)
(* RLB-v1 (UNBOUNDED): for N <= W consecutive DIRTY outcomes followed   *)
(* by clean outcomes, the dirty-run length L = peak + W - 1, where         *)
(* peak = N.                                                                *)
(*                                                                          *)
(* Statement in terms of CleanAfterDirty:                                  *)
(*                                                                          *)
(*   - cycles 1..N: count goes 1, 2, ..., N (all dirty)                    *)
(*   - cycles N+1..W: count stays at N (window not yet full, all dirty)    *)
(*   - cycles W+1..W+N-1: count goes N-1, N-2, ..., 1 (all dirty)          *)
(*   - cycle W+N: count = 0 (clean -- recovery transition)                 *)
(*                                                                          *)
(* Total dirty cycles = W + N - 1 = peak + W - 1.                         *)
(*                                                                          *)
(* DISCHARGE GUIDANCE: two arithmetic instantiations of                    *)
(* CleanAfterDirty_count.                                                  *)
(*                                                                          *)
(*   <1>1. CountDirty(CleanAfterDirty(N, W-1)) = 1 > 0.                    *)
(*         Apply CleanAfterDirty_count at k = W - 1. Since N >= 1,         *)
(*         W - 1 >= W - N, so we use the second branch:                    *)
(*         N - ((W-1) - (W - N)) = N - (N - 1) = 1.                       *)
(*   <1>2. CountDirty(CleanAfterDirty(N, W)) = 0.                          *)
(*         Apply CleanAfterDirty_count at k = W. Second branch:            *)
(*         N - (W - (W - N)) = N - N = 0.                                 *)
(*   <1>3. QED with L = W + N - 1, witnessing the existential.             *)
(*                                                                          *)
(* Estimated effort: ~10 BY lines (the easy part once Lemma 4 lands).      *)
(****************************************************************************)

THEOREM Theorem1_unbounded ==
    \A N \in 1..W :
        \E L \in Nat :
            /\ L = W + N - 1
            /\ CountDirty(CleanAfterDirty(N, L - N)) > 0
            /\ CountDirty(CleanAfterDirty(N, L - N + 1)) = 0
PROOF OMITTED  \* ~10 BY steps; see Rlb_unbounded_handproof.md Theorem 1

================================================================================
