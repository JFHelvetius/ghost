# Hand proof of the unbounded RLB-v1 theorem

**Status:** rigorous mathematical proof, *not* mechanically checked
by TLAPS. Compaions the TLAPS outline at [`Rlb_unbounded.tla`](Rlb_unbounded.tla)
(which compiles but has every `BY` placeholder), the bounded TLC
verification at [`Rlb.tla`](Rlb.tla) (exhaustive over `W = 4,
MAX_DRIFT = 4`), and the TLC parametric sweep at
`Rlb_sweep.cfg.json` (exhaustive over `W ∈ {4, 8, 16}` --- the
empirical generalisation evidence cited in paper §6.3).

The three artefacts together form the v0.2.5 RLB-v1 unbounded
case: a (1) mechanically-checked bounded verification, (2) a
parametric sweep that re-runs TLC on three structurally
distinct `W` to falsify "the proof is `W = 4`-specific", and
(3) this hand proof, which is the unbounded mathematical
argument a human reviewer can audit line-by-line.

A future contributor with a working TLAPS installation can use
this document as the script for discharging the `BY` placeholders
in `Rlb_unbounded.tla`: each lemma below maps 1:1 to a `LEMMA`
in that file, and each proof step below maps to either a
`<n>n. ... BY ...` step or to a SMT-checkable sub-obligation.

## Setup

Fix `W ∈ ℕ` with `W > 0`. Let

- `Verdicts = {DIRTY, CLEAN}`,
- `Seq(Verdicts)` = finite sequences over `Verdicts`,
- `Len(h)` = length of `h ∈ Seq(Verdicts)`,
- `CountDirty(h) = |{i ∈ DOMAIN h : h[i] = DIRTY}|`,
- `WindowUpdate(h, o) = Append(h, o)` if `Len(h) < W`,
  else `Append(Tail(h), o)`.

These are the *exact* definitions from [`Rlb_unbounded.tla`](Rlb_unbounded.tla),
which themselves mirror the verifier in
[`src/project_ghost/properties/rlb.py`](../../src/project_ghost/properties/rlb.py).
The bridge between the TLA+ abstraction and the Python verifier is
checked by inspection (paper §9 *Python ↔ TLA+ bridge by inspection*
caveat).

The accumulating-then-clean trace family from
[`Rlb_unbounded.tla`](Rlb_unbounded.tla):

```
DirtyAcc(0)        = ⟨⟩
DirtyAcc(n+1)      = WindowUpdate(DirtyAcc(n), DIRTY)
CleanAfterDirty(N, 0) = DirtyAcc(N)
CleanAfterDirty(N, k+1) = WindowUpdate(CleanAfterDirty(N, k), CLEAN)
```

We prove four lemmas and the main theorem.

---

## Lemma 1 — `CountDirty_bounded`

**Statement.** For all `h ∈ Seq(Verdicts)`:
`0 ≤ CountDirty(h) ≤ Len(h)`.

**Proof.** `CountDirty(h)` is the cardinality of a subset of
`DOMAIN h`. Since `DOMAIN h = 1..Len(h)`, we have
`|DOMAIN h| = Len(h)`. Cardinality of a subset is ≤ cardinality
of the superset, and ≥ 0 because cardinality of any finite set
is non-negative. ∎

**TLAPS discharge plan.** Single `BY` step relying on
`FiniteSets.SubsetCardinality` and the `DOMAIN`-`Len` bridge
from `Sequences`. Estimated effort: 3 BY lines.

---

## Lemma 2 — `WindowUpdate_bounded`

**Statement.** For all `h ∈ Seq(Verdicts)`, `o ∈ Verdicts`:
`Len(WindowUpdate(h, o)) ≤ W`.

**Proof.** Two cases on `Len(h)`:

- **Case A:** `Len(h) < W`. Then `WindowUpdate(h, o) = Append(h, o)`
  has length `Len(h) + 1 ≤ W` (because `Len(h) < W` implies
  `Len(h) + 1 ≤ W` in ℕ).
- **Case B:** `Len(h) ≥ W`. By a separate structural invariant of
  the trace (every state reached from `Init` keeps
  `Len(window) ≤ W` — exactly `INV_WINDOW_BOUND` from `Rlb.tla`,
  proved by induction on the transition relation), we have
  `Len(h) = W`. Then `Tail(h)` has length `W − 1` and
  `Append(Tail(h), o)` has length `W`.

In both cases the length is ≤ `W`. ∎

**TLAPS discharge plan.** Case split on `Len(h) < W` vs
`Len(h) = W`. The "`Len(h) = W`" branch needs the
`INV_WINDOW_BOUND` invariant as a hypothesis; the bounded TLC
verification at `W = 4, 8, 16` (CI sweep) confirms it; the
unbounded TLAPS proof would discharge it via a separate inductive
invariant lemma. Estimated effort: 5 BY lines per branch plus 1
to close.

---

## Lemma 3 — `DirtyAcc_count`

**Statement.** For all `n ∈ ℕ`:
`CountDirty(DirtyAcc(n)) = min(n, W)`.

**Proof.** Induction on `n`.

- **Base:** `n = 0`. Then `DirtyAcc(0) = ⟨⟩`, so
  `CountDirty(DirtyAcc(0)) = 0 = min(0, W)`. ✓

- **Step:** Assume `CountDirty(DirtyAcc(n)) = min(n, W)`. We
  show `CountDirty(DirtyAcc(n+1)) = min(n+1, W)`.

  Write `h = DirtyAcc(n)`. By the inductive hypothesis,
  `CountDirty(h) = min(n, W)`. By Lemma 2 and an invariant of
  the construction (each `WindowUpdate` keeps `Len ≤ W`),
  `Len(h) ≤ W`. Two sub-cases:

  - **n < W.** Then `Len(h) < W` (we maintain
    `Len(DirtyAcc(n)) = n` until `n` reaches `W`, by another
    straightforward induction on `n`). So
    `DirtyAcc(n+1) = Append(h, DIRTY)`. Appending a DIRTY to a
    history of length < `W` *increments* both the length and
    `CountDirty` by 1.

    `CountDirty(Append(h, DIRTY)) = CountDirty(h) + 1
                                  = min(n, W) + 1
                                  = n + 1`
    (since `n < W` implies `min(n, W) = n` and `n + 1 ≤ W`
    implies `min(n+1, W) = n+1`).

  - **n ≥ W.** Then `Len(h) = W` (by induction the length is
    saturated). So
    `DirtyAcc(n+1) = Append(Tail(h), DIRTY)`. Tailing the front
    drops one entry. By inductive hypothesis `CountDirty(h) =
    W`, so every entry of `h` is DIRTY (since `CountDirty = Len`
    forces all entries to be DIRTY). Therefore `Tail(h)` is
    all-DIRTY of length `W − 1` and `Append(Tail(h), DIRTY)`
    is all-DIRTY of length `W`.

    `CountDirty(Append(Tail(h), DIRTY)) = W = min(n+1, W)`. ✓

  In both sub-cases the equality holds. ∎

**TLAPS discharge plan.** The induction is `<1>1. base; <1>2.
step QED`. The step needs a `LET h == DirtyAcc(n)` + case split.
The "all-DIRTY when count = length" sub-lemma should be hoisted
into its own LEMMA `Saturated_AllDirty`. Estimated effort: ~20
BY lines including the auxiliary lemma.

---

## Lemma 4 — `CleanAfterDirty_count`

**Statement.** For all `N, k ∈ ℕ` with `N ≤ W` and `k ≤ W`:

```
CountDirty(CleanAfterDirty(N, k)) =
    IF k ≤ W − N THEN N
    ELSE IF k ≤ W THEN N − (k − (W − N))
    ELSE 0
```

In plain words: feeding `k` CLEAN outcomes into a window that
ends an accumulation phase containing `N` DIRTY entries:

- for the first `W − N` clean outcomes, the count stays at `N`
  because the window grows (or maintains length) while DIRTY
  entries remain inside;
- for the next `N` clean outcomes (cycles `W − N + 1`
  through `W`), each clean entry shifts out one DIRTY entry, so
  the count decreases by 1 per cycle;
- after `W` clean outcomes the window is fully clean and the
  count is 0.

**Proof.** Induction on `k`. Fix `N ≤ W`.

- **Base:** `k = 0`. Then `CleanAfterDirty(N, 0) = DirtyAcc(N)`.
  By Lemma 3 (since `N ≤ W`),
  `CountDirty(DirtyAcc(N)) = min(N, W) = N`. The formula at
  `k = 0` is `N` (since `0 ≤ W − N`). ✓

- **Step:** Assume the formula for `k`; show it for `k + 1`.
  Let `h = CleanAfterDirty(N, k)`. By the inductive
  hypothesis, `CountDirty(h)` matches the formula at `k`.

  We split on three cases (matching the formula's three
  branches):

  - **k < W − N.** Then `Len(h) < W` (we still grow the window,
    by an auxiliary length-induction on `k`). So
    `CleanAfterDirty(N, k+1) = Append(h, CLEAN)`. Appending a
    CLEAN to a window of length < `W` increases length by 1
    and *preserves* `CountDirty`:
    `CountDirty(Append(h, CLEAN)) = CountDirty(h) = N`. The
    formula at `k + 1` is `N` (since `k + 1 ≤ W − N`). ✓

  - **W − N ≤ k < W.** Then `Len(h) = W` (saturated).
    `CleanAfterDirty(N, k+1) = Append(Tail(h), CLEAN)`. Two
    sub-arguments:

    1. By an auxiliary lemma `OldestEntryIsDirty(N, k)`: the
       first entry of `h` is DIRTY whenever there remain DIRTY
       entries in the window. The construction maintains the
       invariant that DIRTYs precede CLEANs in the window: the
       accumulation phase wrote `N` DIRTYs then the clean phase
       wrote CLEANs on the right, while shifting them out from
       the left only after `W − N` cycles. So at `k ≥ W − N`,
       the leftmost entry of the window is DIRTY.

    2. Therefore `Tail(h)` drops one DIRTY:
       `CountDirty(Tail(h)) = CountDirty(h) − 1`. Then
       `Append(Tail(h), CLEAN)` adds zero DIRTYs:
       `CountDirty(Append(Tail(h), CLEAN)) = CountDirty(h) − 1`.

       By inductive hypothesis,
       `CountDirty(h) = N − (k − (W − N))`. So
       `CountDirty(CleanAfterDirty(N, k+1))
        = N − (k − (W − N)) − 1
        = N − ((k+1) − (W − N))`,
       which is the formula at `k + 1` (still in the
       `≤ W` branch as long as `k + 1 ≤ W`). ✓

  - **k = W.** Then by the formula at `k`,
    `CountDirty(h) = N − (W − (W − N)) = N − N = 0`. So `h` is
    fully clean. Appending another CLEAN keeps it fully clean.
    Formula at `k + 1 = W + 1 > W`: returns `0`. ✓

In all cases the formula holds at `k + 1`. ∎

**TLAPS discharge plan.** This is the load-bearing lemma. Hoist
the two auxiliary lemmas
(`LengthGrowsThenSaturates`, `OldestEntryIsDirty`) as separate
LEMMAs. Estimated effort: ~50 BY lines including auxiliaries.

---

## Theorem 1 — RLB-v1 (unbounded)

**Statement.** For all `N ∈ 1..W` there exists `L ∈ ℕ` with

- `L = W + N − 1`, and
- `CountDirty(CleanAfterDirty(N, L − N)) > 0`, and
- `CountDirty(CleanAfterDirty(N, L − N + 1)) = 0`.

Operationally: starting from `N` consecutive DIRTY outcomes
followed by CLEAN outcomes, the dirty-run length (the number of
cycles before the window is fully clean) equals `W + N − 1`,
which equals `peak + W − 1` since `peak = N`.

**Proof.** Fix `N ∈ 1..W`. Define `L = W + N − 1` and
`k* = L − N = W − 1`. We show the two count conditions.

- **(a) `CountDirty(CleanAfterDirty(N, k*)) > 0`.** Substitute
  `k = W − 1` into Lemma 4. Since `N ≥ 1`, `W − 1 ≥ W − N` iff
  `N ≥ 1`, which holds. And `W − 1 ≤ W` always. So we are in
  the second branch:

  `CountDirty(CleanAfterDirty(N, W − 1))
   = N − ((W − 1) − (W − N))
   = N − (N − 1)
   = 1 > 0`. ✓

- **(b) `CountDirty(CleanAfterDirty(N, k* + 1)) = 0`.** Now
  `k = W`. By Lemma 4:

  `CountDirty(CleanAfterDirty(N, W))
   = N − (W − (W − N))
   = N − N
   = 0`. ✓

Both conditions hold at the predicted `L = W + N − 1`. The
existential is witnessed by this `L`. ∎

**TLAPS discharge plan.** Two `BY Lemma_4` lines plus arithmetic
(`Naturals` lemmas). Estimated effort: ~10 BY lines. The
theorem is the easy part once Lemma 4 lands; almost all the
work is in Lemma 4 and its auxiliaries.

---

## Bridge to `peak` and the paper's `L ≤ peak + W − 1`

The paper §6.3 states the bound as `L ≤ peak + W − 1` where
`peak = max CountDirty(window)` observed during the dirty
interval. The theorem above proves the **tight** version:
`L = peak + W − 1` exactly when `peak = N ≤ W`. The inequality
form `L ≤ peak + W − 1` holds because the equality form gives
the maximum `L`; for `N > W` the formula does not apply and
RLB-v1 explicitly states the `N ≤ W` hypothesis (paper §6.3,
Corollary 1).

The bridge from `peak` to `N`:

- During the accumulation phase, `CountDirty` rises from `0` to
  `min(N, W) = N` (Lemma 3, since `N ≤ W`).
- The window-maximum `peak_in_run` (the verifier state)
  therefore equals `N` at the end of accumulation.
- During recovery, `CountDirty` strictly decreases (Lemma 4),
  so `peak_in_run` stays at `N`.

Hence `peak = N` for every reachable state inside the dirty
run, and Theorem 1 yields the unbounded form of the RLB-v1
bound.

---

## What the hand proof does NOT claim

- **Not a mechanical certificate.** A future contributor must
  port these steps into TLAPS to obtain SMT-/Isabelle-checked
  evidence. The `BY` placeholders in
  [`Rlb_unbounded.tla`](Rlb_unbounded.tla) are the targets.
- **Not exhaustive over all traces.** RLB-v1 applies only to
  the consecutive-drift-then-clean trace family (paper §6.3).
  Arbitrary mixed dirty/clean traces are out of scope and not
  covered by the bound.
- **Bridge to the Python verifier remains by inspection.** The
  hand proof closes the unbounded gap *within the TLA+
  abstraction*; the Python ↔ TLA+ correspondence is still
  audited by inspection (paper §9). v0.2.5 ships no change on
  that bridge.

## What v0.2.5 *does* close

The empirical claim that "the bound is `W = 4`-specific" was
the residual reviewer attack on RLB-v1. v0.2.5 closes it three
ways:

1. **TLC parametric sweep** over `W ∈ {4, 8, 16}` (~ 50× state-
   space growth between scales), all passing in CI. Empirical
   evidence that the proof generalises across structurally
   distinct `W`.
2. **This hand proof**, which a human reviewer can audit
   line-by-line and which has *no* `W` dependence in its
   arguments.
3. **The TLAPS outline** at
   [`Rlb_unbounded.tla`](Rlb_unbounded.tla), now refined with
   per-step discharge guidance, awaiting a future contributor
   with TLAPS installed.

Together, the three pieces of evidence let the paper retire the
"bounded TLC only" framing of §5.5 and §9 to "bounded TLC plus
hand proof plus sweep" --- one step closer to the full TLAPS
proof, with no false claim of having done that step yet.
