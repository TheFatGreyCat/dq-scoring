from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.data import dataset_dashboard_rows, dataset_runs, latest_dataset_scores, load_dashboard_frames, run_details, score_summary_metrics  # noqa: E402
from dashboard.onboarding import infer_schema, load_csv_bytes, rows_to_schema, sanitize_dataset_id, schema_to_rows  # noqa: E402
from dq_core.health import get_system_health  # noqa: E402
from dq_core.runtime import DqRuntime  # noqa: E402
from persistence.repository import DqPostgresRepository  # noqa: E402


STATUS_COLORS = {
    "pass": "#16794c",
    "warning": "#a36200",
    "fail": "#b42318",
    "not_scored": "#667085",
    "not_available": "#667085",
}


V2_SETUP_COMMANDS = [
    "python -m persistence.db migrate",
    "python -m dq_core.cli bootstrap_catalog",
    "python -m dq_core.cli register_dataset --csv data/samples/customer_master.csv --dataset-id customer_master --dataset-type customer",
    "python -m dq_core.cli profile_dataset --dataset-version-id <dataset_version_id>",
    "python -m dq_core.cli recommend_rules --dataset-version-id <dataset_version_id>",
    "python -m dq_core.cli review_recommendation --recommendation-id <recommendation_id> --decision accepted",
    "python -m dq_core.cli save_recommended_bindings --dataset-version-id <dataset_version_id>",
    "python -m dq_core.cli run_validation --dataset-version-id <dataset_version_id>",
    "python -m dq_core.cli calculate_score --validation-run-id <validation_run_id>",
]


def main() -> None:
    st.set_page_config(page_title="DQ Score Dashboard", layout="wide")
    _inject_styles()
    st.title("DQ Score Dashboard")
    repository = DqPostgresRepository()
    runtime = DqRuntime(repository)

    dashboard_tab, onboarding_tab, catalog_tab, health_tab, logs_tab = st.tabs(["Dashboard", "Onboard", "Catalog", "System Health", "Logs"])
    with dashboard_tab:
        _render_dashboard()
    with onboarding_tab:
        _render_onboarding(runtime)
    with catalog_tab:
        _render_catalog(runtime)
    with health_tab:
        _render_health()
    with logs_tab:
        _render_logs(runtime)


def _render_dashboard() -> None:
    frames = load_dashboard_frames()
    latest = latest_dataset_scores(frames)
    if latest.empty:
        st.warning("No score history found. Register a dataset, run validation, then calculate a score.")
        st.code("\n".join(V2_SETUP_COMMANDS), language="powershell")
        return

    st.subheader("Overview")
    cols = st.columns(3)
    cols[0].metric("Datasets", len(latest))
    cols[1].metric("Average DQ Score", _score_text(latest["dq_core_score"].dropna().mean()))
    cols[2].metric("Failing Gates", int(latest["quality_gate_status"].eq("fail").sum()))
    overview = pd.DataFrame(
        [
            {
                "dataset_id": row.dataset_id,
                "dataset_name": row.dataset_name,
                "dataset_version_id": row.dataset_version_id,
                "dq_score": _round_score(row.dq_score),
                "quality_gate_status": row.quality_gate_status,
                "score_status": row.score_status,
                "last_run_at": row.last_run_at,
            }
            for row in dataset_dashboard_rows(frames)
        ]
    )
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

    run_now = st.checkbox("Run baseline after register", value=True)
    if st.button("Register Dataset", type="primary"):
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
        }
        dataset_version_id = runtime.register_dataset_bytes(csv_content, metadata)
        summary = {"dataset_version_id": dataset_version_id}
        if run_now:
            summary["profiling_run_id"] = runtime.profile_dataset(dataset_version_id)
            summary["binding_run_id"] = runtime.save_recommended_rule_bindings(dataset_version_id, accept_all_above_threshold=True)
            validation_run_id = runtime.run_validation(dataset_version_id)
            summary["validation_run_id"] = validation_run_id
            summary["score_run_id"] = runtime.calculate_score(validation_run_id)
        st.success("V2 onboarding completed")
        st.json(summary)



def _render_catalog(runtime: DqRuntime) -> None:
    st.subheader("Rule Catalog")
    try:
        inventory = runtime.catalog_inventory()
    except Exception as exc:
        st.warning(f"Cannot load catalog inventory: {exc}")
        return
    rules = pd.DataFrame(inventory.get("rules", []))
    coverage = pd.DataFrame(inventory.get("backend_coverage", []))
    issues = pd.DataFrame(inventory.get("issues", []))
    cols = st.columns(3)
    cols[0].metric("Rules", len(rules))
    cols[1].metric("Families", rules["family"].nunique() if "family" in rules.columns and not rules.empty else 0)
    cols[2].metric("Catalog Issues", len(issues))
    st.markdown("### Inventory")
    st.dataframe(rules, hide_index=True, use_container_width=True)
    st.markdown("### Backend Coverage")
    st.dataframe(coverage, hide_index=True, use_container_width=True)
    if not issues.empty:
        st.markdown("### Catalog Issues")
        st.dataframe(issues, hide_index=True, use_container_width=True)

def _render_health() -> None:
    health = get_system_health()
    st.subheader("System Health")
    cols = st.columns(4)
    cols[0].metric("PostgreSQL", health["postgresql"]["status"])
    cols[1].metric("Schema", health["schema"]["status"])
    cols[2].metric("Rule Catalog", health["rule_catalog"]["status"])
    cols[3].metric("Local LLM", health["local_llm"]["status"])

    rows = [
        {"component": "PostgreSQL", "key": "database", "value": health["postgresql"]["database"]},
        {"component": "PostgreSQL", "key": "host", "value": health["postgresql"]["host"]},
        {"component": "Schema", "key": "migration_table", "value": health["schema"]["migration_table"]},
        {"component": "Schema", "key": "latest_migration", "value": health["schema"]["latest_migration"]},
        {"component": "Schema", "key": "migration_count", "value": health["schema"]["migration_count"]},
        {"component": "Rule Catalog", "key": "template_count", "value": health["rule_catalog"]["template_count"]},
        {"component": "Runtime Storage", "key": "path", "value": health["runtime_storage"]["path"]},
        {"component": "Runtime Storage", "key": "writable", "value": health["runtime_storage"]["writable"]},
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    if health["postgresql"].get("error"):
        st.warning(health["postgresql"]["error"])


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
    cols = st.columns(5)
    cols[0].metric("DQ Score", _score_text(metrics["dq_core_score"]))
    cols[1].markdown(_status_badge(str(metrics["quality_gate_status"])), unsafe_allow_html=True)
    cols[2].metric("Coverage", _coverage_text(metrics.get("measurement_coverage")))
    cols[3].metric("Rules", metrics["rules_total"])
    cols[4].metric("Failed Rules", metrics["rules_failed"])

    dim_col, rule_col = st.columns([1, 1.4])
    with dim_col:
        st.markdown("### Dimensions")
        st.dataframe(details["dimensions"], hide_index=True, use_container_width=True)
    with rule_col:
        st.markdown("### Rules")
        st.dataframe(details["rules"], hide_index=True, use_container_width=True)

    breakdown_col, record_col = st.columns([1.2, 1])
    with breakdown_col:
        st.markdown("### Column Breakdown")
        column_breakdown = details.get("column_breakdown", pd.DataFrame())
        if column_breakdown.empty:
            st.info("No column-level rule or issue breakdown is available for this score run.")
        else:
            st.dataframe(column_breakdown, hide_index=True, use_container_width=True)
    with record_col:
        st.markdown("### Record Breakdown")
        record_breakdown = details.get("record_breakdown", pd.DataFrame())
        if record_breakdown.empty:
            st.info("No record-level issue samples are available for this score run.")
        else:
            st.dataframe(record_breakdown, hide_index=True, use_container_width=True)

    st.markdown("### Recommendations")
    recommendation_columns = [
        "column_id",
        "rule_code",
        "family",
        "dimension",
        "candidate_score",
        "rank",
        "score_margin",
        "ambiguity_status",
        "review_status",
        "score_components_jsonb",
        "warnings",
        "suggested_parameters_jsonb",
        "reason",
    ]
    recommendations = details.get("recommendations", pd.DataFrame())
    if recommendations.empty:
        st.info("No recommendation results are available for this dataset version yet.")
    else:
        st.dataframe(recommendations[[column for column in recommendation_columns if column in recommendations.columns]], hide_index=True, use_container_width=True)

    st.markdown("### Profiling Evidence")
    profile_columns = [
        "column_name",
        "inferred_type",
        "inferred_type_confidence",
        "metric_scope",
        "scan_mode",
        "coverage_estimate",
        "null_count",
        "blank_count",
        "distinct_count",
        "miscast_count",
        "miscast_ratio",
        "patterns",
        "top_values",
    ]
    profile_evidence = details.get("profile_evidence", pd.DataFrame())
    if profile_evidence.empty:
        st.info("No profiling evidence is available for this dataset version yet.")
    else:
        st.dataframe(profile_evidence[[column for column in profile_columns if column in profile_evidence.columns]], hide_index=True, use_container_width=True)

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


def _coverage_text(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.0f}%"


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





