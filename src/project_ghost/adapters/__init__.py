"""``project_ghost.adapters`` — converters from third-party
telemetry formats to the Ghost pipeline schema (paper §10,
candidate ADR-0037).

The package starts narrow: a single PX4 ULog adapter that converts
a ``.ulg`` flight log into the time series of ``VehicleState``
records the Ghost closed-loop pipeline consumes. Future adapters
(ROSBag, EuRoC MAV) follow the same shape.

Honest scope (paper §8.7): the parser and the topic mapping are
implemented and unit-tested with synthetic ULog fixtures; an
end-to-end run on a real flight log with an independent ground
truth is the v0.3.0 deliverable.
"""

from __future__ import annotations

from .px4_ulog import (
    ULogParseError,
    ULogPoseSample,
    ULogTopicNames,
    parse_ulog_pose_samples,
)

__all__ = [
    "ULogParseError",
    "ULogPoseSample",
    "ULogTopicNames",
    "parse_ulog_pose_samples",
]
