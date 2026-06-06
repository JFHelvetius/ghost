"""`generate_run_report` — write a deterministic JSON sidecar from a
``RunSummary``.

Output format::

    {
      "schema_version": "1",
      "summary": { ... summary fields, alphabetically sorted ... }
    }

Encoding rules (these are the only knobs and are frozen):

- ``sort_keys=True`` — alphabetical key order at every dict level.
- ``indent=2`` — human-readable indentation.
- ``ensure_ascii=False`` — UTF-8 throughout; no ``\\uXXXX`` escapes.
- Trailing newline appended.
- UTF-8 byte encoding.

Byte-deterministic within a fixed CPython version.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from .models import RunSummary


REPORT_SCHEMA_VERSION: str = "1"


def generate_run_report(summary: RunSummary, output_path: Path) -> None:
    """Write ``summary`` as a JSON file at ``output_path``.

    Overwrites if the file already exists. Creates parent directories
    only if they already exist — this function does not invent paths.
    """
    output_path.write_bytes(encode_report_to_bytes(summary))


def encode_report_to_bytes(summary: RunSummary) -> bytes:
    """Encode ``summary`` to deterministic UTF-8 bytes.

    Pure function — no filesystem access. Useful for byte-determinism
    tests and for embedding the encoding in larger workflows.
    """
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "summary": dataclasses.asdict(summary),
    }
    serialized = json.dumps(
        report,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "encode_report_to_bytes",
    "generate_run_report",
]
