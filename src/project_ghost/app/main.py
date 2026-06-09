"""Project Ghost — Streamlit dashboard.

Two tabs:
- **Run Smoke**: configure and execute the closed-loop pipeline, download MCAP.
- **Inspect MCAP**: upload any captured run and explore its telemetry.

Usage::

    streamlit run src/project_ghost/app/main.py
    # or via console script:
    ghost-app
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from project_ghost.core.actuation.types import ActuationDirective
from project_ghost.core.decisions.types import DecisionRationale
from project_ghost.core.feedback.types import CalibratedSelfAssessment
from project_ghost.core.fusion.types import FusionResult
from project_ghost.core.prediction.divergence import PredictionOutcome
from project_ghost.core.uncertainty.self_assessment import BeliefSelfAssessment
from project_ghost.examples.closed_loop_smoke import (
    SmokeSummary,
    run_closed_loop_smoke,
)
from project_ghost.telemetry import (
    CHANNEL_ACTUATIONS,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT,
    CHANNEL_DECISIONS,
    CHANNEL_FUSION_RESULTS,
    CHANNEL_PREDICTION_OUTCOMES,
    CHANNEL_SELF_ASSESSMENT,
    MCAPReplayReader,
    decode_message,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_LEVEL_NUM: dict[str, int] = {"known": 0, "uncertain": 1, "unknown": 2}


def _ms(ns: int) -> float:
    return round(ns / 1_000_000, 1)


@st.cache_data(show_spinner=False)
def _decode_mcap(file_bytes: bytes) -> dict[str, list[tuple[int, Any]]]:
    """Decode all messages from MCAP bytes (cached per unique file)."""
    with tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    result: dict[str, list[tuple[int, Any]]] = {}
    try:
        with MCAPReplayReader(tmp_path) as reader:
            for msg in reader.iter_messages():
                try:
                    obj = decode_message(msg)
                    result.setdefault(msg.channel, []).append(
                        (msg.log_time_sim_ns, obj)
                    )
                except (KeyError, ValueError):
                    pass
    finally:
        tmp_path.unlink(missing_ok=True)
    return result


# ---------------------------------------------------------------------------
# Run tab
# ---------------------------------------------------------------------------


def _show_run_results(summary: SmokeSummary, mcap_bytes: bytes) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cycles", summary.n_cycles)
    c2.metric("Decisions", summary.n_decisions)
    c3.metric("Outcomes", summary.n_outcomes)
    c4.metric("Final verdict", (summary.final_verdict or "—").replace("_", " "))

    col_a, col_b = st.columns(2)

    with col_a:
        st.caption("**Decisions by kind**")
        df_dec = pd.DataFrame(
            list(summary.decisions_by_kind.items()),
            columns=["Kind", "Count"],
        )
        st.bar_chart(df_dec.set_index("Kind"), color="#4e79a7")

    with col_b:
        st.caption("**Calibrated level per cycle**")
        levels = summary.calibrated_levels_observed
        df_cal = pd.DataFrame(
            {
                "Cycle": range(1, len(levels) + 1),
                "Level": levels,
                "Numeric": [_LEVEL_NUM.get(lv, -1) for lv in levels],
            }
        )
        st.line_chart(
            df_cal.set_index("Cycle")["Numeric"],
            color="#f28e2b",
        )
        st.caption("0 = known · 1 = uncertain · 2 = unknown")

    with st.expander("Full calibration sequence"):
        st.dataframe(
            df_cal.drop(columns=["Numeric"]),
            hide_index=True,
            use_container_width=True,
        )

    with st.expander("Provenance"):
        st.code(f"SHA-256  {summary.mcap_sha256}")

    st.download_button(
        "⬇ Download MCAP",
        data=mcap_bytes,
        file_name="smoke.mcap",
        mime="application/octet-stream",
        use_container_width=True,
    )


def _run_tab() -> None:
    st.markdown(
        "Execute the **closed-loop smoke** pipeline — oracle fusion → "
        "self-assessment → calibration → decision → actuation → "
        "forward prediction → divergence feedback."
    )

    if "run_result" not in st.session_state:
        st.session_state["run_result"] = None

    n_cycles = st.slider("Number of cycles", min_value=2, max_value=50, value=10)

    if st.button("▶ Run pipeline", type="primary", use_container_width=True):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mcap_path = Path(tmp_dir) / "smoke.mcap"
            with st.spinner(f"Running {n_cycles}-cycle pipeline…"):
                summary = run_closed_loop_smoke(mcap_path, n_cycles=n_cycles)
            mcap_bytes = mcap_path.read_bytes()
        st.session_state["run_result"] = (summary, mcap_bytes)

    result = st.session_state.get("run_result")
    if result is not None:
        summary, mcap_bytes = result
        st.divider()
        _show_run_results(summary, mcap_bytes)


# ---------------------------------------------------------------------------
# Inspect tab — section renderers
# ---------------------------------------------------------------------------


def _show_overview(messages: dict[str, list[tuple[int, Any]]]) -> None:
    rows = [
        {"Channel": ch, "Messages": len(msgs)}
        for ch, msgs in sorted(messages.items())
    ]
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, use_container_width=True
    )


def _show_decisions(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (t, obj) in enumerate(entries):
        if isinstance(obj, DecisionRationale):
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(t),
                    "Kind": obj.decision.kind.value,
                    "Policy": obj.policy_id,
                }
            )
    if not rows:
        st.info("No DecisionRationale records.")
        return
    df = pd.DataFrame(rows)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        counts = df["Kind"].value_counts().reset_index()
        counts.columns = pd.Index(["Kind", "Count"])
        st.caption("**Distribution**")
        st.bar_chart(counts.set_index("Kind"), color="#4e79a7")
    with col_b:
        st.caption("**All decisions**")
        st.dataframe(df, hide_index=True, use_container_width=True)


def _show_calibration(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (t, obj) in enumerate(entries):
        if isinstance(obj, CalibratedSelfAssessment):
            lvl = obj.adjusted_overall_level.value
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(t),
                    "Adjusted level": lvl,
                    "_num": _LEVEL_NUM.get(lvl, -1),
                }
            )
    if not rows:
        st.info("No CalibratedSelfAssessment records.")
        return
    df = pd.DataFrame(rows)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.caption("**Level over cycles** (0=known · 1=uncertain · 2=unknown)")
        st.line_chart(df.set_index("Cycle")["_num"], color="#f28e2b")
    with col_b:
        st.caption("**All records**")
        st.dataframe(
            df.drop(columns=["_num"]),
            hide_index=True,
            use_container_width=True,
        )


def _show_divergence(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (t, obj) in enumerate(entries):
        if isinstance(obj, PredictionOutcome):
            rows.append(
                {
                    "Outcome": i + 1,
                    "Stamp (ms)": _ms(t),
                    "Verdict": obj.verdict.value,
                    "Pos Mahal": round(obj.position_mahalanobis_max, 2),
                    "Ori Mahal": round(obj.orientation_mahalanobis_max, 2),
                    "Pos error (m)": round(float(obj.position_error_norm_m), 3),
                }
            )
    if not rows:
        st.info("No PredictionOutcome records.")
        return
    df = pd.DataFrame(rows)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.caption("**Position Mahalanobis over outcomes**")
        st.line_chart(df.set_index("Outcome")["Pos Mahal"], color="#e15759")
    with col_b:
        st.caption("**All outcomes**")
        st.dataframe(df, hide_index=True, use_container_width=True)


def _show_actuations(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (t, obj) in enumerate(entries):
        if isinstance(obj, ActuationDirective):
            cmd = obj.actuator_command
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(t),
                    "Command": type(cmd).__name__ if cmd is not None else "None",
                    "Reason": obj.reason,
                    "Policy": obj.policy_id,
                }
            )
    if not rows:
        st.info("No ActuationDirective records.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _show_self_assessment(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (t, obj) in enumerate(entries):
        if isinstance(obj, BeliefSelfAssessment):
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(t),
                    "Overall": obj.overall_level.value,
                    "Position": obj.position_overall_level.value,
                    "Velocity": obj.velocity_overall_level.value,
                    "Orientation": obj.orientation_overall_level.value,
                    "Cov present": obj.covariance_present,
                }
            )
    if not rows:
        st.info("No BeliefSelfAssessment records.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _show_fusion(entries: list[tuple[int, Any]]) -> None:
    rows = []
    for i, (t, obj) in enumerate(entries):
        if isinstance(obj, FusionResult):
            pos = obj.belief.nav.pose.position_enu_m
            rows.append(
                {
                    "Cycle": i + 1,
                    "Stamp (ms)": _ms(t),
                    "Policy": obj.fusion_policy_id,
                    "x (m)": round(float(pos[0]), 4),
                    "y (m)": round(float(pos[1]), 4),
                    "z (m)": round(float(pos[2]), 4),
                }
            )
    if not rows:
        st.info("No FusionResult records.")
        return
    df = pd.DataFrame(rows)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.caption("**Belief position x over cycles**")
        st.line_chart(df.set_index("Cycle")["x (m)"], color="#76b7b2")
    with col_b:
        st.caption("**All fusion records**")
        st.dataframe(df, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Replay verification section (expander inside Inspect)
# ---------------------------------------------------------------------------


def _show_replay_verification(file_bytes: bytes) -> None:
    st.markdown(
        "Re-execute the downstream pipeline from stored `/fusion/results` "
        "and verify byte-equality of all six downstream channels (ADR-0030)."
    )
    if st.button("▶ Verify replay", key="replay_btn"):
        from project_ghost.examples.replay_verification import (
            replay_downstream_from_fusion,
        )

        with (
            tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as src_tmp,
            tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as rpl_tmp,
        ):
            src_tmp.write(file_bytes)
            src_path = Path(src_tmp.name)
            rpl_path = Path(rpl_tmp.name)

        try:
            with st.spinner("Running replay verification…"):
                summary = replay_downstream_from_fusion(src_path, rpl_path)
        finally:
            src_path.unlink(missing_ok=True)
            rpl_path.unlink(missing_ok=True)

        if summary.all_channels_byte_equal:
            st.success("✅ All downstream channels are byte-equal.")
        else:
            st.error("❌ Some channels differ — pipeline non-determinism detected.")

        rows = [
            {
                "Channel": cv.channel,
                "Source msgs": cv.source_count,
                "Replay msgs": cv.replay_count,
                "Byte-equal": "✅" if cv.byte_equal else "❌",
            }
            for cv in summary.channels
        ]
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, use_container_width=True
        )


# ---------------------------------------------------------------------------
# Inspect tab
# ---------------------------------------------------------------------------

_SECTIONS = [
    ("📊 Decisions", CHANNEL_DECISIONS, _show_decisions),
    ("🧠 Calibration", CHANNEL_CALIBRATED_SELF_ASSESSMENT, _show_calibration),
    ("🎯 Divergence", CHANNEL_PREDICTION_OUTCOMES, _show_divergence),
    ("⚙ Actuations", CHANNEL_ACTUATIONS, _show_actuations),
    ("🔬 Self-Assessment", CHANNEL_SELF_ASSESSMENT, _show_self_assessment),
    ("🔭 Fusion", CHANNEL_FUSION_RESULTS, _show_fusion),
]


def _inspect_tab() -> None:
    st.markdown(
        "Upload a `.mcap` file produced by the closed-loop pipeline and "
        "explore decisions, calibration, divergence, actuation, and "
        "belief telemetry."
    )

    uploaded = st.file_uploader("Upload MCAP file", type=["mcap"])
    if uploaded is None:
        st.info("Upload a `.mcap` file to begin.")
        return

    file_bytes = uploaded.read()

    with st.spinner("Decoding MCAP…"):
        messages = _decode_mcap(file_bytes)

    if not messages:
        st.error("No decodeable messages found in this file.")
        return

    with st.expander("📁 Channel overview", expanded=True):
        _show_overview(messages)

    for title, channel, fn in _SECTIONS:
        if channel in messages:
            with st.expander(title, expanded=True):
                fn(messages[channel])

    if CHANNEL_FUSION_RESULTS in messages:
        with st.expander("🔄 Replay verification"):
            _show_replay_verification(file_bytes)


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Project Ghost",
    page_icon="👻",
    layout="wide",
    menu_items={
        "About": "Project Ghost — autonomy under uncertainty, sim-first."
    },
)
st.title("👻 Project Ghost")
st.caption("Autonomy under uncertainty — sim-first research platform")

_tab_run, _tab_inspect = st.tabs(["▶ Run Smoke", "🔍 Inspect MCAP"])

with _tab_run:
    _run_tab()

with _tab_inspect:
    _inspect_tab()
