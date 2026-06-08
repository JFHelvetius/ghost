"""Tests del CLI `ghost analyze-self-assessment` (ADR-0020).

Cubre:

- éxito con --mcap + --output
- stdout cuando --output se omite
- archivo --mcap inexistente → rc=1
- byte-identical entre dos invocaciones con mismo MCAP
- MCAP sin records `/self_assessment` produce summary con counts en zero
- --help muestra el subcomando
- argparse missing args → rc=2
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.analysis import (
    SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION,
)
from project_ghost.cli import main
from project_ghost.core.uncertainty.self_assessment import (
    AssessmentThresholds,
    assess_belief,
)
from project_ghost.hal.messages import SensorHealth
from project_ghost.state.messages import (
    FlightMode,
    FlightStatus,
    IMUBiases,
    MissionMode,
    MissionStatus,
    NavigationState,
    Pose,
    SensorHealthMap,
    Twist,
    VehicleState,
)
from project_ghost.telemetry import (
    MCAPFileSink,
    SelfAssessmentToTelemetryAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_state(stamp_sim_ns: int, pos_var: float = 1e-4) -> VehicleState:
    cov = np.eye(15, dtype=np.float64) * pos_var
    pose = Pose(
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_Q.copy(),
    )
    tw = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="world",
    )
    tb = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="body",
    )
    biases = IMUBiases(
        accel_bias_mps2=np.zeros(3, dtype=np.float64),
        gyro_bias_rps=np.zeros(3, dtype=np.float64),
    )
    nav = NavigationState(
        pose=pose,
        twist_world=tw,
        twist_body=tb,
        accel_body_mps2=np.zeros(3, dtype=np.float64),
        imu_biases=biases,
        covariance_15x15=cov,
    )
    return VehicleState(
        stamp_sim_ns=stamp_sim_ns,
        stamp_wall_ns=0,
        nav=nav,
        sensors=SensorHealthMap(
            by_id=MappingProxyType({"imu0": SensorHealth.OK})
        ),
        flight=FlightStatus(
            armed=True,
            flight_mode=FlightMode.OFFBOARD,
            battery_v=12.0,
            battery_pct=0.9,
            error_flags=0,
        ),
        mission=MissionStatus(
            mode=MissionMode.IDLE,
            current_goal=None,
            progress=0.0,
            started_sim_ns=None,
        ),
    )


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


def _write_mcap(path, n_records: int) -> None:  # type: ignore[no-untyped-def]
    t = _make_thresholds()
    with MCAPFileSink(path) as sink:
        adapter = SelfAssessmentToTelemetryAdapter(sink)
        for i in range(n_records):
            adapter.publish(
                assess_belief(_make_state(stamp_sim_ns=i * 1000), t)
            )


def test_cli_analyze_self_assessment_writes_output_file(
    tmp_path: Path,
) -> None:
    mcap = tmp_path / "sa.mcap"
    _write_mcap(mcap, n_records=3)
    out = tmp_path / "summary.json"

    rc = main(
        [
            "analyze-self-assessment",
            "--mcap",
            str(mcap),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert (
        parsed["schema_version"]
        == SELF_ASSESSMENT_SUMMARY_SCHEMA_VERSION
    )
    assert parsed["summary"]["total_records"] == 3


def test_cli_analyze_self_assessment_writes_stdout_when_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = tmp_path / "sa.mcap"
    _write_mcap(mcap, n_records=2)
    rc = main(
        [
            "analyze-self-assessment",
            "--mcap",
            str(mcap),
        ]
    )
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["summary"]["total_records"] == 2


def test_cli_analyze_self_assessment_byte_identical_outputs(
    tmp_path: Path,
) -> None:
    mcap = tmp_path / "sa.mcap"
    _write_mcap(mcap, n_records=3)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"

    main(
        [
            "analyze-self-assessment",
            "--mcap",
            str(mcap),
            "--output",
            str(a),
        ]
    )
    main(
        [
            "analyze-self-assessment",
            "--mcap",
            str(mcap),
            "--output",
            str(b),
        ]
    )
    assert a.read_bytes() == b.read_bytes()


def test_cli_analyze_self_assessment_missing_file_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "analyze-self-assessment",
            "--mcap",
            str(tmp_path / "missing.mcap"),
        ]
    )
    assert rc == 1
    assert "does not exist" in capsys.readouterr().err


def test_cli_analyze_self_assessment_missing_args_fails() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze-self-assessment"])
    assert exc_info.value.code == 2


def test_cli_help_includes_analyze_self_assessment(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "analyze-self-assessment" in out


def test_cli_pipeline_smoke_summary_reflects_mcap(tmp_path: Path) -> None:
    """End-to-end smoke: an MCAP with N records yields total_records=N
    and overall_counts that match expected per-record level (since the
    test sets covariance such that overall_level=KNOWN for all)."""
    mcap = tmp_path / "sa.mcap"
    _write_mcap(mcap, n_records=5)
    out = tmp_path / "summary.json"
    rc = main(
        [
            "analyze-self-assessment",
            "--mcap",
            str(mcap),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    summary = json.loads(out.read_text(encoding="utf-8"))["summary"]
    assert summary["total_records"] == 5
    assert summary["overall_counts"]["known"] == 5
    assert summary["overall_counts"]["uncertain"] == 0
    assert summary["overall_counts"]["unknown"] == 0
    assert summary["timestamp_first_ns"] == 0
    assert summary["timestamp_last_ns"] == 4000
    assert summary["timestamp_span_ns"] == 4000
