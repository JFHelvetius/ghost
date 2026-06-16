# ADR-0039 — False Positive Bound Property v2 (FPB-v2, statistical)

## Status

Accepted (v0.2.5).

Promotes the candidate slot reserved for ADR-0039 in
ADR-0035 §"Tract para FPB-v2 estadística" and in the paper
(§10 Future work, ADR-0039 entry) to an accepted ADR. ADR-0035
(FPB-v1) is **not** deprecated; the two coexist with distinct
contracts (see §3 below).

## Context

FPB-v1 (ADR-0035) ships an **observational** comparison:

    holds  iff  fire_fraction <= max_fire_fraction

where ``fire_fraction = cycles_baud_fires / cycles_total`` is the
empirical rate of BAUD-v1 precondition firings on the captured
MCAP. This contract is correct but statistically anaemic. A
verdict on ``n = 10`` cycles is treated identically to a verdict
on ``n = 10 000`` cycles, even though the small sample carries
essentially no statistical authority over the **underlying**
firing probability.

The paper's §9 limitations explicitly carried this gap as
*"FPB-v1 is observational; a statistical FPB-v2 with Monte
Carlo bounds is a candidate future ADR"*. v0.2.5 closes that
gap with a closed-form, distribution-free confidence interval
(no Monte Carlo harness required), and ships an exact-binomial
variant for callers who prefer tighter bounds under a stronger
modelling assumption.

## Decision

### 1. Property statement (FPB-v2)

Given an MCAP and a target ``confidence_level`` in ``(0, 1)``,
the verifier computes a one-sided **upper bound** on the *true*
firing probability ``p`` such that, under the chosen
``ConfidenceMethod``,

> *With confidence at least ``confidence_level``, the true firing
> probability ``p`` is at most ``confidence_upper_bound``.*

The property HOLDS iff
``confidence_upper_bound <= max_fire_probability``.

### 2. Estimators

Two estimators are shipped behind a closed
``ConfidenceMethod`` enum:

#### 2.1 ``HOEFFDING`` (default, stdlib-only)

    ub = p_hat + sqrt(ln(1 / (1 - level)) / (2 * n))

Distribution-free: assumes only that observations live in
``[0, 1]``. Looser than the exact binomial CI but does not
require iid Bernoulli observations to be sound, and runs in
constant time without external dependencies. Default for any
caller who does not have a strong reason to prefer Clopper-
Pearson.

#### 2.2 ``CLOPPER_PEARSON`` (opt-in, requires SciPy)

    ub = BetaInv(level; cycles_fires + 1, cycles_total - cycles_fires)

The exact one-sided binomial upper bound. Tighter than
Hoeffding when observations are iid Bernoulli (this assumption
is plausible for BAUD's precondition under iid trials but is
not formally checked here). SciPy is imported lazily; absence
of SciPy raises a clear ``ImportError`` rather than silently
falling back.

### 3. Relationship to FPB-v1

| | FPB-v1 (ADR-0035) | FPB-v2 (this ADR) |
|---|---|---|
| Contract surface | empirical point estimate | confidence upper bound |
| Stdlib-only? | yes | yes (Hoeffding); SciPy for CP |
| Small-sample behaviour | passes anything <= threshold | conservatively widens, fails tight bounds |
| Use case | CI smoke regression gate | statistical safety case |
| Coexists with the other? | **yes** | **yes** |

FPB-v1 and FPB-v2 are *both* shipped. FPB-v1 answers "is my
observed rate above a regression threshold?" — useful as a CI
smoke that pins the reference run's empirical rate (paper §8.2).
FPB-v2 answers "is the *underlying* rate above a contractual
bound, with the confidence I claim?" — the statistical safety
case the paper §9 caveat called out.

### 4. Scope — what FPB-v2 claims and does NOT claim

**FPB-v2 claims (v2):**

- A one-sided upper bound on the true firing probability ``p``
  such that ``P(p > upper_bound) <= 1 - confidence_level`` under
  the assumptions of the chosen estimator (Hoeffding:
  ``X_i in [0, 1]``; Clopper-Pearson: iid Bernoulli).
- Deterministic byte-exact reproducibility of the report given
  the same MCAP, parameters, and method.

**FPB-v2 does NOT claim (v2):**

- **A two-sided confidence interval**: only the upper bound is
  reported. A symmetric CI would change the operational
  semantics (passes/fails under wider tolerance) and is out of
  scope.
- **Empirical validation of the Bernoulli assumption**: when
  ``CLOPPER_PEARSON`` is selected, the verifier trusts the
  caller's modelling assumption. Hoeffding sidesteps this
  entirely.
- **Multiple-testing correction**: a release that runs FPB-v2
  ``k`` times with different parameters and reports the minimum
  ``upper_bound`` will compound the false-positive rate. The
  verifier does not adjust for this; callers are expected to
  parameterise once per release.

### 5. Verification plan

#### 5.1 Verifier public surface (`src/project_ghost/properties/fpb_v2.py`)

`verify_fpb_v2(mcap_path, *, min_outcomes=4, downgrade_threshold=2,
max_fire_probability=1.0, confidence_level=0.95,
method=ConfidenceMethod.HOEFFDING) → FPBv2VerificationReport`.

Report carries: ``mcap_sha256``, ``method``,
``confidence_level``, ``max_fire_probability``, ``cycles_total``,
``cycles_precondition_held``, ``fire_fraction``,
``confidence_upper_bound``, ``first_precondition_cycle_stamp_sim_ns``,
``violations``. ``holds`` derives from
``confidence_upper_bound <= max_fire_probability``.

#### 5.2 Hypothesis property tests (`tests/properties/test_fpb_v2_property.py`)

Six structural properties that any sound estimator must
satisfy:

- **P1 — sound bound**: ``p_hat <= upper_bound <= 1.0``.
- **P2 — Hoeffding ≥ Clopper-Pearson**: distribution-free CI is
  at least as wide as exact binomial.
- **P3 — monotone in ``p_hat`` at fixed ``n``**.
- **P4 — decreasing in ``n`` at fixed ``p_hat``** (verified by
  doubling ``(k, n) → (2k, 2n)``).
- **P5 — consistency**: gap to ``p_hat`` < 0.05 at ``n = 10 000``,
  ``level = 0.95``.
- **P6 — small-sample correctness**: ``n = 0 ⇒ ub = 1.0``;
  ``k = 0, n > 0 ⇒ ub < 1.0``.

P2 + P3 + P4 jointly pin the qualitative shape of any future
estimator (e.g. Wilson score) added to ``ConfidenceMethod``.

#### 5.3 End-to-end smoke on the reference MCAP

On ``sample.ulg`` (``n = 71``, ``p_hat = 0.9437``):

| method | max_fire_prob = 1.0 | 0.99 | 0.95 | 0.5 |
|---|:---:|:---:|:---:|:---:|
| HOEFFDING       | HOLDS | VIOL  | VIOL  | VIOL |
| CLOPPER_PEARSON | HOLDS | HOLDS | VIOL  | VIOL |

The table demonstrates the small-sample conservatism that
distinguishes FPB-v2 from FPB-v1 (which would HOLD on the
``0.95`` column because ``0.9437 < 0.95``).

## Consequences

### Positive

- **Closes the §9 caveat**: the paper can now drop the
  "FPB-v1 is observational; a statistical FPB-v2…" deferment
  and state that a statistical bound ships.
- **Small-sample correctness**: tight regression gates on
  short MCAPs correctly fail to certify, instead of giving a
  false sense of authority.
- **Two contracts, two answers**: FPB-v1's CI-smoke use case
  remains; FPB-v2's statistical safety case is a new tool. A
  reviewer can immediately see which contract a release is
  invoking from the property version field.

### Negative / costs

- **SciPy as an optional dependency**: ``CLOPPER_PEARSON``
  requires it. Mitigation: Hoeffding is the stdlib-only default
  and is fully featured; SciPy is gated behind explicit opt-in.
- **Conservatism of Hoeffding**: distribution-free bounds are
  loose. A maintainer who wants the tightest possible bound
  must opt into ``CLOPPER_PEARSON`` and accept the iid
  Bernoulli assumption.
- **No multiple-testing correction** (see scope §4). A release
  that runs FPB-v2 with many parameterisations is responsible
  for not cherry-picking the best result.

## Alternatives considered

1. **Monte Carlo harness** as suggested in the original
   ADR-0035 §"Tract para FPB-v2 estadística". Rejected for the
   v0.2.5 round: Monte Carlo introduces a runtime cost and a
   non-deterministic reporting layer that contradicts ADR-0030
   (replay verification). Closed-form bounds satisfy the
   statistical claim without sacrificing determinism.
2. **Wilson score interval** as a third method. Considered:
   Wilson is intermediate in tightness between Hoeffding and
   Clopper-Pearson, no SciPy required. Deferred to a future
   amendment; the two-method enum already exposes the
   right-shaped API and Wilson is a drop-in addition.
3. **Replace FPB-v1**. Rejected: the two contracts answer
   different questions (regression gate vs statistical safety
   case). The paper §3.5 documents both side by side; CI uses
   FPB-v1 for the smoke pin (paper §8.2) and FPB-v2 for the
   statistical claim.
4. **Deprecation of FPB-v1**. Same as #3 — kept for the
   smoke-regression use case. The property versions
   (``"FPB-v1"`` / ``"FPB-v2"``) are distinct strings so a
   verdict bundle can carry both without ambiguity.

## Implementation roadmap (informational)

Already shipped in v0.2.5:

1. ``src/project_ghost/properties/fpb_v2.py`` with two
   estimators, fully type-checked.
2. ``tests/properties/test_fpb_v2_property.py`` with six
   Hypothesis properties.
3. ``project_ghost.properties.__init__`` re-exports the v2
   public surface alongside v1.
4. Paper updates: §3.5 documents the two contracts, §9 drops
   the "no statistical bound" caveat, §10 ADR-0039 entry
   advances from "candidate" to "accepted, v0.2.5".

Future amendments (not blocking):

- Wilson score as third ``ConfidenceMethod``.
- Two-sided variants for callers who want lower bounds too.
- An A/B smoke that exercises both methods on the same MCAP
  and pins their relationship.
