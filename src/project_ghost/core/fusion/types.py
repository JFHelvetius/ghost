"""Sensor-to-belief fusion emission types (ADR-0028).

Stdlib only para el encoding canónico. Frozen, pure data,
content-addressed por construcción.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from project_ghost.state.messages import VehicleState

if TYPE_CHECKING:
    from project_ghost.hal.messages.sensors import SensorSample


FUSION_PROTOCOL_VERSION: Final[int] = 1

_TAXONOMY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
_TAXONOMY_MAX_LEN: Final[int] = 64
_SHA256_HEX_LEN: Final[int] = 64
_HEX_CHARS: Final[frozenset[str]] = frozenset("0123456789abcdef")


def _validate_taxonomy(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(
            f"{field} must be str; got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{field} cannot be empty")
    if len(value) > _TAXONOMY_MAX_LEN:
        raise ValueError(
            f"{field} must be <= {_TAXONOMY_MAX_LEN} chars; got "
            f"len={len(value)}"
        )
    if not _TAXONOMY_PATTERN.match(value):
        raise ValueError(
            f"{field} must match {_TAXONOMY_PATTERN.pattern!r}; got "
            f"{value!r}"
        )


def _validate_sha256_hex(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(
            f"{field} must be str; got {type(value).__name__}"
        )
    if len(value) != _SHA256_HEX_LEN:
        raise ValueError(
            f"{field} must be {_SHA256_HEX_LEN} hex chars; got "
            f"len={len(value)}"
        )
    if not all(c in _HEX_CHARS for c in value):
        raise ValueError(
            f"{field} must be lowercase hex; got {value!r}"
        )


@dataclass(frozen=True)
class FusionInput:
    """Bundle de inputs que el ``SensorFusionPolicy`` ve para producir
    el siguiente belief.

    Auto-contenido (no holds references mutable) para que
    ``policy.fuse`` sea pure: mismo input → mismo result.

    ``sensor_samples`` puede ser vacío para policies oracle que
    ignoran sensores (e.g. ``LinearMotionOracleFusionPolicy``).
    Estimadores reales (KF, factor graph) lo consumirán.

    ``prior_belief_stamp_sim_ns`` es ``None`` en la primera fusión
    del run (cold start); de otro modo debe ser ``< target_stamp_sim_ns``
    (la fusión avanza temporalmente, no rewrite history).
    """

    sensor_samples: tuple[SensorSample[Any], ...]
    prior_belief_stamp_sim_ns: int | None
    target_stamp_sim_ns: int
    schema_version: int = FUSION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.sensor_samples, tuple):
            raise TypeError(
                f"sensor_samples must be tuple; got "
                f"{type(self.sensor_samples).__name__}"
            )
        if self.target_stamp_sim_ns < 0:
            raise ValueError(
                f"target_stamp_sim_ns must be >= 0; got "
                f"{self.target_stamp_sim_ns}"
            )
        if self.prior_belief_stamp_sim_ns is not None:
            if self.prior_belief_stamp_sim_ns < 0:
                raise ValueError(
                    f"prior_belief_stamp_sim_ns must be >= 0 when not "
                    f"None; got {self.prior_belief_stamp_sim_ns}"
                )
            if (
                self.prior_belief_stamp_sim_ns
                >= self.target_stamp_sim_ns
            ):
                raise ValueError(
                    f"prior_belief_stamp_sim_ns "
                    f"({self.prior_belief_stamp_sim_ns}) must be < "
                    f"target_stamp_sim_ns ({self.target_stamp_sim_ns})"
                )
        if self.schema_version != FUSION_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {FUSION_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )


def compute_fusion_input_sha256(fusion_input: FusionInput) -> str:
    """SHA-256 hex canónico del ``FusionInput``.

    Canonical: ``sort_keys=True``, ``ensure_ascii=False``,
    ``separators=(",", ":")``. Cross-process byte-identical para
    inputs iguales (mismo posture que ADR-0022).

    Useful for callers verifying ``FusionResult.fusion_input_sha256``
    matches the input that produced the result.

    The import of ``to_json_safe`` is deferred to avoid a circular
    import: ``core.fusion.types`` must not import from
    ``telemetry.*`` at module level (architectural rule).
    """
    from project_ghost.telemetry.serialization import to_json_safe  # noqa: PLC0415

    payload = to_json_safe(fusion_input)
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FusionResult:
    """Envelope que ata el belief producido al hash de su input.

    El ``belief`` viaja inline para auto-contención auditable.
    ``fusion_input_sha256`` es la identidad content-addressed del
    input productor — dos results con el mismo hash usaron el mismo
    input bit-a-bit.

    Stamps:

    - ``belief.stamp_sim_ns`` debe matchear
      ``target_stamp_sim_ns`` del FusionInput productor. El stamp no
      se duplica en el record (queda en el input via hash); el adapter
      usa ``belief.stamp_sim_ns`` como ``log_time``.
    """

    belief: VehicleState
    fusion_input_sha256: str
    fusion_policy_id: str
    schema_version: int = FUSION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.belief, VehicleState):
            raise TypeError(
                f"belief must be VehicleState; got "
                f"{type(self.belief).__name__}"
            )
        _validate_sha256_hex(
            self.fusion_input_sha256, field="fusion_input_sha256"
        )
        _validate_taxonomy(
            self.fusion_policy_id, field="fusion_policy_id"
        )
        if self.schema_version != FUSION_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be {FUSION_PROTOCOL_VERSION}; "
                f"got {self.schema_version}"
            )


__all__ = [
    "FUSION_PROTOCOL_VERSION",
    "FusionInput",
    "FusionResult",
    "compute_fusion_input_sha256",
]
