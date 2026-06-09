"""`core.fusion` — sensor-to-belief fusion contract (ADR-0028).

Define los shapes contractuales para que un estimador produzca un
``VehicleState`` (belief) a partir de inputs de sensores.

- ``FusionInput`` / ``FusionResult`` — types puros, frozen,
  content-addressed.
- ``FUSION_PROTOCOL_VERSION`` — versión del contrato.
- ``compute_fusion_input_sha256`` — hash canónico del input.
- ``SensorFusionPolicy`` / ``FusionResultSink`` — Protocols
  ``@runtime_checkable``.
- ``NullFusionResultSink`` / ``RecordingFusionResultSink`` — sinks de
  referencia para tests.
- ``LinearMotionOracleFusionPolicy`` — policy oracle mínima: propaga
  linealmente desde configuración conocida; valida el contrato sin
  estimación real.
- ``fuse_and_publish`` — orquestación canónica.
"""

from __future__ import annotations

from .orchestration import fuse_and_publish
from .protocols import FusionResultSink, SensorFusionPolicy
from .reference_policy import LinearMotionOracleFusionPolicy
from .sinks import NullFusionResultSink, RecordingFusionResultSink
from .types import (
    FUSION_PROTOCOL_VERSION,
    FusionInput,
    FusionResult,
    compute_fusion_input_sha256,
)

__all__ = [
    "FUSION_PROTOCOL_VERSION",
    "FusionInput",
    "FusionResult",
    "FusionResultSink",
    "LinearMotionOracleFusionPolicy",
    "NullFusionResultSink",
    "RecordingFusionResultSink",
    "SensorFusionPolicy",
    "compute_fusion_input_sha256",
    "fuse_and_publish",
]
