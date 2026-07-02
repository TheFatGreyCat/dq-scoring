from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.data import (  # noqa: E402
    DEFAULT_RULE_STORE_PATH,
    DEFAULT_SCORE_STORE_PATH,
    aggregate_latest_status_counts,
    dataset_runs,
    latest_dataset_scores,
    load_dashboard_frames,
    run_details,
    score_summary_metrics,
)
from dashboard.onboarding import (  # noqa: E402
    DATASET_TYPES,
    SUPPORTED_TYPES,
    artifact_summary,
    default_cde_fields,
    default_mandatory_fields,
    infer_schema,
    load_csv_bytes,
    persist_onboarding_artifacts,
    rows_to_schema,
    sanitize_dataset_id,
    schema_to_rows,
    to_json_text,
)
from scoring.run import run_scoring  # noqa: E402


STATUS_COLORS = {
    "pass": "#16794c",
    "warning": "#a36200",
    "fail": "#b42318",
    "not_scored": "#667085",
    "not_available": "#667085",
}


def main() -> None:
    st.set_page_config(page_title="DQ Score Dashboard", layout="wide")
    _inject_styles()

    st.title("DQ Score Dashboard")
    st.caption("Phase 1 DQ Core Score across sample datasets")

    score_store, rule_store = _store_inputs()
    frames = load_dashboard_frames(score_store, rule_store)
    latest = latest_dataset_scores(frames)

    dashboard_tab, add_dataset_tab = st.tabs(["Dashboard", "Add Dataset"])
    with dashboard_tab:
        _render_dashboard(latest, frames)
    with add_dataset_tab:
        _render_add_dataset(score_store, rule_store)


def _render_dashboard(latest: pd.DataFrame, frames) -> None:
    if latest.empty:
        st.warning("No score history found. Run the demo data generator first.")
        st.code(r".\.venv\Scripts\python.exe dashboard\generate_demo_data.py --datasets all", language="powershell")
        return

    _render_overview(latest, frames)

    dataset_id = _dataset_selector(latest)
    runs = dataset_runs(frames, dataset_id)
    selected_run_id = _run_selector(runs)
    details = run_details(frames, selected_run_id)

    st.divider()
    _render_dataset_detail(dataset_id, details)
    st.divider()
    _render_trend(dataset_id, runs)
    st.divider()
    _render_methodology()


def _render_add_dataset(score_store: Path, rule_store: Path) -> None:
    st.subheader("Add Dataset")
    last_summary = st.session_state.pop("onboarding_summary", None)
    if last_summary:
        st.success("Dataset config created and scoring completed.")
        st.json(last_summary)

    uploaded = st.file_uploader("CSV dataset", type=["csv"])
    if uploaded is None:
        st.info("Upload a CSV file to infer schema and generate a first-pass DQ config.")
        return

    try:
        csv_content = uploaded.getvalue()
        dataframe = load_csv_bytes(csv_content)
    except Exception as exc:
        st.error(f"Cannot read uploaded CSV: {exc}")
        return

    default_dataset_id = sanitize_dataset_id(Path(uploaded.name).stem)
    dataset_id = st.text_input("Dataset ID", value=default_dataset_id)
    dataset_name = st.text_input("Dataset name", value=Path(uploaded.name).stem.replace("_", " ").title())
    dataset_type = st.selectbox("Dataset type", DATASET_TYPES, index=0)

    st.markdown("### Preview")
    preview_cols = st.columns(3)
    preview_cols[0].metric("Rows", len(dataframe))
    preview_cols[1].metric("Columns", len(dataframe.columns))
    preview_cols[2].metric("File", uploaded.name)
    st.dataframe(dataframe.head(20), use_container_width=True)

    inferred_schema = infer_schema(dataframe)
    schema_rows = schema_to_rows(inferred_schema)
    st.markdown("### Schema")
    edited_schema = st.data_editor(
        schema_rows,
        use_container_width=True,
        hide_index=True,
        disabled=["column_name"],
        column_config={
            "column_name": "Column",
            "data_type": st.column_config.SelectboxColumn("Data Type", options=SUPPORTED_TYPES, required=True),
            "nullable": st.column_config.CheckboxColumn("Nullable"),
        },
    )
    edited_schema_rows = _schema_editor_rows(edited_schema)

    columns = [str(column) for column in dataframe.columns]
    inferred_mandatory = default_mandatory_fields(dataframe)
    primary_key = st.multiselect("Primary key columns", columns, default=_default_key_columns(columns))
    business_key = st.multiselect("Business key columns", columns, default=[] if primary_key else _default_key_columns(columns))
    mandatory_fields = st.multiselect("Mandatory fields", columns, default=inferred_mandatory)
    cde_fields = st.multiselect("CDE fields", columns, default=default_cde_fields(dataframe, mandatory_fields))
    datetime_columns = [
        row["column_name"]
        for row in edited_schema_rows
        if row.get("data_type") == "datetime" and row.get("column_name") in columns
    ]
    timestamp_options = [""] + datetime_columns
    timestamp_column = st.selectbox("Timestamp column", timestamp_options, format_func=lambda value: value or "None")
    max_freshness_lag_hours = None
    if timestamp_column:
        max_freshness_lag_hours = st.number_input("Max freshness lag hours", min_value=1, value=24, step=1)

    run_scoring_now = st.checkbox("Run scoring after creating config", value=True)
    if st.button("Create Dataset Config", type="primary"):
        try:
            normalized_dataset_id = sanitize_dataset_id(dataset_id)
            declared_schema = rows_to_schema(edited_schema_rows)
            artifacts = persist_onboarding_artifacts(
                root=ROOT,
                dataset_id=normalized_dataset_id,
                dataset_name=dataset_name,
                dataset_type=dataset_type,
                csv_content=csv_content,
                declared_schema=declared_schema,
                primary_key=primary_key,
                business_key=business_key,
                mandatory_fields=mandatory_fields,
                cde_fields=cde_fields,
                timestamp_column=timestamp_column or None,
                max_freshness_lag_hours=int(max_freshness_lag_hours) if max_freshness_lag_hours else None,
            )
            summary: dict[str, object] = {"artifacts": artifact_summary(artifacts)}
            if run_scoring_now:
                result = run_scoring(
                    str(artifacts.dataset_config_path),
                    str(artifacts.rules_config_path),
                    str(artifacts.scoring_config_path),
                    str(rule_store),
                    str(score_store),
                )
                export_path = ROOT / "data" / "score_store" / f"{normalized_dataset_id}_score.json"
                export_path.parent.mkdir(parents=True, exist_ok=True)
                export_path.write_text(to_json_text(result.to_artifact()), encoding="utf-8")
                summary["scoring"] = result.to_summary(str(score_store))
                summary["export_json"] = str(export_path)
            st.session_state["onboarding_summary"] = summary
            st.rerun()
        except Exception as exc:
            st.error(f"Dataset onboarding failed: {exc}")


def _store_inputs() -> tuple[Path, Path]:
    with st.sidebar:
        st.header("Data Stores")
        score_store = Path(
            st.text_input("Score store", value=str(DEFAULT_SCORE_STORE_PATH), help="SQLite database with score history")
        )
        rule_store = Path(
            st.text_input("Rules store", value=str(DEFAULT_RULE_STORE_PATH), help="SQLite database with rule results")
        )
    return score_store, rule_store


def _render_overview(latest: pd.DataFrame, frames) -> None:
    st.subheader("Overview")
    counts = aggregate_latest_status_counts(frames)
    total_datasets = len(latest)
    avg_score = latest["dq_core_score"].dropna().mean() if "dq_core_score" in latest else None

    cols = st.columns(4)
    cols[0].metric("Datasets", total_datasets)
    cols[1].metric("Average DQ Core", _score_text(avg_score))
    cols[2].metric("Passing", counts.get("pass", 0))
    cols[3].metric("Warning / Fail", counts.get("warning", 0) + counts.get("fail", 0))

    overview = latest[
        [
            "dataset_id",
            "dq_core_score",
            "quality_gate_status",
            "total_records",
            "rules_total",
            "rules_failed",
            "run_timestamp",
        ]
    ].copy()
    overview["dq_core_score"] = overview["dq_core_score"].map(_round_score)
    st.dataframe(
        overview,
        use_container_width=True,
        hide_index=True,
        column_config={
            "dataset_id": "Dataset",
            "dq_core_score": st.column_config.NumberColumn("DQ Core", format="%.2f"),
            "quality_gate_status": "Gate",
            "total_records": st.column_config.NumberColumn("Records", format="%d"),
            "rules_total": st.column_config.NumberColumn("Rules", format="%d"),
            "rules_failed": st.column_config.NumberColumn("Failed Rules", format="%d"),
            "run_timestamp": st.column_config.DatetimeColumn("Latest Run"),
        },
    )


def _dataset_selector(latest: pd.DataFrame) -> str:
    dataset_ids = latest["dataset_id"].sort_values().tolist()
    with st.sidebar:
        st.header("Dataset")
        return st.selectbox("Dataset", dataset_ids)


def _default_key_columns(columns: list[str]) -> list[str]:
    for column in columns:
        lower = column.lower()
        if lower == "id" or lower.endswith("_id"):
            return [column]
    return []


def _schema_editor_rows(value) -> list[dict]:
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    return [dict(row) for row in value]


def _run_selector(runs: pd.DataFrame) -> str:
    if runs.empty:
        return ""
    labels = {
        row.run_id: f"{row.run_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC') if pd.notna(row.run_timestamp) else row.run_id} - {row.run_id}"
        for row in runs.itertuples()
    }
    with st.sidebar:
        return st.selectbox("Run", list(labels.keys()), format_func=lambda run_id: labels[run_id])


def _render_dataset_detail(dataset_id: str, details: dict) -> None:
    st.subheader(f"Dataset Detail: {dataset_id}")
    metrics = score_summary_metrics(details["dataset_score"])
    score = metrics["dq_core_score"]
    status = str(metrics["quality_gate_status"])

    cols = st.columns(5)
    cols[0].metric("DQ Core Score", _score_text(score))
    cols[1].markdown(_status_badge(status), unsafe_allow_html=True)
    cols[2].metric("Records", metrics["total_records"])
    cols[3].metric("Rules", metrics["rules_total"])
    cols[4].metric("Failed Rules", metrics["rules_failed"])

    dim_col, issue_col = st.columns([1.4, 1])
    with dim_col:
        _render_dimensions(details["dimensions"])
    with issue_col:
        _render_issue_summary(details["issues"])

    st.markdown("### Rule Breakdown")
    _render_rules(details["rules"])

    st.markdown("### Issue Samples")
    _render_issues(details["issues"])


def _render_dimensions(dimensions: pd.DataFrame) -> None:
    st.markdown("### Dimension Scores")
    if dimensions.empty:
        st.info("No dimension scores for this run.")
        return
    chart_data = dimensions[dimensions["measurement_status"] == "measured"][["dimension", "dimension_score"]]
    if not chart_data.empty:
        st.bar_chart(chart_data.set_index("dimension"), height=280)
    table = dimensions[
        [
            "dimension",
            "dimension_score",
            "dimension_weight",
            "measurement_status",
            "rules_total",
            "rules_failed",
            "rules_warning",
            "rules_passed",
        ]
    ].copy()
    table["dimension_score"] = table["dimension_score"].map(_round_score)
    st.dataframe(table, hide_index=True, use_container_width=True)


def _render_issue_summary(issues: pd.DataFrame) -> None:
    st.markdown("### Issue Counts")
    if issues.empty:
        st.info("No issue samples captured for this run.")
        return
    counts = issues["issue_type"].value_counts().rename_axis("issue_type").reset_index(name="sample_count")
    st.bar_chart(counts.set_index("issue_type"), height=280)
    st.dataframe(counts, hide_index=True, use_container_width=True)


def _render_rules(rules: pd.DataFrame) -> None:
    if rules.empty:
        st.info("No rule scores for this run.")
        return
    columns = [
        "rule_id",
        "rule_name",
        "dimension",
        "target_column",
        "rule_score",
        "threshold",
        "quality_status",
        "passed",
        "failed",
        "miscast",
        "empty",
        "not_applicable",
        "measurement_status",
        "severity",
    ]
    existing = [column for column in columns if column in rules.columns]
    table = rules[existing].copy()
    if "rule_score" in table:
        table["rule_score"] = table["rule_score"].map(_round_score)
    st.dataframe(table, hide_index=True, use_container_width=True)


def _render_issues(issues: pd.DataFrame) -> None:
    if issues.empty:
        st.info("No issue samples captured for this run.")
        return
    columns = [
        "rule_id",
        "rule_name",
        "severity",
        "record_key",
        "target_column",
        "actual_value",
        "issue_type",
        "expected_condition",
    ]
    existing = [column for column in columns if column in issues.columns]
    st.dataframe(issues[existing], hide_index=True, use_container_width=True)


def _render_trend(dataset_id: str, runs: pd.DataFrame) -> None:
    st.subheader("Trend")
    if runs.empty:
        st.info("No run history available.")
        return
    trend = runs.sort_values("run_timestamp")[["run_timestamp", "dq_core_score", "quality_gate_status", "rules_failed"]]
    st.line_chart(trend.set_index("run_timestamp")[["dq_core_score"]], height=260)
    st.dataframe(trend, hide_index=True, use_container_width=True)


def _render_methodology() -> None:
    st.subheader("Methodology")
    col1, col2, col3 = st.columns(3)
    col1.markdown("**RuleScore**")
    col1.code("passed / total_records_in_scope * 100")
    col2.markdown("**DimensionScore**")
    col2.code("weighted average of measured RuleScore")
    col3.markdown("**DQ Core Score**")
    col3.code("sum(dimension_weight * DimensionScore)")
    st.caption(
        "Dimensions with no measured rule are marked not_measured and excluded from the normalized weight sum. "
        "Phase 1 shows DQ Core Score only; TrustScore and FinalScore are outside this dashboard version."
    )


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
        .block-container { padding-top: 1.6rem; }
        .status-card {
            border: 1px solid #d0d5dd;
            border-radius: 8px;
            min-height: 78px;
            padding: 0.75rem 0.9rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 0.15rem;
        }
        .status-card span {
            display: block;
            width: 36px;
            height: 5px;
            border-radius: 999px;
            margin-bottom: 0.2rem;
        }
        .status-card strong { text-transform: uppercase; font-size: 1.05rem; }
        .status-card small { color: #667085; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
