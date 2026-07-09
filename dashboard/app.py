from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.data import dataset_runs, latest_dataset_scores, load_dashboard_frames, run_details, score_summary_metrics  # noqa: E402
from dashboard.onboarding import infer_schema, load_csv_bytes, rows_to_schema, sanitize_dataset_id, schema_to_rows  # noqa: E402
from dq_core.runtime import DqRuntime  # noqa: E402
from persistence.repository import DqPostgresRepository  # noqa: E402


STATUS_COLORS = {
    "pass": "#16794c",
    "warning": "#a36200",
    "fail": "#b42318",
    "not_scored": "#667085",
    "not_available": "#667085",
}


def main() -> None:
    st.set_page_config(page_title="DQ Score Dashboard V2", layout="wide")
    _inject_styles()
    st.title("DQ Score Dashboard V2")
    database_url = st.sidebar.text_input("PostgreSQL URL", value="", type="password", help="Defaults to DQ_DATABASE_URL when empty")
    repository = DqPostgresRepository(database_url or None)
    runtime = DqRuntime(repository)

    dashboard_tab, onboarding_tab, logs_tab = st.tabs(["Dashboard", "Onboard", "Logs"])
    with dashboard_tab:
        _render_dashboard(database_url or None)
    with onboarding_tab:
        _render_onboarding(runtime)
    with logs_tab:
        _render_logs(runtime)


def _render_dashboard(database_url: str | None) -> None:
    frames = load_dashboard_frames(database_url)
    latest = latest_dataset_scores(frames)
    if latest.empty:
        st.warning("No V2 score history found. Import legacy metadata, run validation, then calculate score.")
        st.code("python -m persistence.import_legacy --dry-run", language="powershell")
        return

    st.subheader("Overview")
    cols = st.columns(3)
    cols[0].metric("Datasets", len(latest))
    cols[1].metric("Average DQ Score", _score_text(latest["dq_core_score"].dropna().mean()))
    cols[2].metric("Failing Gates", int(latest["quality_gate_status"].eq("fail").sum()))
    overview = latest[["dataset_id", "dq_core_score", "quality_gate_status", "run_timestamp"]].copy()
    overview["dq_core_score"] = overview["dq_core_score"].map(_round_score)
    st.dataframe(overview, use_container_width=True, hide_index=True)

    dataset_id = st.sidebar.selectbox("Dataset", latest["dataset_id"].sort_values().tolist())
    runs = dataset_runs(frames, dataset_id)
    run_id = st.sidebar.selectbox("Score Run", runs["run_id"].tolist())
    details = run_details(frames, run_id)
    _render_dataset_detail(dataset_id, details)


def _render_onboarding(runtime: DqRuntime) -> None:
    st.subheader("Dataset Onboarding")
    uploaded = st.file_uploader("CSV dataset", type=["csv"])
    if uploaded is None:
        return
    csv_content = uploaded.getvalue()
    dataframe = load_csv_bytes(csv_content)
    dataset_id = sanitize_dataset_id(st.text_input("Dataset ID", value=Path(uploaded.name).stem))
    dataset_name = st.text_input("Dataset name", value=Path(uploaded.name).stem.replace("_", " ").title())
    dataset_type = st.text_input("Dataset type", value="default")
    st.dataframe(dataframe.head(20), use_container_width=True)

    schema_rows = schema_to_rows(infer_schema(dataframe))
    edited_schema = st.data_editor(schema_rows, use_container_width=True, hide_index=True, disabled=["column_name"])
    edited_schema_rows = edited_schema.to_dict(orient="records") if hasattr(edited_schema, "to_dict") else [dict(row) for row in edited_schema]
    columns = [str(column) for column in dataframe.columns]
    primary_key = st.multiselect("Primary key", columns, default=_default_key_columns(columns))
    business_key = st.multiselect("Business key", columns, default=[])
    mandatory_fields = st.multiselect("Mandatory fields", columns, default=primary_key)
    cde_fields = st.multiselect("CDE fields", columns, default=[])
    timestamp_column = st.selectbox("Timestamp column", [""] + columns)

    run_now = st.checkbox("Run V2 baseline after register", value=True)
    if st.button("Register Dataset", type="primary"):
        temp_path = ROOT / "data" / "uploads" / uploaded.name
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(csv_content)
        metadata = {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "dataset_type": dataset_type,
            "declared_schema": rows_to_schema(edited_schema_rows),
            "primary_key": primary_key,
            "business_key": business_key,
            "mandatory_fields": mandatory_fields,
            "cde_fields": cde_fields,
            "timestamp_column": timestamp_column or None,
            "storage_path": str(temp_path),
        }
        dataset_version_id = runtime.register_dataset(temp_path, metadata)
        summary = {"dataset_version_id": dataset_version_id}
        if run_now:
            summary["profiling_run_id"] = runtime.profile_dataset(dataset_version_id)
            summary["binding_run_id"] = runtime.save_recommended_rule_bindings(dataset_version_id)
            validation_run_id = runtime.run_validation(dataset_version_id)
            summary["validation_run_id"] = validation_run_id
            summary["score_run_id"] = runtime.calculate_score(validation_run_id)
        st.success("V2 onboarding completed")
        st.json(summary)


def _render_logs(runtime: DqRuntime) -> None:
    try:
        logs = pd.DataFrame(runtime.get_pipeline_logs())
    except Exception as exc:
        st.warning(f"Cannot load pipeline logs: {exc}")
        return
    if logs.empty:
        st.info("No pipeline logs yet.")
        return
    st.dataframe(logs.sort_values("created_at", ascending=False), use_container_width=True, hide_index=True)


def _render_dataset_detail(dataset_id: str, details: dict) -> None:
    st.subheader(f"Dataset Detail: {dataset_id}")
    metrics = score_summary_metrics(details["dataset_score"])
    cols = st.columns(4)
    cols[0].metric("DQ Score", _score_text(metrics["dq_core_score"]))
    cols[1].markdown(_status_badge(str(metrics["quality_gate_status"])), unsafe_allow_html=True)
    cols[2].metric("Rules", metrics["rules_total"])
    cols[3].metric("Failed Rules", metrics["rules_failed"])

    dim_col, rule_col = st.columns([1, 1.4])
    with dim_col:
        st.markdown("### Dimensions")
        st.dataframe(details["dimensions"], hide_index=True, use_container_width=True)
    with rule_col:
        st.markdown("### Rules")
        st.dataframe(details["rules"], hide_index=True, use_container_width=True)
    st.markdown("### Issue Samples")
    st.dataframe(details["issues"], hide_index=True, use_container_width=True)


def _default_key_columns(columns: list[str]) -> list[str]:
    for column in columns:
        lower = column.lower()
        if lower == "id" or lower.endswith("_id"):
            return [column]
    return []


def _status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#667085")
    return f'<div class="status-card"><span style="background:{color}"></span><strong>{status}</strong><small>Quality Gate</small></div>'


def _score_text(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.2f}"


def _round_score(value):
    if value is None or pd.isna(value):
        return None
    return round(float(value), 2)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.4rem; }
        .status-card { border: 1px solid #d0d5dd; border-radius: 8px; min-height: 76px; padding: .75rem .9rem; display:flex; flex-direction:column; justify-content:center; gap:.15rem; }
        .status-card span { display:block; width:36px; height:5px; border-radius:999px; margin-bottom:.2rem; }
        .status-card strong { text-transform:uppercase; font-size:1.05rem; }
        .status-card small { color:#667085; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
