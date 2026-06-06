"""`core.uncertainty` — núcleo matemático y semántico de la incertidumbre.

Primera materialización en código (U1.a) del mecanismo descrito en
`docs/specs/uncertainty.md` y los ADRs ADR-0008 / ADR-0009 / ADR-0010.

Alcance U1.a (uncertainty.md §2, §3, §5, §6, §8):

- Tipos congelados: `Validity`, `EstimateSource`, `Estimate[T]`,
  `NavUncertainty`, `NominalEnvelope`, `PerceptionMode`.
- Invariantes verificados por constructor: sealing recursivo, simetría, PSD,
  groundtruth↔covariance, consistencia validity↔envelope.
- Helpers puros: `make_estimate`, `inflate_isotropic`, `inflate_directional`,
  `inflate_stale`, `compose_validity`, `age_ns`, `downgrade_by_age`.

Fuera de alcance todavía:

- FSM perceptual y eventos `/perception/mode` (U1.b).
- Modos LOW_LIGHT / IMU_SATURATION / VIO_LOST / MAP_AMBIGUOUS /
  PERCEPTION_DEAD del catálogo (U1.c).
- EventBus real (Phase 1 T5).
- Productores reales en `perception/` (Fase 3).
"""

from __future__ import annotations

from .composition import age_ns, compose_validity, downgrade_by_age
from .estimate import Estimate, make_estimate
from .inflation import inflate_directional, inflate_isotropic, inflate_stale
from .types import (
    EstimateKind,
    EstimateSource,
    NavUncertainty,
    NominalEnvelope,
    PerceptionMode,
    Validity,
)

UNCERTAINTY_PROTOCOL_VERSION: int = 1

__all__ = [
    "UNCERTAINTY_PROTOCOL_VERSION",
    "Estimate",
    "EstimateKind",
    "EstimateSource",
    "NavUncertainty",
    "NominalEnvelope",
    "PerceptionMode",
    "Validity",
    "age_ns",
    "compose_validity",
    "downgrade_by_age",
    "inflate_directional",
    "inflate_isotropic",
    "inflate_stale",
    "make_estimate",
]
