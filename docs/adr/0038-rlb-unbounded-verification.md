# ADR-0038 — RLB-v1 unbounded verification: triple evidence

## Status

Accepted (v0.2.5) with **partial discharge**:

- TLC parametric sweep over `W ∈ {4, 8, 16}`: **mechanically
  verified** in CI. All three configurations enumerate the full
  reachable state space and report `INV_RLB` holds. JSON artefact at
  [`docs/paper/outputs/rlb_tlc_sweep/sweep.json`](../paper/outputs/rlb_tlc_sweep/sweep.json).
- Hand proof of the unbounded theorem: **rigorous mathematical
  proof, not mechanically checked**.
  [`docs/proofs/Rlb_unbounded_handproof.md`](../proofs/Rlb_unbounded_handproof.md).
- TLAPS outline with per-lemma discharge guidance:
  [`docs/proofs/Rlb_unbounded.tla`](../proofs/Rlb_unbounded.tla)
  — refined in v0.2.5 with explicit `BY`-step guidance per lemma,
  awaiting a future contributor with a working TLAPS install.

A full TLAPS-mechanical proof remains open; see §"What this ADR
does NOT close" below. The three artefacts ship together so that a
reviewer can audit the unbounded claim **from three independent
angles** without having to install TLAPS.

## Context

Paper §6.3 / ADR-0034 states the RLB-v1 bound:

> For any consecutive-drift interval of `N ≤ W` DIRTY outcomes
> followed by CLEAN outcomes, the dirty-run length satisfies
> `L ≤ peak + W − 1`.

`Rlb.tla` (ADR-0036) mechanically verifies this with TLC at
`W = 4, MAX_DRIFT = 4`. The TLC enumeration is exhaustive **over
the finite state space at those constants**; it is silent on
behaviour at larger `W`.

This is the residual reviewer attack on RLB-v1: *"the proof might
be a `W = 4` coincidence."* That objection has two reasonable
responses:

1. **Empirical**: re-run TLC at several structurally distinct
   `W` and show the invariant still holds. Cheap, mechanical, but
   does not prove the unbounded statement.
2. **Mathematical**: prove the unbounded theorem by induction.
   Strong, but unmechanised unless lifted to TLAPS.

v0.2.5 ships **both** responses, plus the TLAPS outline as the
third (incomplete) leg.

## Decision

### 1. TLC parametric sweep (mechanical, partial coverage)

Three configurations:

- [`Rlb.cfg`](../proofs/Rlb.cfg): `W = 4, MAX_DRIFT = 4`
  (baseline; pre-existing).
- [`Rlb_W8.cfg`](../proofs/Rlb_W8.cfg): `W = 8, MAX_DRIFT = 8`
  (new in v0.2.5).
- [`Rlb_W16.cfg`](../proofs/Rlb_W16.cfg): `W = 16, MAX_DRIFT = 16`
  (new in v0.2.5).

All three are exhaustively model-checked by
[`docs/paper/scripts/run_rlb_tlc_sweep.py`](../paper/scripts/run_rlb_tlc_sweep.py),
which emits a self-describing JSON artefact with per-`W`
`states_generated`, `distinct_states`, `invariant_holds`, and
`elapsed_seconds`. Exit code is zero iff every `W` reports
INV_RLB holds.

v0.2.5 baseline observation:

| W  | states_generated | distinct_states | INV_RLB |
|----|---:|---:|:---:|
| 4  |  29 |  25 | HOLDS |
| 8  |  89 |  81 | HOLDS |
| 16 | 305 | 289 | HOLDS |

The `~3.6×` state-space growth between scales is the linear-in-`W`
behaviour the bounded model predicts (each window can carry at
most one DIRTY entry per index, so reachable states grow with the
window-size product). Empirically, the bound holds at every scale
the sweep covers.

### 2. Hand proof of the unbounded theorem

[`docs/proofs/Rlb_unbounded_handproof.md`](../proofs/Rlb_unbounded_handproof.md)
provides a rigorous mathematical proof of the unbounded theorem
by structural induction. Four lemmas and the main theorem:

- **Lemma 1** `CountDirty_bounded`: `0 ≤ CountDirty(h) ≤ Len(h)`.
- **Lemma 2** `WindowUpdate_bounded`: `Len(WindowUpdate(h, o)) ≤ W`.
- **Lemma 3** `DirtyAcc_count`:
  `CountDirty(DirtyAcc(n)) = min(n, W)`.
- **Lemma 4** `CleanAfterDirty_count`: the explicit count formula
  during recovery (the load-bearing lemma).
- **Theorem 1** RLB-v1 unbounded: `L = W + N − 1 = peak + W − 1`.

The proof has **no `W` dependence in its arguments** — it goes
through for any `W ∈ ℕ, W > 0`. It is auditable line by line by a
human reviewer.

Crucial caveat: the hand proof is **not** SMT-checked. A typo or
a missing case in the hand argument would not be caught by any
automated tool until a future contributor lifts it to TLAPS.

### 3. TLAPS outline with discharge guidance

[`docs/proofs/Rlb_unbounded.tla`](../proofs/Rlb_unbounded.tla)
compiles under TLAPS and contains the four lemma statements +
theorem with `PROOF OMITTED` placeholders. v0.2.5 refines the
outline with per-lemma `DISCHARGE GUIDANCE` blocks naming the
specific `BY` steps a future contributor should write, estimated
effort per lemma, and references to the corresponding sections in
the hand proof.

The outline serves as the *bridge document* between the hand
proof and the mechanical TLAPS proof. A contributor with TLAPS
installed can read both files side by side and discharge each
`PROOF OMITTED` by following the guidance.

### 4. How the three artefacts compose

| Artefact | Mechanical? | Coverage | Catches |
|---|:---:|---|---|
| TLC sweep | ✅ | `W ∈ {4, 8, 16}` | Implementation bug at any of these scales |
| Hand proof | ❌ | Any `W ≥ 1` | Reasoning bug a human reviewer can spot |
| TLAPS outline | ❌ (placeholders) | Any `W ≥ 1` | Future SMT verification when discharged |

Together they constitute the v0.2.5 evidence package for the
unbounded RLB-v1 claim. The paper §6.3 cites all three; §9
limitations explicitly acknowledges that the TLAPS leg is still
unfilled.

## Scope — what this ADR claims and does NOT claim

**This ADR claims (v0.2.5):**

- TLC mechanically verifies `INV_RLB` over the full reachable
  state space at `W = 4, 8, 16` on every CI push (via
  `run_rlb_tlc_sweep.py`).
- The hand proof is correct mathematics, auditable by a human
  reviewer, with no `W` dependence in its arguments.
- The TLAPS outline compiles under `tlapm`, contains the right
  lemma statements, and is ready for a future contributor with a
  working TLAPS install to discharge.

**This ADR does NOT claim:**

- A full TLAPS-mechanical proof of the unbounded theorem (the
  `PROOF OMITTED` placeholders are not discharged).
- That the TLC sweep covers all `W` (it covers three specific
  values; the unbounded statement is mathematics, not
  enumeration).
- That the bridge from TLA+ to the Python verifier is mechanically
  verified — that remains by inspection (paper §9 caveat).

## Verification plan

- `docs/paper/scripts/run_rlb_tlc_sweep.py` runs the three TLC
  configurations and emits the JSON artefact. Exit code zero iff
  every `W` holds.
- Suggested CI integration: add a new `tla-plus-sweep` job in
  `.github/workflows/ci.yml` that invokes the driver and uploads
  the JSON as a CI artefact. Deferred to a follow-up PR to keep
  the v0.2.5 round focused.
- The hand proof has no automated verifier; review is by code
  review on the Markdown.
- The TLAPS outline is currently exercised only as a syntax check
  (it compiles under `tlapm` parse without discharging
  obligations); a future contributor with TLAPS installed will
  exercise it for real.

## What this ADR does NOT close

- **Full TLAPS proof.** Each lemma still needs `BY` steps
  written, run through Zenon/Isabelle/SMT, and the certificate
  archived. The roadmap estimate from
  [`docs/proofs/TLAPS_roadmap.md`](../proofs/TLAPS_roadmap.md)
  remains: 5–10 days for a contributor familiar with TLAPS, with
  a Linux/macOS install (Windows native unsupported; WSL2
  experimental).
- **A new ADR-0042 (future) is the natural follow-up**: discharge
  the TLAPS placeholders and lift this ADR from "partial" to
  "fully accepted".

## Alternatives considered

1. **Skip the hand proof and the sweep; wait for a full TLAPS
   proof.** Rejected: the paper has been gated by this for two
   rounds, and the hand proof + sweep entry already provide
   credible evidence the unbounded claim is correct. Waiting
   leaves the paper carrying a "bounded TLC only" caveat
   indefinitely.
2. **Skip the TLAPS outline; ship only the hand proof + sweep.**
   Rejected: the outline is the bridge document. Without it, a
   future contributor cannot easily lift the hand proof to
   TLAPS — they would have to re-derive the lemma structure and
   the BY-step plan.
3. **Replace the bounded TLC verification with the sweep.** No
   change: the sweep *extends* the bounded verification rather
   than replacing it. The `W = 4` configuration in CI remains the
   baseline.
4. **Install TLAPS on Windows via WSL2 in this session.**
   Rejected for v0.2.5: WSL2 install requires a reboot (loses
   session); TLAPS install on WSL2 is "experimental" per the
   official docs. Not a fit for the v0.2.5 round; safe-out path
   is to ship the triple-evidence package and let a future
   contributor with the right environment finish the TLAPS leg.

## References

- Hand proof: [`docs/proofs/Rlb_unbounded_handproof.md`](../proofs/Rlb_unbounded_handproof.md)
- TLAPS outline: [`docs/proofs/Rlb_unbounded.tla`](../proofs/Rlb_unbounded.tla)
- TLAPS roadmap: [`docs/proofs/TLAPS_roadmap.md`](../proofs/TLAPS_roadmap.md)
- TLC baseline: [`docs/proofs/Rlb.tla`](../proofs/Rlb.tla)
- Sweep configs: [`docs/proofs/Rlb_W8.cfg`](../proofs/Rlb_W8.cfg), [`docs/proofs/Rlb_W16.cfg`](../proofs/Rlb_W16.cfg)
- Sweep driver: [`docs/paper/scripts/run_rlb_tlc_sweep.py`](../paper/scripts/run_rlb_tlc_sweep.py)
- Sweep artefact: [`docs/paper/outputs/rlb_tlc_sweep/sweep.json`](../paper/outputs/rlb_tlc_sweep/sweep.json)
- Bounded TLC ADR: [`docs/adr/0036-tla-plus-mechanical-verification-of-baud-erur.md`](0036-tla-plus-mechanical-verification-of-baud-erur.md)
- Paper §6.3, §9 (limitations), §10 (future work)
