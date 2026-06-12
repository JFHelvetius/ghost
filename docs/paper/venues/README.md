# Venue submission plans

Per-venue submission plans for the Project Ghost paper. Each
document covers the venue's CFP details, why the paper fits there,
how to adapt `docs/paper/arxiv/main.tex` for the venue's required
class file, venue-specific strengthening edits, and a submission
checklist.

## Active plans

| Venue | Status | Plan |
|---|---|---|
| arXiv preprint | Submission instructions in [`../arxiv/README.md`](../arxiv/README.md) | Self-archive immediately — gives DOI and prior-art timestamp |
| **FMAS 2026** | **Primary target (deadline 17 Aug 2026)** | [`fmas2026.md`](fmas2026.md) |
| **RV 2027** | **Secondary target (CFP opens ~Apr 2027)** | [`rv2027.md`](rv2027.md) |

## Strategy at a glance

1. **Now:** self-archive on arXiv from the LaTeX source at
   `../arxiv/main.tex`. Categories: cs.SE primary, cs.LO + cs.RO
   secondary. This establishes prior-art timestamp and a citable
   DOI.
2. **By 14–17 August 2026:** submit to FMAS 2026 (EPTCS format).
   The autonomy-domain framing is the natural first audience.
3. **If FMAS accepts:** present at Southampton 17–18 Nov 2026. Use
   the workshop feedback to polish for RV 2027.
4. **If FMAS rejects (or in parallel with the journal special-issue
   extension):** target RV 2027 (deadline ~mid-2027) as the tool
   paper venue. The RV community values the verifier algorithm +
   TLA+ specs deeply.
5. **Fallbacks:** NFM 2027, TACAS 2027 tool track, SEFM 2026,
   workshops co-located with CAV 2027.

## Why not RV 2026

RV 2026 deadline is 14 June 2026 — three days after this artifact
package was finalised. Not enough runway to peer-review-grade the
submission. See [`rv2027.md`](rv2027.md) §Why not RV 2026.

## Why not NFM 2026

NFM 2026 deadline already passed (Jan 2026). Target NFM 2027
instead (see fallbacks in `rv2027.md`).

## Common preparation

For any of these venues:

- Compile the LaTeX source locally (TeX Live + `pdflatex + bibtex`)
  or via Overleaf to confirm page count fits.
- Generate the bibliography with `bibtex main` so `main.bbl` exists
  before tarballing for submission.
- Pin the corresponding repository release tag (`vX.Y.Z`) so
  reviewers can clone an exact artifact.
- Update [`../arxiv/README.md`](../arxiv/README.md) with the venue's
  preprint policy (most allow simultaneous arXiv self-archival).
