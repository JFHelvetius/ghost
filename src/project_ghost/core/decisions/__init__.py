"""`core.decisions` — capa contractual creencia → acción (ADR-0021).

Define los shapes mínimos para que el agente convierta lo que cree
saber en una afirmación de qué hacer:

- ``DecisionKind`` (catálogo cerrado).
- ``DecisionContext`` (entrada al policy).
- ``Decision`` (salida; afirmación clasificatoria).
- ``DecisionRationale`` (auditoría con content-address al
  ``BeliefSelfAssessment``).
- ``Policy`` (Protocol pure function).
- ``DecisionSink`` (Protocol consumer con enforcement
  "no decisión sin rationale").
- ``NullDecisionSink`` / ``RecordingDecisionSink`` (implementaciones
  de referencia para tests).
- ``UncertaintyAwareReferencePolicy`` (mapping mínimo level → decision
  que valida que el contrato es sound).
- ``decide_with_rationale`` / ``decide_and_publish`` (orquestación
  canónica).
- ``self_assessment_sha256`` (firma content-address del assessment).

Cero implementaciones de control. Cero translation a ``ActuatorCommand``.
Cero policies operativos. Esos llegan en ADRs futuras componiéndose
sobre estos shapes.
"""

from __future__ import annotations

from .orchestration import (
    decide_and_publish,
    decide_with_rationale,
    self_assessment_sha256,
)
from .protocols import DecisionSink, Policy
from .reference_policy import UncertaintyAwareReferencePolicy
from .sinks import NullDecisionSink, RecordingDecisionSink
from .types import (
    DECISION_PROTOCOL_VERSION,
    Decision,
    DecisionContext,
    DecisionKind,
    DecisionRationale,
)

__all__ = [
    "DECISION_PROTOCOL_VERSION",
    "Decision",
    "DecisionContext",
    "DecisionKind",
    "DecisionRationale",
    "DecisionSink",
    "NullDecisionSink",
    "Policy",
    "RecordingDecisionSink",
    "UncertaintyAwareReferencePolicy",
    "decide_and_publish",
    "decide_with_rationale",
    "self_assessment_sha256",
]
