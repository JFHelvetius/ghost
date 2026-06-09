"""Project Ghost integration examples.

These are not contracts and not policy. They're runnable scenarios that
exercise the contracts (ADR-0019 through ADR-0026) as a single
pipeline. Their purpose is twofold:

1. **Validate composability.** When a multi-cycle scenario doesn't
   wire cleanly, the contract is wrong — fix the contract, not the
   example.
2. **Surface gaps.** If a contract produces an auditable record that
   has no behavioral consequence in the cycle, the example exposes
   it. That signal informs the next ADR.

Modules:

- ``closed_loop_smoke``: N-cycle pipeline belief → assess → predict →
  decide → actuate → observe → divergence → feedback. Returns a
  summary dict and writes a complete MCAP.
"""

from __future__ import annotations
