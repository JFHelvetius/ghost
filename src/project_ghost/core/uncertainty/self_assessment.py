"""Belief self-assessment runtime (ADR-0020 core).

Stdlib-only (excepto el reuso de ``numpy`` para leer la covarianza ya
materializada en ``VehicleState``, que es la convención del proyecto en
``state.messages``). Pure. Deterministic. Observational.

El agente lee su propio ``VehicleState`` y emite una afirmación
clasificatoria — un ``BeliefSelfAssessment`` — sobre qué afirma saber
por-eje (X/Y/Z) en posición, velocidad y orientación. La clasificación
es discreta (KNOWN / UNCERTAIN / UNKNOWN), rule-based, contra umbrales
explícitos que el operador escoge y que viajan auto-contenidos dentro
del assessment para auditabilidad total.

**Honesty framing.** Este módulo NO:

- infiere causalidad,
- afirma "calibración",
- detecta anomalías o outliers,
- corre tests estadísticos,
- toma decisiones de control,
- penaliza data stale (timestamp viejo),
- evalúa sensor health o perception mode (esos son canales aparte).

Sólo aplica reglas determinísticas contra umbrales para clasificar el
conocimiento declarado, con provenance content-addressed vía SHA-256 de
los thresholds. El operador interpreta.

**Block-to-covariance mapping (ADR-0005 / ``NavigationState``):**

- ``covariance_15x15[0:3, 0:3]`` → posición ENU.
- ``covariance_15x15[3:6, 3:6]`` → velocidad world.
- ``covariance_15x15[6:9, 6:9]`` → orientación tangent (axis-angle).
- ``covariance_15x15[9:12, 9:12]`` → accel bias (NO evaluado en V1).
- ``covariance_15x15[12:15, 12:15]`` → gyro bias (NO evaluado en V1).

Convenciones de frontera frozen:

- ``std == known_threshold`` → ``KNOWN`` (resolución hacia mejor).
- ``std == unknown_threshold`` → ``UNKNOWN`` (resolución hacia peor).
- Covarianza ``None`` → todos los stds son ``None``, todos los levels
  son ``UNKNOWN`` (el agente reconoce abiertamente que carece de
  representación de incertidumbre para esta belief).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import numpy as np  # noqa: TC002  (runtime use in _diagonal_std)

if TYPE_CHECKING:
    from project_ghost.state.messages import VehicleState


SELF_ASSESSMENT_PROTOCOL_VERSION: Final[int] = 1
_SHA256_HEX_LEN: Final[int] = 64


# Block diagonal indices for the 15x15 covariance.
_POSITION_DIAG_INDICES: Final[tuple[int, int, int]] = (0, 1, 2)
_VELOCITY_DIAG_INDICES: Final[tuple[int, int, int]] = (3, 4, 5)
_ORIENTATION_DIAG_INDICES: Final[tuple[int, int, int]] = (6, 7, 8)


class SelfAssessmentLevel(StrEnum):
    """Closed catalog of self-assessment categorical levels.

    Ordered KNOWN < UNCERTAIN < UNKNOWN. ``worst_of`` derives the
    block / overall level from per-axis levels by taking the max in
    this ordering.

    Modificar el catálogo (añadir / renombrar / borrar) requiere bump
    de ``SELF_ASSESSMENT_PROTOCOL_VERSION`` y ADR explícito.
    """

    KNOWN = "known"
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"


_LEVEL_ORDER: Final[dict[SelfAssessmentLevel, int]] = {
    SelfAssessmentLevel.KNOWN: 0,
    SelfAssessmentLevel.UNCERTAIN: 1,
    SelfAssessmentLevel.UNKNOWN: 2,
}


def _worst_of(*levels: SelfAssessmentLevel) -> SelfAssessmentLevel:
    """Return the worst (highest-ordered) level among ``levels``.

    Empty input raises ``ValueError`` — the caller must always provide
    at least one level (cf. block reduction always uses 3 axes).
    """
    if not levels:
        raise ValueError("_worst_of: at least one level required")
    return max(levels, key=lambda lv: _LEVEL_ORDER[lv])


# ---------------------------------------------------------------------------
# AssessmentThresholds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssessmentThresholds:
    """Umbrales que el operador escoge para clasificar el conocimiento
    declarado por el agente.

    Seis números, todos positivos y finitos, tales que para cada bloque
    el umbral ``known`` es estrictamente menor que el ``unknown``
    (regiones no se solapan, frontera bien definida).

    El proyecto NO impone valores default. La elección de umbrales es
    decisión del experimento; los umbrales viajan dentro del
    ``BeliefSelfAssessment`` que producen para que toda lectura sea
    reproducible.
    """

    position_known_std_m: float
    position_unknown_std_m: float
    velocity_known_std_mps: float
    velocity_unknown_std_mps: float
    orientation_known_std_rad: float
    orientation_unknown_std_rad: float
    schema_version: int = SELF_ASSESSMENT_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        pairs = (
            (
                "position",
                self.position_known_std_m,
                self.position_unknown_std_m,
            ),
            (
                "velocity",
                self.velocity_known_std_mps,
                self.velocity_unknown_std_mps,
            ),
            (
                "orientation",
                self.orientation_known_std_rad,
                self.orientation_unknown_std_rad,
            ),
        )
        for block, known, unknown in pairs:
            if not isinstance(known, (int, float)) or not isinstance(
                unknown, (int, float)
            ):
                raise TypeError(
                    f"AssessmentThresholds: {block} thresholds must be "
                    f"numeric; got {type(known).__name__} / "
                    f"{type(unknown).__name__}"
                )
            if not math.isfinite(float(known)) or not math.isfinite(
                float(unknown)
            ):
                raise ValueError(
                    f"AssessmentThresholds: {block} thresholds must be "
                    f"finite; got known={known} unknown={unknown}"
                )
            if known <= 0.0 or unknown <= 0.0:
                raise ValueError(
                    f"AssessmentThresholds: {block} thresholds must be "
                    f"> 0; got known={known} unknown={unknown}"
                )
            if not known < unknown:
                raise ValueError(
                    f"AssessmentThresholds: {block} known threshold "
                    f"must be < unknown; got known={known} "
                    f"unknown={unknown}"
                )
        if self.schema_version != SELF_ASSESSMENT_PROTOCOL_VERSION:
            raise ValueError(
                f"AssessmentThresholds: schema_version must be "
                f"{SELF_ASSESSMENT_PROTOCOL_VERSION}; got "
                f"{self.schema_version}"
            )


def thresholds_sha256(thresholds: AssessmentThresholds) -> str:
    """Return SHA-256 hex digest of the canonical JSON of ``thresholds``.

    Canonical: ``sort_keys=True``, ``ensure_ascii=False``,
    ``separators=(",", ":")`` (compact, no whitespace). The hash is the
    content-addressed identity of an `AssessmentThresholds` value.
    Two configurations that produce the same hash are bit-equal.
    """
    payload = dataclasses.asdict(thresholds)
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# BeliefSelfAssessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BeliefSelfAssessment:
    """Afirmación clasificatoria del agente sobre su propio belief.

    Por cada eje de cada bloque (posición / velocidad / orientación):
    el std declarado (``None`` si no hay covarianza) y la clasificación
    contra los umbrales. Cada bloque tiene un ``overall_level`` (worst
    de sus tres axes). El ``overall_level`` global es worst de los tres
    bloques.

    ``thresholds_used`` viaja inline para auto-contención auditable.
    ``thresholds_sha256`` es la identidad content-addressed: dos
    assessments con el mismo hash usaron los mismos umbrales bit-a-bit.

    ``belief_stamp_sim_ns`` es el ``stamp_sim_ns`` del ``VehicleState``
    que produjo este assessment — el adapter usa este timestamp como
    ``log_time`` de MCAP (ADR-0002).
    """

    belief_stamp_sim_ns: int

    # Per-axis std declarado (None si covariance_15x15 is None).
    position_axis_x_std_m: float | None
    position_axis_y_std_m: float | None
    position_axis_z_std_m: float | None
    velocity_axis_x_std_mps: float | None
    velocity_axis_y_std_mps: float | None
    velocity_axis_z_std_mps: float | None
    orientation_axis_x_std_rad: float | None
    orientation_axis_y_std_rad: float | None
    orientation_axis_z_std_rad: float | None

    # Per-axis levels.
    position_axis_x_level: SelfAssessmentLevel
    position_axis_y_level: SelfAssessmentLevel
    position_axis_z_level: SelfAssessmentLevel
    velocity_axis_x_level: SelfAssessmentLevel
    velocity_axis_y_level: SelfAssessmentLevel
    velocity_axis_z_level: SelfAssessmentLevel
    orientation_axis_x_level: SelfAssessmentLevel
    orientation_axis_y_level: SelfAssessmentLevel
    orientation_axis_z_level: SelfAssessmentLevel

    # Per-block overall levels.
    position_overall_level: SelfAssessmentLevel
    velocity_overall_level: SelfAssessmentLevel
    orientation_overall_level: SelfAssessmentLevel

    # Global overall.
    overall_level: SelfAssessmentLevel

    # Provenance.
    thresholds_used: AssessmentThresholds
    thresholds_sha256: str

    # Whether the source state's covariance_15x15 was present at all.
    # Convenience for downstream filtering (e.g. ignore records where
    # the agent simply had no covariance to assess).
    covariance_available: bool

    schema_version: int = SELF_ASSESSMENT_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.belief_stamp_sim_ns < 0:
            raise ValueError(
                f"belief_stamp_sim_ns must be >= 0; got "
                f"{self.belief_stamp_sim_ns}"
            )
        # Hash format check: 64 lowercase hex chars.
        if not isinstance(self.thresholds_sha256, str):
            raise TypeError(
                f"thresholds_sha256 must be str; got "
                f"{type(self.thresholds_sha256).__name__}"
            )
        if len(self.thresholds_sha256) != _SHA256_HEX_LEN:
            raise ValueError(
                f"thresholds_sha256 must be {_SHA256_HEX_LEN} hex chars; "
                f"got len={len(self.thresholds_sha256)}"
            )
        for c in self.thresholds_sha256:
            if c not in "0123456789abcdef":
                raise ValueError(
                    f"thresholds_sha256 must be lowercase hex; got "
                    f"{self.thresholds_sha256!r}"
                )
        if self.schema_version != SELF_ASSESSMENT_PROTOCOL_VERSION:
            raise ValueError(
                f"schema_version must be "
                f"{SELF_ASSESSMENT_PROTOCOL_VERSION}; got "
                f"{self.schema_version}"
            )


# ---------------------------------------------------------------------------
# assess_belief
# ---------------------------------------------------------------------------


def _classify_axis(
    std: float | None,
    known_threshold: float,
    unknown_threshold: float,
) -> SelfAssessmentLevel:
    """Classify a single axis std against its block thresholds.

    Frontiers (frozen):
    - ``std == known_threshold`` → KNOWN (best resolution).
    - ``std == unknown_threshold`` → UNKNOWN (worst resolution).
    - ``std is None`` or non-finite → UNKNOWN.
    """
    if std is None:
        return SelfAssessmentLevel.UNKNOWN
    if not math.isfinite(std):
        return SelfAssessmentLevel.UNKNOWN
    if std <= known_threshold:
        return SelfAssessmentLevel.KNOWN
    if std >= unknown_threshold:
        return SelfAssessmentLevel.UNKNOWN
    return SelfAssessmentLevel.UNCERTAIN


def _diagonal_std(
    cov: np.ndarray | None, idx: int
) -> float | None:
    """Return ``sqrt(cov[idx, idx])`` or ``None`` if cov is None or the
    diagonal value is negative / non-finite (defensive — PSD covariance
    won't produce negatives, but we guard so downstream classification
    has a clean None signal)."""
    if cov is None:
        return None
    value = float(cov[idx, idx])
    if not math.isfinite(value) or value < 0.0:
        return None
    return math.sqrt(value)


def assess_belief(
    state: VehicleState,
    thresholds: AssessmentThresholds,
) -> BeliefSelfAssessment:
    """Produce a ``BeliefSelfAssessment`` of ``state`` against ``thresholds``.

    Pure function: no clock reads, no random, no I/O, no thread-local
    state. Same ``(state, thresholds)`` → same assessment bit-a-bit
    tras serialización.

    Si ``state.nav.covariance_15x15 is None``, todos los stds resultantes
    son ``None`` y todos los levels son ``UNKNOWN`` — el agente
    reconoce abiertamente que no tiene representación de incertidumbre.
    """
    cov = state.nav.covariance_15x15
    covariance_available = cov is not None

    # Position block (axes 0, 1, 2).
    pos_std_x = _diagonal_std(cov, _POSITION_DIAG_INDICES[0])
    pos_std_y = _diagonal_std(cov, _POSITION_DIAG_INDICES[1])
    pos_std_z = _diagonal_std(cov, _POSITION_DIAG_INDICES[2])
    pos_lvl_x = _classify_axis(
        pos_std_x,
        thresholds.position_known_std_m,
        thresholds.position_unknown_std_m,
    )
    pos_lvl_y = _classify_axis(
        pos_std_y,
        thresholds.position_known_std_m,
        thresholds.position_unknown_std_m,
    )
    pos_lvl_z = _classify_axis(
        pos_std_z,
        thresholds.position_known_std_m,
        thresholds.position_unknown_std_m,
    )

    # Velocity block (axes 3, 4, 5).
    vel_std_x = _diagonal_std(cov, _VELOCITY_DIAG_INDICES[0])
    vel_std_y = _diagonal_std(cov, _VELOCITY_DIAG_INDICES[1])
    vel_std_z = _diagonal_std(cov, _VELOCITY_DIAG_INDICES[2])
    vel_lvl_x = _classify_axis(
        vel_std_x,
        thresholds.velocity_known_std_mps,
        thresholds.velocity_unknown_std_mps,
    )
    vel_lvl_y = _classify_axis(
        vel_std_y,
        thresholds.velocity_known_std_mps,
        thresholds.velocity_unknown_std_mps,
    )
    vel_lvl_z = _classify_axis(
        vel_std_z,
        thresholds.velocity_known_std_mps,
        thresholds.velocity_unknown_std_mps,
    )

    # Orientation block (axes 6, 7, 8).
    ori_std_x = _diagonal_std(cov, _ORIENTATION_DIAG_INDICES[0])
    ori_std_y = _diagonal_std(cov, _ORIENTATION_DIAG_INDICES[1])
    ori_std_z = _diagonal_std(cov, _ORIENTATION_DIAG_INDICES[2])
    ori_lvl_x = _classify_axis(
        ori_std_x,
        thresholds.orientation_known_std_rad,
        thresholds.orientation_unknown_std_rad,
    )
    ori_lvl_y = _classify_axis(
        ori_std_y,
        thresholds.orientation_known_std_rad,
        thresholds.orientation_unknown_std_rad,
    )
    ori_lvl_z = _classify_axis(
        ori_std_z,
        thresholds.orientation_known_std_rad,
        thresholds.orientation_unknown_std_rad,
    )

    # Block overall: worst of three axes.
    pos_overall = _worst_of(pos_lvl_x, pos_lvl_y, pos_lvl_z)
    vel_overall = _worst_of(vel_lvl_x, vel_lvl_y, vel_lvl_z)
    ori_overall = _worst_of(ori_lvl_x, ori_lvl_y, ori_lvl_z)

    # Global overall: worst of three blocks.
    overall = _worst_of(pos_overall, vel_overall, ori_overall)

    thresh_hash = thresholds_sha256(thresholds)

    return BeliefSelfAssessment(
        belief_stamp_sim_ns=state.stamp_sim_ns,
        position_axis_x_std_m=pos_std_x,
        position_axis_y_std_m=pos_std_y,
        position_axis_z_std_m=pos_std_z,
        velocity_axis_x_std_mps=vel_std_x,
        velocity_axis_y_std_mps=vel_std_y,
        velocity_axis_z_std_mps=vel_std_z,
        orientation_axis_x_std_rad=ori_std_x,
        orientation_axis_y_std_rad=ori_std_y,
        orientation_axis_z_std_rad=ori_std_z,
        position_axis_x_level=pos_lvl_x,
        position_axis_y_level=pos_lvl_y,
        position_axis_z_level=pos_lvl_z,
        velocity_axis_x_level=vel_lvl_x,
        velocity_axis_y_level=vel_lvl_y,
        velocity_axis_z_level=vel_lvl_z,
        orientation_axis_x_level=ori_lvl_x,
        orientation_axis_y_level=ori_lvl_y,
        orientation_axis_z_level=ori_lvl_z,
        position_overall_level=pos_overall,
        velocity_overall_level=vel_overall,
        orientation_overall_level=ori_overall,
        overall_level=overall,
        thresholds_used=thresholds,
        thresholds_sha256=thresh_hash,
        covariance_available=covariance_available,
    )


__all__ = [
    "SELF_ASSESSMENT_PROTOCOL_VERSION",
    "AssessmentThresholds",
    "BeliefSelfAssessment",
    "SelfAssessmentLevel",
    "assess_belief",
    "thresholds_sha256",
]
