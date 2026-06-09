"""Channel name constants for the telemetry layer.

Names are part of the file format: once an `.mcap` file is written, the
channel strings inside are part of the contract any replay tool must
understand. We commit to them here and never typo them at call sites.

Adding a new channel here is fine. Renaming an existing one breaks
backward compatibility with previously captured runs — treat as an
ADR-grade change.
"""

from __future__ import annotations

TELEMETRY_PROTOCOL_VERSION: int = 1

CHANNEL_EVENTS: str = "/events"
"""Generic `Event` traffic from `events.EventBus`."""

CHANNEL_STATE_NAV: str = "/state/nav"
"""`VehicleState` snapshots from `state.aggregator` (and, eventually, from
real estimators)."""

CHANNEL_PERCEPTION_MODE: str = "/perception/mode"
"""`PerceptionModeChanged` events from `core.uncertainty.PerceptionModeDetector`
(spec: uncertainty.md §9). Persisted via
``telemetry.adapters.ModeEventToTelemetryAdapter``."""

CHANNEL_SELF_ASSESSMENT: str = "/self_assessment"
"""`BeliefSelfAssessment` runtime introspection records from
``core.uncertainty.self_assessment.assess_belief`` (ADR-0020). Each
record is the agent's classificatory claim about what it believes it
knows. Persisted via
``telemetry.adapters.SelfAssessmentToTelemetryAdapter``."""

CHANNEL_DECISIONS: str = "/decisions"
"""`DecisionRationale` records — el agente afirmando qué decide hacer
con la creencia que tiene (ADR-0021). Cada record carga la decisión Y
la justificación content-addressed al ``BeliefSelfAssessment`` input.
Persistido vía ``telemetry.adapters.DecisionToTelemetryAdapter``."""

CHANNEL_ACTUATIONS: str = "/actuations"
"""`ActuationDirective` records — el directive que ata cada decisión
a un ``ActuatorCommand`` opcional (ADR-0023). ``actuator_command=None``
es estado legítimo cuando la policy declara que para esa decisión no
procede emitir comando. Persistido vía
``telemetry.adapters.ActuationToTelemetryAdapter``."""

CHANNEL_FORWARD_PREDICTIONS: str = "/predictions/forward"
"""`BeliefForwardPrediction` records — el agente declarando qué espera
observar en ``stamp + horizon_ns`` (ADR-0024). El record viaja con std
posicional + orientacional, opcionalmente atado a un
``ActuationDirective`` via ``associated_directive_hash``. Persistido
vía ``telemetry.adapters.ForwardPredictionToTelemetryAdapter``."""

CHANNEL_PREDICTION_OUTCOMES: str = "/predictions/outcomes"
"""`PredictionOutcome` records — la observación real comparada contra
una predicción previamente emitida (ADR-0025). Cada record carga la
predicción inline, la pose observada, los residuos posicional y
orientacional, los Mahalanobis máximos por eje y un verdict categórico
cerrado. Persistido vía
``telemetry.adapters.PredictionOutcomeToTelemetryAdapter``."""

CHANNEL_CALIBRATED_SELF_ASSESSMENT: str = "/self_assessment/calibrated"
"""`CalibratedSelfAssessment` records — el self-assessment crudo
(ADR-0020) ajustado por la evidencia agregada de outcomes recientes
(ADR-0025) vía una ``CalibrationAdjustmentPolicy`` (ADR-0026). Cada
record carga el assessment crudo inline, el ``CalibrationHistory`` que
lo informa, el level ajustado, el ``adjustment_policy_id`` y el
``adjustment_reason`` taxonomizados. Persistido vía
``telemetry.adapters.CalibratedSelfAssessmentToTelemetryAdapter``."""

_SENSOR_PREFIX: str = "/sensors/"


def channel_for_sensor(sensor_id: str) -> str:
    """Channel name for a given sensor id.

    Convention: ``/sensors/<sensor_id>``. We forbid ``/`` inside
    ``sensor_id`` so the prefix split is unambiguous in tooling.
    """
    if not sensor_id:
        raise ValueError("sensor_id no puede ser vacío")
    if "/" in sensor_id:
        raise ValueError(
            f"sensor_id no puede contener '/'; recibido {sensor_id!r}"
        )
    return _SENSOR_PREFIX + sensor_id


__all__ = [
    "CHANNEL_ACTUATIONS",
    "CHANNEL_CALIBRATED_SELF_ASSESSMENT",
    "CHANNEL_DECISIONS",
    "CHANNEL_EVENTS",
    "CHANNEL_FORWARD_PREDICTIONS",
    "CHANNEL_PERCEPTION_MODE",
    "CHANNEL_PREDICTION_OUTCOMES",
    "CHANNEL_SELF_ASSESSMENT",
    "CHANNEL_STATE_NAV",
    "TELEMETRY_PROTOCOL_VERSION",
    "channel_for_sensor",
]
