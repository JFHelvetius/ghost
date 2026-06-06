"""Modelos de inflación de covarianza.

Implementa `docs/specs/uncertainty.md` §5.1, §5.2, §5.4. Los valores numéricos
defaults son hipótesis (per disclaimer §5); calibración real en U2/U6.

Todas las funciones son **puras**: no mutan inputs, devuelven arrays sellados
(``flags.writeable=False``). El sealing del output permite componerlas en
pipelines sin riesgo de mutación accidental.
"""

from __future__ import annotations

import numpy as np

_NS_PER_SECOND: float = 1e9


def _seal(arr: np.ndarray) -> np.ndarray:
    """Devuelve un array float64 sellado equivalente a `arr` (copia si hace falta)."""
    out = np.asarray(arr, dtype=np.float64)
    if out is arr or out.flags.writeable:
        # Copiamos si todavía es escribible (o si compartimos buffer con input).
        out = out.copy()
    out.flags.writeable = False
    return out


def inflate_isotropic(
    C: np.ndarray,
    severity: float,
    alpha: float = 2.0,
) -> np.ndarray:
    """Inflación isotrópica (uncertainty.md §5.1).

    .. math::

        C_{\\mathrm{eff}} = (1 + \\alpha \\cdot s)^2 \\, C_{\\mathrm{nominal}}

    con ``severity`` clipado a ``[0, 1]``. Al recuperar `severity=0` el factor
    es 1 y se devuelve una copia exacta de la covarianza nominal (test
    obligatorio ``test_isotropic_inflation_recovers_nominal_at_zero_severity``).

    Args:
        C: covarianza nominal, (n, n) simétrica PSD float64.
        severity: severidad en [0, 1]; valores fuera de rango son clipados.
        alpha: factor de penalización; default 2.0 (hipótesis, no calibrado).

    Returns:
        Covarianza inflada, sellada.
    """
    sev = float(np.clip(severity, 0.0, 1.0))
    if alpha < 0:
        raise ValueError(f"inflate_isotropic: alpha debe ser ≥ 0; recibido {alpha}")
    factor = (1.0 + alpha * sev) ** 2
    return _seal(factor * np.asarray(C, dtype=np.float64))


def inflate_directional(
    C: np.ndarray,
    R_cam_world: np.ndarray,
    scales: np.ndarray,
) -> np.ndarray:
    """Inflación direccional (uncertainty.md §5.2).

    .. math::

        C_{\\mathrm{eff}} =
            R \\, S \\, R^{\\top} \\, C_{\\mathrm{nominal}} \\, R \\, S \\, R^{\\top}

    con :math:`S = \\mathrm{diag}(s_x^2, s_y^2, s_z^2)` los factores por eje
    en marco cámara, y :math:`R` la rotación camara->mundo (3x3 ortogonal).

    Args:
        C: covarianza nominal, (3, 3) simétrica PSD float64.
        R_cam_world: matriz de rotación cámara→mundo, (3, 3) ortogonal.
        scales: factores por eje en marco cámara, (3,); típicamente
            ``(1.0, 1.0, 3.0)`` para el eje óptico hacia delante en FLU.

    Returns:
        Covarianza inflada, sellada.
    """
    cov = np.asarray(C, dtype=np.float64)
    R = np.asarray(R_cam_world, dtype=np.float64)
    s = np.asarray(scales, dtype=np.float64)
    if cov.shape != (3, 3):
        raise ValueError(f"inflate_directional: C debe ser (3, 3); recibido {cov.shape}")
    if R.shape != (3, 3):
        raise ValueError(f"inflate_directional: R_cam_world debe ser (3, 3); recibido {R.shape}")
    if s.shape != (3,):
        raise ValueError(f"inflate_directional: scales debe ser (3,); recibido {s.shape}")
    if not np.all(s >= 0):
        raise ValueError(f"inflate_directional: scales debe ser no-negativo; recibido {s}")
    # Spec §5.2: C_eff = R S Rᵀ C R S Rᵀ con S=diag(s²).
    S = np.diag(s * s)
    M = R @ S @ R.T
    return _seal(M @ cov @ M)


def inflate_stale(
    C: np.ndarray,
    age_ns: int,
    Q_dr: np.ndarray,
) -> np.ndarray:
    """Inflación por staleness / dead reckoning (uncertainty.md §5.4).

    .. math::

        C_{\\mathrm{eff}}(\\mathrm{age}) =
            C_{\\mathrm{last}} + Q_{\\mathrm{dr}} \\cdot \\mathrm{age}_s^2

    Esta forma garantiza monotonía estricta en la edad para cualquier ``Q_dr``
    no nulo (test obligatorio ``test_stale_inflation_monotonic_in_age``).

    Args:
        C: covarianza al instante de la última observación válida, (n, n)
            simétrica PSD float64.
        age_ns: edad de la observación en nanosegundos; debe ser ≥ 0.
        Q_dr: matriz Q de dead reckoning, (n, n) simétrica PSD float64.
            Defaults documentados en uncertainty.md §5.4 (hipótesis).

    Returns:
        Covarianza inflada, sellada.
    """
    if age_ns < 0:
        raise ValueError(f"inflate_stale: age_ns debe ser ≥ 0; recibido {age_ns}")
    cov = np.asarray(C, dtype=np.float64)
    Q = np.asarray(Q_dr, dtype=np.float64)
    if cov.shape != Q.shape:
        raise ValueError(
            f"inflate_stale: C y Q_dr deben coincidir en shape; C={cov.shape}, Q_dr={Q.shape}"
        )
    age_s = float(age_ns) / _NS_PER_SECOND
    return _seal(cov + Q * (age_s * age_s))


__all__ = ["inflate_directional", "inflate_isotropic", "inflate_stale"]
