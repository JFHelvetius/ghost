"""Tests del módulo `analysis.comparison` (ADR-0018 core).

Cubre, por categorías:

- `ManifestArtifact`: validación de path, kind, sha256.
- `RunManifest`: validación de run_id, config_descriptor JSON-safe,
  inputs/outputs tipo tuple, frozen, normalización de MappingProxyType.
- `build_run_manifest`: hashing single/multi/empty/large files; archivo
  inexistente.
- `verify_run_manifest`: archivos sin cambios; modificación detectada;
  archivo borrado detectado.
- `LabeledSummary`: con/sin manifest; label vacío.
- `MetricDelta`: int / float / None; baseline self = 0; rechazo
  baseline ausente.
- `build_comparative_report`: N=1, N=2, N=3; vacío; labels duplicados;
  preservación de orden; cobertura de los 20 metric names.
- Deltas: int → int, float → float, None propagation.
- Pass-through de manifests.
- JSON canónico: sort_keys, indent=2, trailing newline, UTF-8.
- Determinismo: dos encodings byte-idénticos; builds equal.
- Round-trip: encode → decode → equal.
- Validación de schema_version / analysis_version.
- Writer output byte-idéntico.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, Any

import pytest

from project_ghost.analysis import (
    BeliefConsistencySummary,
    encode_consistency_summary_to_bytes,
)
from project_ghost.analysis.comparison import (
    BELIEF_COMPARISON_ANALYSIS_VERSION,
    BELIEF_COMPARISON_REPORT_SCHEMA_VERSION,
    RUN_MANIFEST_SCHEMA_VERSION,
    ComparativeBeliefReport,
    LabeledSummary,
    ManifestArtifact,
    MetricDelta,
    RunManifest,
    build_comparative_report,
    build_run_manifest,
    decode_comparative_report_from_json,
    decode_consistency_summary_from_json,
    decode_run_manifest_from_json,
    encode_comparative_report_to_bytes,
    encode_run_manifest_to_bytes,
    generate_comparative_report,
    generate_run_manifest,
    verify_run_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DUMMY_SHA256 = "a" * 64


def _summary_with(**overrides: Any) -> BeliefConsistencySummary:
    """Construct a BeliefConsistencySummary with the empty defaults
    overridden by ``overrides``."""
    base: dict[str, Any] = {
        "total_samples": 0,
        "samples_with_covariance": 0,
        "samples_without_covariance": 0,
        "timestamp_first_ns": None,
        "timestamp_last_ns": None,
        "timestamp_span_ns": None,
        "position_error_min_m": 0.0,
        "position_error_max_m": 0.0,
        "position_error_mean_m": 0.0,
        "orientation_error_min_rad": 0.0,
        "orientation_error_max_rad": 0.0,
        "orientation_error_mean_rad": 0.0,
        "covariance_trace_min": None,
        "covariance_trace_max": None,
        "covariance_trace_mean": None,
        "covariance_condition_number_min": None,
        "covariance_condition_number_max": None,
        "covariance_condition_number_mean": None,
        "samples_with_finite_trace": 0,
        "samples_with_finite_condition_number": 0,
    }
    base.update(overrides)
    return BeliefConsistencySummary(**base)


def _empty_summary() -> BeliefConsistencySummary:
    return _summary_with()


# ---------------------------------------------------------------------------
# ManifestArtifact
# ---------------------------------------------------------------------------


def test_manifest_artifact_valid_construction() -> None:
    art = ManifestArtifact(path="a.txt", sha256=_DUMMY_SHA256, kind="data")
    assert art.path == "a.txt"
    assert art.sha256 == _DUMMY_SHA256
    assert art.kind == "data"


def test_manifest_artifact_is_frozen() -> None:
    art = ManifestArtifact(path="a", sha256=_DUMMY_SHA256, kind="x")
    with pytest.raises(FrozenInstanceError):
        art.path = "b"  # type: ignore[misc]


def test_manifest_artifact_rejects_empty_path() -> None:
    with pytest.raises(ValueError, match="path"):
        ManifestArtifact(path="", sha256=_DUMMY_SHA256, kind="x")


def test_manifest_artifact_rejects_empty_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        ManifestArtifact(path="a", sha256=_DUMMY_SHA256, kind="")


def test_manifest_artifact_rejects_short_sha256() -> None:
    with pytest.raises(ValueError, match="sha256"):
        ManifestArtifact(path="a", sha256="abc", kind="x")


def test_manifest_artifact_rejects_long_sha256() -> None:
    with pytest.raises(ValueError, match="sha256"):
        ManifestArtifact(path="a", sha256="a" * 100, kind="x")


def test_manifest_artifact_rejects_uppercase_sha256() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        ManifestArtifact(path="a", sha256="A" * 64, kind="x")


def test_manifest_artifact_rejects_non_hex_sha256() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        ManifestArtifact(path="a", sha256="g" * 64, kind="x")


# ---------------------------------------------------------------------------
# RunManifest
# ---------------------------------------------------------------------------


def test_run_manifest_valid_construction_empty_io() -> None:
    m = RunManifest(run_id="r1", config_descriptor={}, inputs=(), outputs=())
    assert m.run_id == "r1"
    assert m.inputs == ()
    assert m.outputs == ()


def test_run_manifest_rejects_empty_run_id() -> None:
    with pytest.raises(ValueError, match="run_id"):
        RunManifest(run_id="", config_descriptor={}, inputs=(), outputs=())


def test_run_manifest_rejects_non_mapping_config() -> None:
    with pytest.raises(TypeError, match="Mapping"):
        RunManifest(
            run_id="r",
            config_descriptor=[],  # type: ignore[arg-type]
            inputs=(),
            outputs=(),
        )


def test_run_manifest_rejects_non_json_safe_config() -> None:
    with pytest.raises(TypeError, match="JSON-safe"):
        RunManifest(
            run_id="r",
            config_descriptor={"x": {1, 2, 3}},
            inputs=(),
            outputs=(),
        )


def test_run_manifest_rejects_non_tuple_inputs() -> None:
    with pytest.raises(TypeError, match=r"inputs.*tuple"):
        RunManifest(
            run_id="r",
            config_descriptor={},
            inputs=[],  # type: ignore[arg-type]
            outputs=(),
        )


def test_run_manifest_rejects_non_tuple_outputs() -> None:
    with pytest.raises(TypeError, match=r"outputs.*tuple"):
        RunManifest(
            run_id="r",
            config_descriptor={},
            inputs=(),
            outputs=[],  # type: ignore[arg-type]
        )


def test_run_manifest_is_frozen() -> None:
    m = RunManifest(run_id="r", config_descriptor={}, inputs=(), outputs=())
    with pytest.raises(FrozenInstanceError):
        m.run_id = "x"  # type: ignore[misc]


def test_run_manifest_normalizes_mapping_to_dict() -> None:
    """Caller pasa MappingProxyType; storage debe ser dict para serialización
    consistente."""
    from types import MappingProxyType

    cfg = MappingProxyType({"k": "v"})
    m = RunManifest(run_id="r", config_descriptor=cfg, inputs=(), outputs=())
    # El field almacenado debe ser dict para que dataclasses.asdict y
    # json.dumps lo manejen.
    assert isinstance(m.config_descriptor, dict)
    assert m.config_descriptor == {"k": "v"}


def test_run_manifest_complex_json_safe_config_round_trip() -> None:
    cfg = {
        "estimator": "Noisy",
        "stds": {"pos": 0.05, "orient": 0.01},
        "seeds": [1, 2, 3],
        "flag": True,
        "value": None,
    }
    m = RunManifest(run_id="r", config_descriptor=cfg, inputs=(), outputs=())
    encoded = encode_run_manifest_to_bytes(m)
    decoded = decode_run_manifest_from_json(
        json.loads(encoded.decode("utf-8"))
    )
    assert decoded.config_descriptor == cfg


# ---------------------------------------------------------------------------
# build_run_manifest
# ---------------------------------------------------------------------------


def test_build_run_manifest_single_input(tmp_path: Path) -> None:
    p = tmp_path / "in.txt"
    p.write_bytes(b"hello")
    expected = hashlib.sha256(b"hello").hexdigest()

    m = build_run_manifest(
        run_id="t", config_descriptor={}, inputs=[(p, "data")], outputs=[]
    )

    assert len(m.inputs) == 1
    assert m.inputs[0].sha256 == expected
    assert m.inputs[0].path == str(p)
    assert m.inputs[0].kind == "data"


def test_build_run_manifest_multiple_inputs_and_outputs(tmp_path: Path) -> None:
    pa = tmp_path / "a"
    pb = tmp_path / "b"
    pc = tmp_path / "c"
    pa.write_bytes(b"AAA")
    pb.write_bytes(b"BBB")
    pc.write_bytes(b"CCC")

    m = build_run_manifest(
        run_id="t",
        config_descriptor={"seed": 42},
        inputs=[(pa, "x"), (pb, "y")],
        outputs=[(pc, "z")],
    )

    assert len(m.inputs) == 2
    assert len(m.outputs) == 1
    assert m.inputs[0].sha256 == hashlib.sha256(b"AAA").hexdigest()
    assert m.outputs[0].sha256 == hashlib.sha256(b"CCC").hexdigest()
    assert m.config_descriptor == {"seed": 42}


def test_build_run_manifest_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty"
    p.write_bytes(b"")
    expected = hashlib.sha256(b"").hexdigest()

    m = build_run_manifest(
        run_id="t", config_descriptor={}, inputs=[(p, "data")], outputs=[]
    )
    assert m.inputs[0].sha256 == expected


def test_build_run_manifest_large_file_multi_chunk(tmp_path: Path) -> None:
    """Files > 1 MiB use multiple read iterations; verify rolling SHA-256."""
    p = tmp_path / "big"
    content = b"X" * (3 * 1024 * 1024 + 17)  # 3 MiB + 17 bytes
    p.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()

    m = build_run_manifest(
        run_id="t", config_descriptor={}, inputs=[(p, "data")], outputs=[]
    )
    assert m.inputs[0].sha256 == expected


def test_build_run_manifest_missing_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        build_run_manifest(
            run_id="t",
            config_descriptor={},
            inputs=[(p, "x")],
            outputs=[],
        )


# ---------------------------------------------------------------------------
# verify_run_manifest
# ---------------------------------------------------------------------------


def test_verify_run_manifest_unchanged_files(tmp_path: Path) -> None:
    p_in = tmp_path / "in"
    p_out = tmp_path / "out"
    p_in.write_bytes(b"input_data")
    p_out.write_bytes(b"output_data")

    m = build_run_manifest(
        run_id="t",
        config_descriptor={},
        inputs=[(p_in, "x")],
        outputs=[(p_out, "y")],
    )

    ok, msgs = verify_run_manifest(m)
    assert ok is True
    assert msgs == ()


def test_verify_run_manifest_detects_modified_input(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_bytes(b"original")
    m = build_run_manifest(
        run_id="t",
        config_descriptor={},
        inputs=[(p, "x")],
        outputs=[],
    )
    p.write_bytes(b"tampered")

    ok, msgs = verify_run_manifest(m)
    assert ok is False
    assert any("sha256 mismatch" in msg for msg in msgs)


def test_verify_run_manifest_detects_modified_output(tmp_path: Path) -> None:
    p_in = tmp_path / "in"
    p_out = tmp_path / "out"
    p_in.write_bytes(b"a")
    p_out.write_bytes(b"b")
    m = build_run_manifest(
        run_id="t",
        config_descriptor={},
        inputs=[(p_in, "x")],
        outputs=[(p_out, "y")],
    )
    p_out.write_bytes(b"modified")

    ok, msgs = verify_run_manifest(m)
    assert ok is False
    assert any("sha256 mismatch" in msg and str(p_out) in msg for msg in msgs)


def test_verify_run_manifest_detects_missing_file(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_bytes(b"data")
    m = build_run_manifest(
        run_id="t",
        config_descriptor={},
        inputs=[(p, "x")],
        outputs=[],
    )
    p.unlink()

    ok, msgs = verify_run_manifest(m)
    assert ok is False
    assert any("missing file" in msg for msg in msgs)


# ---------------------------------------------------------------------------
# LabeledSummary
# ---------------------------------------------------------------------------


def test_labeled_summary_with_manifest_construction(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_bytes(b"x")
    manifest = build_run_manifest(
        run_id="r",
        config_descriptor={},
        inputs=[(p, "x")],
        outputs=[],
    )
    ls = LabeledSummary(label="A", summary=_empty_summary(), manifest=manifest)
    assert ls.label == "A"
    assert ls.manifest is manifest


def test_labeled_summary_without_manifest() -> None:
    ls = LabeledSummary(label="B", summary=_empty_summary(), manifest=None)
    assert ls.manifest is None


def test_labeled_summary_rejects_empty_label() -> None:
    with pytest.raises(ValueError, match="label"):
        LabeledSummary(label="", summary=_empty_summary(), manifest=None)


def test_labeled_summary_is_frozen() -> None:
    ls = LabeledSummary(label="A", summary=_empty_summary(), manifest=None)
    with pytest.raises(FrozenInstanceError):
        ls.label = "B"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MetricDelta
# ---------------------------------------------------------------------------


def test_metric_delta_int_values() -> None:
    d = MetricDelta(
        baseline_label="A",
        baseline_value=5,
        values={"A": 5, "B": 7},
        deltas={"A": 0, "B": 2},
    )
    assert d.deltas["A"] == 0
    assert d.deltas["B"] == 2
    assert isinstance(d.deltas["A"], int)


def test_metric_delta_float_values() -> None:
    d = MetricDelta(
        baseline_label="A",
        baseline_value=0.5,
        values={"A": 0.5, "B": 1.5},
        deltas={"A": 0.0, "B": 1.0},
    )
    assert isinstance(d.deltas["B"], float)


def test_metric_delta_none_baseline() -> None:
    d = MetricDelta(
        baseline_label="A",
        baseline_value=None,
        values={"A": None, "B": None},
        deltas={"A": None, "B": None},
    )
    assert d.baseline_value is None
    assert d.deltas["A"] is None
    assert d.deltas["B"] is None


def test_metric_delta_rejects_empty_baseline_label() -> None:
    with pytest.raises(ValueError, match="baseline_label"):
        MetricDelta(
            baseline_label="",
            baseline_value=None,
            values={"x": None},
            deltas={"x": None},
        )


def test_metric_delta_rejects_baseline_missing_from_values() -> None:
    with pytest.raises(ValueError, match="values"):
        MetricDelta(
            baseline_label="A",
            baseline_value=1,
            values={"B": 1},
            deltas={"B": 0},
        )


def test_metric_delta_rejects_baseline_missing_from_deltas() -> None:
    with pytest.raises(ValueError, match="deltas"):
        MetricDelta(
            baseline_label="A",
            baseline_value=1,
            values={"A": 1},
            deltas={"B": 0},
        )


def test_metric_delta_rejects_non_mapping_values() -> None:
    with pytest.raises(TypeError, match=r"values.*Mapping"):
        MetricDelta(
            baseline_label="A",
            baseline_value=None,
            values=[],  # type: ignore[arg-type]
            deltas={"A": None},
        )


def test_metric_delta_rejects_non_mapping_deltas() -> None:
    with pytest.raises(TypeError, match=r"deltas.*Mapping"):
        MetricDelta(
            baseline_label="A",
            baseline_value=None,
            values={"A": None},
            deltas=[],  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# ComparativeBeliefReport — construction-time invariants
# ---------------------------------------------------------------------------


def test_comparative_report_rejects_baseline_mismatch() -> None:
    with pytest.raises(ValueError, match="baseline_label"):
        ComparativeBeliefReport(
            baseline_label="A",
            labels=("B",),
            metrics={},
            manifests={"B": None},
        )


def test_comparative_report_rejects_empty_baseline_label() -> None:
    with pytest.raises(ValueError, match="baseline_label"):
        ComparativeBeliefReport(
            baseline_label="",
            labels=("A",),
            metrics={},
            manifests={"A": None},
        )


def test_comparative_report_rejects_non_tuple_labels() -> None:
    with pytest.raises(TypeError, match="labels"):
        ComparativeBeliefReport(
            baseline_label="A",
            labels=["A"],  # type: ignore[arg-type]
            metrics={},
            manifests={"A": None},
        )


def test_comparative_report_rejects_empty_labels() -> None:
    with pytest.raises(ValueError, match="labels"):
        ComparativeBeliefReport(
            baseline_label="A",
            labels=(),
            metrics={},
            manifests={},
        )


def test_comparative_report_rejects_duplicate_labels() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ComparativeBeliefReport(
            baseline_label="A",
            labels=("A", "A"),
            metrics={},
            manifests={"A": None},
        )


def test_comparative_report_rejects_missing_manifest_entry() -> None:
    with pytest.raises(ValueError, match="manifests"):
        ComparativeBeliefReport(
            baseline_label="A",
            labels=("A", "B"),
            metrics={},
            manifests={"A": None},
        )


def test_comparative_report_rejects_non_mapping_metrics() -> None:
    with pytest.raises(TypeError, match="metrics"):
        ComparativeBeliefReport(
            baseline_label="A",
            labels=("A",),
            metrics=[],  # type: ignore[arg-type]
            manifests={"A": None},
        )


def test_comparative_report_rejects_non_mapping_manifests() -> None:
    with pytest.raises(TypeError, match="manifests"):
        ComparativeBeliefReport(
            baseline_label="A",
            labels=("A",),
            metrics={},
            manifests=[],  # type: ignore[arg-type]
        )


def test_comparative_report_is_frozen() -> None:
    r = ComparativeBeliefReport(
        baseline_label="A",
        labels=("A",),
        metrics={},
        manifests={"A": None},
    )
    with pytest.raises(FrozenInstanceError):
        r.baseline_label = "B"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_comparative_report — happy paths
# ---------------------------------------------------------------------------


def test_build_comparative_report_n1() -> None:
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=_empty_summary(), manifest=None)]
    )
    assert report.baseline_label == "A"
    assert report.labels == ("A",)
    assert len(report.metrics) == 20


def test_build_comparative_report_n2_int_delta() -> None:
    s_a = _summary_with(total_samples=10)
    s_b = _summary_with(total_samples=25)
    report = build_comparative_report(
        [
            LabeledSummary(label="A", summary=s_a, manifest=None),
            LabeledSummary(label="B", summary=s_b, manifest=None),
        ]
    )
    metric = report.metrics["total_samples"]
    assert metric.baseline_value == 10
    assert metric.values == {"A": 10, "B": 25}
    assert metric.deltas == {"A": 0, "B": 15}
    assert isinstance(metric.deltas["A"], int)
    assert isinstance(metric.deltas["B"], int)


def test_build_comparative_report_n2_float_delta() -> None:
    s_a = _summary_with(position_error_mean_m=0.5)
    s_b = _summary_with(position_error_mean_m=0.8)
    report = build_comparative_report(
        [
            LabeledSummary(label="A", summary=s_a, manifest=None),
            LabeledSummary(label="B", summary=s_b, manifest=None),
        ]
    )
    metric = report.metrics["position_error_mean_m"]
    assert metric.baseline_value == 0.5
    assert metric.deltas["A"] == 0.0
    assert metric.deltas["B"] is not None
    assert abs(metric.deltas["B"] - 0.3) < 1e-12
    assert isinstance(metric.deltas["B"], float)


def test_build_comparative_report_n3() -> None:
    summaries = [_summary_with(total_samples=v) for v in (10, 20, 30)]
    report = build_comparative_report(
        [
            LabeledSummary(label=lbl, summary=s, manifest=None)
            for lbl, s in zip(["A", "B", "C"], summaries, strict=True)
        ]
    )
    assert report.labels == ("A", "B", "C")
    metric = report.metrics["total_samples"]
    assert metric.deltas == {"A": 0, "B": 10, "C": 20}


def test_build_comparative_report_baseline_self_delta_is_zero_int() -> None:
    s = _summary_with(total_samples=7)
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=s, manifest=None)]
    )
    assert report.metrics["total_samples"].deltas["A"] == 0


def test_build_comparative_report_baseline_self_delta_is_zero_float() -> None:
    s = _summary_with(position_error_max_m=1.25)
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=s, manifest=None)]
    )
    assert report.metrics["position_error_max_m"].deltas["A"] == 0.0


def test_build_comparative_report_baseline_none_yields_none_delta() -> None:
    """Si el baseline tiene None, todos los deltas son None — incluido
    el self-delta del baseline."""
    s_a = _summary_with(timestamp_first_ns=None)
    s_b = _summary_with(timestamp_first_ns=100)
    report = build_comparative_report(
        [
            LabeledSummary(label="A", summary=s_a, manifest=None),
            LabeledSummary(label="B", summary=s_b, manifest=None),
        ]
    )
    metric = report.metrics["timestamp_first_ns"]
    assert metric.baseline_value is None
    assert metric.deltas["A"] is None
    assert metric.deltas["B"] is None


def test_build_comparative_report_value_none_yields_none_delta() -> None:
    """Si un label tiene None, su delta es None aunque baseline sea int."""
    s_a = _summary_with(timestamp_first_ns=100)
    s_b = _summary_with(timestamp_first_ns=None)
    report = build_comparative_report(
        [
            LabeledSummary(label="A", summary=s_a, manifest=None),
            LabeledSummary(label="B", summary=s_b, manifest=None),
        ]
    )
    metric = report.metrics["timestamp_first_ns"]
    assert metric.deltas["A"] == 0
    assert metric.deltas["B"] is None


def test_build_comparative_report_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_comparative_report([])


def test_build_comparative_report_duplicate_labels_raises() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        build_comparative_report(
            [
                LabeledSummary(label="X", summary=_empty_summary(), manifest=None),
                LabeledSummary(label="X", summary=_empty_summary(), manifest=None),
            ]
        )


def test_build_comparative_report_preserves_input_order() -> None:
    """labels[] sigue exactamente el orden de entrada; el baseline es el
    primero, sin re-ordenamiento alfabético."""
    s = _empty_summary()
    report = build_comparative_report(
        [
            LabeledSummary(label="Z", summary=s, manifest=None),
            LabeledSummary(label="A", summary=s, manifest=None),
            LabeledSummary(label="M", summary=s, manifest=None),
        ]
    )
    assert report.labels == ("Z", "A", "M")
    assert report.baseline_label == "Z"


def test_build_comparative_report_covers_all_20_metric_names() -> None:
    """Verifica que el reporte cubre exactamente los 20 campos numéricos
    de BeliefConsistencySummary."""
    s = _empty_summary()
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=s, manifest=None)]
    )
    expected = {
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
    }
    assert set(report.metrics.keys()) == expected
    assert len(expected) == 20


def test_build_comparative_report_passes_through_manifests(
    tmp_path: Path,
) -> None:
    p = tmp_path / "f"
    p.write_bytes(b"x")
    m = build_run_manifest(
        run_id="A", config_descriptor={}, inputs=[(p, "x")], outputs=[]
    )
    report = build_comparative_report(
        [
            LabeledSummary(label="A", summary=_empty_summary(), manifest=m),
            LabeledSummary(label="B", summary=_empty_summary(), manifest=None),
        ]
    )
    assert report.manifests["A"] == m
    assert report.manifests["B"] is None


# ---------------------------------------------------------------------------
# JSON canonical encoding
# ---------------------------------------------------------------------------


def test_encode_run_manifest_trailing_newline() -> None:
    m = RunManifest(run_id="r", config_descriptor={}, inputs=(), outputs=())
    assert encode_run_manifest_to_bytes(m).endswith(b"\n")


def test_encode_run_manifest_uses_indent_2() -> None:
    m = RunManifest(run_id="r", config_descriptor={}, inputs=(), outputs=())
    encoded = encode_run_manifest_to_bytes(m)
    assert encoded.count(b"\n") > 1


def test_encode_run_manifest_keys_sorted() -> None:
    m = RunManifest(run_id="r", config_descriptor={}, inputs=(), outputs=())
    encoded = encode_run_manifest_to_bytes(m).decode("utf-8")
    # Top-level: "manifest" precede a "schema_version" alfabéticamente.
    idx_manifest = encoded.index('"manifest"')
    idx_schema = encoded.index('"schema_version"')
    assert idx_manifest < idx_schema


def test_encode_run_manifest_is_valid_utf8_json() -> None:
    m = RunManifest(
        run_id="r",
        config_descriptor={"k": "valor con tildes á é í"},
        inputs=(),
        outputs=(),
    )
    parsed = json.loads(encode_run_manifest_to_bytes(m).decode("utf-8"))
    assert parsed["schema_version"] == RUN_MANIFEST_SCHEMA_VERSION
    assert parsed["manifest"]["config_descriptor"]["k"] == "valor con tildes á é í"


def test_encode_comparative_report_trailing_newline() -> None:
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=_empty_summary(), manifest=None)]
    )
    assert encode_comparative_report_to_bytes(report).endswith(b"\n")


def test_encode_comparative_report_envelope_structure() -> None:
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=_empty_summary(), manifest=None)]
    )
    parsed = json.loads(
        encode_comparative_report_to_bytes(report).decode("utf-8")
    )
    assert (
        parsed["schema_version"]
        == BELIEF_COMPARISON_REPORT_SCHEMA_VERSION
    )
    assert "comparison" in parsed
    assert parsed["comparison"]["baseline_label"] == "A"
    assert (
        parsed["comparison"]["analysis_version"]
        == BELIEF_COMPARISON_ANALYSIS_VERSION
    )


# ---------------------------------------------------------------------------
# Determinism: byte-identical reproducibility
# ---------------------------------------------------------------------------


def test_encode_run_manifest_byte_identical() -> None:
    m = RunManifest(
        run_id="r",
        config_descriptor={"x": 1, "y": [1, 2, 3]},
        inputs=(),
        outputs=(),
    )
    assert encode_run_manifest_to_bytes(m) == encode_run_manifest_to_bytes(m)


def test_encode_comparative_report_byte_identical() -> None:
    s = _summary_with(total_samples=10)
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=s, manifest=None)]
    )
    assert encode_comparative_report_to_bytes(
        report
    ) == encode_comparative_report_to_bytes(report)


def test_build_comparative_report_field_equal_across_calls() -> None:
    s_a = _summary_with(total_samples=5)
    s_b = _summary_with(total_samples=7)
    inputs = [
        LabeledSummary(label="A", summary=s_a, manifest=None),
        LabeledSummary(label="B", summary=s_b, manifest=None),
    ]
    assert build_comparative_report(inputs) == build_comparative_report(inputs)


def test_sha256_stable_across_repeated_encodings() -> None:
    report = build_comparative_report(
        [
            LabeledSummary(
                label=lbl, summary=_summary_with(total_samples=i), manifest=None
            )
            for i, lbl in enumerate(["A", "B", "C"])
        ]
    )
    hashes = {
        hashlib.sha256(encode_comparative_report_to_bytes(report)).hexdigest()
        for _ in range(5)
    }
    assert len(hashes) == 1


# ---------------------------------------------------------------------------
# Round-trip decoders
# ---------------------------------------------------------------------------


def test_run_manifest_round_trip_with_file(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_bytes(b"hello")
    original = build_run_manifest(
        run_id="r",
        config_descriptor={"seed": 42, "sigma": 0.1},
        inputs=[(p, "data")],
        outputs=[],
    )
    decoded = decode_run_manifest_from_json(
        json.loads(encode_run_manifest_to_bytes(original).decode("utf-8"))
    )
    assert decoded == original


def test_comparative_report_round_trip_no_manifests() -> None:
    s_a = _summary_with(total_samples=5)
    s_b = _summary_with(total_samples=7)
    original = build_comparative_report(
        [
            LabeledSummary(label="A", summary=s_a, manifest=None),
            LabeledSummary(label="B", summary=s_b, manifest=None),
        ]
    )
    decoded = decode_comparative_report_from_json(
        json.loads(
            encode_comparative_report_to_bytes(original).decode("utf-8")
        )
    )
    assert decoded == original


def test_comparative_report_round_trip_with_manifests(tmp_path: Path) -> None:
    p = tmp_path / "f"
    p.write_bytes(b"x")
    m = build_run_manifest(
        run_id="A",
        config_descriptor={"k": 1},
        inputs=[(p, "x")],
        outputs=[],
    )
    s = _summary_with(total_samples=10)
    original = build_comparative_report(
        [LabeledSummary(label="A", summary=s, manifest=m)]
    )
    decoded = decode_comparative_report_from_json(
        json.loads(
            encode_comparative_report_to_bytes(original).decode("utf-8")
        )
    )
    assert decoded == original


def test_decode_consistency_summary_envelope() -> None:
    summary = _summary_with(total_samples=42, position_error_max_m=0.7)
    data = json.loads(
        encode_consistency_summary_to_bytes(summary).decode("utf-8")
    )
    decoded = decode_consistency_summary_from_json(data)
    assert decoded == summary


# ---------------------------------------------------------------------------
# Schema / analysis_version validation
# ---------------------------------------------------------------------------


def test_decode_run_manifest_schema_mismatch_raises() -> None:
    data: dict[str, Any] = {"schema_version": "999", "manifest": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_run_manifest_from_json(data)


def test_decode_run_manifest_missing_schema_raises() -> None:
    data: dict[str, Any] = {"manifest": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_run_manifest_from_json(data)


def test_decode_run_manifest_missing_inner_raises() -> None:
    data: dict[str, Any] = {"schema_version": RUN_MANIFEST_SCHEMA_VERSION}
    with pytest.raises(ValueError, match="manifest"):
        decode_run_manifest_from_json(data)


def test_decode_run_manifest_non_mapping_raises() -> None:
    with pytest.raises(TypeError, match="mapping"):
        decode_run_manifest_from_json("not a dict")  # type: ignore[arg-type]


def test_decode_run_manifest_inner_non_mapping_raises() -> None:
    data: dict[str, Any] = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "manifest": [1, 2, 3],
    }
    with pytest.raises(TypeError, match="mapping"):
        decode_run_manifest_from_json(data)


def test_decode_comparative_report_schema_mismatch_raises() -> None:
    data: dict[str, Any] = {"schema_version": "999", "comparison": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_comparative_report_from_json(data)


def test_decode_comparative_report_analysis_version_mismatch_raises() -> None:
    data: dict[str, Any] = {
        "schema_version": BELIEF_COMPARISON_REPORT_SCHEMA_VERSION,
        "comparison": {
            "analysis_version": 999,
            "baseline_label": "A",
            "labels": ["A"],
            "metrics": {},
            "manifests": {"A": None},
        },
    }
    with pytest.raises(ValueError, match="analysis_version"):
        decode_comparative_report_from_json(data)


def test_decode_consistency_summary_schema_mismatch_raises() -> None:
    data: dict[str, Any] = {"schema_version": "999", "summary": {}}
    with pytest.raises(ValueError, match="schema_version"):
        decode_consistency_summary_from_json(data)


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def test_generate_run_manifest_writes_canonical_bytes(
    tmp_path: Path,
) -> None:
    m = RunManifest(run_id="r", config_descriptor={}, inputs=(), outputs=())
    p = tmp_path / "manifest.json"
    generate_run_manifest(m, p)
    assert p.read_bytes() == encode_run_manifest_to_bytes(m)


def test_generate_run_manifest_two_writes_byte_identical(
    tmp_path: Path,
) -> None:
    m = RunManifest(run_id="r", config_descriptor={"k": 1}, inputs=(), outputs=())
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    generate_run_manifest(m, a)
    generate_run_manifest(m, b)
    assert a.read_bytes() == b.read_bytes()


def test_generate_comparative_report_writes_canonical_bytes(
    tmp_path: Path,
) -> None:
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=_empty_summary(), manifest=None)]
    )
    p = tmp_path / "comp.json"
    generate_comparative_report(report, p)
    assert p.read_bytes() == encode_comparative_report_to_bytes(report)


def test_generate_comparative_report_two_writes_byte_identical(
    tmp_path: Path,
) -> None:
    report = build_comparative_report(
        [LabeledSummary(label="A", summary=_empty_summary(), manifest=None)]
    )
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    generate_comparative_report(report, a)
    generate_comparative_report(report, b)
    assert a.read_bytes() == b.read_bytes()
