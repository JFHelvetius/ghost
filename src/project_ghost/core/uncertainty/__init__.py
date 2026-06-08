"""`core.uncertainty` — núcleo matemático y semántico de la incertidumbre.

Primera materialización en código (U1) del mecanismo descrito en
`docs/specs/uncertainty.md` y los ADRs ADR-0008 / ADR-0009 / ADR-0010.

Alcance acumulado a U1.b:

- **U1.a — Tipos y helpers (uncertainty.md §2, §3, §5, §6, §8):**

  - Tipos congelados: `Validity`, `EstimateSource`, `Estimate[T]`,
    `NavUncertainty`, `NominalEnvelope`, `PerceptionMode`.
  - Invariantes verificados por constructor: sealing recursivo, simetría, PSD,
    groundtruth↔covariance, consistencia validity↔envelope.
  - Helpers puros: `make_estimate`, `inflate_isotropic`, `inflate_directional`,
    `inflate_stale`, `compose_validity`, `age_ns`, `downgrade_by_age`.

- **U1.b — Detector de modo perceptual (perception.md §3-§4, §5.6,
  uncertainty.md §9, ADR-0010):**

  - `PerceptionModeChanged` event + `ModeEventSink` Protocol +
    `NullModeEventSink` / `RecordingModeEventSink`.
  - `DetectorConfig` con thresholds de uncertainty.md §7.
  - `PerceptionModeDetector` FSM con doble condición; subconjunto de
    transiciones: NOMINAL ↔ MOTION_AGGRESSIVE, MOTION_AGGRESSIVE →
    LOW_TEXTURE (timeout), NOMINAL ↔ LOW_TEXTURE. Resto deferido a U1.c.

Fuera de alcance todavía:

- Modos LOW_LIGHT / IMU_SATURATION / VIO_LOST / MAP_AMBIGUOUS /
  PERCEPTION_DEAD del catálogo (U1.c).
- EventBus real (Phase 1 T5).
- Productores reales en `perception/` (Fase 3).
"""

from __future__ import annotations

from .composition import age_ns, compose_validity, downgrade_by_age
from .estimate import Estimate, make_estimate
from .inflation import inflate_directional, inflate_isotropic, inflate_stale
from .mode_detector import DetectorConfig, PerceptionModeDetector
from .mode_events import (
    ModeEventSink,
    NullModeEventSink,
    PerceptionModeChanged,
    RecordingModeEventSink,
)
from .self_assessment import (
    SELF_ASSESSMENT_PROTOCOL_VERSION,
    AssessmentThresholds,
    BeliefSelfAssessment,
    SelfAssessmentLevel,
    assess_belief,
    thresholds_sha256,
)
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
    "SELF_ASSESSMENT_PROTOCOL_VERSION",
    "UNCERTAINTY_PROTOCOL_VERSION",
    "AssessmentThresholds",
    "BeliefSelfAssessment",
    "DetectorConfig",
    "Estimate",
    "EstimateKind",
    "EstimateSource",
    "ModeEventSink",
    "NavUncertainty",
    "NominalEnvelope",
    "NullModeEventSink",
    "PerceptionMode",
    "PerceptionModeChanged",
    "PerceptionModeDetector",
    "RecordingModeEventSink",
    "SelfAssessmentLevel",
    "Validity",
    "age_ns",
    "assess_belief",
    "compose_validity",
    "downgrade_by_age",
    "inflate_directional",
    "inflate_isotropic",
    "inflate_stale",
    "make_estimate",
    "thresholds_sha256",
]
