"""Tests del CLI `ghost analyze-belief` (ADR-0016).

Cubre:

- éxito con flags requeridos y output a archivo
- escritura a stdout cuando se omite --output
- bytes idénticos entre invocaciones repetidas con mismos MCAPs
- detección de length mismatch (return code 1)
- detección de stamp mismatch (return code 1)
- presencia del subcomando en `--help`
- fallo de argparse cuando faltan flags requeridos
"""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from project_ghost.analysis import BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION
from project_ghost.cli import main
from project_ghost.hal.messages import GroundTruth, SensorHealth
from project_ghost.state import (
    FlightMode,
    FlightStatus,
    MissionMode,
    MissionStatus,
    SensorHealthMap,
    VehicleState,
    vehicle_state_from_ground_truth,
)
from project_ghost.state.messages import (
    IMUBiases,
    NavigationState,
    Pose,
    Twist,
)
from project_ghost.telemetry import CHANNEL_STATE_NAV, MCAPFileSink

_Q_IDENTITY = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_truth(stamp_sim_ns: int) -> VehicleState:
    gt = GroundTruth(
        stamp_sim_ns=stamp_sim_ns,
        position_enu_m=np.zeros(3, dtype=np.float64),
        orientation_q=_Q_IDENTITY.copy(),
        linear_velocity_world_mps=np.zeros(3, dtype=np.float64),
        angular_velocity_body_rps=np.zeros(3, dtype=np.float64),
        accel_body_mps2=np.zeros(3, dtype=np.float64),
    )
    return vehicle_state_from_ground_truth(
        gt=gt,
        sensors_health=SensorHealthMap(by_id=MappingProxyType({"imu0": SensorHealth.OK})),
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
        stamp_wall_ns=stamp_sim_ns,
    )


def _make_belief(
    stamp_sim_ns: int,
    *,
    position_offset: np.ndarray | None = None,
) -> VehicleState:
    pos = position_offset.copy() if position_offset is not None else np.zeros(3, dtype=np.float64)
    pose = Pose(position_enu_m=pos, orientation_q=_Q_IDENTITY.copy())
    twist_world = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="world",
    )
    twist_body = Twist(
        linear_mps=np.zeros(3, dtype=np.float64),
        angular_rps=np.zeros(3, dtype=np.float64),
        frame="body",
    )
    nav = NavigationState(
        pose=pose,
        twist_world=twist_world,
        twist_body=twist_body,
        accel_body_mps2=np.zeros(3, dtype=np.float64),
        imu_biases=IMUBiases(
            accel_bias_mps2=np.zeros(3, dtype=np.float64),
            gyro_bias_rps=np.zeros(3, dtype=np.float64),
        ),
        covariance_15x15=np.eye(15, dtype=np.float64) * 1e-3,
    )
    return VehicleState(
        stamp_sim_ns=stamp_sim_ns,
        stamp_wall_ns=stamp_sim_ns,
        nav=nav,
        sensors=SensorHealthMap(by_id=MappingProxyType({"imu0": SensorHealth.OK})),
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


def _write_mcap(path: Path, states: list[VehicleState]) -> None:
    with MCAPFileSink(path) as sink:
        for s in states:
            sink.publish(CHANNEL_STATE_NAV, s.stamp_sim_ns, s)


def _setup_aligned(tmp_path: Path) -> tuple[Path, Path]:
    truth_path = tmp_path / "truth.mcap"
    belief_path = tmp_path / "belief.mcap"
    stamps = [0, 1_000, 2_000]
    truth_states = [_make_truth(s) for s in stamps]
    belief_states = [
        _make_belief(s, position_offset=np.array([0.01 * i, 0.0, 0.0]))
        for i, s in enumerate(stamps)
    ]
    _write_mcap(truth_path, truth_states)
    _write_mcap(belief_path, belief_states)
    return truth_path, belief_path


def test_cli_analyze_belief_writes_report_to_output(tmp_path: Path) -> None:
    truth_path, belief_path = _setup_aligned(tmp_path)
    output = tmp_path / "belief_report.json"

    rc = main(
        [
            "analyze-belief",
            "--truth-mcap",
            str(truth_path),
            "--belief-mcap",
            str(belief_path),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION
    assert data["report"]["total_samples"] == 3
    assert data["report"]["samples_with_covariance"] == 3


def test_cli_analyze_belief_writes_to_stdout_when_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    truth_path, belief_path = _setup_aligned(tmp_path)
    rc = main(
        [
            "analyze-belief",
            "--truth-mcap",
            str(truth_path),
            "--belief-mcap",
            str(belief_path),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["schema_version"] == BELIEF_TRACEABILITY_REPORT_SCHEMA_VERSION


def test_cli_analyze_belief_byte_identical_outputs(tmp_path: Path) -> None:
    truth_path, belief_path = _setup_aligned(tmp_path)
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"

    main(
        [
            "analyze-belief",
            "--truth-mcap",
            str(truth_path),
            "--belief-mcap",
            str(belief_path),
            "--output",
            str(out_a),
        ]
    )
    main(
        [
            "analyze-belief",
            "--truth-mcap",
            str(truth_path),
            "--belief-mcap",
            str(belief_path),
            "--output",
            str(out_b),
        ]
    )

    assert out_a.read_bytes() == out_b.read_bytes()


def test_cli_analyze_belief_length_mismatch_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    truth_path = tmp_path / "truth.mcap"
    belief_path = tmp_path / "belief.mcap"
    _write_mcap(truth_path, [_make_truth(0), _make_truth(1)])
    _write_mcap(belief_path, [_make_belief(0)])

    rc = main(
        [
            "analyze-belief",
            "--truth-mcap",
            str(truth_path),
            "--belief-mcap",
            str(belief_path),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "longitudes" in err


def test_cli_analyze_belief_stamp_mismatch_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    truth_path = tmp_path / "truth.mcap"
    belief_path = tmp_path / "belief.mcap"
    _write_mcap(truth_path, [_make_truth(0)])
    _write_mcap(belief_path, [_make_belief(5)])

    rc = main(
        [
            "analyze-belief",
            "--truth-mcap",
            str(truth_path),
            "--belief-mcap",
            str(belief_path),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "stamp_sim_ns" in err


def test_cli_analyze_belief_missing_args_fails() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["analyze-belief"])
    assert exc_info.value.code == 2


def test_cli_help_includes_analyze_belief(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "analyze-belief" in out
