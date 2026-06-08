"""`core.actuation` — capa contractual decisión → comando al actuador
(ADR-0023).

Define los shapes mínimos para que el agente convierta una decisión
en un directive auditable que carga el comando concreto (o ``None``
si la policy declara no emitir).

- ``ActuationDirective`` (envelope decision + comando opcional +
  identificadores).
- ``ActuationPolicy`` (Protocol pure function).
- ``ActuationSink`` (Protocol consumer).
- ``NullActuationSink`` / ``RecordingActuationSink`` (implementaciones
  de referencia para tests).
- ``KillOnlyActuationPolicy`` (mapping mínimo que valida que el
  contrato es sound).
- ``actuate_and_publish`` (orquestación canónica).

Cero implementaciones de control real. Cero trayectorias, cero
attitude targets para PROCEED/HOLD/RTL/LAND. Esos llegan en ADRs
futuras componiéndose sobre estos shapes.
"""

from __future__ import annotations

from .orchestration import actuate_and_publish
from .protocols import ActuationPolicy, ActuationSink
from .reference_policy import KillOnlyActuationPolicy
from .sinks import NullActuationSink, RecordingActuationSink
from .types import (
    ACTION_PROTOCOL_VERSION,
    ActuationDirective,
)

__all__ = [
    "ACTION_PROTOCOL_VERSION",
    "ActuationDirective",
    "ActuationPolicy",
    "ActuationSink",
    "KillOnlyActuationPolicy",
    "NullActuationSink",
    "RecordingActuationSink",
    "actuate_and_publish",
]
