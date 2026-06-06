"""Composición y envejecimiento de estimaciones.

Implementa `docs/specs/uncertainty.md` §4 (envejecimiento) y §6.1 (composición
de validity). Las inflaciones de §5 viven en `inflation.py`; el envelope
nominal vive en `types.NominalEnvelope`.

Composición de covarianzas (§6.4 — Kalman update, transformación lineal con
jacobiana) NO vive aquí: depende del fusor concreto (EKF en Fase 3). Este
módulo cubre solo las reglas independientes de algoritmo: `compose_validity`,
`age_ns`, `downgrade_by_age`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, TypeVar

from .types import Validity

if TYPE_CHECKING:
    from .estimate import Estimate

T = TypeVar("T")

# Section 4: STALE if age is between 1x and 3x max_age_ns; INVALID if > 3x.
_STALE_MAX_AGE_MULTIPLIER: int = 3


def compose_validity(*validities: Validity) -> Validity:
    """Composición sin upgrade silencioso (uncertainty.md §6.1).

    ``out.validity = min(in_a.validity, in_b.validity, ...)``.

    Implementado como ``min`` sobre `Validity` (que es `IntEnum` con orden
    ``VALID > DEGRADED > STALE > INVALID``), lo cual devuelve la más restrictiva.

    Raises:
        ValueError: si no se pasa ningún input. El contrato del fusor exige al
            menos un input; composición vacía es bug del caller.
    """
    if not validities:
        raise ValueError("compose_validity requiere al menos un input (uncertainty.md §6)")
    return min(validities)


def age_ns(estimate: Estimate[T], now_ns: int) -> int:
    """Edad de un `Estimate` respecto a `now_ns` (uncertainty.md §4).

    Devuelve ``now_ns - estimate.stamp_sim_ns``. No corrige edades negativas;
    si ``now_ns < estimate.stamp_sim_ns`` el caller tiene un problema de
    sincronización que no le toca a esta función arreglar silenciosamente.
    """
    return now_ns - estimate.stamp_sim_ns


def downgrade_by_age(
    estimate: Estimate[T],
    now_ns: int,
    max_age_ns: int,
) -> Estimate[T]:
    """Aplica las reglas de envejecimiento de uncertainty.md §4.

    ``age = now_ns - estimate.stamp_sim_ns``.

    - ``age ≤ max_age_ns``: sin cambio.
    - ``max_age_ns < age ≤ 3 · max_age_ns``: downgrade a ``STALE``
      (clipeado al `validity` actual: nunca *upgrade*).
    - ``age > 3 · max_age_ns``: downgrade a ``INVALID``.

    La inflación de covarianza es responsabilidad del caller (típicamente
    `inflate_stale` aplicado a `estimate.covariance` antes o después de este
    downgrade). El spec §3.10 invariante de consistencia validity↔envelope
    NO se verifica aquí porque el estimado degradado es derivado, no
    declaración de productor: usamos `dataclasses.replace` que pasa por
    `__post_init__` (checks estructurales) pero no por `make_estimate`
    (que requiere envelope).

    Returns:
        Un nuevo `Estimate` con `validity` ajustado. Los demás campos se
        preservan (covarianza incluida; inflarla es trabajo del caller).
    """
    if max_age_ns <= 0:
        raise ValueError(f"downgrade_by_age: max_age_ns debe ser > 0; recibido {max_age_ns}")

    age = age_ns(estimate, now_ns)
    if age < 0:
        # Reloj retrocedió, o stamp en el futuro. No hacemos magia.
        raise ValueError(
            f"downgrade_by_age: age={age} ns < 0; estimate.stamp_sim_ns="
            f"{estimate.stamp_sim_ns}, now_ns={now_ns}"
        )

    if age <= max_age_ns:
        return estimate

    new_validity: Validity
    if age <= _STALE_MAX_AGE_MULTIPLIER * max_age_ns:
        new_validity = Validity.STALE
    else:
        new_validity = Validity.INVALID

    # Nunca subir el validity. Si ya era peor, mantener el peor (composición §6.1).
    final_validity = min(estimate.validity, new_validity)
    if final_validity == estimate.validity:
        return estimate

    return replace(estimate, validity=final_validity)


__all__ = ["age_ns", "compose_validity", "downgrade_by_age"]
