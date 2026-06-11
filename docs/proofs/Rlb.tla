------------------------------- MODULE Rlb -------------------------------
(****************************************************************************)
(* TLA+ specification of the RLB-v1 property and Theorem 1 from              *)
(* ADR-0034 / paper §6.                                                     *)
(*                                                                          *)
(* This spec models the sliding-window calibration history of               *)
(* ``MahalanobisDowngradePolicy(M, K)`` with window size W. At each tick    *)
(* a non-deterministic outcome arrives, the window absorbs it, and the      *)
(* verifier-side state (current dirty run length and peak observed during   *)
(* the run) is updated according to the same algorithm as                   *)
(* ``src/project_ghost/properties/rlb.py``.                                 *)
(*                                                                          *)
(* The single invariant ``INV_RLB`` asserts that *on any recovery           *)
(* transition* (the first cycle whose window contains no dirty entries      *)
(* after a non-empty dirty run), the observed dirty-run length is at most   *)
(* ``peak + W - 1``. This is the mechanical witness of Theorem 1.           *)
(*                                                                          *)
(* Bounds for TLC tractability:                                             *)
(*   W = 4 (matches the bounds-sufficiency argument of ADR-0036 §3)         *)
(*   MAX_DIRTY_RUN bounds the per-run counter so the state space is         *)
(*   finite. RLB-v1 is local to a single dirty run; the invariant fires     *)
(*   on each recovery, so bounding individual runs does not weaken the      *)
(*   claim.                                                                 *)
(*                                                                          *)
(* Run with TLC:                                                            *)
(*                                                                          *)
(*   java -cp tla2tools.jar tlc2.TLC -config Rlb.cfg Rlb                    *)
(****************************************************************************)

EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS
    W,                \* sliding-window size (calibrator's max_history)
    MAX_DIRTY_RUN     \* upper bound on a single dirty run for TLC

(* ----------------------------- DOMAIN CONSTANTS --------------------------- *)

DIRTY == "dirty"
CLEAN == "clean"
Verdicts == {DIRTY, CLEAN}

(* -------------------------------- ASSUMPTIONS ----------------------------- *)

ASSUME W \in Nat /\ W > 0
ASSUME MAX_DIRTY_RUN \in Nat /\ MAX_DIRTY_RUN >= 2 * W

(* -------------------------------- VARIABLES ------------------------------ *)

VARIABLES
    window,        \* Seq(Verdicts) with Len(window) <= W
    dirty_run,     \* Nat. Cycles since last fully-clean window (verifier state).
    peak_in_run    \* Nat. Max CountDirty observed in the window during this run.

vars == <<window, dirty_run, peak_in_run>>

(* ------------------------------- WINDOW HELPERS --------------------------- *)

CountDirty(h) == Cardinality({i \in DOMAIN h : h[i] = DIRTY})

\* Sliding-window update: append; drop oldest when full.
WindowUpdate(h, o) ==
    IF Len(h) < W
    THEN Append(h, o)
    ELSE Append(Tail(h), o)

(* ------------------------- INITIAL STATE + TRANSITION -------------------- *)

\* Empty window; verifier counters at zero.
Init ==
    /\ window = <<>>
    /\ dirty_run = 0
    /\ peak_in_run = 0

\* AddOutcome: an arbitrary outcome arrives. Two cases mirror the verifier
\* algorithm in src/project_ghost/properties/rlb.py:
\*
\* - If the new window contains at least one dirty entry: increment
\*   dirty_run, update peak_in_run.
\* - If the new window is fully clean: this is a recovery transition (the
\*   invariant INV_RLB is checked at this state); reset counters.
AddOutcome ==
    \E o \in Verdicts:
        LET h2 == WindowUpdate(window, o)
            c  == CountDirty(h2)
        IN  /\ window' = h2
            /\ IF c > 0
               THEN /\ dirty_run' = dirty_run + 1
                    /\ peak_in_run' = IF c > peak_in_run THEN c ELSE peak_in_run
                    /\ dirty_run + 1 <= MAX_DIRTY_RUN  \* TLC bound
               ELSE /\ dirty_run' = 0
                    /\ peak_in_run' = 0

Next == AddOutcome

Spec == Init /\ [][Next]_vars

(* ================================ INVARIANT =============================== *)

(****************************************************************************)
(* INV_RLB (Theorem 1)                                                       *)
(*                                                                          *)
(* On a recovery transition — defined as the first cycle whose window is    *)
(* fully clean after a non-empty dirty run — the observed dirty-run length  *)
(* is at most peak_in_run + W - 1.                                          *)
(*                                                                          *)
(* The check is encoded as a one-step-forward implication: in any state     *)
(* about to recover (i.e., dirty_run > 0 and there exists a clean outcome   *)
(* yielding a fully-clean window), the bound must hold.                     *)
(*                                                                          *)
(* TLC enumerates all reachable (window, dirty_run, peak_in_run) tuples;    *)
(* the invariant is checked on each.                                        *)
(****************************************************************************)

\* Predicate: from the current state, adding a CLEAN outcome would yield
\* a fully-clean window (i.e., the window currently contains exactly one
\* dirty entry at its oldest position, which would be expelled).
WouldRecoverOnNextClean ==
    /\ dirty_run > 0
    /\ LET h2 == WindowUpdate(window, CLEAN)
       IN  CountDirty(h2) = 0

\* On a recovery transition, the bound must hold. The verifier checks this
\* AT the recovery cycle, but logically the dirty_run counter holds the value
\* it would have if we counted the recovery cycle itself; we therefore check
\* the bound on the dirty_run value *before* the recovery (i.e., the run
\* length up to but not including the recovery cycle).
INV_RLB ==
    WouldRecoverOnNextClean =>
        dirty_run <= peak_in_run + W - 1

(****************************************************************************)
(* INV_PEAK_BOUNDED                                                          *)
(*                                                                          *)
(* Sanity invariant: peak_in_run is always bounded by W (the window can     *)
(* never hold more dirty entries than its capacity).                       *)
(****************************************************************************)

INV_PEAK_BOUNDED == peak_in_run <= W

(****************************************************************************)
(* INV_WINDOW_BOUND                                                          *)
(*                                                                          *)
(* Structural sanity: the window never exceeds W entries.                  *)
(****************************************************************************)

INV_WINDOW_BOUND == Len(window) <= W

================================================================================
