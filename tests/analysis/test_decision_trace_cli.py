"""Tests del CLI `ghost trace-decisions` (ADR-0022).

Cubre:

- éxito con --mcap + --output (escribe report JSON).
- stdout cuando --output se omite.
- archivo inexistente → rc=1.
- args faltantes → rc=2.
- --help muestra el subcomando.
- byte-identical entre dos invocaciones con mismo MCAP.
- pipeline smoke end-to-end.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.analysis import DECISION_TRACE_REPORT_SCHEMA_VERSION
from project_ghost.cli import main
from project_ghost.core.decisions import (
    UncertaintyAwareReferencePolicy,
    decide_and_publish,
)
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
    DecisionToTelemetryAdapter,
    MCAPFileSink,
    SelfAssessmentToTelemetryAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path

    from project_ghost.core.decisions import DecisionContext


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_state(stamp: int) -> VehicleState:
    cov = np.eye(15, dtype=np.float64) * 1e-4
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
        stamp_sim_ns=stamp,
        stamp_wall_ns=0,
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


def _make_ctx(stamp: int) -> DecisionContext:
    from project_ghost.core.decisions import DecisionContext

    state = _make_state(stamp)
    thresh = AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )
    return DecisionContext(
        belief_stamp_sim_ns=stamp,
        self_assessment=assess_belief(state, thresh),
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )


def _write_pipeline_mcap(path: Path, stamps: list[int]) -> None:
    policy = UncertaintyAwareReferencePolicy()
    with MCAPFileSink(path) as sink:
        sa = SelfAssessmentToTelemetryAdapter(sink)
        d_adapter = DecisionToTelemetryAdapter(sink)
        for stamp in stamps:
            ctx = _make_ctx(stamp)
            assert ctx.self_assessment is not None
            sa.publish(ctx.self_assessment)
            decide_and_publish(policy, ctx, d_adapter)


def test_cli_trace_decisions_writes_output(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_pipeline_mcap(mcap, [100, 200, 300])
    out = tmp_path / "trace.json"
    rc = main(
        [
            "trace-decisions",
            "--mcap",
            str(mcap),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == DECISION_TRACE_REPORT_SCHEMA_VERSION
    assert data["trace"]["total_decisions"] == 3
    assert data["trace"]["verified_count"] == 3


def test_cli_trace_decisions_writes_stdout_when_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mcap = tmp_path / "run.mcap"
    _write_pipeline_mcap(mcap, [100])
    rc = main(
        [
            "trace-decisions",
            "--mcap",
            str(mcap),
        ]
    )
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["trace"]["total_decisions"] == 1


def test_cli_trace_decisions_missing_file_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "trace-decisions",
            "--mcap",
            str(tmp_path / "missing.mcap"),
        ]
    )
    assert rc == 1
    assert "does not exist" in capsys.readouterr().err


def test_cli_trace_decisions_missing_args_fails() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["trace-decisions"])
    assert exc.value.code == 2


def test_cli_help_includes_trace_decisions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "trace-decisions" in out


def test_cli_trace_decisions_byte_identical_outputs(tmp_path: Path) -> None:
    mcap = tmp_path / "run.mcap"
    _write_pipeline_mcap(mcap, [100, 200])
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    main(
        [
            "trace-decisions",
            "--mcap",
            str(mcap),
            "--output",
            str(a),
        ]
    )
    main(
        [
            "trace-decisions",
            "--mcap",
            str(mcap),
            "--output",
            str(b),
        ]
    )
    assert a.read_bytes() == b.read_bytes()


def test_cli_pipeline_smoke_end_to_end(tmp_path: Path) -> None:
    """End-to-end smoke: capture pipeline → trace-decisions → JSON
    summary reflects everything."""
    mcap = tmp_path / "run.mcap"
    _write_pipeline_mcap(mcap, [0, 1000, 2000])
    out = tmp_path / "trace.json"
    rc = main(
        [
            "trace-decisions",
            "--mcap",
            str(mcap),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    trace = json.loads(out.read_text(encoding="utf-8"))["trace"]
    assert trace["total_decisions"] == 3
    assert trace["verified_count"] == 3
    assert trace["broken_count"] == 0
    assert trace["assessment_missing_count"] == 0
    assert trace["no_assessment_claimed_count"] == 0
    assert trace["timestamp_first_ns"] == 0
    assert trace["timestamp_last_ns"] == 2000
    assert trace["timestamp_span_ns"] == 2000
    assert trace["per_decision_kind_counts"] == {"proceed": 3}
    assert trace["per_policy_id_counts"] == {
        "uncertainty_aware_reference_v1": 3,
    }
