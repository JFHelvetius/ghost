"""Tests del ``FusionResultToTelemetryAdapter`` y round-trip MCAP
(ADR-0028).

Cubre:

- Adapter publica al canal correcto con stamp del belief.
- Adapter respeta canal custom.
- Adapter rechaza canal sin leading slash.
- Adapter satisface ``FusionResultSink`` estructuralmente.
- MCAP round-trip: write FusionResult → read → decoded matchea.
- Determinismo bytes-equal MCAP capture.
- Pipeline end-to-end: FusionInput → fuse_and_publish → MCAP → decode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from project_ghost.core.fusion import (
    FusionInput,
    FusionResult,
    FusionResultSink,
    LinearMotionOracleFusionPolicy,
    fuse_and_publish,
)
from project_ghost.telemetry import (
    CHANNEL_FUSION_RESULTS,
    FusionResultToTelemetryAdapter,
    InMemorySink,
    MCAPFileSink,
    MCAPReplayReader,
    decode_message,
)

if TYPE_CHECKING:
    from pathlib import Path


_ZERO3 = np.zeros(3, dtype=np.float64)


def _make_oracle(
    *,
    velocity: np.ndarray | None = None,
    start_ns: int = 0,
    cov: float = 1.0,
) -> LinearMotionOracleFusionPolicy:
    return LinearMotionOracleFusionPolicy(
        initial_position_enu_m=_ZERO3.copy(),
        velocity_world_mps=(
            velocity if velocity is not None else _ZERO3.copy()
        ),
        start_stamp_sim_ns=start_ns,
        covariance_diag=cov,
    )


def _make_input(
    *,
    target_ns: int = 1000,
    prior_ns: int | None = None,
) -> FusionInput:
    return FusionInput(
        sensor_samples=(),
        prior_belief_stamp_sim_ns=prior_ns,
        target_stamp_sim_ns=target_ns,
    )


def _make_result(stamp_ns: int = 1000) -> FusionResult:
    return _make_oracle().fuse(_make_input(target_ns=stamp_ns))


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------


def test_adapter_publishes_to_default_channel() -> None:
    sink = InMemorySink()
    adapter = FusionResultToTelemetryAdapter(sink)
    result = _make_result(stamp_ns=1000)
    adapter.publish(result)
    assert len(sink.captured) == 1
    assert sink.captured[0].channel == CHANNEL_FUSION_RESULTS


def test_adapter_uses_belief_stamp_as_log_time() -> None:
    sink = InMemorySink()
    adapter = FusionResultToTelemetryAdapter(sink)
    result = _make_result(stamp_ns=42_000)
    adapter.publish(result)
    assert sink.captured[0].stamp_sim_ns == 42_000


def test_adapter_publishes_result_as_message() -> None:
    sink = InMemorySink()
    adapter = FusionResultToTelemetryAdapter(sink)
    result = _make_result()
    adapter.publish(result)
    assert sink.captured[0].message is result


def test_adapter_accepts_custom_channel() -> None:
    sink = InMemorySink()
    adapter = FusionResultToTelemetryAdapter(sink, channel="/custom/fusion")
    result = _make_result()
    adapter.publish(result)
    assert sink.captured[0].channel == "/custom/fusion"
    assert adapter.channel == "/custom/fusion"


def test_adapter_rejects_channel_without_leading_slash() -> None:
    sink = InMemorySink()
    with pytest.raises(ValueError, match="'/'"):
        FusionResultToTelemetryAdapter(sink, channel="no_slash")


def test_adapter_satisfies_fusion_result_sink_protocol() -> None:
    sink = InMemorySink()
    adapter = FusionResultToTelemetryAdapter(sink)
    assert isinstance(adapter, FusionResultSink)


# ---------------------------------------------------------------------------
# MCAP round-trip
# ---------------------------------------------------------------------------


def test_mcap_round_trip_single_result(tmp_path: Path) -> None:
    p = tmp_path / "fusion.mcap"
    oracle = _make_oracle(
        velocity=np.array([2.0, 0.0, 0.0], dtype=np.float64),
        cov=0.5,
    )
    fi = _make_input(target_ns=1_000_000_000)
    original = oracle.fuse(fi)

    with MCAPFileSink(p) as mcap:
        FusionResultToTelemetryAdapter(mcap).publish(original)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    assert msgs[0].channel == CHANNEL_FUSION_RESULTS
    assert msgs[0].log_time_sim_ns == 1_000_000_000
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, FusionResult)
    assert decoded.belief.stamp_sim_ns == 1_000_000_000
    assert decoded.fusion_policy_id == original.fusion_policy_id
    assert decoded.fusion_input_sha256 == original.fusion_input_sha256
    np.testing.assert_array_equal(
        decoded.belief.nav.pose.position_enu_m,
        original.belief.nav.pose.position_enu_m,
    )


def test_mcap_round_trip_multiple_results(tmp_path: Path) -> None:
    p = tmp_path / "multi.mcap"
    oracle = _make_oracle()
    stamps = [100, 200, 300]
    originals: list[FusionResult] = []
    with MCAPFileSink(p) as mcap:
        adapter = FusionResultToTelemetryAdapter(mcap)
        for i, stamp in enumerate(stamps):
            fi = _make_input(
                target_ns=stamp,
                prior_ns=stamps[i - 1] if i > 0 else None,
            )
            result = oracle.fuse(fi)
            adapter.publish(result)
            originals.append(result)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == len(stamps)
    for orig, msg in zip(originals, msgs, strict=True):
        decoded = decode_message(msg)
        assert decoded.belief.stamp_sim_ns == orig.belief.stamp_sim_ns
        assert decoded.fusion_policy_id == orig.fusion_policy_id


def test_mcap_capture_is_byte_deterministic(tmp_path: Path) -> None:
    def write(path: Path) -> None:
        oracle = _make_oracle(
            velocity=np.array([1.0, 2.0, 3.0], dtype=np.float64),
            cov=0.1,
        )
        fi = _make_input(target_ns=500_000_000)
        with MCAPFileSink(path) as mcap:
            FusionResultToTelemetryAdapter(mcap).publish(oracle.fuse(fi))

    a_path = tmp_path / "a.mcap"
    b_path = tmp_path / "b.mcap"
    write(a_path)
    write(b_path)
    assert a_path.read_bytes() == b_path.read_bytes()


# ---------------------------------------------------------------------------
# Pipeline end-to-end: FusionInput → fuse_and_publish → MCAP → decode
# ---------------------------------------------------------------------------


def test_pipeline_fuse_and_publish_through_mcap(tmp_path: Path) -> None:
    p = tmp_path / "pipeline.mcap"
    oracle = _make_oracle(
        velocity=np.array([3.0, 0.0, 0.0], dtype=np.float64),
    )
    fi = _make_input(target_ns=1_000_000_000)

    with MCAPFileSink(p) as mcap:
        adapter = FusionResultToTelemetryAdapter(mcap)
        returned = fuse_and_publish(oracle, fi, adapter)

    with MCAPReplayReader(p) as reader:
        msgs = list(reader.iter_messages())

    assert len(msgs) == 1
    decoded = decode_message(msgs[0])
    assert isinstance(decoded, FusionResult)
    assert decoded.belief.stamp_sim_ns == 1_000_000_000
    # oracle propagates 3 m/s * 1 s = 3 m in x
    np.testing.assert_allclose(
        decoded.belief.nav.pose.position_enu_m,
        np.array([3.0, 0.0, 0.0], dtype=np.float64),
    )
    assert returned.fusion_input_sha256 == decoded.fusion_input_sha256
