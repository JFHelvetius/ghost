"""Tests del módulo `analysis.decision_trace` (ADR-0022).

Cubre:

- ``ChainStatus`` enum cerrado.
- ``DecisionTraceRecord`` / ``DecisionTraceReport`` validación.
- ``build_decision_trace_report`` con MCAPs reales:
  * vacío,
  * cadena íntegra,
  * cadena rota (SHA mismatch),
  * assessment ausente,
  * decisión sin claim (rationale.self_assessment_sha256 = None),
  * mix.
- ``verify_decision_chain``: ok, broken, missing.
- Agregados (per_kind, per_policy, timestamps).
- ``source_mcap_sha256`` matchea hashlib del archivo.
- JSON canonical encoding.
- Determinismo y round-trip.
- Schema / analysis_version validation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.analysis import (
    DECISION_TRACE_REPORT_SCHEMA_VERSION,
    ChainStatus,
    DecisionTraceRecord,
    DecisionTraceReport,
    build_decision_trace_report,
    decode_decision_trace_report_from_json,
    encode_decision_trace_report_to_bytes,
    generate_decision_trace_report,
    verify_decision_chain,
)
from project_ghost.core.decisions import (
    Decision,
    DecisionContext,
    DecisionKind,
    DecisionRationale,
    UncertaintyAwareReferencePolicy,
    decide_and_publish,
    decide_with_rationale,
    self_assessment_sha256,
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


_Q = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def _make_state(*, stamp_sim_ns: int, pos_var: float = 1e-4) -> VehicleState:
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


def _make_thresholds() -> AssessmentThresholds:
    return AssessmentThresholds(
        position_known_std_m=0.05,
        position_unknown_std_m=0.5,
        velocity_known_std_mps=0.1,
        velocity_unknown_std_mps=1.0,
        orientation_known_std_rad=0.05,
        orientation_unknown_std_rad=0.5,
    )


def _make_context(stamp_sim_ns: int, pos_var: float = 1e-4) -> DecisionContext:
    state = _make_state(stamp_sim_ns=stamp_sim_ns, pos_var=pos_var)
    return DecisionContext(
        belief_stamp_sim_ns=stamp_sim_ns,
        self_assessment=assess_belief(state, _make_thresholds()),
        flight_status=state.flight,
        mission_status=state.mission,
        perception_mode=None,
    )


def _write_clean_mcap(path: Path, stamps: list[int]) -> None:
    """Pipeline canónica: publica assessment + decision en /self_assessment
    y /decisions para cada stamp."""
    policy = UncertaintyAwareReferencePolicy()
    with MCAPFileSink(path) as sink:
        sa_adapter = SelfAssessmentToTelemetryAdapter(sink)
        d_adapter = DecisionToTelemetryAdapter(sink)
        for stamp in stamps:
            ctx = _make_context(stamp)
            assert ctx.self_assessment is not None
            sa_adapter.publish(ctx.self_assessment)
            decide_and_publish(policy, ctx, d_adapter)


# ---------------------------------------------------------------------------
# ChainStatus
# ---------------------------------------------------------------------------


def test_chain_status_catalog_is_four_entries() -> None:
    expected = {
        "verified",
        "broken",
        "assessment_missing",
        "no_assessment_claimed",
    }
    assert {cs.value for cs in ChainStatus} == expected


# ---------------------------------------------------------------------------
# DecisionTraceRecord validation
# ---------------------------------------------------------------------------


def test_record_valid_construction() -> None:
    rec = DecisionTraceRecord(
        timestamp_ns=1000,
        decision_kind=DecisionKind.PROCEED,
        decision_reason="overall_known",
        policy_id="p",
        claimed_assessment_sha256="a" * 64,
        recomputed_assessment_sha256="a" * 64,
        chain_status=ChainStatus.VERIFIED,
    )
    assert rec.timestamp_ns == 1000
    assert rec.chain_status == ChainStatus.VERIFIED


def test_record_rejects_negative_stamp() -> None:
    with pytest.raises(ValueError, match="timestamp_ns"):
        DecisionTraceRecord(
            timestamp_ns=-1,
            decision_kind=DecisionKind.PROCEED,
            decision_reason="ok",
            policy_id="p",
            claimed_assessment_sha256=None,
            recomputed_assessment_sha256=None,
            chain_status=ChainStatus.NO_ASSESSMENT_CLAIMED,
        )


def test_record_rejects_non_chain_status() -> None:
    with pytest.raises(TypeError, match="chain_status"):
        DecisionTraceRecord(
            timestamp_ns=0,
            decision_kind=DecisionKind.PROCEED,
            decision_reason="ok",
            policy_id="p",
            claimed_assessment_sha256=None,
            recomputed_assessment_sha256=None,
            chain_status="verified",  # type: ignore[arg-type]
        )


def test_record_rejects_bad_sha_format() -> None:
    with pytest.raises(ValueError, match="hex"):
        DecisionTraceRecord(
            timestamp_ns=0,
            decision_kind=DecisionKind.PROCEED,
            decision_reason="ok",
            policy_id="p",
            claimed_assessment_sha256="A" * 64,  # uppercase
            recomputed_assessment_sha256=None,
            chain_status=ChainStatus.BROKEN,
        )


def test_record_is_frozen() -> None:
    rec = DecisionTraceRecord(
        timestamp_ns=0,
        decision_kind=DecisionKind.PROCEED,
        decision_reason="ok",
        policy_id="p",
        claimed_assessment_sha256=None,
        recomputed_assessment_sha256=None,
        chain_status=ChainStatus.NO_ASSESSMENT_CLAIMED,
    )
    with pytest.raises(FrozenInstanceError):
        rec.timestamp_ns = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DecisionTraceReport validation
# ---------------------------------------------------------------------------


def test_report_rejects_bad_source_sha() -> None:
    with pytest.raises(ValueError, match="hex"):
        DecisionTraceReport(
            source_mcap_sha256="not-hex",
            total_decisions=0,
            verified_count=0,
            broken_count=0,
            assessment_missing_count=0,
            no_assessment_claimed_count=0,
            per_decision_kind_counts={},
            per_policy_id_counts={},
            timestamp_first_ns=None,
            timestamp_last_ns=None,
            timestamp_span_ns=None,
            records=(),
        )


def test_report_rejects_total_mismatch_with_records() -> None:
    with pytest.raises(ValueError, match="len\\(records\\)"):
        DecisionTraceReport(
            source_mcap_sha256="a" * 64,
            total_decisions=5,
            verified_count=0,
            broken_count=0,
            assessment_missing_count=0,
            no_assessment_claimed_count=0,
            per_decision_kind_counts={},
            per_policy_id_counts={},
            timestamp_first_ns=None,
            timestamp_last_ns=None,
            timestamp_span_ns=None,
            records=(),
        )


def test_report_rejects_counts_sum_mismatch() -> None:
    rec = DecisionTraceRecord(
        timestamp_ns=0,
        decision_kind=DecisionKind.PROCEED,
        decision_reason="ok",
        policy_id="p",
        claimed_assessment_sha256=None,
        recomputed_assessment_sha256=None,
        chain_status=ChainStatus.NO_ASSESSMENT_CLAIMED,
    )
    with pytest.raises(ValueError, match="counts sum"):
        DecisionTraceReport(
            source_mcap_sha256="a" * 64,
            total_decisions=1,
            verified_count=5,  # too many
            broken_count=0,
            assessment_missing_count=0,
            no_assessment_claimed_count=0,
            per_decision_kind_counts={"proceed": 1},
            per_policy_id_counts={"p": 1},
            timestamp_first_ns=0,
            timestamp_last_ns=0,
            timestamp_span_ns=0,
            records=(rec,),
        )


def test_report_is_frozen() -> None:
    r = DecisionTraceReport(
        source_mcap_sha256="a" * 64,
        total_decisions=0,
        verified_count=0,
        broken_count=0,
        assessment_missing_count=0,
        no_assessment_claimed_count=0,
        per_decision_kind_counts={},
        per_policy_id_counts={},
        timestamp_first_ns=None,
        timestamp_last_ns=None,
        timestamp_span_ns=None,
        records=(),
    )
    with pytest.raises(FrozenInstanceError):
        r.total_decisions = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_decision_trace_report — happy paths
# ---------------------------------------------------------------------------


def test_build_empty_mcap_yields_empty_report(tmp_path: Path) -> None:
    p = tmp_path / "empty.mcap"
    with MCAPFileSink(p):
        pass  # no records
    report = build_decision_trace_report(p)
    assert report.total_decisions == 0
    assert report.records == ()
    assert report.timestamp_first_ns is None


def test_build_clean_chain_all_verified(tmp_path: Path) -> None:
    p = tmp_path / "clean.mcap"
    stamps = [0, 1000, 2000]
    _write_clean_mcap(p, stamps)
    report = build_decision_trace_report(p)
    assert report.total_decisions == 3
    assert report.verified_count == 3
    assert report.broken_count == 0
    assert report.assessment_missing_count == 0
    assert report.no_assessment_claimed_count == 0
    for rec in report.records:
        assert rec.chain_status == ChainStatus.VERIFIED


def test_build_no_assessment_claimed_when_rationale_has_none(
    tmp_path: Path,
) -> None:
    """Publica una decisión con rationale.self_assessment_sha256=None
    (caso legítimo cuando el agente no tenía introspección)."""
    p = tmp_path / "no_claim.mcap"
    d = Decision(
        kind=DecisionKind.ABSTAIN_UNCERTAIN,
        decision_stamp_sim_ns=500,
        reason="no_assessment",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=500,
        self_assessment_sha256=None,
        policy_id="p",
    )
    with MCAPFileSink(p) as sink:
        DecisionToTelemetryAdapter(sink).publish(d, r)
    report = build_decision_trace_report(p)
    assert report.total_decisions == 1
    assert report.no_assessment_claimed_count == 1
    assert report.records[0].chain_status == ChainStatus.NO_ASSESSMENT_CLAIMED


def test_build_assessment_missing_when_no_assessment_at_stamp(
    tmp_path: Path,
) -> None:
    """Publica un rationale con SHA pero NO publica el assessment
    correspondiente — la cadena reporta assessment_missing."""
    p = tmp_path / "missing.mcap"
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=500,
        reason="overall_known",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=500,
        self_assessment_sha256="a" * 64,  # arbitrary SHA, no matching assessment
        policy_id="p",
    )
    with MCAPFileSink(p) as sink:
        DecisionToTelemetryAdapter(sink).publish(d, r)
    report = build_decision_trace_report(p)
    assert report.total_decisions == 1
    assert report.assessment_missing_count == 1
    rec = report.records[0]
    assert rec.chain_status == ChainStatus.ASSESSMENT_MISSING
    assert rec.recomputed_assessment_sha256 is None


def test_build_broken_when_sha_mismatch(tmp_path: Path) -> None:
    """Publica un assessment + un rationale con SHA inventado distinto
    del real → cadena rota."""
    p = tmp_path / "broken.mcap"
    state = _make_state(stamp_sim_ns=500)
    assessment = assess_belief(state, _make_thresholds())
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=500,
        reason="overall_known",
    )
    bad_sha = "f" * 64  # not the real one
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=500,
        self_assessment_sha256=bad_sha,
        policy_id="p",
    )
    with MCAPFileSink(p) as sink:
        SelfAssessmentToTelemetryAdapter(sink).publish(assessment)
        DecisionToTelemetryAdapter(sink).publish(d, r)
    report = build_decision_trace_report(p)
    assert report.broken_count == 1
    rec = report.records[0]
    assert rec.chain_status == ChainStatus.BROKEN
    assert rec.claimed_assessment_sha256 == bad_sha
    assert rec.recomputed_assessment_sha256 == self_assessment_sha256(assessment)


def test_build_mix_of_all_four_states(tmp_path: Path) -> None:
    """MCAP con: 1 verified + 1 broken + 1 missing + 1 no_claim."""
    p = tmp_path / "mix.mcap"
    policy = UncertaintyAwareReferencePolicy()
    state_verified = _make_state(stamp_sim_ns=100)
    state_broken = _make_state(stamp_sim_ns=200)
    assessment_verified = assess_belief(state_verified, _make_thresholds())
    assessment_broken = assess_belief(state_broken, _make_thresholds())

    # 1. verified (clean pipeline)
    ctx_v = _make_context(stamp_sim_ns=100)
    decision_v, rationale_v = decide_with_rationale(policy, ctx_v)

    # 2. broken: claim wrong SHA
    decision_b = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=200,
        reason="overall_known",
    )
    rationale_b = DecisionRationale(
        decision=decision_b,
        belief_stamp_sim_ns=200,
        self_assessment_sha256="0" * 64,
        policy_id="p",
    )

    # 3. assessment_missing: claim SHA but no assessment at stamp 300
    decision_m = Decision(
        kind=DecisionKind.HOLD,
        decision_stamp_sim_ns=300,
        reason="overall_uncertain",
    )
    rationale_m = DecisionRationale(
        decision=decision_m,
        belief_stamp_sim_ns=300,
        self_assessment_sha256="1" * 64,
        policy_id="p",
    )

    # 4. no_claim
    decision_n = Decision(
        kind=DecisionKind.ABSTAIN_UNCERTAIN,
        decision_stamp_sim_ns=400,
        reason="no_assessment",
    )
    rationale_n = DecisionRationale(
        decision=decision_n,
        belief_stamp_sim_ns=400,
        self_assessment_sha256=None,
        policy_id="p",
    )

    with MCAPFileSink(p) as sink:
        sa = SelfAssessmentToTelemetryAdapter(sink)
        sa.publish(assessment_verified)
        sa.publish(assessment_broken)  # exists for stamp 200, just wrong SHA claim
        d_adapter = DecisionToTelemetryAdapter(sink)
        d_adapter.publish(decision_v, rationale_v)
        d_adapter.publish(decision_b, rationale_b)
        d_adapter.publish(decision_m, rationale_m)
        d_adapter.publish(decision_n, rationale_n)

    report = build_decision_trace_report(p)
    assert report.total_decisions == 4
    assert report.verified_count == 1
    assert report.broken_count == 1
    assert report.assessment_missing_count == 1
    assert report.no_assessment_claimed_count == 1


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def test_per_kind_counts_correct(tmp_path: Path) -> None:
    """Three PROCEED decisions (covariance KNOWN) → per_kind has only proceed=3."""
    p = tmp_path / "agg.mcap"
    _write_clean_mcap(p, [100, 200, 300])
    report = build_decision_trace_report(p)
    assert report.per_decision_kind_counts == {"proceed": 3}


def test_per_policy_counts_correct(tmp_path: Path) -> None:
    p = tmp_path / "agg.mcap"
    _write_clean_mcap(p, [100, 200])
    report = build_decision_trace_report(p)
    assert report.per_policy_id_counts == {
        "uncertainty_aware_reference_v1": 2,
    }


def test_timestamp_aggregates_use_min_max(tmp_path: Path) -> None:
    p = tmp_path / "ts.mcap"
    # Publish in a known order; min/max should reflect the values.
    _write_clean_mcap(p, [500, 100, 300])
    report = build_decision_trace_report(p)
    assert report.timestamp_first_ns == 100
    assert report.timestamp_last_ns == 500
    assert report.timestamp_span_ns == 400


# ---------------------------------------------------------------------------
# source_mcap_sha256 matches hashlib
# ---------------------------------------------------------------------------


def test_source_mcap_sha256_matches_hashlib(tmp_path: Path) -> None:
    p = tmp_path / "sha.mcap"
    _write_clean_mcap(p, [100, 200])
    report = build_decision_trace_report(p)
    expected = hashlib.sha256(p.read_bytes()).hexdigest()
    assert report.source_mcap_sha256 == expected


# ---------------------------------------------------------------------------
# verify_decision_chain
# ---------------------------------------------------------------------------


def test_verify_clean_chain_is_ok(tmp_path: Path) -> None:
    p = tmp_path / "clean.mcap"
    _write_clean_mcap(p, [100, 200, 300])
    ok, msgs = verify_decision_chain(p)
    assert ok is True
    assert msgs == ()


def test_verify_broken_chain_returns_false(tmp_path: Path) -> None:
    p = tmp_path / "broken.mcap"
    state = _make_state(stamp_sim_ns=500)
    assessment = assess_belief(state, _make_thresholds())
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=500,
        reason="overall_known",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=500,
        self_assessment_sha256="0" * 64,
        policy_id="p",
    )
    with MCAPFileSink(p) as sink:
        SelfAssessmentToTelemetryAdapter(sink).publish(assessment)
        DecisionToTelemetryAdapter(sink).publish(d, r)
    ok, msgs = verify_decision_chain(p)
    assert ok is False
    assert any("sha256 mismatch" in m for m in msgs)


def test_verify_missing_assessment_returns_false(tmp_path: Path) -> None:
    p = tmp_path / "missing.mcap"
    d = Decision(
        kind=DecisionKind.PROCEED,
        decision_stamp_sim_ns=500,
        reason="overall_known",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=500,
        self_assessment_sha256="a" * 64,
        policy_id="p",
    )
    with MCAPFileSink(p) as sink:
        DecisionToTelemetryAdapter(sink).publish(d, r)
    ok, msgs = verify_decision_chain(p)
    assert ok is False
    assert any("assessment missing" in m for m in msgs)


def test_verify_no_assessment_claimed_is_still_ok(tmp_path: Path) -> None:
    """no_assessment_claimed es un caso legítimo, NO debe fallar verify."""
    p = tmp_path / "no_claim.mcap"
    d = Decision(
        kind=DecisionKind.ABSTAIN_UNCERTAIN,
        decision_stamp_sim_ns=500,
        reason="no_assessment",
    )
    r = DecisionRationale(
        decision=d,
        belief_stamp_sim_ns=500,
        self_assessment_sha256=None,
        policy_id="p",
    )
    with MCAPFileSink(p) as sink:
        DecisionToTelemetryAdapter(sink).publish(d, r)
    ok, msgs = verify_decision_chain(p)
    assert ok is True
    assert msgs == ()


# ---------------------------------------------------------------------------
# JSON canonical encoding
# ---------------------------------------------------------------------------


def test_encoded_report_trailing_newline(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    _write_clean_mcap(p, [100])
    report = build_decision_trace_report(p)
    encoded = encode_decision_trace_report_to_bytes(report)
    assert encoded.endswith(b"\n")


def test_encoded_report_envelope_structure(tmp_path: Path) -> None:
    p = tmp_path / "x.mcap"
    _write_clean_mcap(p, [100])
    report = build_decision_trace_report(p)
    parsed = json.loads(encode_decision_trace_report_to_bytes(report).decode("utf-8"))
    assert parsed["schema_version"] == DECISION_TRACE_REPORT_SCHEMA_VERSION
    assert "trace" in parsed
    assert parsed["trace"]["total_decisions"] == 1


# ---------------------------------------------------------------------------
# Determinism + round-trip
# ---------------------------------------------------------------------------


def test_two_encodings_are_byte_identical(tmp_path: Path) -> None:
    p = tmp_path / "det.mcap"
    _write_clean_mcap(p, [100, 200, 300])
    report = build_decision_trace_report(p)
    a = encode_decision_trace_report_to_bytes(report)
    b = encode_decision_trace_report_to_bytes(report)
    assert a == b


def test_two_builds_yield_equal_reports(tmp_path: Path) -> None:
    p = tmp_path / "det.mcap"
    _write_clean_mcap(p, [100, 200])
    a = build_decision_trace_report(p)
    b = build_decision_trace_report(p)
    assert a == b


def test_round_trip_encode_decode_preserves_report(tmp_path: Path) -> None:
    p = tmp_path / "rt.mcap"
    _write_clean_mcap(p, [100, 200, 300])
    original = build_decision_trace_report(p)
    encoded = encode_decision_trace_report_to_bytes(original)
    decoded = decode_decision_trace_report_from_json(json.loads(encoded.decode("utf-8")))
    assert decoded == original


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_decode_schema_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        decode_decision_trace_report_from_json({"schema_version": "999", "trace": {}})


def test_decode_missing_schema_raises() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        decode_decision_trace_report_from_json({"trace": {}})


def test_decode_non_mapping_raises() -> None:
    with pytest.raises(TypeError, match="mapping"):
        decode_decision_trace_report_from_json("not a dict")  # type: ignore[arg-type]


def test_decode_analysis_version_mismatch_raises() -> None:
    data = {
        "schema_version": DECISION_TRACE_REPORT_SCHEMA_VERSION,
        "trace": {
            "analysis_version": 999,
            "source_mcap_sha256": "a" * 64,
            "total_decisions": 0,
            "verified_count": 0,
            "broken_count": 0,
            "assessment_missing_count": 0,
            "no_assessment_claimed_count": 0,
            "per_decision_kind_counts": {},
            "per_policy_id_counts": {},
            "timestamp_first_ns": None,
            "timestamp_last_ns": None,
            "timestamp_span_ns": None,
            "records": [],
        },
    }
    with pytest.raises(ValueError, match="analysis_version"):
        decode_decision_trace_report_from_json(data)


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------


def test_record_rejects_non_decisionkind() -> None:
    with pytest.raises(TypeError, match="decision_kind"):
        DecisionTraceRecord(
            timestamp_ns=0,
            decision_kind="proceed",  # type: ignore[arg-type]
            decision_reason="ok",
            policy_id="p",
            claimed_assessment_sha256=None,
            recomputed_assessment_sha256=None,
            chain_status=ChainStatus.NO_ASSESSMENT_CLAIMED,
        )


def test_report_rejects_non_string_source_sha() -> None:
    with pytest.raises(TypeError, match="must be str"):
        DecisionTraceReport(
            source_mcap_sha256=12345,  # type: ignore[arg-type]
            total_decisions=0,
            verified_count=0,
            broken_count=0,
            assessment_missing_count=0,
            no_assessment_claimed_count=0,
            per_decision_kind_counts={},
            per_policy_id_counts={},
            timestamp_first_ns=None,
            timestamp_last_ns=None,
            timestamp_span_ns=None,
            records=(),
        )


def test_report_rejects_non_tuple_records() -> None:
    with pytest.raises(TypeError, match="tuple"):
        DecisionTraceReport(
            source_mcap_sha256="a" * 64,
            total_decisions=0,
            verified_count=0,
            broken_count=0,
            assessment_missing_count=0,
            no_assessment_claimed_count=0,
            per_decision_kind_counts={},
            per_policy_id_counts={},
            timestamp_first_ns=None,
            timestamp_last_ns=None,
            timestamp_span_ns=None,
            records=[],  # type: ignore[arg-type]
        )


def test_report_rejects_non_mapping_per_kind_counts() -> None:
    with pytest.raises(TypeError, match="must be a Mapping"):
        DecisionTraceReport(
            source_mcap_sha256="a" * 64,
            total_decisions=0,
            verified_count=0,
            broken_count=0,
            assessment_missing_count=0,
            no_assessment_claimed_count=0,
            per_decision_kind_counts=[],  # type: ignore[arg-type]
            per_policy_id_counts={},
            timestamp_first_ns=None,
            timestamp_last_ns=None,
            timestamp_span_ns=None,
            records=(),
        )


def test_decode_missing_inner_raises() -> None:
    with pytest.raises(ValueError, match="trace"):
        decode_decision_trace_report_from_json(
            {"schema_version": DECISION_TRACE_REPORT_SCHEMA_VERSION}
        )


def test_decode_non_mapping_inner_raises() -> None:
    with pytest.raises(TypeError, match="mapping"):
        decode_decision_trace_report_from_json(
            {
                "schema_version": DECISION_TRACE_REPORT_SCHEMA_VERSION,
                "trace": [1, 2, 3],
            }
        )


def test_generate_writes_canonical_bytes(tmp_path: Path) -> None:
    p = tmp_path / "w.mcap"
    _write_clean_mcap(p, [100])
    report = build_decision_trace_report(p)
    out = tmp_path / "out.json"
    generate_decision_trace_report(report, out)
    assert out.read_bytes() == encode_decision_trace_report_to_bytes(report)
