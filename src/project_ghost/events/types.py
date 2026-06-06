"""Tipos del Event System — `Event`, `EventSeverity`, `EventType`.

Schema canónico per `docs/specs/events.md` §3 y ADR-0006. Solo el dataclass
frozen `Event` y sus enums asociados; la mecánica del bus vive en `bus.py`.

Alcance T5.a:

- Estructura del evento completa per spec (incluye `correlation_id`,
  `schema_version`, `payload` como `Mapping`).
- Catálogo cerrado de 19 `EventType` listados en §3 del spec.
- Validación por `__post_init__`: `sequence >= 0` (lo asigna el bus,
  el cliente pasa 0), `stamp_sim_ns >= 0`, `stamp_wall_ns >= 0`,
  `payload` ya inmutable cuando se pasa (responsabilidad del publisher),
  `schema_version >= 1`, `source` no-vacío.

Fuera de alcance T5.a:

- Generación de `correlation_id` con `uuid7()` (helper futuro, T5.b).
- Roundtrip Protobuf (T2 cuando llegue; lo importante aquí es que la
  forma Python sea estable).
"""

from __future__ import annotations

# `Mapping` se importa a runtime (no en TYPE_CHECKING) para que
# `typing.get_type_hints(Event)` pueda resolver `payload: Mapping[str, Any]`
# — `telemetry.serialization.from_json_dict` lo necesita para round-trip.
from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any


class EventSeverity(IntEnum):
    """Severidad del evento (clock.md §9).

    El orden numérico coincide con la criticidad: mayor valor = más crítico.
    Usable directamente en comparaciones (`ev.severity >= EventSeverity.WARN`).
    """

    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40
    CRITICAL = 50


class EventType(StrEnum):
    """Catálogo cerrado de tipos de evento per `events.md` §3.

    Modificar este catálogo requiere ADR (regla análoga a ADR-0010 para
    `PerceptionMode`). Crear tipos ad-hoc rompe la semántica del sistema.
    """

    # Lifecycle
    ARMED = "armed"
    DISARMED = "disarmed"
    TAKEOFF = "takeoff"
    LANDED = "landed"
    KILL = "kill"
    # Mission
    MISSION_START = "mission_start"
    MISSION_END = "mission_end"
    WAYPOINT_REACHED = "waypoint_reached"
    GOAL_UPDATED = "goal_updated"
    # Safety
    SAFETY_VIOLATION = "safety_violation"
    GEOFENCE_BREACH = "geofence_breach"
    COLLISION_WARNING = "collision_warning"
    COLLISION = "collision"
    RECOVERY_TRIGGERED = "recovery_triggered"
    # Sensors / system
    SENSOR_FAULT = "sensor_fault"
    SENSOR_RECOVERED = "sensor_recovered"
    BATTERY_LOW = "battery_low"
    # Infra
    TELEMETRY_BACKPRESSURE = "telemetry_backpressure"
    SCHEDULER_CALLBACK_FAILED = "scheduler_callback_failed"


@dataclass(frozen=True)
class Event:
    """Evento del bus per `events.md` §3.

    Convención: el publisher construye el evento con `sequence=0`; el bus
    sobrescribe ese campo con el siguiente sequence global atómico. Como
    `Event` es frozen, la "sobrescritura" se hace creando un nuevo Event
    con `dataclasses.replace`. El campo `sequence` queda inmutable una vez
    publicado.

    `stamp_sim_ns` viene del `SimClock` del publisher; `stamp_wall_ns` del
    reloj wall (uso solo para diagnóstico cross-reference, no para
    ordenamiento — el orden total se decide por `(stamp_sim_ns, sequence)`
    como dice clock.md §6).

    `payload` es `Mapping[str, Any]` — el publisher debe pasar un mapping
    inmutable (e.g. `MappingProxyType` o un dict que ya no muta). El bus
    no defiende contra mutación post-publish.

    `correlation_id` opcional; usar para encadenar eventos relacionados
    (e.g. `MISSION_START -> WAYPOINT_REACHED * n -> MISSION_END`).
    """

    type: EventType
    severity: EventSeverity
    source: str
    stamp_sim_ns: int
    stamp_wall_ns: int
    sequence: int
    payload: Mapping[str, Any]
    correlation_id: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("Event.source no puede ser vacío")
        if self.stamp_sim_ns < 0:
            raise ValueError(
                f"Event.stamp_sim_ns debe ser >= 0; recibido {self.stamp_sim_ns}"
            )
        if self.stamp_wall_ns < 0:
            raise ValueError(
                f"Event.stamp_wall_ns debe ser >= 0; recibido {self.stamp_wall_ns}"
            )
        if self.sequence < 0:
            raise ValueError(
                f"Event.sequence debe ser >= 0; recibido {self.sequence}. "
                f"Publishers pasan 0; el bus lo sobrescribe."
            )
        if self.schema_version < 1:
            raise ValueError(
                f"Event.schema_version debe ser >= 1; recibido {self.schema_version}"
            )


__all__ = ["Event", "EventSeverity", "EventType"]
