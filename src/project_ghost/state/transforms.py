"""Utilidades estables de transformación de marco (T2.a.5).

Materializa `docs/specs/state.md` §6 — el conjunto exhaustivo de
conversiones de marco permitidas en Project Ghost. Estas son la **única**
vía aceptada para convertir entre representaciones: cualquier inversión
manual es candidata a bug (state.md §7).

Convenciones congeladas (state.md §2):

- Marco mundo: ENU (East, North, Up); z=0 al suelo.
- Marco cuerpo: FLU (Forward, Left, Up).
- Cuaternión: Hamilton, ``[w, x, y, z]``.
- Scipy usa ``[x, y, z, w]`` — solo se cruza esa frontera con los helpers
  `quat_hamilton_to_scipy` / `quat_scipy_to_hamilton`.

Decisiones de implementación cerradas en T2.a.5:

- `R_body_to_world` se calcula con la fórmula cerrada de Hamilton sobre
  numpy puro. **No** se importa `scipy.spatial.transform.Rotation`: la
  fórmula es determinística entre versiones de numpy y CPython, scipy
  agregaría una dep pesada cuyo único uso aquí sería repetir esta
  fórmula internamente.
- Toda la API valida shape/dtype/finitud en frontera. Quaterniones
  además se validan como unit (tolerancia 1e-3) — son boundary
  functions que clientes pueden invocar con arrays arbitrarios.
- Returns están sellados (`flags.writeable=False`). Mismo patrón que
  `hal.messages` y `state.messages`.

Propagación de incertidumbre: este módulo produce point-estimate
rotations. La transformación de covarianza ``Σ_new = R Σ_old Rᵀ`` vive
en `core.uncertainty.inflation.inflate_directional` — separación a
propósito. Las dos piezas se componen en estimadores aguas arriba.

Separación simulación/runtime: estas funciones son puras (sin reloj,
sin random, sin estado interno). Idénticas en sim y en hardware. No
introducen acoplamiento entre HAL y backends.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_VEC3_LEN: Final[int] = 3
_QUAT_LEN: Final[int] = 4
_QUAT_NORM_TOLERANCE: Final[float] = 1e-3


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _validate_vec3(arr: Any, *, name: str) -> None:
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{name} debe ser np.ndarray; recibido {type(arr).__name__}"
        )
    if arr.shape != (_VEC3_LEN,):
        raise TypeError(
            f"{name} debe tener shape ({_VEC3_LEN},); recibido {arr.shape}"
        )
    if arr.dtype != np.float64:
        raise TypeError(
            f"{name} debe tener dtype float64; recibido {arr.dtype}"
        )
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} contiene NaN o Inf")


def _validate_quat(q: Any, *, name: str = "q") -> None:
    if not isinstance(q, np.ndarray):
        raise TypeError(
            f"{name} debe ser np.ndarray; recibido {type(q).__name__}"
        )
    if q.shape != (_QUAT_LEN,):
        raise TypeError(
            f"{name} debe tener shape ({_QUAT_LEN},); recibido {q.shape}"
        )
    if q.dtype != np.float64:
        raise TypeError(
            f"{name} debe tener dtype float64; recibido {q.dtype}"
        )
    if not bool(np.all(np.isfinite(q))):
        raise ValueError(f"{name} contiene NaN o Inf")
    norm = float(np.linalg.norm(q))
    if abs(norm - 1.0) > _QUAT_NORM_TOLERANCE:
        raise ValueError(
            f"{name} debe ser unit (tolerancia {_QUAT_NORM_TOLERANCE}); "
            f"norm={norm}"
        )


def _seal(arr: np.ndarray) -> np.ndarray:
    arr.setflags(write=False)
    return arr


# ---------------------------------------------------------------------------
# Quaternion permutaciones — Hamilton <-> scipy
# ---------------------------------------------------------------------------


def quat_hamilton_to_scipy(q: np.ndarray) -> np.ndarray:
    """Convierte un quaternion Hamilton ``[w, x, y, z]`` al orden de scipy
    ``[x, y, z, w]``.

    La permutación es exacta (no cambia la rotación representada); las
    operaciones algebraicas que el caller haga con `scipy.spatial.transform.
    Rotation` se aplicarán sobre el mismo rotor.
    """
    _validate_quat(q, name="q")
    return _seal(np.array([q[1], q[2], q[3], q[0]], dtype=np.float64))


def quat_scipy_to_hamilton(q: np.ndarray) -> np.ndarray:
    """Convierte un quaternion en orden scipy ``[x, y, z, w]`` a Hamilton
    ``[w, x, y, z]`` — inverso de `quat_hamilton_to_scipy`."""
    _validate_quat(q, name="q")
    return _seal(np.array([q[3], q[0], q[1], q[2]], dtype=np.float64))


# ---------------------------------------------------------------------------
# Rotation matrices — body <-> world
# ---------------------------------------------------------------------------


def R_body_to_world(q_hamilton: np.ndarray) -> np.ndarray:
    """Matriz de rotación 3x3 que mapea un vector en frame body al frame
    world: ``v_world = R_body_to_world(q) @ v_body``.

    Fórmula cerrada para Hamilton ``q = [w, x, y, z]`` (Shoemake, 1985).
    El quaternion **debe** ser unit; se valida con tolerancia 1e-3.

    Para propagar covarianza bajo esta rotación (e.g. al transformar la
    nube ruidosa de una estimación de velocidad de body a world), pasar
    R y la covarianza original a
    `core.uncertainty.inflation.inflate_directional`.
    """
    _validate_quat(q_hamilton, name="q_hamilton")
    w, x, y, z = q_hamilton
    r = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    return _seal(r)


def R_world_to_body(q_hamilton: np.ndarray) -> np.ndarray:
    """Inversa (= transpose, porque R es ortogonal) de `R_body_to_world`.

    Mapea un vector en frame world al frame body:
    ``v_body = R_world_to_body(q) @ v_world``.
    """
    # Construimos la matriz body->world y devolvemos su transpose; la copia
    # explícita asegura que el array devuelto sea sellable independiente.
    r = np.ascontiguousarray(R_body_to_world(q_hamilton).T, dtype=np.float64)
    return _seal(r)


# ---------------------------------------------------------------------------
# ENU <-> NED
# ---------------------------------------------------------------------------


def enu_to_ned(v_enu: np.ndarray) -> np.ndarray:
    """Convierte un vector ENU ``[East, North, Up]`` a NED
    ``[North, East, Down]``.

    Convención estándar aeroespacial: permuta los dos primeros ejes y
    voltea el signo del tercero. Involutiva: `ned_to_enu(enu_to_ned(v))
    == v`.
    """
    _validate_vec3(v_enu, name="v_enu")
    east, north, up = v_enu
    return _seal(np.array([north, east, -up], dtype=np.float64))


def ned_to_enu(v_ned: np.ndarray) -> np.ndarray:
    """Convierte un vector NED ``[North, East, Down]`` a ENU
    ``[East, North, Up]`` — inverso de `enu_to_ned`."""
    _validate_vec3(v_ned, name="v_ned")
    north, east, down = v_ned
    return _seal(np.array([east, north, -down], dtype=np.float64))


# ---------------------------------------------------------------------------
# FLU <-> FRD
# ---------------------------------------------------------------------------


def flu_to_frd(v_flu: np.ndarray) -> np.ndarray:
    """Convierte un vector body FLU ``[Forward, Left, Up]`` a FRD
    ``[Forward, Right, Down]``.

    Mantiene Forward; voltea Left↔Right (cambio de signo en eje y) y
    Up↔Down (cambio de signo en eje z). Involutiva.
    """
    _validate_vec3(v_flu, name="v_flu")
    f, left, up = v_flu
    return _seal(np.array([f, -left, -up], dtype=np.float64))


def frd_to_flu(v_frd: np.ndarray) -> np.ndarray:
    """Convierte un vector body FRD ``[Forward, Right, Down]`` a FLU
    ``[Forward, Left, Up]`` — inverso de `flu_to_frd`."""
    _validate_vec3(v_frd, name="v_frd")
    f, right, down = v_frd
    return _seal(np.array([f, -right, -down], dtype=np.float64))


__all__ = [
    "R_body_to_world",
    "R_world_to_body",
    "enu_to_ned",
    "flu_to_frd",
    "frd_to_flu",
    "ned_to_enu",
    "quat_hamilton_to_scipy",
    "quat_scipy_to_hamilton",
]
