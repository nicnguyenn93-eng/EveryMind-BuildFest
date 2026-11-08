import io
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from analysis import AUDIENCES, analyze_data
from clean import load_export
from report import draft_report_from_payload
# from feedback import search_feedback
# from export_pdf import generate_pdf_bytes

ACTION_CATALOG = json.loads((Path(__file__).parent / "action_catalog.json").read_text(encoding="utf-8"))
AUDIENCE_OPTIONS = ["All respondents"] + sorted(AUDIENCES - {"All respondents"})


def gemini_key():
    """API key from the environment or .streamlit/secrets.toml (both git-ignored)."""
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None


def current_analysis(audience):
    """Aggregate analysis for the loaded file and audience, computed once and reused."""
    cache = st.session_state.analysis_cache
    if audience not in cache:
        payload = analyze_data(st.session_state.df_responses, st.session_state.dataset_key,
                               audience, st.session_state.df_private_comments)
        payload["schema_version"] = "everymind.analysis.v2"
        cache[audience] = payload
    return cache[audience]


st.set_page_config(page_title="EveryMind Training Improvement Assistant", page_icon="🧠", layout="wide")

# -----------------------------------------------------------------------------
# 1. SESSION STATE
# -----------------------------------------------------------------------------
for name, default in [("dataset_key", None), ("df_responses", None), ("df_private_comments", None),
                      ("active_report", None), ("analysis_cache", {}), ("filename", None)]:
    if name not in st.session_state:
        st.session_state[name] = default

st.title("🧠 EveryMind Training Improvement Assistant")
st.caption("BuildFest 2026 Live Workspace")

# -----------------------------------------------------------------------------
# 2. STEP 1: UPLOAD THE ORIGINAL SURVEY EXPORT (first thing on the page)
# -----------------------------------------------------------------------------
with st.container(border=True):
    st.subheader("Step 1 · Upload the original survey export")
    uploaded_file = st.file_uploader(
        "Original EveryMind survey export (XLSX or CSV). It is cleaned and analyzed on this computer; "
        "only aggregate numbers are sent to the AI.",
        type=["xlsx", "csv"],
    )

if uploaded_file is not None:
    try:
        current_key, df_resp, df_priv, audit = load_export(uploaded_file.getvalue(), uploaded_file.name)
    except Exception as e:
        st.error(f"Could not read this file: {e}")
        st.stop()
    if st.session_state.dataset_key != current_key:  # new file: reset everything derived from the old one
        st.session_state.dataset_key = current_key
        st.session_state.df_responses = df_resp
        st.session_state.df_private_comments = df_priv  # stays local; never sent to the AI
        st.session_state.active_report = None
        st.session_state.analysis_cache = {}
        st.session_state.filename = uploaded_file.name
    st.success(f"Loaded **{st.session_state.filename}**: {len(st.session_state.df_responses)} responses.")
else:
    st.session_state.dataset_key = None
    st.session_state.df_responses = None
    st.session_state.df_private_comments = None
    st.session_state.active_report = None
    st.session_state.analysis_cache = {}

if st.session_state.dataset_key is None:
    st.info("👆 Upload the original survey export to start. Nothing else happens until a file is loaded.")
    st.stop()

# -----------------------------------------------------------------------------
# 3. STEP 2: AUDIENCE
# -----------------------------------------------------------------------------
selected_audience = st.selectbox("Step 2 · Choose the audience to analyze", AUDIENCE_OPTIONS)
payload = current_analysis(selected_audience)
evidence = payload["quantitative_evidence"]

if not evidence:
    st.warning(f"Not enough valid responses to report on **{selected_audience}** "
               "(groups under 10 people are withheld for privacy). Choose another audience.")
    st.stop()

tab_report, tab_explore = st.tabs(["📄 Report & Action Plan", "🔍 Evidence & Feedback"])

# -----------------------------------------------------------------------------
# TAB 1: REPORT AND ACTION PLAN
# -----------------------------------------------------------------------------
with tab_report:
    st.header(f"Report & action plan · {selected_audience}")

    report = st.session_state.active_report
    if report is not None and (report.get("dataset_key") != st.session_state.dataset_key
                               or report.get("audience") != selected_audience):
        st.session_state.active_report = None  # a report belongs to one file and one audience

    if st.session_state.active_report is None:
        if not gemini_key():
            st.caption("No GEMINI_API_KEY found, so the report will use the non-AI template.")
        if st.button("🚀 Generate report", type="primary"):
            with st.spinner("Sending aggregate evidence to Gemini and checking every number..."):
                st.session_state.active_report = draft_report_from_payload(
                    payload, ACTION_CATALOG, api_key=gemini_key())
            st.rerun()

    r = st.session_state.active_report
    if r is not None:
        if r["mode"] == "llm":
            st.success(f"AI-drafted report ({r['model']}). Every number was checked against the evidence.")
        else:
            st.warning(f"Template report (no AI). Reason: {r['fallback_reason']}")

        with st.container(border=True):
            st.subheader("🎯 Proposed action")
            st.markdown(f"**{r['proposed_action']}**")
            c_owner, c_measure = st.columns(2)
            c_owner.markdown(f"👤 **Staff owner:** {r['staff_owner']}")
            c_measure.markdown(f"📈 **Success measure:** {r['follow_up_measure']}")

        st.subheader("Summary")
        for block in r["summary_blocks"]:
            st.write(block)

        if r.get("proposed_recommendations"):
            st.subheader("Proposed pilots")
            for rec in r["proposed_recommendations"]:
                with st.expander(rec["proposed_action"]):
                    st.markdown(rec["pilot"])
                    st.markdown(f"**Owner:** {rec['staff_owner']}  \n**Measure:** {rec['follow_up_measure']}")
                    st.caption(f"Uncertainty: {rec['uncertainty']}")
                    st.caption("Evidence: " + ", ".join(rec["evidence_ids"]))

        st.caption(f"**Limitations:** {r['limitations']}")
        if st.button("↻ Regenerate"):
            st.session_state.active_report = None
            st.rerun()

        # PDF export (Role 4) is still a placeholder until export_pdf.py is implemented.
        st.markdown("---")
        st.download_button("📥 Download report (JSON)", data=json.dumps(r, indent=2, ensure_ascii=False),
                           file_name=f"everymind_report_{selected_audience.replace(' ', '_').replace('/', '_')}.json",
                           mime="application/json")

# -----------------------------------------------------------------------------
# TAB 2: EVIDENCE AND FEEDBACK (real numbers from the uploaded file)
# -----------------------------------------------------------------------------
with tab_explore:
    st.header(f"Evidence · {selected_audience}")
    def find(suffix):
        return next((e for e in evidence if e["evidence_id"].endswith(suffix)), None)

    cards = [("Can describe 988 (after)", find("EXPLAIN_988_POST"), find("EXPLAIN_988_CHANGE")),
             ("Know when to use 988 (after)", find("WHEN_988_POST"), find("WHEN_988_CHANGE")),
             ("Recommendation (0–10)", find("RECOMMENDATION_MEAN"), None)]
    cols = st.columns(3)
    for col, (label, e, change) in zip(cols, cards):
        with col:
            if e is None:
                st.metric(label, "withheld")
                continue
            st.metric(label, e["display_value"], delta=change["display_value"] if change else None)
            st.caption(f"{int(e['valid_denominator'])} valid answers · {e['caveat']}")

    st.subheader("All evidence sent to the AI")
    table = pd.DataFrame(evidence)[["evidence_id", "survey_question", "display_value", "valid_denominator", "caveat"]]
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.subheader("Open-answer themes")
    if payload["qualitative_themes"]:
        st.dataframe(pd.DataFrame(payload["qualitative_themes"]), hide_index=True, use_container_width=True)
    else:
        st.info("No reviewed comment themes yet. Themes appear here after a team member approves "
                "paraphrased comments; until then, reports use the numbers only.")
