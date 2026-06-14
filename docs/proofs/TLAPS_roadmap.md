# TLAPS roadmap for unbounded RLB-v1 (Action C)

## What TLAPS would add

`Rlb.tla` proves RLB-v1 (`L ≤ peak + W − 1`) over a bounded state
space by exhaustive TLC enumeration: `W = 4, MAX_DRIFT = 4`. The
TLAPS extension `Rlb_unbounded.tla` would prove the same theorem for
**any finite W ∈ Nat** using TLAPS proof tactics that are checked by
a combination of Zenon, Isabelle/HOL, CVC4, and Z3.

This converts the paper's RLB-v1 from:

- "Verified by TLC on bounded `W ≤ 4`"

to:

- "Verified by TLAPS for any finite `W`"

The unbounded proof is the stronger formal claim and closes the
``bounded TLC, not unbounded`` honest-scope clause of paper §5.5.

## Status of `Rlb_unbounded.tla`

The module compiles but the BY tactics are placeholders
(``PROOF OMITTED``). Discharging them requires:

- **Install TLAPS** (~30 minutes, Linux/macOS supported, Windows
  experimentally via WSL2).
- **Discharge each lemma**, in order:
  1. `CountDirty_bounded` — induction on `Len(h)`.
  2. `WindowUpdate_bounded` — case split on `Len(h) < W` vs `= W`.
  3. `DirtyAcc_count` — induction on `n` with the `W` boundary.
  4. `CleanAfterDirty_count` — induction on `k`.
- **Discharge the main theorem** by composing the lemmas.

Estimated effort for someone familiar with TLAPS: **5–10 days**.
For someone new: longer, with a learning curve on the TLAPS proof
language.

## Installation steps (for future contributor)

1. **Install OCaml + Opam** (TLAPS is OCaml-based):

   ```bash
   # Linux / WSL2
   sudo apt install opam ocaml
   opam init
   eval $(opam env)
   ```

2. **Install TLAPS** from source:

   ```bash
   git clone https://github.com/tlaplus/tlapm.git
   cd tlapm
   ./configure
   make
   make install
   ```

3. **Install the SMT back-ends**:

   ```bash
   sudo apt install z3 cvc4
   ```

4. **Verify installation**:

   ```bash
   tlapm --version
   tlapm docs/proofs/Rlb_unbounded.tla
   ```

   At this point TLAPS will report every `PROOF OMITTED` as an
   incomplete obligation. Discharging them is the work item.

## How to discharge a lemma

Each `PROOF OMITTED` is replaced by a chain of `BY` tactics:

```tla
LEMMA WindowUpdate_bounded ==
    \A h \in Seq(Verdicts), o \in Verdicts :
        Len(WindowUpdate(h, o)) <= W
PROOF
  <1>1. \A h \in Seq(Verdicts), o \in Verdicts :
            Len(h) < W => Len(WindowUpdate(h, o)) = Len(h) + 1
    BY DEF WindowUpdate
  <1>2. \A h \in Seq(Verdicts), o \in Verdicts :
            Len(h) = W => Len(WindowUpdate(h, o)) = W
    BY DEF WindowUpdate, Tail
  <1>3. QED BY <1>1, <1>2, W_pos DEF WindowUpdate
```

The `<1>n. PROP BY ...` shape is the TLAPS hierarchical-proof
syntax. TLAPS will try each named back-end (Zenon, Isabelle, SMT) on
each obligation; if any succeeds, the obligation is discharged.

## Why this is out of scope for v0.2.x

- **No Java/OCaml CI tooling.** The current TLA+ CI job uses
  `tla2tools.jar` (TLC). Adding TLAPS would require an
  Ubuntu-only CI runner with the SMT stack installed; the cost is
  modest but non-zero.
- **TLAPS proof effort is not parallelisable with single-author
  work.** A full proof takes uninterrupted time. The paper's
  contribution is the property set, the verifier, and the
  partition theorem mechanisation — RLB-v1 unbounded is a
  follow-up improvement, not a load-bearing claim.
- **The honest-scope clause already documents this.** Paper §5.5
  explicitly states "TLC is exhaustive over the finite state space
  defined by the constants" — the bounded-vs-unbounded distinction
  is part of the published scope.

## What we shipped instead (v0.2.1+)

- `Rlb.tla` proves RLB-v1 by TLC over the bounded state space.
  This is sufficient for the paper's claim.
- `Rlb_unbounded.tla` is a **proof outline** that compiles under
  TLAPS and lists every obligation; it serves as the concrete
  roadmap for a future contributor.

A future ADR-0038 (already named in `docs/adr/0036-...md` §6 as a
candidate) would lift `Rlb_unbounded.tla` from outline to verified
proof.

## References

- Lamport, L. *Specifying Systems* (the TLA+ book), Addison-Wesley
  2002, chapters 6–8 (TLAPS proof language).
- TLAPS home page: <https://tla.msr-inria.inria.fr/tlaps/>
- TLAPS tutorial:
  <https://lamport.azurewebsites.net/tla/tutorial/>
- TLA+ Hyperbook (Lamport):
  <https://lamport.azurewebsites.net/tla/hyperbook.html>
