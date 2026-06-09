"""Project Ghost — Streamlit dashboard with guided UX.

Designed for first-time visitors: explains what the platform is,
what each pipeline stage does, and interprets results in plain language.

Usage::

    streamlit run src/project_ghost/app/main.py
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
# Colour palette  (consistent across all visualisations)
# ---------------------------------------------------------------------------

_KIND_COLOR: dict[str, str] = {
    "proceed":      "#59a14f",
    "hold":         "#f28e2b",
    "engage_kill":  "#e15759",
}
_LEVEL_COLOR: dict[str, str] = {
    "known":     "#59a14f",
    "uncertain": "#f28e2b",
    "unknown":   "#e15759",
}
_VERDICT_COLOR: dict[str, str] = {
    "within_1_std": "#59a14f",
    "beyond_1_std": "#f28e2b",
    "beyond_3_std": "#e15759",
    "beyond_5_std": "#b07aa1",
}
_LEVEL_NUM: dict[str, int] = {"known": 0, "uncertain": 1, "unknown": 2}

# ---------------------------------------------------------------------------
# HTML / CSS helpers
# ---------------------------------------------------------------------------

_CSS = """
<style>
.pg-badge {
    display:inline-block;
    padding:3px 11px;
    border-radius:5px;
    font-weight:700;
    font-size:13px;
    white-space:nowrap;
    color:#fff;
    margin:2px;
}
.pg-pipeline-step {
    text-align:center;
    padding:10px 4px;
    border-radius:8px;
    background:#1c1c2e;
}
.pg-pipeline-arrow {
    text-align:center;
    font-size:20px;
    opacity:0.5;
    padding-top:14px;
}
.pg-callout {
    padding:14px 18px;
    border-radius:8px;
    border-left:4px solid #4e79a7;
    background:#1c1c2e;
    margin:12px 0;
    line-height:1.6;
}
</style>
"""


def _inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def _badge(label: str, color: str) -> str:
    return f'<span class="pg-badge" style="background:{color}">{label}</span>'


def _badges(mapping: dict[str, int], color_map: dict[str, str]) -> None:
    parts = [
        _badge(f"{k.replace('_',' ').upper()} x{v}", color_map.get(k, "#888"))
        for k, v in sorted(mapping.items(), key=lambda x: -x[1])
    ]
    st.markdown("&nbsp;".join(parts), unsafe_allow_html=True)


def _callout(text: str) -> None:
    st.markdown(
        f'<div class="pg-callout">{text}</div>', unsafe_allow_html=True
    )


def _section(icon: str, title: str, description: str) -> None:
    st.markdown(f"### {icon}&nbsp; {title}")
    st.caption(description)


# ---------------------------------------------------------------------------
# MCAP decode cache
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _decode_mcap(file_bytes: bytes) -> dict[str, list[tuple[int, Any]]]:
    """Decode all messages from MCAP bytes. Cached per unique file."""
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


def _ms(ns: int) -> float:
    return round(ns / 1_000_000, 1)


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------


def _hero() -> None:
    st.markdown(
        "#### An autonomous agent that knows what it doesn't know."
    )
    _callout(
        "Project Ghost is a <strong>research platform for autonomy under "
        "uncertainty</strong>. The agent estimates its own position and "
        "orientation, assesses how confident it is in those estimates, "
        "calibrates that confidence against real prediction errors — and "
        "then decides whether to <strong>proceed</strong>, "
        "<strong>hold</strong>, or <strong>abort</strong>. "
        "Everything is deterministic, auditable, and traceable."
    )


# ---------------------------------------------------------------------------
# Pipeline diagram
# ---------------------------------------------------------------------------

_PIPELINE: list[tuple[str, str, str]] = [
    ("🔭", "Fusion", "Sensor data → belief about current state"),
    ("🧠", "Assessment", "Am I confident in this belief?"),
    ("⚖️", "Calibration", "Adjust for past prediction errors"),
    ("🎯", "Decision", "Proceed · Hold · Abort"),
    ("⚙️", "Actuation", "Send command to vehicle"),
    ("🔮", "Prediction", "What will the state be next cycle?"),
    ("📊", "Outcome", "Was that prediction right?"),
    ("🔄", "Feedback", "Update confidence model"),
]


def _pipeline_diagram() -> None:
    st.markdown("#### The 8-step decision loop")
    n = len(_PIPELINE)
    # interleave steps and arrows: 8 steps + 7 arrows = 15 columns
    widths = []
    for i in range(n):
        widths.append(3)
        if i < n - 1:
            widths.append(1)
    cols = st.columns(widths)
    col_idx = 0
    for i, (icon, name, desc) in enumerate(_PIPELINE):
        with cols[col_idx]:
            st.markdown(
                f'<div class="pg-pipeline-step">'
                f"<div style='font-size:22px'>{icon}</div>"
                f"<div style='font-weight:700;font-size:13px'>{name}</div>"
                f"<div style='font-size:11px;opacity:0.7;margin-top:4px'>{desc}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        col_idx += 1
        if i < n - 1:
            with cols[col_idx]:
                st.markdown(
                    '<div class="pg-pipeline-arrow">→</div>',
                    unsafe_allow_html=True,
                )
            col_idx += 1
    st.caption(
        "The feedback loop (steps 6 → 8 → 3) is the key: if predictions are "
        "consistently wrong, confidence is downgraded automatically — preventing "
        "the agent from acting on an unreliable belief."
    )


# ---------------------------------------------------------------------------
# Run narrative
# ---------------------------------------------------------------------------


def _run_narrative(summary: SmokeSummary) -> str:
    levels = summary.calibrated_levels_observed
    first_change = next(
        (i + 1 for i, lv in enumerate(levels) if lv != "known"), None
    )
    verdict = summary.final_verdict or ""
    verdict_human = {
        "beyond_5_std":  "consistently <strong>way off</strong> (more than 5-sigma)",
        "beyond_3_std":  "significantly off (more than 3-sigma)",
        "beyond_1_std":  "moderately off (more than 1-sigma)",
        "within_1_std":  "accurate (within 1-sigma)",
    }.get(verdict, verdict.replace("_", " "))

    parts: list[str] = [
        f"The agent completed <strong>{summary.n_cycles} cycles</strong>."
    ]

    if first_change and first_change > 1:
        parts.append(
            f"For the first <strong>{first_change - 1} cycle(s)</strong> "
            f"it was fully confident (<em>known</em>) and chose to "
            f"<strong>proceed</strong>. "
            f"At cycle <strong>{first_change}</strong> the accumulated "
            f"prediction errors triggered a confidence downgrade to "
            f"<em>uncertain</em>, switching all subsequent decisions to "
            f"<strong>hold</strong>."
        )
    elif first_change == 1:
        parts.append(
            "The agent was <em>uncertain</em> from cycle 1 and held throughout."
        )
    else:
        parts.append(
            "The agent remained <em>known</em> throughout all cycles "
            "and always chose to <strong>proceed</strong>."
        )

    parts.append(
        f"Every prediction was {verdict_human}. "
        "The oracle believed the vehicle was stationary while ground truth "
        "drifted at 5 m/s — a deliberate overconfidence trap to test the "
        "calibration feedback loop."
    )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Run tab
# ---------------------------------------------------------------------------


def _show_run_results(summary: SmokeSummary, mcap_bytes: bytes) -> None:
    _callout(_run_narrative(summary))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cycles run", summary.n_cycles)
    c2.metric("Decisions made", summary.n_decisions)
    c3.metric("Outcomes evaluated", summary.n_outcomes)
    verdict = (summary.final_verdict or "—").replace("_", " ")
    c4.metric("Prediction quality", verdict)

    col_a, col_b = st.columns(2)

    with col_a:
        _section(
            "🎯", "Decision distribution",
            "How the agent decided to act each cycle. "
            "PROCEED = confident & safe. HOLD = uncertain, stay put.",
        )
        _badges(summary.decisions_by_kind, _KIND_COLOR)
        df_dec = pd.DataFrame(
            list(summary.decisions_by_kind.items()), columns=["Kind", "Count"]
        )
        st.bar_chart(df_dec.set_index("Kind"), color="#4e79a7")

    with col_b:
        _section(
            "⚖️", "Calibration over time",
            "0 = KNOWN (high confidence) · 1 = UNCERTAIN (degraded) · "
            "2 = UNKNOWN (blind). Watch for the downgrade event.",
        )
        levels = summary.calibrated_levels_observed
        df_cal = pd.DataFrame(
            {
                "Cycle": range(1, len(levels) + 1),
                "Level (0=known)": [_LEVEL_NUM.get(lv, -1) for lv in levels],
            }
        )
        st.line_chart(df_cal.set_index("Cycle"), color="#f28e2b")

    with st.expander("📋 Calibrated level per cycle"):
        df_show = pd.DataFrame(
            {"Cycle": range(1, len(levels) + 1), "Adjusted level": levels}
        )
        st.dataframe(df_show, hide_index=True, use_container_width=True)

    with st.expander("🔐 Provenance (SHA-256)"):
        st.caption(
            "Every MCAP is content-addressed. Same inputs → same hash. "
            "This hash is the fingerprint of this exact run."
        )
        st.code(summary.mcap_sha256, language=None)

    st.download_button(
        "⬇ Download MCAP",
        data=mcap_bytes,
        file_name="project_ghost_smoke.mcap",
        mime="application/octet-stream",
        help="Download the full telemetry log. Upload it to the Inspect tab to explore.",
        use_container_width=True,
    )


def _run_tab() -> None:
    st.markdown(
        "Run the **closed-loop simulation** in your browser. "
        "The pipeline executes in full: oracle fusion → self-assessment → "
        "calibration → decision → actuation → forward prediction → "
        "divergence feedback. Results are captured to a downloadable MCAP file."
    )

    st.divider()
    _pipeline_diagram()
    st.divider()

    if "run_result" not in st.session_state:
        st.session_state["run_result"] = None

    st.markdown("#### Configure the run")
    n_cycles = st.slider(
        "Number of cycles",
        min_value=2,
        max_value=50,
        value=10,
        help=(
            "Each cycle is one iteration of the full 8-step loop. "
            "With fewer than 5 cycles the calibration downgrade won't fire — "
            "try 10 or more to see the full feedback story."
        ),
    )

    if st.button("▶ Run simulation", type="primary", use_container_width=True):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mcap_path = Path(tmp_dir) / "smoke.mcap"
            with st.spinner(f"Running {n_cycles}-cycle pipeline…"):
                summary = run_closed_loop_smoke(mcap_path, n_cycles=n_cycles)
            mcap_bytes = mcap_path.read_bytes()
        st.session_state["run_result"] = (summary, mcap_bytes)

    result = st.session_state.get("run_result")
    if result is not None:
        st.divider()
        st.markdown("#### What happened")
        _show_run_results(*result)


# ---------------------------------------------------------------------------
# Inspect tab — section renderers
# ---------------------------------------------------------------------------


def _show_overview(messages: dict[str, list[tuple[int, Any]]]) -> None:
    rows = [
        {"Channel": ch, "Messages": len(msgs)}
        for ch, msgs in sorted(messages.items())
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


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
        st.info("No DecisionRationale records in this MCAP.")
        return
    df = pd.DataFrame(rows)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        counts = df["Kind"].value_counts().reset_index()
        counts.columns = pd.Index(["Kind", "Count"])
        _badges(
            dict(zip(counts["Kind"], counts["Count"], strict=True)), _KIND_COLOR
        )
        st.bar_chart(counts.set_index("Kind"), color="#4e79a7")
    with col_b:
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
        st.info("No CalibratedSelfAssessment records in this MCAP.")
        return
    df = pd.DataFrame(rows)
    downgrade_cycle = next(
        (r["Cycle"] for r in rows if r["_num"] > 0), None
    )
    if downgrade_cycle:
        st.warning(
            f"⚠️ Confidence downgraded at **cycle {downgrade_cycle}** — "
            "prediction errors exceeded the calibration threshold."
        )
    else:
        st.success("✅ Confidence stayed **known** throughout all cycles.")

    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.caption("**Level over cycles** — 0 = known · 1 = uncertain · 2 = unknown")
        st.line_chart(df.set_index("Cycle")["_num"], color="#f28e2b")
    with col_b:
        st.dataframe(
            df.drop(columns=["_num"]), hide_index=True, use_container_width=True
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
                    "Pos Mahalanobis": round(obj.position_mahalanobis_max, 2),
                    "Ori Mahalanobis": round(obj.orientation_mahalanobis_max, 2),
                    "Pos error (m)": round(float(obj.position_error_norm_m), 3),
                }
            )
    if not rows:
        st.info("No PredictionOutcome records in this MCAP.")
        return
    df = pd.DataFrame(rows)
    verdict_counts = df["Verdict"].value_counts().to_dict()
    _badges(verdict_counts, _VERDICT_COLOR)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.caption("**Position Mahalanobis** — how many 'standard surprises' off")
        st.line_chart(df.set_index("Outcome")["Pos Mahalanobis"], color="#e15759")
    with col_b:
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
                    "Command type": type(cmd).__name__ if cmd is not None else "None",
                    "Reason": obj.reason,
                    "Policy": obj.policy_id,
                }
            )
    if not rows:
        st.info("No ActuationDirective records in this MCAP.")
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
        st.info("No BeliefSelfAssessment records in this MCAP.")
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
        st.info("No FusionResult records in this MCAP.")
        return
    df = pd.DataFrame(rows)
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.caption(
            "**Belief position x** — the oracle believes the vehicle is "
            "stationary at 0 m while ground truth drifts at 5 m/s."
        )
        st.line_chart(df.set_index("Cycle")["x (m)"], color="#76b7b2")
    with col_b:
        st.dataframe(df, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Replay verification
# ---------------------------------------------------------------------------


def _show_replay_verification(file_bytes: bytes) -> None:
    st.caption(
        "Re-executes the downstream pipeline (assessment → calibration → "
        "decision → actuation → prediction → divergence) from the stored "
        "`/fusion/results` channel and verifies that every message is "
        "byte-for-byte identical to the original run. "
        "This proves the pipeline has no hidden non-determinism."
    )
    if not st.button("▶ Run verification", key="replay_btn"):
        return

    from project_ghost.examples.replay_verification import (
        replay_downstream_from_fusion,
    )

    with (
        tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as src_f,
        tempfile.NamedTemporaryFile(suffix=".mcap", delete=False) as rpl_f,
    ):
        src_f.write(file_bytes)
        src_path, rpl_path = Path(src_f.name), Path(rpl_f.name)

    try:
        with st.spinner("Replaying downstream pipeline…"):
            summary = replay_downstream_from_fusion(src_path, rpl_path)
    finally:
        src_path.unlink(missing_ok=True)
        rpl_path.unlink(missing_ok=True)

    if summary.all_channels_byte_equal:
        st.success(
            "✅ **Byte-perfect replay.** All 6 downstream channels are "
            "identical between original run and replay."
        )
    else:
        st.error(
            "❌ **Mismatch detected.** At least one channel differs — "
            "possible non-determinism in the pipeline."
        )

    rows = [
        {
            "Channel": cv.channel,
            "Original": cv.source_count,
            "Replay": cv.replay_count,
            "Result": "✅ byte-equal" if cv.byte_equal else "❌ differs",
        }
        for cv in summary.channels
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Inspect tab
# ---------------------------------------------------------------------------

_INSPECT_SECTIONS: list[tuple[str, str, str, str]] = [
    (
        CHANNEL_DECISIONS, "🎯", "Decisions",
        "Each cycle the agent chose one action based on its calibrated confidence. "
        "**PROCEED** means the agent is confident enough to continue. "
        "**HOLD** means it detected uncertainty and stopped to reassess.",
    ),
    (
        CHANNEL_CALIBRATED_SELF_ASSESSMENT, "⚖️", "Calibration",
        "The raw confidence level adjusted by the feedback loop. "
        "When past predictions are consistently wrong the agent downgrades from "
        "**KNOWN** to **UNCERTAIN** — preventing it from acting on a stale belief.",
    ),
    (
        CHANNEL_PREDICTION_OUTCOMES, "📊", "Divergence outcomes",
        "After each cycle the prediction made the cycle before is compared to "
        "ground truth. The **Mahalanobis distance** says how many 'standard "
        "surprises' the actual observation was from the prediction. "
        ">5-sigma means the model was wildly wrong.",
    ),
    (
        CHANNEL_ACTUATIONS, "⚙️", "Actuations",
        "The physical command issued each cycle. "
        "**AttitudeCommand** holds attitude and thrust. "
        "**DirectMotorCommand** drives motors directly (emergency). "
        "**None** means the policy chose not to emit a command.",
    ),
    (
        CHANNEL_SELF_ASSESSMENT, "🧠", "Raw self-assessment",
        "The unfiltered confidence estimate before the calibration feedback loop. "
        "Compare this to the calibrated level to see the effect of the feedback.",
    ),
    (
        CHANNEL_FUSION_RESULTS, "🔭", "Fusion results",
        "The agent's belief about its current state, produced by the fusion layer. "
        "In this simulation the oracle always reports position ≈ 0 — "
        "while ground truth drifts. That gap drives the divergence.",
    ),
]

_SECTION_FN = {
    CHANNEL_DECISIONS: _show_decisions,
    CHANNEL_CALIBRATED_SELF_ASSESSMENT: _show_calibration,
    CHANNEL_PREDICTION_OUTCOMES: _show_divergence,
    CHANNEL_ACTUATIONS: _show_actuations,
    CHANNEL_SELF_ASSESSMENT: _show_self_assessment,
    CHANNEL_FUSION_RESULTS: _show_fusion,
}


def _inspect_tab() -> None:
    st.markdown(
        "Upload a `.mcap` file to explore every layer of the pipeline: "
        "decisions, calibration, divergence, actuations, raw self-assessment, "
        "and the belief produced by fusion."
    )
    st.info(
        "💡 **Tip:** Run the simulation in the **▶ Try the simulation** tab "
        "and download the MCAP — then upload it here to see what happened "
        "inside each step.",
        icon="💡",
    )

    uploaded = st.file_uploader(
        "Upload MCAP file",
        type=["mcap"],
        help="Files produced by ghost-app, the ghost CLI, or run_closed_loop_smoke().",
    )
    if uploaded is None:
        return

    file_bytes = uploaded.read()
    with st.spinner("Decoding MCAP…"):
        messages = _decode_mcap(file_bytes)

    if not messages:
        st.error("No decodeable messages found. Is this a valid Project Ghost MCAP?")
        return

    with st.expander("📁 Channel overview", expanded=False):
        _show_overview(messages)

    for channel, icon, title, description in _INSPECT_SECTIONS:
        if channel not in messages:
            continue
        with st.expander(f"{icon} {title}", expanded=True):
            st.caption(description)
            _SECTION_FN[channel](messages[channel])

    if CHANNEL_FUSION_RESULTS in messages:
        with st.expander("🔄 Replay verification", expanded=False):
            _show_replay_verification(file_bytes)


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Project Ghost",
    page_icon="👻",
    layout="wide",
    menu_items={"About": "Project Ghost — autonomy under uncertainty, sim-first."},
)

_inject_css()

st.title("👻 Project Ghost")
_hero()
st.divider()

_tab_run, _tab_inspect = st.tabs(
    ["▶ Try the simulation", "🔍 Inspect a run"]
)

with _tab_run:
    _run_tab()

with _tab_inspect:
    _inspect_tab()
