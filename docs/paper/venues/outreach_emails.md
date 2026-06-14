# External audit emails — pre-submission outreach

Four drafted emails to runtime-verification and formal-methods
experts whose prior work appears in the paper's related-work section.
The goal is pre-submission feedback before the paper goes to arXiv
or to FMAS 2026.

**Instructions to send these:**

1. Open each block below; copy into your Gmail (or whichever client).
2. Replace the placeholder fields (`[YOUR_NAME]`, `[ARXIV_URL_WHEN_READY]`,
   etc.) with your details.
3. Address fields:
   - **To**: the recipient's primary academic email — look up the
     latest one on their institutional page or their most recent
     paper. **Do NOT guess**; if the email cannot be confirmed,
     skip that recipient and target the next.
   - **From**: your gmail `jfhelvetius@gmail.com`.
4. Send as plain text. Attach the PDF (or paste the arXiv URL once
   published) only if invited; the initial outreach should be
   short and respectful of their time.

**Realistic expectations:**

- 30 % response rate is normal for cold academic outreach.
- Those who respond usually do so within 1–3 weeks; some take longer.
- The responses you get are gold: incorporate them into the paper
  before submitting to FMAS / arXiv.
- Acknowledge their feedback in the paper's acknowledgements
  section (we'll add that section once we have feedback).

---

## Email 1 — Ezio Bartocci (MoonLight, RV Lectures)

**Subject:** Feedback request: TLA+ verification of a sliding-window
safety supervisor for autonomy

```
Dear Prof. Bartocci,

I am preparing a paper to submit to FMAS 2026 / RV 2027 on a
verifiable safety-property surface for autonomy under uncertainty.
The work cites your MoonLight tool (RV 2020 / STTT 2023) and the
Runtime Verification lecture series (LNCS 10457) as central
references.

Three pieces of the paper might be of interest:

1. A closed-form, tight recovery latency bound L ≤ peak + W − 1 for
   count-of-K-in-W sliding-window calibration filters. I have
   stated this as the recovery latency bound with a sliding-window proof and a
   tightness witness; I would deeply appreciate your judgement on
   whether the bound is genuinely novel relative to the runtime
   verification literature or whether I am missing prior work that
   states it explicitly.

2. A mechanical verification of the BAUD ⊕ ERUR partition theorem
   over the abstract state space of the reference policy, in TLA+
   verified by TLC. I have not found prior TLA+ work on autonomy
   supervisors (most existing formal verification for runtime
   monitors targets STL via tools like yours and RTAMT, or it uses
   theorem provers such as Coq/Lean). Pointers to anything I should
   have cited would be very welcome.

3. A reproducibility pattern that ships the verifier as a pip-
   installable CLI over content-addressed MCAP logs, with the
   verification re-runnable from `pip install project-ghost==0.2.1`.

The paper draft is at [ARXIV_URL_WHEN_READY] (12 pages).
Code, TLA+ specs, and CI artifacts at
https://github.com/JFHelvetius/ghost (release v0.2.1).

I am sending this as a polite pre-submission consultation; any
quick reaction — "this looks reasonable", "you missed X", "the
theorem statement is wrong because Y" — would help the work land
in a better venue than a blind submission would reach.

Thank you for your time. No reply is, of course, perfectly fine.

Best regards,
Javier Menéndez Mateos
Independent researcher
jfhelvetius@gmail.com
https://github.com/JFHelvetius
```

---

## Email 2 — Dejan Niković (RTAMT)

**Subject:** Comparative positioning of an MCAP-based safety-property
verifier vs RTAMT

```
Dear Dr. Niković,

I am drafting a paper on a runtime safety-property verifier for
autonomy pipelines (Project Ghost, v0.2.1). RTAMT
(ATVA 2020 / STTT 2023) is the closest tool I cite in the related-
work comparison matrix.

In §2.3 I position Ghost as differing from RTAMT along three
axes: (a) hand-crafted property predicates with policy parameters
rather than STL-defined; (b) mechanical TLA+/TLC proofs of the
underlying invariants in addition to the runtime verifier; (c)
distribution as a content-addressed PyPI wheel with OIDC trusted
publishing rather than a source/runtime tool.

I would value your reading of whether that positioning is fair to
RTAMT's current scope, and whether RTAMT has features I should
acknowledge (the comparison was based on the 2023 STTT paper).

The draft is at [ARXIV_URL_WHEN_READY] (12 pages); repository at
https://github.com/JFHelvetius/ghost.

A short reaction would be deeply appreciated; if RTAMT is closer to
Ghost than I think, I would rather find out before submission than
during review.

Thank you for your time.

Best regards,
Javier Menéndez Mateos
Independent researcher
jfhelvetius@gmail.com
```

---

## Email 3 — Angelo Ferrando (ROSMonitoring)

**Subject:** Quick sanity check on a sliding-window safety claim for
ROS-style autonomy

```
Dear Dr. Ferrando,

I am preparing a runtime-verification tool paper on safety properties
for autonomy under uncertainty (Project Ghost, v0.2.1). I cite
ROSMonitoring (TAROS 2020) as the closest live-middleware monitor in
the related-work section.

Ghost takes a different angle from ROSMonitoring: it verifies safety
properties **post-hoc** over captured MCAP logs (content-addressed
SHA-256, replayable byte-exact), rather than live in the ROS
middleware. The verifier is a pure Python CLI; the input is a log,
not a running system.

Two questions where your perspective would help:

1. Is the post-hoc-on-MCAP angle a genuinely complementary niche to
   live ROS monitoring, or does ROSMonitoring already cover this
   territory in a way I have missed?

2. Are there ROS-community datasets of telemetry logs (PX4, ROSBag,
   MCAP) that would be standard reference benchmarks for a tool
   like Ghost to verify against? I plan to add a real-data case
   study before final submission and would prefer a benchmark the
   community recognises.

Paper draft at [ARXIV_URL_WHEN_READY] (12 pages); code at
https://github.com/JFHelvetius/ghost.

Any quick reaction would help me situate the work better.

Thank you for your time.

Best regards,
Javier Menéndez Mateos
Independent researcher
jfhelvetius@gmail.com
```

---

## Email 4 — Yliès Falcone (Runtime Verification editor)

**Subject:** Pre-submission consultation: TLA+ mechanically-verified
safety properties for autonomy

```
Dear Prof. Falcone,

I am preparing a tool paper for RV 2027 / FMAS 2026 on a verifiable
safety-property surface for autonomy under uncertainty. The work
draws on the Runtime Verification lecture series (Bartocci et al.,
LNCS 10457, 2018) that you co-edited.

The contribution that I think is most likely to interest you is a
TLA+/TLC mechanical verification of two structural properties of an
autonomy supervisor:

1. A partition theorem (BAUD ⊕ ERUR) over the conditional behaviour
   space of a closed-loop supervisor, verified by TLC over the full
   reachable state space at small bounded constants.
2. A tight closed-form recovery-latency bound (the recovery latency bound,
   L ≤ peak + W − 1) for sliding-window count-of-K-in-W filters,
   also mechanised in TLA+ under its consecutive-drift hypothesis.

To the best of my knowledge after a deliberate prior-art review,
mechanically-verified TLA+ specs for autonomy safety supervisors do
not exist in the published literature (prior formal verification
for autonomy targets Lean/Coq or Hamilton-Jacobi reachability).
That claim is load-bearing for the paper and I would prefer to
have it sanity-checked by someone with broader purview of the field
than mine.

A short reaction — "fair claim", "you missed X" — would be hugely
valuable. The draft is at [ARXIV_URL_WHEN_READY] (12 pages); code
+ specs at https://github.com/JFHelvetius/ghost (release v0.2.1).

I appreciate your time even just to read this.

Best regards,
Javier Menéndez Mateos
Independent researcher
jfhelvetius@gmail.com
```

---

## After sending

When responses arrive:

1. Save each reply (export from Gmail as `.eml` or `.txt`) into a
   private `docs/paper/audit/` folder *not committed to the public
   repository* — academic correspondence is private by default
   unless the sender explicitly permits sharing.
2. For each substantive piece of feedback, log it in
   `docs/paper/audit/feedback_log.md` (created in the same private
   folder) with: date, source, comment summary, action taken, paper
   sections touched.
3. Update the paper before submission. Acknowledge the
   reviewers explicitly in the camera-ready version's
   acknowledgements section.

## What NOT to do

- **Do not cc** all four recipients on the same email. Send four
  separate messages.
- **Do not forward** their replies elsewhere without permission.
- **Do not post** the feedback publicly even paraphrased without
  confirming the contributor consents.
- **Do not send chase emails** if there is no reply within 4 weeks.
  Treat silence as polite decline.
- **Do not promise reciprocal reviews** unless you genuinely have
  time and expertise to deliver them.
