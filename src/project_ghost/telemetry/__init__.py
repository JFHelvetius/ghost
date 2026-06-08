"""`telemetry` — deterministic capture and replay of runtime history.

T4 of the Fase 1 roadmap. The goal is not logging: it is **deterministic
capture of runtime history** to make the project's claims about replay,
debugging, evaluation, and future autonomy analysis auditable.

Modules:

- ``channels``: channel name constants (``/events``, ``/state/nav``,
  ``/sensors/<id>``).
- ``serialization``: byte-deterministic JSON encoding + round-trip
  decoder for Project Ghost frozen dataclasses.
- ``sink``: ``TelemetrySink`` Protocol + ``InMemorySink`` for tests.
- ``mcap_sink``: ``MCAPFileSink`` for on-disk capture (lazy ``mcap``
  import; install via ``[telemetry]`` extra).
- ``replay``: ``MCAPReplayReader`` + ``decode_message`` for reading
  captured runs back into typed dataclass instances.

Architecture intentionally absent:

- No central ``TelemetryBus`` class. Publishers hold a sink reference.
- No console / Rerun / dashboard sinks. Inspectability via ``mcap`` CLI
  tooling is sufficient.
- No sidecar manifest files. MCAP's built-in ``Statistics`` / ``Schema``
  / ``Channel`` records are self-describing.
- No ``ReplayClock`` here. Replay yields an iterator; what drives a
  clock from it is a future concern.

Determinism guarantees (verified by test):

- ``encode_to_bytes(x)`` is byte-identical for identical ``x`` within
  a single CPython version.
- ``MCAPFileSink`` produces byte-identical files for identical publish
  sequences within a single (CPython, mcap library) version pair.
- Cross-version byte equality is **not** guaranteed; semantic equality
  (channel, log_time, decoded payload) is preserved across compatible
  ``mcap`` library versions.
"""

from __future__ import annotations

from .adapters import (
    ActuationToTelemetryAdapter,
    DecisionToTelemetryAdapter,
    ForwardPredictionToTelemetryAdapter,
    ModeEventToTelemetryAdapter,
    PredictionOutcomeToTelemetryAdapter,
    SelfAssessmentToTelemetryAdapter,
)
from .channels import (
    CHANNEL_ACTUATIONS,
    CHANNEL_DECISIONS,
    CHANNEL_EVENTS,
    CHANNEL_FORWARD_PREDICTIONS,
    CHANNEL_PERCEPTION_MODE,
    CHANNEL_PREDICTION_OUTCOMES,
    CHANNEL_SELF_ASSESSMENT,
    CHANNEL_STATE_NAV,
    TELEMETRY_PROTOCOL_VERSION,
    channel_for_sensor,
)
from .mcap_sink import MCAPFileSink
from .replay import (
    MCAPReplayReader,
    ReplayMessage,
    decode_message,
    make_sensor_sample_decoder,
    supported_schemas,
)
from .serialization import encode_to_bytes, from_json_dict, to_json_safe
from .sink import CapturedMessage, InMemorySink, TelemetrySink

__all__ = [
    "CHANNEL_ACTUATIONS",
    "CHANNEL_DECISIONS",
    "CHANNEL_EVENTS",
    "CHANNEL_FORWARD_PREDICTIONS",
    "CHANNEL_PERCEPTION_MODE",
    "CHANNEL_PREDICTION_OUTCOMES",
    "CHANNEL_SELF_ASSESSMENT",
    "CHANNEL_STATE_NAV",
    "TELEMETRY_PROTOCOL_VERSION",
    "ActuationToTelemetryAdapter",
    "CapturedMessage",
    "DecisionToTelemetryAdapter",
    "ForwardPredictionToTelemetryAdapter",
    "InMemorySink",
    "MCAPFileSink",
    "MCAPReplayReader",
    "ModeEventToTelemetryAdapter",
    "PredictionOutcomeToTelemetryAdapter",
    "ReplayMessage",
    "SelfAssessmentToTelemetryAdapter",
    "TelemetrySink",
    "channel_for_sensor",
    "decode_message",
    "encode_to_bytes",
    "from_json_dict",
    "make_sensor_sample_decoder",
    "supported_schemas",
    "to_json_safe",
]
