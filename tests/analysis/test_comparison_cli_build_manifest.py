"""Tests del CLI `ghost build-manifest` (ADR-0018).

Cubre:

- éxito con --input + --output-artifact + --output
- éxito con --config-json + --config-kv (merge, KV override)
- stdout cuando --output se omite
- archivo --input inexistente → rc=1
- --config-json malformed → rc=1
- --config-json no es objeto JSON → rc=1
- --config-kv sin '=' → rc=1
- --input sin '=' → rc=1
- --output-artifact sin '=' → rc=1
- argparse missing --run-id → rc=2
- byte-identical entre dos invocaciones con mismos inputs
- --help muestra el subcomando
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from project_ghost.analysis import RUN_MANIFEST_SCHEMA_VERSION
from project_ghost.cli import main


def _write(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def test_cli_build_manifest_writes_to_output_file(tmp_path: Path) -> None:
    f_in = tmp_path / "in.bin"
    f_out = tmp_path / "out.bin"
    _write(f_in, b"AAA")
    _write(f_out, b"BBB")
    manifest_path = tmp_path / "manifest.json"

    rc = main(
        [
            "build-manifest",
            "--run-id",
            "test_run",
            "--input",
            f"{f_in}=mcap_truth",
            "--output-artifact",
            f"{f_out}=belief_report",
            "--output",
            str(manifest_path),
        ]
    )

    assert rc == 0
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == RUN_MANIFEST_SCHEMA_VERSION
    assert data["manifest"]["run_id"] == "test_run"
    assert len(data["manifest"]["inputs"]) == 1
    assert data["manifest"]["inputs"][0]["sha256"] == hashlib.sha256(b"AAA").hexdigest()
    assert data["manifest"]["inputs"][0]["kind"] == "mcap_truth"
    assert len(data["manifest"]["outputs"]) == 1
    assert data["manifest"]["outputs"][0]["sha256"] == hashlib.sha256(b"BBB").hexdigest()


def test_cli_build_manifest_writes_to_stdout_when_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "f"
    _write(f, b"x")
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r1",
            "--input",
            f"{f}=data",
        ]
    )
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["schema_version"] == RUN_MANIFEST_SCHEMA_VERSION
    assert parsed["manifest"]["run_id"] == "r1"


def test_cli_build_manifest_merges_config_json_and_kv(tmp_path: Path) -> None:
    f = tmp_path / "f"
    _write(f, b"x")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(
        json.dumps({"seed": 42, "sigma": 0.05, "estimator": "Noisy"}),
        encoding="utf-8",
    )
    out = tmp_path / "m.json"

    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-json",
            str(cfg),
            "--config-kv",
            "sigma=0.10",  # override
            "--config-kv",
            "extra=foo",
            "--input",
            f"{f}=data",
            "--output",
            str(out),
        ]
    )

    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    cfg_desc = data["manifest"]["config_descriptor"]
    assert cfg_desc["seed"] == 42
    assert cfg_desc["sigma"] == "0.10"  # KV override is string-typed
    assert cfg_desc["estimator"] == "Noisy"
    assert cfg_desc["extra"] == "foo"


def test_cli_build_manifest_byte_identical_outputs(tmp_path: Path) -> None:
    f = tmp_path / "fixed.bin"
    _write(f, b"deterministic-bytes-for-this-test")
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"

    main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-kv",
            "k=v",
            "--input",
            f"{f}=data",
            "--output",
            str(a),
        ]
    )
    main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-kv",
            "k=v",
            "--input",
            f"{f}=data",
            "--output",
            str(b),
        ]
    )

    assert a.read_bytes() == b.read_bytes()


def test_cli_build_manifest_missing_input_file_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "does_not_exist.bin"
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--input",
            f"{bad}=data",
        ]
    )
    assert rc == 1
    assert capsys.readouterr().err  # algo se reportó


def test_cli_build_manifest_malformed_config_json_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{this is not valid", encoding="utf-8")
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-json",
            str(bad),
        ]
    )
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_cli_build_manifest_non_object_config_json_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "list.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-json",
            str(bad),
        ]
    )
    assert rc == 1
    assert "JSON object" in capsys.readouterr().err


def test_cli_build_manifest_nonexistent_config_json_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-json",
            str(tmp_path / "missing.json"),
        ]
    )
    assert rc == 1
    assert capsys.readouterr().err


def test_cli_build_manifest_kv_without_equals_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-kv",
            "noequals",
        ]
    )
    assert rc == 1
    assert "KEY=VALUE" in capsys.readouterr().err


def test_cli_build_manifest_input_without_equals_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--input",
            "no_separator",
        ]
    )
    assert rc == 1
    assert "PATH=KIND" in capsys.readouterr().err


def test_cli_build_manifest_output_artifact_without_equals_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--output-artifact",
            "no_separator",
        ]
    )
    assert rc == 1
    assert "PATH=KIND" in capsys.readouterr().err


def test_cli_build_manifest_missing_run_id_fails() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["build-manifest"])
    assert exc_info.value.code == 2


def test_cli_build_manifest_empty_run_id_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "",
        ]
    )
    assert rc == 1
    assert "run_id" in capsys.readouterr().err


def test_cli_build_manifest_kv_empty_key_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`=value` tiene KEY vacío → debe ser rechazado."""
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--config-kv",
            "=value",
        ]
    )
    assert rc == 1
    assert "KEY must be non-empty" in capsys.readouterr().err


def test_cli_build_manifest_input_empty_path_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`=kind` tiene PATH vacío → debe ser rechazado."""
    rc = main(
        [
            "build-manifest",
            "--run-id",
            "r",
            "--input",
            "=kind",
        ]
    )
    assert rc == 1
    assert "non-empty" in capsys.readouterr().err


def test_cli_help_includes_build_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "build-manifest" in out
