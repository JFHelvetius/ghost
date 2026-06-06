"""Sealing recursivo de arrays.

Cierra el agujero de sealing superficial identificado en
`docs/reviews/uncertainty_red_team_review.md` §3.2 y especificado en
`docs/specs/uncertainty.md` §3.2:

    "El constructor de `Estimate` aplica sealing recursivo sobre cualquier
     `np.ndarray` accesible por traversal de los campos cuando `value` es
     dataclass. Verifica el sealing tras construcción y rechaza con
     `ValueError` si encuentra un array escribible."

El traversal NO entra en `set`, `frozenset` ni `dict` (orden de iteración
inestable, prohibido por `docs/specs/uncertainty.md` §10). Si encuentra
estas colecciones en una dataclass siendo sellada, lanza `TypeError`.
"""

from __future__ import annotations

import contextlib
from dataclasses import fields, is_dataclass
from typing import Any, cast

import numpy as np

# Colecciones cuya iteración es estable y por las que sí descendemos.
_STABLE_SEQUENCE_TYPES: tuple[type, ...] = (tuple, list)

# Colecciones de orden inestable. Rechazadas dentro del traversal.
_UNSTABLE_COLLECTION_TYPES: tuple[type, ...] = (set, frozenset, dict)


def seal_recursive(obj: Any) -> None:
    """Sella in-place todo `np.ndarray` alcanzable por traversal de campos.

    Reglas de traversal:

    - `np.ndarray`: aplica ``flags.writeable=False``.
    - dataclass: itera sobre `fields()` (orden de declaración, estable).
    - `tuple` / `list`: itera sobre elementos.
    - `set` / `frozenset` / `dict`: lanza `TypeError` por orden inestable.
    - Cualquier otro tipo: ignorado.

    No verifica al terminar; eso lo hace `assert_all_sealed` por separado.
    Esta separación permite intentar el sealing y luego decidir si fallar.
    """
    if isinstance(obj, np.ndarray):
        # No-owning view de un buffer no-writable: numpy rechaza el cambio.
        # No es error a nuestro nivel; el array ya queda efectivamente read-only.
        with contextlib.suppress(ValueError):
            obj.flags.writeable = False
        return

    if isinstance(obj, _UNSTABLE_COLLECTION_TYPES):
        raise TypeError(
            f"sealing recursivo encontró colección inestable de tipo {type(obj).__name__}; "
            "prohibido por docs/specs/uncertainty.md §10"
        )

    if is_dataclass(obj) and not isinstance(obj, type):
        for f in fields(obj):
            child = getattr(obj, f.name)
            seal_recursive(child)
        return

    if isinstance(obj, _STABLE_SEQUENCE_TYPES):
        for item in cast("tuple[Any, ...] | list[Any]", obj):
            seal_recursive(item)
        return

    # Tipos escalares (int, float, str, None, enums, etc.) o tipos no
    # contemplados: no hay nada que sellar.


def assert_all_sealed(obj: Any) -> None:
    """Verifica que ningún `np.ndarray` alcanzable es escribible.

    Lanza `ValueError` con el path del primer array problemático que encuentra.
    Usado por `make_estimate` después del sealing para garantizar el invariante
    de `docs/specs/uncertainty.md` §3.2.

    Path: cadena humana del estilo ``value.pose.position_enu_m``.
    """
    _assert_all_sealed_at(obj, path="")


def _assert_all_sealed_at(obj: Any, path: str) -> None:
    if isinstance(obj, np.ndarray):
        if obj.flags.writeable:
            raise ValueError(
                f"sealing recursivo dejó un array escribible en {path or '<root>'}; "
                "indica que el productor expuso un buffer mutable. "
                "Ver docs/specs/uncertainty.md §3.2."
            )
        return

    if isinstance(obj, _UNSTABLE_COLLECTION_TYPES):
        raise TypeError(
            f"verificación de sealing encontró colección inestable en {path or '<root>'}; "
            "prohibido por docs/specs/uncertainty.md §10"
        )

    if is_dataclass(obj) and not isinstance(obj, type):
        for f in fields(obj):
            child = getattr(obj, f.name)
            child_path = f"{path}.{f.name}" if path else f.name
            _assert_all_sealed_at(child, child_path)
        return

    if isinstance(obj, _STABLE_SEQUENCE_TYPES):
        for i, item in enumerate(cast("tuple[Any, ...] | list[Any]", obj)):
            child_path = f"{path}[{i}]" if path else f"[{i}]"
            _assert_all_sealed_at(item, child_path)
        return


__all__ = ["assert_all_sealed", "seal_recursive"]
