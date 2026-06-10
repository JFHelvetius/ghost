"""Tests for the ``ghost verify-properties`` subcommand (ADR-0031..0035
verifier surface).

The CLI is glue around ``verify_baud`` / ``verify_erur`` / ``verify_md``
/ ``verify_rlb`` / ``verify_fpb`` plus formatting + exit-code policy.
These tests exercise the wiring end-to-end against a real smoke MCAP.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from project_ghost.cli import main
from project_ghost.examples.closed_loop_smoke import run_closed_loop_smoke

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def smoke_mcap(tmp_path: Path) -> Path:
    mcap_path = tmp_path / "smoke.mcap"
    run_closed_loop_smoke(mcap_path, n_cycles=10)
    return mcap_path


def test_verify_properties_exit_zero_when_all_hold(
    smoke_mcap: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["verify-properties", "--mcap", str(smoke_mcap)])
    assert rc == 0
    captured = capsys.readouterr()
    # All five property tags appear in the default text output.
    for tag in ("BAUD-v1", "ERUR-v1", "MD-v1", "RLB-v1", "FPB-v1"):
        assert tag in captured.out
        assert f"{tag}: HOLDS" in captured.out


def test_verify_properties_exit_one_when_any_violates(
    smoke_mcap: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A tight ``--max-fire-fraction`` turns FPB into a failing
    regression gate. The CLI must return 1 for any-property-violation
    (CI-friendly exit policy)."""
    rc = main([
        "verify-properties",
        "--mcap", str(smoke_mcap),
        "--max-fire-fraction", "0.5",
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "FPB-v1: VIOLATED" in captured.out
    # Other four still hold — make sure we report them too.
    assert "BAUD-v1: HOLDS" in captured.out


def test_verify_properties_json_mode_is_structured(
    smoke_mcap: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """``--json`` emits a parseable JSON document with all five
    properties under ``.properties.*`` and an ``.all_properties_hold``
    boolean for CI gating."""
    rc = main(["verify-properties", "--mcap", str(smoke_mcap), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    assert doc["all_properties_hold"] is True
    assert set(doc["properties"].keys()) == {
        "BAUD-v1", "ERUR-v1", "MD-v1", "RLB-v1", "FPB-v1",
    }
    # SHA-256 is the same across all reports (same MCAP).
    sha = doc["properties"]["BAUD-v1"]["mcap_sha256"]
    assert len(sha) == 64
    for tag in doc["properties"]:
        assert doc["properties"][tag]["mcap_sha256"] == sha
        assert doc["properties"][tag]["holds"] is True


def test_verify_properties_json_carries_property_specific_fields(
    smoke_mcap: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    main(["verify-properties", "--mcap", str(smoke_mcap), "--json"])
    doc = json.loads(capsys.readouterr().out)
    # BAUD/ERUR/FPB carry M and K.
    for tag in ("BAUD-v1", "ERUR-v1", "FPB-v1"):
        assert doc["properties"][tag]["min_outcomes"] == 4
        assert doc["properties"][tag]["downgrade_threshold"] == 2
    # RLB carries W.
    assert doc["properties"]["RLB-v1"]["max_history"] == 32
    # FPB carries the observed fire fraction.
    assert doc["properties"]["FPB-v1"]["fire_fraction"] == 0.6
    assert doc["properties"]["FPB-v1"]["max_fire_fraction"] == 1.0
    # MD has no parametric fields.
    assert "min_outcomes" not in doc["properties"]["MD-v1"]
    assert "max_history" not in doc["properties"]["MD-v1"]


def test_verify_properties_missing_mcap_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main([
        "verify-properties",
        "--mcap", str(tmp_path / "does_not_exist.mcap"),
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "does not exist" in err


def test_verify_properties_custom_m_and_k_propagate_to_report(
    smoke_mcap: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Passing ``--min-outcomes`` and ``--downgrade-threshold`` reaches
    the BAUD/ERUR/FPB verifiers and is echoed in the JSON report.

    Note: this test does NOT assert ``rc == 0``. Verifying against
    parameters different from those the MCAP was produced under is
    legitimate, but the verdict can be either pass (if the MCAP
    happens to also satisfy the custom-param property) or fail (if
    the recorded behaviour doesn't match what the custom-param policy
    would have emitted). Either way, the parameters must propagate
    into the report — that's all we test here.
    """
    main([
        "verify-properties",
        "--mcap", str(smoke_mcap),
        "--min-outcomes", "8",
        "--downgrade-threshold", "5",
        "--json",
    ])
    doc = json.loads(capsys.readouterr().out)
    for tag in ("BAUD-v1", "ERUR-v1", "FPB-v1"):
        assert doc["properties"][tag]["min_outcomes"] == 8
        assert doc["properties"][tag]["downgrade_threshold"] == 5


def test_verify_properties_custom_max_history_propagates_to_report(
    smoke_mcap: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """``--max-history`` reaches verify_rlb and is echoed in JSON."""
    main([
        "verify-properties",
        "--mcap", str(smoke_mcap),
        "--max-history", "64",
        "--json",
    ])
    doc = json.loads(capsys.readouterr().out)
    assert doc["properties"]["RLB-v1"]["max_history"] == 64


def test_verify_properties_json_is_deterministic(
    smoke_mcap: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Same MCAP + same params produce byte-identical JSON output (the
    verifier is pure and ``json.dumps(sort_keys=True)`` is stable)."""
    main(["verify-properties", "--mcap", str(smoke_mcap), "--json"])
    first = capsys.readouterr().out
    main(["verify-properties", "--mcap", str(smoke_mcap), "--json"])
    second = capsys.readouterr().out
    assert first == second
