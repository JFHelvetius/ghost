"""Comparative belief analysis with provenance manifests (ADR-0018 core).

Stdlib-only. Pure. Deterministic. Observational.

This module is the architectural core of ADR-0018. It provides:

- ``ManifestArtifact`` / ``RunManifest``: content-addressed provenance
  for a run. SHA-256 of every declared input and output is captured at
  the moment ``build_run_manifest`` is called.
- ``verify_run_manifest``: re-hashes the files referenced by a manifest
  and reports mismatches. Audit primitive; modifies nothing.
- ``LabeledSummary``: pairs a label, a ADR-0017
  ``BeliefConsistencySummary``, and an optional ``RunManifest``.
- ``MetricDelta`` / ``ComparativeBeliefReport``: N-way structured deltas
  between summaries. First label in input order is the baseline. Deltas
  are pure arithmetic; ``None`` propagates.
- Encoders / decoders for canonical JSON round-trip (same posture as
  ADR-0013 / ADR-0016 / ADR-0017).

What this module deliberately does NOT do:

- No IA, no ML, no clustering, no classification.
- No ratios (only deltas).
- No statistics over labels (no mean of deltas, no std).
- No ranking, no scoring, no anomaly detection.
- No recommendations, no alerting.

Comparison is arithmetic; provenance is hashing. The operator interprets.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from project_ghost.telemetry import from_json_dict

from .belief_consistency import (
    BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION,
    BeliefConsistencySummary,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

BELIEF_COMPARISON_ANALYSIS_VERSION: int = 1
BELIEF_COMPARISON_REPORT_SCHEMA_VERSION: str = "1"
RUN_MANIFEST_SCHEMA_VERSION: str = "1"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_SHA256_HEX_LEN: int = 64
_HASH_CHUNK_BYTES: int = 1 << 20  # 1 MiB
_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdef")

# Closed catalog of the 20 numeric metrics from BeliefConsistencySummary
# (excludes ``analysis_version``). Alphabetical order is the contractual
# iteration order for ``ComparativeBeliefReport.metrics``.
_NUMERIC_METRIC_NAMES: tuple[str, ...] = (
    "covariance_condition_number_max",
    "covariance_condition_number_mean",
    "covariance_condition_number_min",
    "covariance_trace_max",
    "covariance_trace_mean",
    "covariance_trace_min",
    "orientation_error_max_rad",
    "orientation_error_mean_rad",
    "orientation_error_min_rad",
    "position_error_max_m",
    "position_error_mean_m",
    "position_error_min_m",
    "samples_with_covariance",
    "samples_with_finite_condition_number",
    "samples_with_finite_trace",
    "samples_without_covariance",
    "timestamp_first_ns",
    "timestamp_last_ns",
    "timestamp_span_ns",
    "total_samples",
)


def _hash_file_sha256(path: Path) -> str:
    """Stream a file through SHA-256 with 1 MiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _validate_envelope(
    data: object,
    *,
    schema_version: str,
    inner_key: str,
) -> Mapping[str, Any]:
    """Validate the ``{schema_version, <inner_key>}`` JSON envelope.

    Returns the inner mapping on success.
    """
    if not isinstance(data, Mapping):
        raise TypeError(f"expected JSON mapping; got {type(data).__name__}")
    if "schema_version" not in data:
        raise ValueError("missing 'schema_version' in JSON envelope")
    if data["schema_version"] != schema_version:
        raise ValueError(
            f"incompatible schema_version {data['schema_version']!r}; expected {schema_version!r}"
        )
    if inner_key not in data:
        raise ValueError(f"missing {inner_key!r} in JSON envelope")
    inner = data[inner_key]
    if not isinstance(inner, Mapping):
        raise TypeError(f"{inner_key!r} must be a mapping; got {type(inner).__name__}")
    return inner


# ---------------------------------------------------------------------------
# ManifestArtifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestArtifact:
    """A single declared input or output of a run.

    ``sha256`` is the hex digest at the moment the manifest was built —
    the integrity claim. ``path`` is preserved verbatim (no
    normalization, no symlink resolution). ``kind`` is a free-form
    taxonomy hint chosen by the caller (e.g. ``"mcap_truth"``,
    ``"consistency_summary"``).
    """

    path: str
    sha256: str
    kind: str

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("ManifestArtifact: path cannot be empty")
        if not self.kind:
            raise ValueError("ManifestArtifact: kind cannot be empty")
        if len(self.sha256) != _SHA256_HEX_LEN:
            raise ValueError(
                f"ManifestArtifact: sha256 must be {_SHA256_HEX_LEN} hex "
                f"chars; got len={len(self.sha256)}"
            )
        for c in self.sha256:
            if c not in _HEX_CHARS:
                raise ValueError(
                    f"ManifestArtifact: sha256 must be lowercase hex; got {self.sha256!r}"
                )


# ---------------------------------------------------------------------------
# RunManifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunManifest:
    """Content-addressed provenance for one run.

    ``config_descriptor`` is an opaque JSON-safe mapping chosen by the
    caller. Its only contract is JSON serializability, validated at
    construction time. The stored value is always a plain ``dict`` —
    if the caller passes a ``MappingProxyType`` or another ``Mapping``
    subclass, ``__post_init__`` normalizes it so downstream encoding
    and equality are well-behaved.

    ``inputs`` and ``outputs`` are tuples of ``ManifestArtifact`` whose
    ``sha256`` fields are integrity claims; ``build_run_manifest``
    computes them from disk, ``verify_run_manifest`` re-checks them.
    """

    run_id: str
    config_descriptor: Mapping[str, Any]
    inputs: tuple[ManifestArtifact, ...]
    outputs: tuple[ManifestArtifact, ...]

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("RunManifest: run_id cannot be empty")
        if not isinstance(self.config_descriptor, Mapping):
            raise TypeError(
                "RunManifest: config_descriptor must be a Mapping; got "
                f"{type(self.config_descriptor).__name__}"
            )
        normalized = dict(self.config_descriptor)
        try:
            json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        except TypeError as e:
            raise TypeError(f"RunManifest: config_descriptor is not JSON-safe: {e}") from e
        object.__setattr__(self, "config_descriptor", normalized)
        if not isinstance(self.inputs, tuple):
            raise TypeError(
                f"RunManifest: inputs must be a tuple; got {type(self.inputs).__name__}"
            )
        if not isinstance(self.outputs, tuple):
            raise TypeError(
                f"RunManifest: outputs must be a tuple; got {type(self.outputs).__name__}"
            )


# ---------------------------------------------------------------------------
# LabeledSummary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabeledSummary:
    """Input to ``build_comparative_report``.

    Pairs a user-facing label with a ``BeliefConsistencySummary`` and an
    optional ``RunManifest``. ``manifest`` is recommended (it makes the
    comparison provenance-aware) but allowed to be ``None``.
    """

    label: str
    summary: BeliefConsistencySummary
    manifest: RunManifest | None

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("LabeledSummary: label cannot be empty")


# ---------------------------------------------------------------------------
# MetricDelta
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricDelta:
    """Per-label values + deltas-against-baseline for one numeric metric.

    Frozen rules:

    - ``deltas[L] = values[L] - baseline_value`` when both are non-None.
    - ``deltas[L] = None`` when either is ``None``.
    - For ``L == baseline_label`` with non-None ``baseline_value`` the
      delta is ``0`` (same numeric type as ``baseline_value``); for
      ``None`` baseline it is ``None``.
    """

    baseline_label: str
    baseline_value: int | float | None
    values: Mapping[str, int | float | None]
    deltas: Mapping[str, int | float | None]

    def __post_init__(self) -> None:
        if not self.baseline_label:
            raise ValueError("MetricDelta: baseline_label cannot be empty")
        if not isinstance(self.values, Mapping):
            raise TypeError(
                f"MetricDelta: values must be a Mapping; got {type(self.values).__name__}"
            )
        if not isinstance(self.deltas, Mapping):
            raise TypeError(
                f"MetricDelta: deltas must be a Mapping; got {type(self.deltas).__name__}"
            )
        object.__setattr__(self, "values", dict(self.values))
        object.__setattr__(self, "deltas", dict(self.deltas))
        if self.baseline_label not in self.values:
            raise ValueError(
                f"MetricDelta: baseline_label {self.baseline_label!r} must appear in values"
            )
        if self.baseline_label not in self.deltas:
            raise ValueError(
                f"MetricDelta: baseline_label {self.baseline_label!r} must appear in deltas"
            )


# ---------------------------------------------------------------------------
# ComparativeBeliefReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComparativeBeliefReport:
    """N-way structured comparison of ``BeliefConsistencySummary`` instances.

    ``labels`` preserves the input order from ``build_comparative_report``;
    ``labels[0] == baseline_label`` is enforced. ``metrics`` covers
    exactly the 20 numeric fields of ``BeliefConsistencySummary``,
    keyed by name. ``manifests`` is a label -> ``RunManifest | None``
    pass-through.
    """

    baseline_label: str
    labels: tuple[str, ...]
    metrics: Mapping[str, MetricDelta]
    manifests: Mapping[str, RunManifest | None]
    analysis_version: int = BELIEF_COMPARISON_ANALYSIS_VERSION

    def __post_init__(self) -> None:
        if not self.baseline_label:
            raise ValueError("ComparativeBeliefReport: baseline_label cannot be empty")
        if not isinstance(self.labels, tuple):
            raise TypeError(
                f"ComparativeBeliefReport: labels must be a tuple; got {type(self.labels).__name__}"
            )
        if not self.labels:
            raise ValueError("ComparativeBeliefReport: labels cannot be empty")
        if self.labels[0] != self.baseline_label:
            raise ValueError(
                f"ComparativeBeliefReport: labels[0] {self.labels[0]!r} "
                f"must equal baseline_label {self.baseline_label!r}"
            )
        seen: list[str] = []
        for label in self.labels:
            if label in seen:
                raise ValueError(f"ComparativeBeliefReport: duplicate label {label!r}")
            seen.append(label)
        if not isinstance(self.metrics, Mapping):
            raise TypeError("ComparativeBeliefReport: metrics must be a Mapping")
        if not isinstance(self.manifests, Mapping):
            raise TypeError("ComparativeBeliefReport: manifests must be a Mapping")
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "manifests", dict(self.manifests))
        for label in self.labels:
            if label not in self.manifests:
                raise ValueError(f"ComparativeBeliefReport: manifests must contain label {label!r}")


# ---------------------------------------------------------------------------
# build_run_manifest / verify_run_manifest
# ---------------------------------------------------------------------------


def build_run_manifest(
    *,
    run_id: str,
    config_descriptor: Mapping[str, Any],
    inputs: Sequence[tuple[Path, str]],
    outputs: Sequence[tuple[Path, str]],
) -> RunManifest:
    """Construct a ``RunManifest`` by hashing the files at the given paths.

    Each ``(path, kind)`` tuple becomes a ``ManifestArtifact`` with the
    SHA-256 hex digest of the file's bytes. ``FileNotFoundError`` from
    the underlying ``Path.open`` propagates unchanged.
    """
    in_arts = tuple(
        ManifestArtifact(
            path=str(p),
            sha256=_hash_file_sha256(p),
            kind=k,
        )
        for p, k in inputs
    )
    out_arts = tuple(
        ManifestArtifact(
            path=str(p),
            sha256=_hash_file_sha256(p),
            kind=k,
        )
        for p, k in outputs
    )
    return RunManifest(
        run_id=run_id,
        config_descriptor=dict(config_descriptor),
        inputs=in_arts,
        outputs=out_arts,
    )


def verify_run_manifest(
    manifest: RunManifest,
) -> tuple[bool, tuple[str, ...]]:
    """Re-hash every input and output referenced by ``manifest``.

    Returns ``(ok, messages)``:

    - ``ok`` is ``True`` iff every referenced file exists and its current
      SHA-256 matches the manifest's recorded value.
    - ``messages`` is a tuple of human-readable strings, one per mismatch
      or missing file, in iteration order (inputs first, then outputs).

    This function reads disk; its return value depends on filesystem
    state and is documented as such. It modifies nothing.
    """
    messages: list[str] = []
    ok = True
    for art in (*manifest.inputs, *manifest.outputs):
        p = Path(art.path)
        if not p.exists():
            messages.append(f"missing file: {art.path}")
            ok = False
            continue
        actual = _hash_file_sha256(p)
        if actual != art.sha256:
            messages.append(f"sha256 mismatch: {art.path} expected={art.sha256} actual={actual}")
            ok = False
    return (ok, tuple(messages))


# ---------------------------------------------------------------------------
# build_comparative_report
# ---------------------------------------------------------------------------


def build_comparative_report(
    labeled_summaries: Sequence[LabeledSummary],
) -> ComparativeBeliefReport:
    """Aggregate descriptive deltas across N labeled summaries.

    The first item in ``labeled_summaries`` is the baseline. Deltas for
    every label are ``value - baseline_value`` with ``None`` propagation.
    Manifests are passed through unchanged in the result's ``manifests``
    mapping.

    Raises ``ValueError`` if ``labeled_summaries`` is empty or contains
    duplicate labels.
    """
    if not labeled_summaries:
        raise ValueError("build_comparative_report: labeled_summaries cannot be empty")

    labels_list: list[str] = []
    for ls in labeled_summaries:
        if ls.label in labels_list:
            raise ValueError(f"build_comparative_report: duplicate label {ls.label!r}")
        labels_list.append(ls.label)

    baseline = labeled_summaries[0]
    baseline_label = baseline.label
    baseline_summary = baseline.summary

    metrics: dict[str, MetricDelta] = {}
    for metric_name in _NUMERIC_METRIC_NAMES:
        baseline_value: int | float | None = getattr(baseline_summary, metric_name)
        values: dict[str, int | float | None] = {}
        deltas: dict[str, int | float | None] = {}
        for ls in labeled_summaries:
            v: int | float | None = getattr(ls.summary, metric_name)
            values[ls.label] = v
            if baseline_value is None or v is None:
                deltas[ls.label] = None
            else:
                deltas[ls.label] = v - baseline_value
        metrics[metric_name] = MetricDelta(
            baseline_label=baseline_label,
            baseline_value=baseline_value,
            values=values,
            deltas=deltas,
        )

    manifests: dict[str, RunManifest | None] = {ls.label: ls.manifest for ls in labeled_summaries}

    return ComparativeBeliefReport(
        baseline_label=baseline_label,
        labels=tuple(labels_list),
        metrics=metrics,
        manifests=manifests,
    )


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------


def _decode_artifact(raw: Mapping[str, Any]) -> ManifestArtifact:
    return ManifestArtifact(
        path=raw["path"],
        sha256=raw["sha256"],
        kind=raw["kind"],
    )


def _decode_run_manifest_inner(raw: Mapping[str, Any]) -> RunManifest:
    return RunManifest(
        run_id=raw["run_id"],
        config_descriptor=dict(raw["config_descriptor"]),
        inputs=tuple(_decode_artifact(a) for a in raw["inputs"]),
        outputs=tuple(_decode_artifact(a) for a in raw["outputs"]),
    )


def decode_run_manifest_from_json(
    data: Mapping[str, Any],
) -> RunManifest:
    """Reconstruct a ``RunManifest`` from the canonical envelope JSON.

    Validates ``schema_version`` against
    ``RUN_MANIFEST_SCHEMA_VERSION``; raises ``ValueError`` on mismatch.
    """
    inner = _validate_envelope(
        data,
        schema_version=RUN_MANIFEST_SCHEMA_VERSION,
        inner_key="manifest",
    )
    return _decode_run_manifest_inner(inner)


def decode_consistency_summary_from_json(
    data: Mapping[str, Any],
) -> BeliefConsistencySummary:
    """Reconstruct a ``BeliefConsistencySummary`` from the ADR-0017 envelope.

    Companion to ``decode_belief_report_from_json`` (ADR-0016 / ADR-0017
    pipeline). Validates ``schema_version`` against
    ``BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION``.
    """
    inner = _validate_envelope(
        data,
        schema_version=BELIEF_CONSISTENCY_REPORT_SCHEMA_VERSION,
        inner_key="summary",
    )
    decoded: BeliefConsistencySummary = from_json_dict(BeliefConsistencySummary, inner)
    return decoded


def _decode_metric_delta(raw: Mapping[str, Any]) -> MetricDelta:
    return MetricDelta(
        baseline_label=raw["baseline_label"],
        baseline_value=raw["baseline_value"],
        values=dict(raw["values"]),
        deltas=dict(raw["deltas"]),
    )


def _decode_comparative_inner(
    raw: Mapping[str, Any],
) -> ComparativeBeliefReport:
    analysis_version = raw.get("analysis_version", BELIEF_COMPARISON_ANALYSIS_VERSION)
    if analysis_version != BELIEF_COMPARISON_ANALYSIS_VERSION:
        raise ValueError(
            f"incompatible analysis_version {analysis_version!r}; "
            f"expected {BELIEF_COMPARISON_ANALYSIS_VERSION!r}"
        )
    raw_metrics: Mapping[str, Mapping[str, Any]] = raw["metrics"]
    metrics: dict[str, MetricDelta] = {}
    for name in sorted(raw_metrics):
        metrics[name] = _decode_metric_delta(raw_metrics[name])
    raw_manifests: Mapping[str, Any] = raw["manifests"]
    manifests: dict[str, RunManifest | None] = {}
    for label, m_raw in raw_manifests.items():
        if m_raw is None:
            manifests[label] = None
        else:
            manifests[label] = _decode_run_manifest_inner(m_raw)
    return ComparativeBeliefReport(
        baseline_label=raw["baseline_label"],
        labels=tuple(raw["labels"]),
        metrics=metrics,
        manifests=manifests,
        analysis_version=analysis_version,
    )


def decode_comparative_report_from_json(
    data: Mapping[str, Any],
) -> ComparativeBeliefReport:
    """Reconstruct a ``ComparativeBeliefReport`` from canonical JSON.

    Validates both ``schema_version`` and ``analysis_version`` against
    the literals in this module; raises ``ValueError`` on either
    mismatch.
    """
    inner = _validate_envelope(
        data,
        schema_version=BELIEF_COMPARISON_REPORT_SCHEMA_VERSION,
        inner_key="comparison",
    )
    return _decode_comparative_inner(inner)


# ---------------------------------------------------------------------------
# Encoders + writers
# ---------------------------------------------------------------------------


def encode_run_manifest_to_bytes(manifest: RunManifest) -> bytes:
    """Encode ``manifest`` as canonical JSON bytes.

    ``sort_keys=True``, ``indent=2``, ``ensure_ascii=False``, trailing
    newline, UTF-8 — identical posture to ADR-0013 / ADR-0016 / ADR-0017.
    """
    document = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "manifest": dataclasses.asdict(manifest),
    }
    serialized = json.dumps(
        document,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


def encode_comparative_report_to_bytes(
    report: ComparativeBeliefReport,
) -> bytes:
    """Encode ``report`` as canonical JSON bytes."""
    document = {
        "schema_version": BELIEF_COMPARISON_REPORT_SCHEMA_VERSION,
        "comparison": dataclasses.asdict(report),
    }
    serialized = json.dumps(
        document,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return (serialized + "\n").encode("utf-8")


def generate_run_manifest(manifest: RunManifest, output_path: Path) -> None:
    """Write ``manifest`` as canonical JSON to ``output_path``."""
    output_path.write_bytes(encode_run_manifest_to_bytes(manifest))


def generate_comparative_report(report: ComparativeBeliefReport, output_path: Path) -> None:
    """Write ``report`` as canonical JSON to ``output_path``."""
    output_path.write_bytes(encode_comparative_report_to_bytes(report))


__all__ = [
    "BELIEF_COMPARISON_ANALYSIS_VERSION",
    "BELIEF_COMPARISON_REPORT_SCHEMA_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "ComparativeBeliefReport",
    "LabeledSummary",
    "ManifestArtifact",
    "MetricDelta",
    "RunManifest",
    "build_comparative_report",
    "build_run_manifest",
    "decode_comparative_report_from_json",
    "decode_consistency_summary_from_json",
    "decode_run_manifest_from_json",
    "encode_comparative_report_to_bytes",
    "encode_run_manifest_to_bytes",
    "generate_comparative_report",
    "generate_run_manifest",
    "verify_run_manifest",
]
