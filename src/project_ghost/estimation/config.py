"""`NoisyGroundTruthConfig` — parámetros de la perturbación + creencia declarada.

Materializa ADR-0015 §1. Frozen dataclass con validación por
constructor; misma posture de validación que el resto de mensajes del
proyecto (`state.messages`, `hal.messages`).

**Decisión clave del ADR.** La covarianza 15x15 es un **parámetro
declarado por el caller**, no una función de los stds de ruido. Esta
clase no infiere covarianza: la valida y la guarda. La validación
(forma, simetría, PSD) reusa las mismas tolerancias que
`NavigationState._validate_covariance` para que el contrato sea
idéntico aguas abajo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np

# Mismas tolerancias que state.messages._validate_covariance para que
# una cov aceptada aquí sea también aceptada por NavigationState al
# emitir el VehicleState.
_COV_DIM: Final[int] = 15
_COV_SYMMETRY_TOL: Final[float] = 1e-9
_COV_PSD_EPS: Final[float] = 1e-12


def _validate_non_negative_std(value: Any, *, name: str) -> None:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} debe ser numérico (int|float); recibido {type(value).__name__}")
    fvalue = float(value)
    if not np.isfinite(fvalue):
        raise ValueError(f"{name} debe ser finito; recibido {value}")
    if fvalue < 0.0:
        raise ValueError(f"{name} debe ser >= 0; recibido {value}")


def _validate_declared_covariance(c: Any, *, name: str) -> None:
    if not isinstance(c, np.ndarray):
        raise TypeError(f"{name} debe ser np.ndarray; recibido {type(c).__name__}")
    if c.shape != (_COV_DIM, _COV_DIM):
        raise TypeError(f"{name} debe tener shape ({_COV_DIM}, {_COV_DIM}); recibido {c.shape}")
    if c.dtype != np.float64:
        raise TypeError(f"{name} debe tener dtype float64; recibido {c.dtype}")
    if not bool(np.all(np.isfinite(c))):
        raise ValueError(f"{name} contiene NaN o Inf")
    asymmetry = float(np.max(np.abs(c - c.T)))
    if asymmetry > _COV_SYMMETRY_TOL:
        raise ValueError(
            f"{name} no es simétrica (max asimetría {asymmetry}, tolerancia {_COV_SYMMETRY_TOL})"
        )
    eigvals = np.linalg.eigvalsh((c + c.T) / 2.0)
    min_eig = float(eigvals.min())
    if min_eig < -_COV_PSD_EPS:
        raise ValueError(f"{name} no es PSD (eigenvalor mínimo {min_eig}, eps {_COV_PSD_EPS})")


@dataclass(frozen=True)
class NoisyGroundTruthConfig:
    """Configuración del `NoisyGroundTruthEstimator` (ADR-0015 §1).

    Los cinco ``*_noise_std_*`` definen el ruido aditivo per-eje. El
    de orientación se interpreta como std del vector tangente
    pequeña-rotación; el resto son aditivos directos al campo
    correspondiente.

    ``declared_covariance_15x15`` es la creencia que el caller decide
    publicar. NO se deriva del ruido. Se valida forma, finitud,
    simetría (tol ``1e-9``) y PSD (eps ``1e-12``) — mismas tolerancias
    que ``state.messages.NavigationState._validate_covariance`` para
    que la cov aceptada aquí pase también el validador aguas abajo.

    ``random_source_label`` determina qué hijo del ``RandomSource``
    parent consume el estimador. Cambiar el label cambia la secuencia
    de ruido pero NO compromete determinismo replay (ADR-0002): mismo
    label + mismo parent seed -> misma secuencia.
    """

    position_noise_std_m: float
    orientation_noise_std_rad: float
    linear_velocity_noise_std_mps: float
    angular_velocity_noise_std_rps: float
    accel_body_noise_std_mps2: float
    declared_covariance_15x15: np.ndarray
    random_source_label: str = "/estimation/noisy_gt"

    def __post_init__(self) -> None:
        _validate_non_negative_std(self.position_noise_std_m, name="position_noise_std_m")
        _validate_non_negative_std(self.orientation_noise_std_rad, name="orientation_noise_std_rad")
        _validate_non_negative_std(
            self.linear_velocity_noise_std_mps,
            name="linear_velocity_noise_std_mps",
        )
        _validate_non_negative_std(
            self.angular_velocity_noise_std_rps,
            name="angular_velocity_noise_std_rps",
        )
        _validate_non_negative_std(self.accel_body_noise_std_mps2, name="accel_body_noise_std_mps2")
        _validate_declared_covariance(
            self.declared_covariance_15x15, name="declared_covariance_15x15"
        )
        if not isinstance(self.random_source_label, str):
            raise TypeError(
                "random_source_label debe ser str; recibido "
                f"{type(self.random_source_label).__name__}"
            )
        if not self.random_source_label.startswith("/"):
            raise ValueError(
                f"random_source_label debe empezar con '/'; recibido {self.random_source_label!r}"
            )
        # Sellar la cov: caller no debe mutarla después de construir el
        # config (ADR-0015: la cov es parámetro declarado, no estado
        # mutable). El estimador hará una copia fresca por VehicleState.
        self.declared_covariance_15x15.setflags(write=False)


__all__ = ["NoisyGroundTruthConfig"]
