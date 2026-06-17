"""Project Ghost — sim-first autonomy under uncertainty.

Closed-loop reference pipeline plus seven epistemic safety contracts
(BAUD-v1, ERUR-v1, ERUR-v2, MD-v1, RLB-v1, FPB-v1, FPB-v2) verifiable
byte-exact from any captured MCAP, with TLA+/TLC and Lean 4 mechanical
evidence for the underlying invariants. See `docs/paper/` for the
companion manuscript and `docs/proofs/` for the formal artefacts.
"""

from __future__ import annotations

__version__ = "0.2.5"
__all__ = ["__version__"]
