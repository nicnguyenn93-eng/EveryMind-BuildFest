import streamlit as st
import pandas as pd
import io

# Import your team's modules
# (Once clean.py, metrics.py, feedback.py, report.py, and export_pdf.py are filled out)
# from clean import load_export
# from metrics import build_evidence
# from feedback import search_feedback
# from report import draft_report
# from export_pdf import generate_pdf_bytes

st.set_page_config(
    page_title="EveryMind Training Improvement Assistant",
    page_icon="🧠",
    layout="wide"
)

# -----------------------------------------------------------------------------
# 1. SESSION STATE INITIALIZATION
# -----------------------------------------------------------------------------
if "dataset_key" not in st.session_state:
    st.session_state.dataset_key = None
if "df_responses" not in st.session_state:
    st.session_state.df_responses = None
if "df_private_comments" not in st.session_state:
    st.session_state.df_private_comments = None
if "active_report" not in st.session_state:
    st.session_state.active_report = None

# -----------------------------------------------------------------------------
# 2. HEADER & JOURNEY TRACKER
# -----------------------------------------------------------------------------
st.title("🧠 EveryMind Training Improvement Assistant")
st.caption("BuildFest 2026 Live Workspace")

# -----------------------------------------------------------------------------
# 3. WORKBOOK IMPORT SIDEBAR (Role 1)
# -----------------------------------------------------------------------------
st.sidebar.header("1. Data Ingestion")
uploaded_file = st.sidebar.file_uploader(
    "Upload Survey Export (XLSX or CSV)",
    type=["xlsx", "csv"],
    help="Must contain the structural ID and knowledge fields."
)

if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name

    # Mocking Role 1 call for boilerplate verification
    # In production, replace with:
    # current_key, df_resp, df_priv, audit = load_export(file_bytes, filename)
    current_key = f"DS_{hash(filename) % 10000}"

    # Atomic State Reset if a brand new file is uploaded
    if st.session_state.dataset_key != current_key:
        st.session_state.dataset_key = current_key
        # Create a tiny mock dataframe to let UI elements render before clean.py is wired
        st.session_state.df_responses = pd.DataFrame({"role": ["Student"] * 12 + ["School staff"] * 5})
        st.session_state.active_report = None  # Invalidate stale report
        st.sidebar.success(f"Loaded: {filename} ({current_key})")
else:
    # Clear state if file is removed
    st.session_state.dataset_key = None
    st.session_state.df_responses = None
    st.session_state.active_report = None

# -----------------------------------------------------------------------------
# 4. AUDIENCE SELECTION (Role 1 / User Question Constraint)
# -----------------------------------------------------------------------------
st.sidebar.header("2. Analysis Parameters")
selected_audience = st.sidebar.selectbox(
    "Select Target Audience",
    options=["Students", "School staff", "All respondents"],
    disabled=st.session_state.dataset_key is None
)

# -----------------------------------------------------------------------------
# 5. MAIN INTERFACE WORKFLOW
# -----------------------------------------------------------------------------
if st.session_state.dataset_key is None:
    st.info("👋 Welcome! Please upload an Excel or CSV survey export file in the sidebar to begin the evaluation workflow.")
else:
    # Main Workflow Tabs
    tab_explore, tab_report = st.tabs(["🔍 Feedback Explorer", "📄 Executive Report & Action Plan"])

    # -------------------------------------------------------------------------
    # TAB 1: EXPLORE RELEVANT FEEDBACK (Role 2)
    # -------------------------------------------------------------------------
    with tab_explore:
        st.header(f"Explore Feedback for: {selected_audience}")

        # User Question Free-Text Intent Routing
        search_query = st.text_input(
            "Search open-text student comments (e.g., type 'teachers' to route to School Staff context):",
            placeholder="Type your search queries here..."
        )

        # Explicit choice intercept requested by user schema
        if "teacher" in search_query.lower():
            st.warning("⚠️ **System Hint:** Your search references 'teachers'. Would you like to explicitly shift your audience selection to **School staff** to match survey records?")
            if st.button("Switch Audience to School staff"):
                st.rerun()

        # Quantitative Metrics Cards Grid
        st.subheader("Current Aggregate Performance Metrics")
        col1, col2, col3 = st.columns(3)

        # Mocking metrics data structure from metrics.py
        with col1:
            st.metric(label="988 Post-Training Agreement", value="90.5%", delta="+2.3%")
            with st.expander("Show evidence"):
                st.json({
                    "evidence_id": "EV_988_POST_01",
                    "question": "post-training agreement on explaining 988",
                    "counts": "1,175 of 1,299 valid responses",
                    "limitations": "none"
                })
        with col2:
            st.metric(label="Recommendation Score (Mean)", value="8.4 / 10")
            with st.expander("Show evidence"):
                st.caption("Source: Q14 Recommendation Rating. Denominator: 1,299.")
        with col3:
            st.metric(label="Processed Theme Coverage", value="94.1%", delta="-0.5% flagged")
            with st.expander("Show evidence"):
                st.caption("1,222 text rows reviewed. 77 suppressed via local paraphrase rules.")

        # Text/Comment Panel
        st.subheader("Paraphrased Theme Distribution (Privacy Preserved)")
        st.markdown("*Displaying approved summaries matching local privacy codebook configurations*")

        # Sample structured view
        mock_comments = [
            {"Theme": "Interactive Exercises", "Paraphrase": "Students requested more hands-on roleplay scenarios for 988 calls.", "Count": 14},
            {"Theme": "Pacing", "Paraphrase": "General agreement that introduction sequence was clear and appropriately timed.", "Count": 11}
        ]
        st.table(pd.DataFrame(mock_comments))

    # -------------------------------------------------------------------------
    # TAB 2: GENERATE REPORT & EXPORT PDF (Role 3 & Role 4)
    # -------------------------------------------------------------------------
    with tab_report:
        st.header("Executive Action Planner")
        st.markdown("Propose data-driven pilots and generate printable artifacts for the Training Lead.")

        # Parameter Mutation Invalidation Check
        if st.session_state.active_report is None:
            if st.button("🚀 Generate Report", type="primary"):
                with st.spinner("Orchestrating non-private evidence tokens via LLM Provider API..."):
                    # Mocking Role 3 draft_report logic
                    st.session_state.active_report = {
                        "summary": "Student confidence benchmarks met the 90% target, but secondary metrics indicate structural requests for applied simulation exercises.",
                        "action_id": "ACT_PILOT_ROLEPLAY",
                        "proposed_action": "Launch a 988 Scenario Roleplay Pilot",
                        "owner": "Training Lead",
                        "measure": "Proportion of students successfully completing the interactive roleplay scenario in the next cohort.",
                        "limitations": "Excludes historical data metrics due to unmapped county aliases."
                    }
                    st.rerun()
            else:
                st.info("Parameters have changed or report has not been compiled yet. Click 'Generate Report' above.")

        # Display Compiled Active Report
        if st.session_state.active_report is not None:
            st.success("Report generation complete!")

            # Action Box Layout
            with st.container(border=True):
                st.subheader("🎯 Proposed Strategic Action")
                st.markdown(f"**Action Item:** {st.session_state.active_report['proposed_action']}")

                c_owner, c_measure = st.columns(2)
                with c_owner:
                    st.markdown(f"👤 **Staff Owner:** {st.session_state.active_report['owner']}")
                with c_measure:
                    st.markdown(f"📈 **Success Measure:** {st.session_state.active_report['measure']}")

            # Summary Narrative Text
            st.subheader("Executive Narrative Summary")
            st.write(st.session_state.active_report["summary"])

            st.caption(f"**Data Limitations & Caveats:** {st.session_state.active_report['limitations']}")

            # PDF Downloader Implementation (Role 4)
            st.markdown("---")
            st.subheader("Download Executive Artifact")

            # Create sample dummy PDF stream for testing the download wrapper button
            pdf_buffer = io.BytesIO()
            pdf_buffer.write(b"%PDF-1.4 Mock Reportlab PDF Output Buffer Data Stream")
            pdf_buffer.seek(0)

            st.download_button(
                label="📥 Download One-Page Executive PDF",
                data=pdf_buffer,
                file_name=f"EveryMind_Executive_Report_{st.session_state.dataset_key}.pdf",
                mime="application/pdf",
                help="Generates tight, high-contrast canvas layout via ReportLab stream."
            )
