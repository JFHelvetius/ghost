------------------------------- MODULE Rlb -------------------------------
(****************************************************************************)
(* TLA+ specification of RLB-v1 (RLB-v1) from ADR-0034 / paper §6.        *)
(*                                                                          *)
(* MODEL: RLB-v1's statement is conditional on a *transient drift        *)
(* interval of N consecutive dirty outcomes followed by clean outcomes*.    *)
(* This spec faithfully restricts the abstract state machine to that        *)
(* pattern by partitioning the trace into two phases:                      *)
(*                                                                          *)
(*   - ACCUMULATING: only DIRTY outcomes may arrive. Transitioning out of   *)
(*     this phase is permitted at any point with at least one DIRTY         *)
(*     observed (so N ranges over [1, MAX_DRIFT]).                          *)
(*   - RECOVERING: only CLEAN outcomes may arrive. The phase persists        *)
(*     until the window is fully clean (a recovery transition fires).      *)
(*                                                                          *)
(* The single safety invariant ``INV_RLB`` asserts that *on any recovery   *)
(* transition* the observed dirty-run length is at most peak + W - 1. This  *)
(* is the mechanical witness of RLB-v1 within its stated hypotheses.    *)
(*                                                                          *)
(* The spec does NOT verify the bound for arbitrary mixed dirty/clean       *)
(* traces; the bound does not hold in general for that case, and the       *)
(* paper's RLB-v1 explicitly states the consecutive-drift hypothesis.    *)
(* TLC discovered exactly this distinction in CI before this refactor —     *)
(* the prior version of the spec was too permissive and produced spurious   *)
(* counterexamples to the bound. See the commit history for the discovery. *)
(*                                                                          *)
(* Bounds for TLC tractability:                                            *)
(*   W = 4 (small but exercises all four proof phases)                     *)
(*   MAX_DRIFT bounds the consecutive-dirty prefix length                  *)
(*                                                                          *)
(* Run with TLC:                                                            *)
(*                                                                          *)
(*   java -cp tla2tools.jar tlc2.TLC -config Rlb.cfg Rlb                    *)
(****************************************************************************)

EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS
    W,            \* sliding-window size (calibrator's max_history)
    MAX_DRIFT     \* upper bound on the consecutive-dirty prefix length

(* ----------------------------- DOMAIN CONSTANTS --------------------------- *)

DIRTY == "dirty"
CLEAN == "clean"
Verdicts == {DIRTY, CLEAN}

\* Phases of the abstract trace.
ACCUMULATING == "accumulating"
RECOVERING   == "recovering"
Phases == {ACCUMULATING, RECOVERING}

(* -------------------------------- ASSUMPTIONS ----------------------------- *)

ASSUME W \in Nat /\ W > 0
ASSUME MAX_DRIFT \in Nat /\ MAX_DRIFT > 0

(* -------------------------------- VARIABLES ------------------------------ *)

VARIABLES
    window,        \* Seq(Verdicts) with Len(window) <= W
    dirty_run,     \* Nat. Cycles where CountDirty(window) > 0 (verifier state)
    peak_in_run,   \* Nat. Max CountDirty observed in the window during this run
    phase,         \* Phases. ACCUMULATING during drift, RECOVERING during clean tail
    n_dirty        \* Nat. How many consecutive DIRTY outcomes have arrived

vars == <<window, dirty_run, peak_in_run, phase, n_dirty>>

(* ------------------------------- WINDOW HELPERS --------------------------- *)

CountDirty(h) == Cardinality({i \in DOMAIN h : h[i] = DIRTY})

WindowUpdate(h, o) ==
    IF Len(h) < W
    THEN Append(h, o)
    ELSE Append(Tail(h), o)

(* ------------------------- INITIAL STATE + TRANSITION -------------------- *)

Init ==
    /\ window = <<>>
    /\ dirty_run = 0
    /\ peak_in_run = 0
    /\ phase = ACCUMULATING
    /\ n_dirty = 0

\* During ACCUMULATING: a DIRTY outcome arrives. Updates counters per the
\* verifier algorithm. May transition to RECOVERING after at least one DIRTY.
AccumulateDirty ==
    /\ phase = ACCUMULATING
    /\ n_dirty < MAX_DRIFT
    /\ LET h2 == WindowUpdate(window, DIRTY)
           c  == CountDirty(h2)
       IN  /\ window' = h2
           /\ dirty_run' = dirty_run + 1
           /\ peak_in_run' = IF c > peak_in_run THEN c ELSE peak_in_run
           /\ n_dirty' = n_dirty + 1
           /\ phase' = phase

\* Transition ACCUMULATING -> RECOVERING. Requires at least one DIRTY
\* observed, so we have a real drift interval. No outcome arrives in this
\* transition (it is a pure phase marker).
EndDrift ==
    /\ phase = ACCUMULATING
    /\ n_dirty > 0
    /\ phase' = RECOVERING
    /\ UNCHANGED <<window, dirty_run, peak_in_run, n_dirty>>

\* During RECOVERING: CLEAN outcomes arrive until the window is fully clean.
\* Mirrors the verifier algorithm: while CountDirty(new window) > 0, the
\* cycle is part of the dirty run; when CountDirty(new window) = 0 it is
\* the recovery transition.
RecoverClean ==
    /\ phase = RECOVERING
    /\ LET h2 == WindowUpdate(window, CLEAN)
           c  == CountDirty(h2)
       IN  /\ window' = h2
           /\ IF c > 0
              THEN /\ dirty_run' = dirty_run + 1
                   /\ peak_in_run' = peak_in_run
              ELSE /\ dirty_run' = 0
                   /\ peak_in_run' = 0
           /\ UNCHANGED <<phase, n_dirty>>

Next == AccumulateDirty \/ EndDrift \/ RecoverClean

Spec == Init /\ [][Next]_vars

(* ================================ INVARIANTS ============================== *)

(****************************************************************************)
(* INV_RLB (RLB-v1)                                                       *)
(*                                                                          *)
(* On a recovery transition — defined as the first cycle whose window is    *)
(* fully clean after a non-empty dirty run — the observed dirty-run length  *)
(* is at most peak_in_run + W - 1. The check is encoded as a forward        *)
(* implication: in any state about to recover (phase = RECOVERING and       *)
(* adding a CLEAN would yield a fully-clean window), the bound must hold.   *)
(****************************************************************************)

WouldRecoverOnNextClean ==
    /\ phase = RECOVERING
    /\ dirty_run > 0
    /\ LET h2 == WindowUpdate(window, CLEAN)
       IN  CountDirty(h2) = 0

INV_RLB ==
    WouldRecoverOnNextClean =>
        dirty_run <= peak_in_run + W - 1

(****************************************************************************)
(* INV_PEAK_BOUNDED                                                          *)
(*                                                                          *)
(* Structural sanity: peak_in_run is always bounded by W.                  *)
(****************************************************************************)

INV_PEAK_BOUNDED == peak_in_run <= W

(****************************************************************************)
(* INV_WINDOW_BOUND                                                          *)
(*                                                                          *)
(* Structural sanity: the window never exceeds W entries.                  *)
(****************************************************************************)

INV_WINDOW_BOUND == Len(window) <= W

================================================================================
