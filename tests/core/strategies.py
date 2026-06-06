"""Hypothesis strategies para tests de `core.uncertainty`.

Estrategias compartidas para que los tests por módulo sean concisos. Toda
estrategia usa `np.float64` por defecto (consistente con uncertainty.md §3.3).

No usar `np.random.*` directamente en producers ni helpers: la regla está
en uncertainty.md §10. En tests, hypothesis controla la aleatoriedad de
forma reproducible.
"""

from __future__ import annotations

import numpy as np
from hypothesis import strategies as st
from hypothesis.extra import numpy as np_st

from project_ghost.core.uncertainty import Validity

# ---------------------------------------------------------------------------
# Floats razonables (sin NaN/Inf por defecto)
# ---------------------------------------------------------------------------

# Rangos elegidos para que A·Aᵀ se mantenga en un régimen numéricamente
# tratable por `eigvalsh`. El spec fija `eps_psd = 1e-12` absoluto; matrices
# con norma >> 1e6 pueden devolver autovalores negativos espurios del orden
# del epsilon de máquina relativo (~1e-15 · ‖C‖) y romper la prueba.
_FINITE_FLOATS = st.floats(
    min_value=-100.0,
    max_value=100.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)

_POSITIVE_FLOATS = st.floats(
    min_value=1e-3,
    max_value=10.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


# ---------------------------------------------------------------------------
# Matrices
# ---------------------------------------------------------------------------


@st.composite
def square_matrices(draw: st.DrawFn, n: int = 3) -> np.ndarray:
    """Matriz cuadrada (n, n) float64 con entradas finitas razonables."""
    arr = draw(
        np_st.arrays(
            dtype=np.float64,
            shape=(n, n),
            elements=_FINITE_FLOATS,
        )
    )
    # Aseguramos float64 (np_st.arrays ya lo da, pero por explicitud).
    return np.asarray(arr, dtype=np.float64)


@st.composite
def symmetric_psd_matrices(draw: st.DrawFn, n: int = 3) -> np.ndarray:
    """Matriz simétrica PSD (n, n) float64.

    Construida como ``A·Aᵀ + eps·I`` con ``A`` cuadrada finita. Esta receta
    garantiza simetría exacta y PSD estricta (eigenvalor mínimo ≥ eps).
    """
    A = draw(square_matrices(n=n))
    eps = draw(_POSITIVE_FLOATS)
    C = A @ A.T + eps * np.eye(n, dtype=np.float64)
    # Simetría exacta: A·Aᵀ ya es simétrica; eps·I es simétrica; suma idem.
    return np.asarray(C, dtype=np.float64)


@st.composite
def diagonal_psd_matrices(draw: st.DrawFn, n: int = 3) -> np.ndarray:
    """Matriz diagonal PSD (n, n) float64; útil para tests de envelope."""
    diag = draw(
        np_st.arrays(
            dtype=np.float64,
            shape=(n,),
            elements=_POSITIVE_FLOATS,
        )
    )
    return np.diag(np.asarray(diag, dtype=np.float64))


@st.composite
def asymmetric_matrices(draw: st.DrawFn, n: int = 3) -> np.ndarray:
    """Matriz claramente asimétrica (fuera de tolerancia 1e-9).

    Tomamos una matriz simétrica PSD y le sumamos una perturbación
    anti-simétrica de magnitud relativa > 1e-6, garantizando que el ratio
    ‖C-Cᵀ‖_F / ‖C‖_F supere holgadamente la tolerancia del constructor.
    """
    C = draw(symmetric_psd_matrices(n=n))
    # Perturbación anti-simétrica: K - Kᵀ.
    K = draw(square_matrices(n=n))
    skew = K - K.T
    skew_norm = float(np.linalg.norm(skew, ord="fro"))
    cov_norm = float(np.linalg.norm(C, ord="fro"))
    if skew_norm == 0.0 or cov_norm == 0.0:
        # Degenerado: empujamos manualmente.
        skew = np.zeros_like(C)
        skew[0, 1] = 1.0
        skew[1, 0] = -1.0
        skew_norm = float(np.linalg.norm(skew, ord="fro"))
        cov_norm = float(np.linalg.norm(C, ord="fro")) or 1.0
    # Escalar para que la asimetría relativa sea ~1e-3, muy por encima de 1e-9.
    target_ratio = 1e-3
    scale = target_ratio * cov_norm / skew_norm
    return np.asarray(C + scale * skew, dtype=np.float64)


@st.composite
def non_psd_matrices(draw: st.DrawFn, n: int = 3) -> np.ndarray:
    """Matriz simétrica con al menos un eigenvalor claramente negativo."""
    C = draw(symmetric_psd_matrices(n=n))
    # Resta un múltiplo de un proyector rango-1 lo suficientemente grande
    # para hacer el eigenvalor mínimo < -1e-6.
    v = draw(np_st.arrays(dtype=np.float64, shape=(n,), elements=_FINITE_FLOATS))
    v_arr = np.asarray(v, dtype=np.float64)
    norm = float(np.linalg.norm(v_arr))
    if norm < 1e-9:
        v_arr = np.zeros(n, dtype=np.float64)
        v_arr[0] = 1.0
        norm = 1.0
    v_hat = v_arr / norm
    # Eigenvalor máximo aproximado de C como cota para sustraer.
    lam = float(np.max(np.linalg.eigvalsh(C)))
    perturbation = (lam + 1.0) * np.outer(v_hat, v_hat)
    return np.asarray(C - perturbation, dtype=np.float64)


# ---------------------------------------------------------------------------
# Enums y escalares
# ---------------------------------------------------------------------------

validity_values = st.sampled_from(list(Validity))

non_negative_ints = st.integers(min_value=0, max_value=2**40)
positive_ints = st.integers(min_value=1, max_value=2**40)
severity_floats = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False, width=64
)
alpha_floats = st.floats(
    min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False, width=64
)


__all__ = [
    "alpha_floats",
    "asymmetric_matrices",
    "diagonal_psd_matrices",
    "non_negative_ints",
    "non_psd_matrices",
    "positive_ints",
    "severity_floats",
    "square_matrices",
    "symmetric_psd_matrices",
    "validity_values",
]
