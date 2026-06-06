"""JSON-safe encoding/decoding for Project Ghost frozen dataclasses.

**Determinism guarantee.** ``encode_to_bytes(x)`` produces byte-identical
output for identical ``x`` within the same Python interpreter version.
The chain is:

1. ``to_json_safe(x)`` walks the dataclass tree and emits a deterministic
   Python value (recursive: same input -> same dict in memory).
2. ``json.dumps`` is called with ``sort_keys=True`` and a compact
   ``separators`` tuple. Within a fixed CPython version, float formatting
   and string escaping are deterministic.
3. UTF-8 encoding is byte-stable.

Limitations (documented explicitly per T4 review):

- Cross-Python-version determinism is **not guaranteed**: float repr
  rules can shift between CPython releases. T4 commits to "byte-identical
  within a fixed interpreter" — that is what replay actually requires.
- Float values that map to multiple textual representations (e.g.
  subnormals, very large exponents) are deterministic per CPython but
  may surprise consumers. We do not attempt to canonicalize further.
- Numpy arrays are serialized via ``tolist()``. Floats are emitted in
  Python ``repr`` form; integers as exact decimal. Both stable.

**Encoding rules.**

- ``None``, ``bool``, ``int``, ``float``, ``str``: emitted as themselves.
- ``IntEnum`` -> ``int`` (the value).
- ``StrEnum`` -> ``str`` (the value).
- ``np.ndarray`` -> ``{"__dtype": "<name>", "__array": [...]}``.
  The dtype tag is required so decoders can reproduce the original
  precision (JSON does not distinguish ``1`` from ``1.0``).
- ``tuple`` / ``list`` -> JSON list (decoder restores tuple where
  the field type says so).
- ``MappingProxyType`` / ``dict`` -> JSON object with string keys.
- Frozen dataclass -> JSON object with all declared fields.

**Decoding.**

``from_json_dict(cls, d)`` invokes the dataclass constructor, which
triggers ``__post_init__``. A round-tripped object therefore satisfies
the same invariants as a freshly-constructed one — or fails loudly. This
turns replay into an active correctness check, not just a load step.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import json
import typing
from enum import Enum, IntEnum, StrEnum
from types import MappingProxyType, UnionType
from typing import Any

import numpy as np

# Wire-format keys for serialized numpy arrays. Underscore prefix avoids
# collision with any dataclass field name in the codebase.
_NDARRAY_DTYPE_KEY: str = "__dtype"
_NDARRAY_DATA_KEY: str = "__array"

# `typing.get_args(tuple[X, ...])` returns 2 elements: (X, Ellipsis).
_HOMOGENEOUS_TUPLE_NUM_ARGS: int = 2

# `typing.get_args(Mapping[K, V])` returns 2 elements: (K, V).
_MAPPING_NUM_ARGS: int = 2


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def to_json_safe(obj: Any) -> Any:  # noqa: PLR0911
    """Convert a Project Ghost dataclass tree to a JSON-safe Python value.

    Total over the supported type set. Raises ``TypeError`` for anything
    outside that set — we prefer loud failure to silent data loss.

    Enum checks come BEFORE the int/str fast path because ``IntEnum`` and
    ``StrEnum`` are subclasses of ``int`` / ``str``; without the early
    return the encoder would emit the enum instance instead of its
    underlying value.
    """
    if obj is None:
        return None
    if isinstance(obj, IntEnum):
        return int(obj.value)
    if isinstance(obj, StrEnum):
        return str(obj.value)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float, str)):
        return obj
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return {
            _NDARRAY_DTYPE_KEY: str(obj.dtype),
            _NDARRAY_DATA_KEY: obj.tolist(),
        }
    if isinstance(obj, Enum):
        # Other (non-Int / non-Str) enums — fall back to value.
        return obj.value
    if isinstance(obj, (MappingProxyType, dict)):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [to_json_safe(v) for v in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_json_safe(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
    raise TypeError(
        f"to_json_safe: tipo no soportado: {type(obj).__name__}"
    )


def encode_to_bytes(obj: Any) -> bytes:
    """Serialize ``obj`` to deterministic UTF-8 JSON bytes.

    Equivalent to ``json.dumps(to_json_safe(obj), sort_keys=True,
    ensure_ascii=False, separators=(",", ":"))`` followed by UTF-8 encoding.
    """
    safe = to_json_safe(obj)
    return json.dumps(
        safe,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def from_json_dict(cls: type[Any], d: collections.abc.Mapping[str, Any]) -> Any:
    """Reconstruct an instance of ``cls`` from a JSON-decoded dict.

    Triggers ``cls.__post_init__`` via the dataclass constructor — invariants
    are re-verified on replay. Raises whatever the constructor raises
    (typically ``TypeError`` / ``ValueError``) on bad data.
    """
    return _decode_dataclass(cls, d)


def _decode_dataclass(
    cls: type[Any], d: collections.abc.Mapping[str, Any]
) -> Any:
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"_decode_dataclass: {cls!r} is not a dataclass")
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if not f.init:
            # Fields with init=False (e.g. ActuatorCommand.level) are set
            # by the dataclass machinery itself; we skip them here.
            continue
        if f.name in d:
            kwargs[f.name] = _decode_value(hints[f.name], d[f.name])
            continue
        if f.default is not dataclasses.MISSING:
            kwargs[f.name] = f.default
            continue
        if f.default_factory is not dataclasses.MISSING:
            kwargs[f.name] = f.default_factory()
            continue
        raise KeyError(
            f"_decode_dataclass: missing required field {f.name!r} for "
            f"{cls.__name__}"
        )
    return cls(**kwargs)


def _decode_value(hint: Any, value: Any) -> Any:  # noqa: PLR0911, PLR0912
    if value is None:
        return None

    origin = typing.get_origin(hint)
    args = typing.get_args(hint)

    # Union / Optional (both `Union[X, None]` and `X | None`).
    if origin is UnionType or origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _decode_value(non_none[0], value)
        for arg in non_none:
            try:
                return _decode_value(arg, value)
            except (TypeError, ValueError, KeyError):
                continue
        raise TypeError(
            f"_decode_value: cannot decode {value!r} for union {hint}"
        )

    # Numpy ndarray.
    if hint is np.ndarray:
        return _decode_ndarray(value)

    # Frozen dataclass (nested).
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        return _decode_dataclass(hint, value)

    # Enums.
    if isinstance(hint, type) and issubclass(hint, Enum):
        return hint(value)

    # tuple[X, ...] (variable-length, homogeneous).
    if origin is tuple:
        if len(args) == _HOMOGENEOUS_TUPLE_NUM_ARGS and args[1] is Ellipsis:
            return tuple(_decode_value(args[0], v) for v in value)
        # Fixed-length heterogeneous tuple.
        return tuple(
            _decode_value(a, v) for a, v in zip(args, value, strict=True)
        )

    # list[X].
    if origin is list:
        if args:
            return [_decode_value(args[0], v) for v in value]
        return list(value)

    # Mapping[K, V] / dict[K, V].
    if origin is dict or origin is collections.abc.Mapping or (
        isinstance(origin, type)
        and issubclass(origin, collections.abc.Mapping)
    ):
        if len(args) == _MAPPING_NUM_ARGS:
            k_hint, v_hint = args
            return {
                _decode_value(k_hint, k): _decode_value(v_hint, v)
                for k, v in value.items()
            }
        return dict(value)

    # Literal types — values are already JSON-primitive.
    if origin is typing.Literal:
        return value

    # Primitives.
    if hint in (int, float, str, bool):
        return value

    # Any / unknown — pass through. The downstream dataclass constructor
    # is the final arbiter of correctness.
    return value


def _decode_ndarray(d: Any) -> np.ndarray:
    if not isinstance(d, collections.abc.Mapping):
        raise TypeError(
            f"_decode_ndarray: expected mapping with {_NDARRAY_DTYPE_KEY!r} "
            f"and {_NDARRAY_DATA_KEY!r} keys; got {type(d).__name__}"
        )
    if _NDARRAY_DTYPE_KEY not in d or _NDARRAY_DATA_KEY not in d:
        raise TypeError(
            f"_decode_ndarray: missing required keys "
            f"{_NDARRAY_DTYPE_KEY!r} / {_NDARRAY_DATA_KEY!r}"
        )
    dtype = np.dtype(d[_NDARRAY_DTYPE_KEY])
    return np.asarray(d[_NDARRAY_DATA_KEY], dtype=dtype)


__all__ = [
    "encode_to_bytes",
    "from_json_dict",
    "to_json_safe",
]
