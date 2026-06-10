"""`RandomSourceImpl` — fuente determinista jerárquica con derivación SHA-256.

Cumple el contrato del Protocol `types.RandomSource` y los requisitos de
`docs/specs/clock.md` §4. Hash determinista entre versiones de CPython
porque `hashlib.sha256` es estable por estándar (no afectado por
`PYTHONHASHSEED`).

Modelo de derivación:

- Raíz: `RandomSourceImpl(seed=S, label="/")`.
- `root.child("imu0")` produce un hijo con seed `SHA-256(f"{S:x}:imu0")[:8]`
  y label `/imu0`.
- `root.child("imu0").child("noise")` deriva del seed del hijo, NO del label
  completo `/imu0/noise`. Esto significa: cadenas de `.child(...)` distintas
  pero con el mismo path final NO necesariamente producen las mismas
  secuencias. La invariante es: **mismo árbol de llamadas + misma seed raíz
  -> mismos números**.
"""

from __future__ import annotations

import hashlib
from typing import Final

import numpy as np

# Bytes del digest usados como seed. 8 bytes -> int64 sin signo, suficiente
# entropía para casos prácticos y dentro de lo que `np.random.default_rng`
# acepta cómodamente.
_SEED_BYTES: Final[int] = 8

# Máscara para mantener el seed positivo y bajo 2**63-1 (límite de int64
# con signo). `default_rng` acepta cualquier int no-negativo, pero
# mantenerlo en int64 es portable.
_MAX_SEED: Final[int] = 2**63 - 1


def _derive_child_seed(parent_seed: int, child_label: str) -> int:
    """Deriva el seed de un hijo a partir del seed del padre y el label.

    Usa SHA-256 sobre `"<parent_hex>:<label>"` (separador ':' inambiguo).
    """
    payload = f"{parent_seed:x}:{child_label}".encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:_SEED_BYTES], "big") & _MAX_SEED


class RandomSourceImpl:
    """Implementación concreta de `RandomSource`.

    Internamente envuelve un `numpy.random.Generator` para tener acceso a
    todas las distribuciones de numpy sin reimplementarlas.
    """

    seed: int
    label: str

    def __init__(self, seed: int, label: str = "/") -> None:
        if seed < 0:
            raise ValueError(f"seed debe ser >= 0; recibido {seed}")
        if not label.startswith("/"):
            raise ValueError(
                f"label debe empezar con '/'; recibido {label!r}. "
                f"Convención: rutas jerárquicas estilo '/sensors/imu0/noise'."
            )
        self.seed = seed
        self.label = label
        self._rng: np.random.Generator = np.random.default_rng(seed)

    def child(self, label: str) -> RandomSourceImpl:
        """Deriva una sub-fuente con seed determinista del label.

        El label del hijo se construye concatenando el path del padre con
        el segmento dado, normalizando slashes.
        """
        if not label:
            raise ValueError("child label no puede ser vacío")
        # Permitir tanto "imu0" como "/imu0"; normalizar a un solo separador.
        segment = label.lstrip("/")
        if not segment:
            raise ValueError(f"child label debe contener algo más que slashes; recibido {label!r}")
        child_seed = _derive_child_seed(self.seed, segment)
        sep = "" if self.label.endswith("/") else "/"
        child_path = self.label + sep + segment
        return RandomSourceImpl(seed=child_seed, label=child_path)

    def uniform(self, a: float, b: float) -> float:
        return float(self._rng.uniform(a, b))

    def normal(self, mu: float, sigma: float) -> float:
        return float(self._rng.normal(mu, sigma))

    def integers(self, low: int, high: int) -> int:
        return int(self._rng.integers(low, high))

    def numpy_rng(self) -> np.random.Generator:
        """Devuelve el `Generator` interno.

        Llamadas sucesivas devuelven el **mismo** objeto. Compartirlo entre
        consumidores rompe determinismo de cada uno; para concerns
        independientes, crear `child()` separado.
        """
        return self._rng


__all__ = ["RandomSourceImpl"]
