"""`traceability` — observational behavior traceability (T6, ADR-0014).

Reconstructs the observable sequence of messages that preceded a target
event within a configurable time window. **Not explanation.** The
system tells you what was observed; it does not interpret intent or
infer causality.

Offline. Deterministic. JSON-only output. No databases, dashboards,
threads, async, ML, anomaly detection, scoring, ranking, or reasoning.

Public API:

- ``BehaviorTrace``: frozen dataclass with the four ordered tuples of
  preceding messages.
- ``TracedMessage``: compact record of one observed message.
- ``EventNotFoundError``: raised when ``event_id`` is not in the MCAP.
- ``build_behavior_trace(*, reader, event_id, window_ns)``.
- ``generate_trace_report(trace, output=None)``.
- ``encode_trace_to_bytes(trace) -> bytes``.
- ``TRACE_SCHEMA_VERSION`` / ``TRACE_REPORT_SCHEMA_VERSION``.

CLI: ``ghost trace-event --mcap PATH --event-id ID --window-seconds N``
lives in ``project_ghost.cli``.
"""

from __future__ import annotations

from .analysis import (
    TRACE_REPORT_SCHEMA_VERSION,
    build_behavior_trace,
    encode_trace_to_bytes,
    generate_trace_report,
)
from .models import (
    TRACE_SCHEMA_VERSION,
    BehaviorTrace,
    EventNotFoundError,
    TracedMessage,
)

__all__ = [
    "TRACE_REPORT_SCHEMA_VERSION",
    "TRACE_SCHEMA_VERSION",
    "BehaviorTrace",
    "EventNotFoundError",
    "TracedMessage",
    "build_behavior_trace",
    "encode_trace_to_bytes",
    "generate_trace_report",
]
