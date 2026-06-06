"""`Estimate[T]` y su constructor `make_estimate`.

Implementa los invariantes de `docs/specs/uncertainty.md` §3:

1. Wrapping obligatorio — `Estimate[T]` es la única salida válida (lo enforza
   la convención de los productores; no es un check de runtime).
2. Sealing recursivo de arrays — §3.2; ver `sealing.py`.
3. Covarianza simétrica — §3.3.
4. Covarianza semidefinida positiva — §3.4.
5. Stamp del productor — diseño, no check.
6. ``VALID`` exige covarianza nominal — §3.6 / §3.10.
7. Composición sin upgrade silencioso — ver `composition.py`.
8. Groundtruth tiene covariance None — §3.8.
9. ``confidence`` no reemplaza covarianza — diseño, no check.
10. Validity↔covariance consistente — §3.10; verificado en `make_estimate`
    cuando se provee `nominal_envelope`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

import numpy as np

from .sealing import assert_all_sealed, seal_recursive
from .types import EstimateSource, NominalEnvelope, Validity

T = TypeVar("T")

# Tolerancias documentadas en uncertainty.md §3.
_SYMMETRY_TOLERANCE: float = 1e-9
_PSD_EPS: float = 1e-12
_COVARIANCE_NDIM: int = 2


@dataclass(frozen=True)
class Estimate(Generic[T]):
    """Envelope de incertidumbre para una estimación que cruza un módulo.

    Construir vía `make_estimate`, no instanciar directamente: la fábrica aplica
    sealing recursivo y la verificación validity↔covariance que el dataclass
    por sí solo no puede hacer (necesita el envelope nominal del productor).

    El `__post_init__` mantiene los checks estructurales (simetría, PSD,
    groundtruth-iff-none, dtype, shape) para que cualquier instanciación —
    incluyendo `dataclasses.replace` desde helpers como `downgrade_by_age` —
    los respete.
    """

    value: T
    covariance: np.ndarray | None
    validity: Validity
    stamp_sim_ns: int
    source: EstimateSource
    confidence: float | None = None

    def __post_init__(self) -> None:
        self._check_groundtruth_iff_covariance_none()
        if self.covariance is not None:
            self._check_and_normalize_covariance()
        self._check_confidence()
        self._check_stamp()

    # ------------------------------------------------------------------
    # Checks estructurales (§3.3, §3.4, §3.8)
    # ------------------------------------------------------------------

    def _check_groundtruth_iff_covariance_none(self) -> None:
        is_gt = self.source.kind == "groundtruth"
        cov_is_none = self.covariance is None
        if is_gt and not cov_is_none:
            raise ValueError(
                "Estimate: source.kind='groundtruth' exige covariance=None (uncertainty.md §3.8)"
            )
        if cov_is_none and not is_gt:
            raise ValueError(
                f"Estimate: source.kind={self.source.kind!r} con covariance=None "
                "no es legal; solo groundtruth puede omitir covarianza "
                "(uncertainty.md §3.8)"
            )

    def _check_and_normalize_covariance(self) -> None:
        cov = self.covariance
        assert cov is not None  # mypy/narrowing; verificado en _check_groundtruth_iff_*
        if cov.ndim != _COVARIANCE_NDIM:
            raise ValueError(f"Estimate.covariance debe ser 2-D; recibido ndim={cov.ndim}")
        if cov.shape[0] != cov.shape[1]:
            raise ValueError(f"Estimate.covariance debe ser cuadrada; recibido shape={cov.shape}")
        if cov.dtype != np.float64:
            raise ValueError(f"Estimate.covariance debe ser float64; recibido dtype={cov.dtype}")

        # Simetría (§3.3): si la asimetría está dentro de tolerancia,
        # simetrizamos en una copia y la reemplazamos; si no, rechazamos.
        diff_norm = float(np.linalg.norm(cov - cov.T, ord="fro"))
        cov_norm = float(np.linalg.norm(cov, ord="fro"))
        if cov_norm == 0.0:
            # Covarianza cero: simétrica trivialmente, PSD trivialmente.
            sym = cov
        elif diff_norm / cov_norm < _SYMMETRY_TOLERANCE:
            # Dentro de tolerancia: simetrizamos.
            sym = 0.5 * (cov + cov.T)
        else:
            raise ValueError(
                f"Estimate.covariance asimétrica fuera de tolerancia: "
                f"‖C-Cᵀ‖_F/‖C‖_F={diff_norm / cov_norm:.3e} ≥ {_SYMMETRY_TOLERANCE:.0e} "
                "(uncertainty.md §3.3)"
            )

        # PSD (§3.4): autovalor mínimo ≥ -eps_psd.
        # `eigvalsh` para simétricas es más estable y barato que `eigvals`.
        min_eig = float(np.min(np.linalg.eigvalsh(sym)))
        if min_eig < -_PSD_EPS:
            raise ValueError(
                f"Estimate.covariance no es PSD: min(eig)={min_eig:.3e} < -{_PSD_EPS:.0e} "
                "(uncertainty.md §3.4)"
            )

        # Reemplazamos la covarianza simétrica/normalizada en la frozen
        # dataclass.
        object.__setattr__(self, "covariance", sym)

    def _check_confidence(self) -> None:
        if self.confidence is None:
            return
        c = float(self.confidence)
        if not (0.0 <= c <= 1.0):
            raise ValueError(f"Estimate.confidence debe estar en [0, 1]; recibido {c}")

    def _check_stamp(self) -> None:
        if self.stamp_sim_ns < 0:
            raise ValueError(f"Estimate.stamp_sim_ns debe ser ≥ 0; recibido {self.stamp_sim_ns}")


# ---------------------------------------------------------------------------
# Factory (uncertainty.md §8)
# ---------------------------------------------------------------------------


def make_estimate(
    value: T,
    *,
    covariance: np.ndarray | None,
    validity: Validity,
    stamp_sim_ns: int,
    source: EstimateSource,
    confidence: float | None = None,
    nominal_envelope: NominalEnvelope | None = None,
) -> Estimate[T]:
    """Construye `Estimate[T]` aplicando sealing y todas las validaciones de §3.

    Pasos:

    1. Construye el `Estimate` (lo cual dispara `__post_init__`: groundtruth-iff,
       simetría, PSD, dtype/shape, confidence en rango, stamp ≥ 0).
    2. Aplica `seal_recursive` sobre el objeto completo.
    3. Verifica con `assert_all_sealed` que no quede ningún `ndarray` escribible.
    4. Si se provee `nominal_envelope`, verifica la consistencia
       validity↔covariance per §3.10:

       - ``VALID`` → covariance debe estar **dentro** del envelope.
       - ``DEGRADED`` y ``STALE`` → covariance debe estar **fuera** (inflada).
       - ``INVALID`` → no se verifica.

    Productores deberían siempre pasar `nominal_envelope`. Helpers internos
    (composición, downgrade por edad, transformaciones de marco) pueden omitirlo
    porque la covarianza resultante no es declaración de productor sino
    derivada.

    Raises:
        ValueError: si cualquier invariante de §3 falla.
        TypeError: si `seal_recursive` encuentra una colección inestable.
    """
    estimate = Estimate(
        value=value,
        covariance=covariance,
        validity=validity,
        stamp_sim_ns=stamp_sim_ns,
        source=source,
        confidence=confidence,
    )

    # Sealing recursivo (§3.2) — sella `value` y `covariance` (si no es None).
    seal_recursive(estimate.value)
    if estimate.covariance is not None:
        seal_recursive(estimate.covariance)
    assert_all_sealed(estimate.value)
    if estimate.covariance is not None:
        assert_all_sealed(estimate.covariance)

    # Consistencia validity↔covariance (§3.10) cuando hay envelope.
    if nominal_envelope is not None and estimate.covariance is not None:
        _check_validity_envelope_consistency(
            estimate.covariance, estimate.validity, nominal_envelope, estimate.source
        )

    return estimate


def _check_validity_envelope_consistency(
    covariance: np.ndarray,
    validity: Validity,
    envelope: NominalEnvelope,
    source: EstimateSource,
) -> None:
    """§3.10: VALID dentro de envelope, DEGRADED/STALE fuera, INVALID sin check."""
    if validity == Validity.INVALID:
        return

    inside = envelope.contains(covariance)

    if validity == Validity.VALID and not inside:
        raise ValueError(
            f"Estimate de {source.module_id!r}: validity=VALID exige covarianza "
            f"dentro del envelope nominal; max_diag={envelope.max_diag}, "
            f"diag(C)={np.diag(covariance)}, trace(C)={float(np.trace(covariance)):.3e}, "
            f"max_trace={envelope.max_trace:.3e} (uncertainty.md §3.10)"
        )
    if validity in (Validity.DEGRADED, Validity.STALE) and inside:
        raise ValueError(
            f"Estimate de {source.module_id!r}: validity={validity.name} exige "
            "covarianza inflada (fuera del envelope nominal); recibida dentro del "
            "envelope. Aplicar `inflate_*` antes de emitir (uncertainty.md §3.10)"
        )


__all__ = ["Estimate", "make_estimate"]
