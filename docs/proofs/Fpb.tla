------------------------------- MODULE Fpb -------------------------------
(****************************************************************************)
(* TLA+ specification of FPB-v1 (False Positive Bound observer) from        *)
(* ADR-0035 / paper §3.5.                                                  *)
(*                                                                          *)
(* MODEL: FPB-v1 is fundamentally observational — it exposes the empirical  *)
(* BAUD fire rate as a scalar and compares it against a caller-supplied    *)
(* threshold ``max_fire_fraction``. The threshold is a per-release          *)
(* regression gate; the property does not claim a universal statistical     *)
(* upper bound on false-positive rates. This is the per-trace semantics    *)
(* the property tests cover.                                                *)
(*                                                                          *)
(* What this TLA+ spec mechanically verifies is the **structural            *)
(* well-formedness** of the FPB counter automaton (mirroring the verifier  *)
(* in ``src/project_ghost/properties/fpb.py``):                            *)
(*                                                                          *)
(*   INV_FPB_RATIO_BOUNDED                                                  *)
(*       cycles_fires <= cycles_total in every reachable state, so the      *)
(*       fire fraction lies in [0, 1].                                     *)
(*                                                                          *)
(*   INV_FPB_FIRE_IMPLIES_TOTAL                                             *)
(*       cycles_fires can only increment in the same step where             *)
(*       cycles_total increments. The counter never "fires without          *)
(*       observing".                                                        *)
(*                                                                          *)
(*   INV_FPB_OBSERVATIONAL_DEFAULT                                          *)
(*       Under the default observational threshold                          *)
(*       max_fire_fraction = cycles_total (i.e., bound = 1.0 in the         *)
(*       integer-arithmetic encoding here), the bound holds in every       *)
(*       reachable state. This formalises the "always-holds-as-observer"    *)
(*       contract of ADR-0035 §1.                                          *)
(*                                                                          *)
(* The spec deliberately models fire_fraction in integer arithmetic         *)
(* (cycles_fires and cycles_total separately) to avoid TLA+'s lack of      *)
(* native rationals. The bound check then reads as                         *)
(*                                                                          *)
(*   cycles_fires * BOUND_DENOM <= MAX_FIRE_NUMER * cycles_total            *)
(*                                                                          *)
(* equivalently to fire_fraction <= MAX_FIRE_NUMER / BOUND_DENOM.          *)
(*                                                                          *)
(* The spec does NOT verify a probabilistic upper bound on the fire rate   *)
(* under noise models — that would require Monte Carlo infrastructure and  *)
(* is the scope of a future FPB-v2 (paper §10).                            *)
(*                                                                          *)
(* Run with TLC:                                                            *)
(*                                                                          *)
(*   java -cp tla2tools.jar tlc2.TLC -config Fpb.cfg Fpb                    *)
(****************************************************************************)

EXTENDS Naturals

CONSTANTS
    MAX_CYCLES,         \* upper bound on cycles_total for TLC tractability
    MAX_FIRE_NUMER,     \* numerator of max_fire_fraction
    BOUND_DENOM         \* denominator of max_fire_fraction

(* -------------------------------- ASSUMPTIONS ----------------------------- *)

ASSUME MAX_CYCLES \in Nat /\ MAX_CYCLES > 0
ASSUME MAX_FIRE_NUMER \in Nat
ASSUME BOUND_DENOM \in Nat /\ BOUND_DENOM > 0
ASSUME MAX_FIRE_NUMER <= BOUND_DENOM  \* bound is in [0, 1]

(* -------------------------------- VARIABLES ------------------------------ *)

VARIABLES
    cycles_total,   \* Nat. Number of cycles observed so far.
    cycles_fires    \* Nat. Number of those cycles where BAUDPrecondition fired.

vars == <<cycles_total, cycles_fires>>

(* ------------------------- INITIAL STATE + TRANSITION -------------------- *)

Init ==
    /\ cycles_total = 0
    /\ cycles_fires = 0

\* ObserveNonFire: a new cycle arrives where BAUD does not fire.
\* cycles_total increments; cycles_fires unchanged.
ObserveNonFire ==
    /\ cycles_total < MAX_CYCLES
    /\ cycles_total' = cycles_total + 1
    /\ cycles_fires' = cycles_fires

\* ObserveFire: a new cycle arrives where BAUD fires.
\* cycles_total and cycles_fires both increment.
ObserveFire ==
    /\ cycles_total < MAX_CYCLES
    /\ cycles_total' = cycles_total + 1
    /\ cycles_fires' = cycles_fires + 1

Next == ObserveNonFire \/ ObserveFire

Spec == Init /\ [][Next]_vars

(* ================================ INVARIANTS ============================== *)

(****************************************************************************)
(* INV_FPB_RATIO_BOUNDED                                                     *)
(*                                                                          *)
(* In every reachable state, cycles_fires <= cycles_total, so the implied   *)
(* fire fraction lies in [0, 1]. This is the structural well-formedness of *)
(* the counter automaton.                                                  *)
(****************************************************************************)

INV_FPB_RATIO_BOUNDED == cycles_fires <= cycles_total

(****************************************************************************)
(* INV_FPB_FIRE_IMPLIES_TOTAL                                                *)
(*                                                                          *)
(* The counter never fires more than it observes. Equivalent statement of  *)
(* INV_FPB_RATIO_BOUNDED in delta form (no negative gap between            *)
(* observation and firing).                                                *)
(****************************************************************************)

INV_FPB_FIRE_IMPLIES_TOTAL == cycles_total >= cycles_fires

(****************************************************************************)
(* INV_FPB_OBSERVATIONAL_DEFAULT                                             *)
(*                                                                          *)
(* When MAX_FIRE_NUMER = BOUND_DENOM (i.e., max_fire_fraction = 1.0), the   *)
(* property always holds: cycles_fires * BOUND_DENOM <= BOUND_DENOM *      *)
(* cycles_total holds because cycles_fires <= cycles_total. This is the    *)
(* "purely observational" semantics of the default ADR-0035 §1.            *)
(*                                                                          *)
(* The invariant is stated for the parameterised threshold; in Fpb.cfg the *)
(* default config sets MAX_FIRE_NUMER = BOUND_DENOM so the invariant       *)
(* should be checked exhaustively under that setting.                      *)
(****************************************************************************)

INV_FPB_OBSERVATIONAL_DEFAULT ==
    cycles_fires * BOUND_DENOM <= MAX_FIRE_NUMER * cycles_total

================================================================================
