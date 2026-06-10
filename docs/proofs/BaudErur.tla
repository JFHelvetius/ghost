---------------------------- MODULE BaudErur ----------------------------
(****************************************************************************)
(* TLA+ specification of the BAUD-v1 / ERUR-v1 / Partition properties from   *)
(* ADRs 0031 / 0032 / 0036.                                                  *)
(*                                                                          *)
(* This spec models the closed-loop pipeline as a state machine: each tick   *)
(* a non-deterministic outcome arrives, the sliding window absorbs it, and   *)
(* the reference calibrator + decision policy + actuator policy run          *)
(* deterministically on the new state. The three invariants below capture    *)
(* exactly the formal statements from the ADRs.                              *)
(*                                                                          *)
(* Bounded constants (M, K, W) are small to keep TLC's state-space           *)
(* enumeration fast; see ADR-0036 §3 for the bounds-sufficiency argument.    *)
(*                                                                          *)
(* Run with TLC:                                                             *)
(*                                                                          *)
(*   java -cp tla2tools.jar tlc2.TLC -config BaudErur.cfg BaudErur           *)
(****************************************************************************)

EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS
    M,    \* min_outcomes  : BAUD precondition floor on outcomes_considered
    K,    \* downgrade_thr : BAUD precondition floor on count_beyond_3_or_worse
    W     \* max_history   : calibration window size

(* ----------------------------- DOMAIN CONSTANTS --------------------------- *)

\* Two-valued verdict abstraction: the only BAUD-relevant distinction is
\* whether an outcome counts toward the downgrade threshold or not.
\* DIRTY ~ {BEYOND_3_STD, BEYOND_5_STD}; CLEAN ~ {WITHIN_1_STD, BEYOND_1_STD}.
DIRTY == "dirty"
CLEAN == "clean"
Verdicts == {DIRTY, CLEAN}

\* Assessment-level lattice (KNOWN < UNCERTAIN < UNKNOWN).
KNOWN_L     == "known"
UNCERTAIN_L == "uncertain"
UNKNOWN_L   == "unknown"
AssessmentLevels == {KNOWN_L, UNCERTAIN_L, UNKNOWN_L}

\* BAUD-relevant decision kinds. We collapse {YIELD_TO_PILOT, ENGAGE_RTL,
\* ENGAGE_LAND, ENGAGE_KILL} into ABSTAIN since BAUD treats them all the
\* same (anything-but-PROCEED).
PROCEED == "proceed"
HOLD    == "hold"
ABSTAIN == "abstain"
DecisionKinds == {PROCEED, HOLD, ABSTAIN}

(* -------------------------------- ASSUMPTIONS ----------------------------- *)

ASSUME M \in Nat /\ M > 0
ASSUME K \in Nat /\ K > 0
ASSUME W \in Nat /\ W > 0

(* -------------------------------- VARIABLES ------------------------------ *)

VARIABLES
    history,        \* Seq(Verdicts) with Len(history) <= W (sliding window)
    raw_level,      \* AssessmentLevels
    adjusted_level, \* derived from raw_level + history via Calibrate
    decision_kind,  \* derived from adjusted_level via Decide
    actuator_safe   \* BOOLEAN — derived from decision_kind via IsActuatorSafe

vars == <<history, raw_level, adjusted_level, decision_kind, actuator_safe>>

(* ----------------------- DERIVED HISTORY PROPERTIES ----------------------- *)

\* outcomes_considered = current window length (always <= W by construction)
OutcomesConsidered(h) == Len(h)

\* count_beyond_3_or_worse == number of DIRTY outcomes in the window
CountDirty(h) == Cardinality({i \in DOMAIN h : h[i] = DIRTY})

(* ------------------------------- PRECONDITIONS ---------------------------- *)

\* BAUD-v1 precondition: the M-guard AND K-threshold both met.
BAUDPrecondition(h) ==
    /\ OutcomesConsidered(h) >= M
    /\ CountDirty(h) >= K

\* ERUR-v1 precondition: literal De Morgan negation of BAUD's drift condition
\* AND raw assessment is KNOWN.
\* See ADR-0032 §1.
DriftClean(h) ==
    \/ OutcomesConsidered(h) < M
    \/ CountDirty(h) < K

ERURPrecondition(h, raw) ==
    /\ DriftClean(h)
    /\ raw = KNOWN_L

(* --------------------------- REFERENCE POLICIES -------------------------- *)

\* MahalanobisDowngradePolicy.adjust(): passthrough or downgrade one level.
\* See src/project_ghost/core/feedback/reference_policy.py:_DOWNGRADE.
Downgrade(level) ==
    IF level = KNOWN_L     THEN UNCERTAIN_L
    ELSE IF level = UNCERTAIN_L THEN UNKNOWN_L
    ELSE                   UNKNOWN_L  \* idempotent at lattice top

Calibrate(raw, h) ==
    IF BAUDPrecondition(h) THEN Downgrade(raw) ELSE raw

\* UncertaintyAwareReferencePolicy (ADR-0027): effective_overall_level maps
\* monotonically to kinds: KNOWN -> PROCEED, UNCERTAIN -> HOLD, else ABSTAIN.
Decide(level) ==
    IF level = KNOWN_L     THEN PROCEED
    ELSE IF level = UNCERTAIN_L THEN HOLD
    ELSE                   ABSTAIN

\* Actuator safety (BAUD postcondition 3 + ADR-0031 §1.1): any non-PROCEED
\* decision is safe under BAUD's safe-reason set.
IsActuatorSafe(d) == d # PROCEED

(* ------------------------- INITIAL STATE + TRANSITION -------------------- *)

\* Empty history, arbitrary raw level. Derived variables are pure functions
\* of the state variables they depend on, so they have unique initial values.
Init ==
    /\ history = <<>>
    /\ raw_level \in AssessmentLevels
    /\ adjusted_level = Calibrate(raw_level, history)
    /\ decision_kind = Decide(adjusted_level)
    /\ actuator_safe = IsActuatorSafe(decision_kind)

\* Sliding-window update: drop the oldest if the window is at capacity.
WindowUpdate(h, o) ==
    IF Len(h) < W
    THEN Append(h, o)
    ELSE Append(Tail(h), o)

\* AddOutcome: an arbitrary outcome arrives; raw level can also be arbitrary
\* on the new cycle (modeling that the raw assessment is independent of the
\* history-state of the calibrator).
AddOutcome ==
    \E o \in Verdicts, r \in AssessmentLevels:
        LET h2 == WindowUpdate(history, o)
            a  == Calibrate(r, h2)
            d  == Decide(a)
        IN  /\ history' = h2
            /\ raw_level' = r
            /\ adjusted_level' = a
            /\ decision_kind' = d
            /\ actuator_safe' = IsActuatorSafe(d)

Next == AddOutcome

Spec == Init /\ [][Next]_vars

(* ================================ INVARIANTS ============================== *)

(****************************************************************************)
(* INV_BAUD                                                                 *)
(*                                                                          *)
(* For every reachable state, BAUD-v1's precondition implies the three      *)
(* postconditions: adjusted level is not KNOWN, decision is not PROCEED,    *)
(* and the actuator command is safe.                                        *)
(****************************************************************************)

INV_BAUD ==
    BAUDPrecondition(history) =>
        /\ adjusted_level # KNOWN_L
        /\ decision_kind # PROCEED
        /\ actuator_safe

(****************************************************************************)
(* INV_ERUR                                                                 *)
(*                                                                          *)
(* For every reachable state, ERUR-v1's precondition implies the two        *)
(* postconditions: adjusted level is KNOWN and decision is PROCEED.         *)
(****************************************************************************)

INV_ERUR ==
    ERURPrecondition(history, raw_level) =>
        /\ adjusted_level = KNOWN_L
        /\ decision_kind = PROCEED

(****************************************************************************)
(* INV_PARTITION                                                            *)
(*                                                                          *)
(* For every reachable state where raw level is KNOWN, exactly one of       *)
(* BAUDPrecondition and ERURPrecondition holds (their drift-conditions are  *)
(* literal complements, and the raw-KNOWN clause is shared).                *)
(*                                                                          *)
(* This is the formal statement of the integration-test invariant           *)
(* test_smoke_baud_and_erur_partition_the_cycle_space — promoted from       *)
(* "observed on the smoke trace" to "proven on the abstract model".         *)
(****************************************************************************)

INV_PARTITION ==
    raw_level = KNOWN_L =>
        (BAUDPrecondition(history) <=> ~ERURPrecondition(history, raw_level))

(****************************************************************************)
(* INV_NO_INVENTED_CONFIDENCE                                               *)
(*                                                                          *)
(* Bonus witness for MD-v1 (ADR-0033): the reference calibrator never       *)
(* emits an adjusted level strictly more confident than the raw.            *)
(*                                                                          *)
(* Encoded via a lattice numerification:                                    *)
(*     KNOWN -> 0, UNCERTAIN -> 1, UNKNOWN -> 2                             *)
(* with the invariant adj_num >= raw_num.                                   *)
(****************************************************************************)

LevelNum(l) ==
    IF l = KNOWN_L     THEN 0
    ELSE IF l = UNCERTAIN_L THEN 1
    ELSE                   2

INV_NO_INVENTED_CONFIDENCE ==
    LevelNum(adjusted_level) >= LevelNum(raw_level)

(****************************************************************************)
(* INV_HISTORY_BOUND                                                        *)
(*                                                                          *)
(* Safety net on the sliding-window model: the history never exceeds W.     *)
(* If TLC ever reports this violated, the WindowUpdate definition is wrong  *)
(* (and so is RLB-v1's structural assumption).                              *)
(****************************************************************************)

INV_HISTORY_BOUND == Len(history) <= W

================================================================================
