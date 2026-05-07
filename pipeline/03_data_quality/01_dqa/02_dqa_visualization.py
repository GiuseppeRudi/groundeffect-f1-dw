from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from string import Template

PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "artifacts").exists():
    raise RuntimeError(
        "This script must be executed from the project root directory.\n"
        "Example:\n"
        "python pipeline/03_data_quality/01_general_dqa/02_general_dqa_visualization_minimal.py"
    )

sys.path.insert(0, str(PROJECT_ROOT))

DQA_CORE_DIR = PROJECT_ROOT / "pipeline" / "03_data_quality" / "01_dqa" / "core"
sys.path.insert(0, str(DQA_CORE_DIR))

from pipeline.utils.output_utils import ensure_dirs
from pipeline.utils.input_utils import read_csv
from dqa_engine import status_from_score


from pipeline.utils.file_names import (
    GENERAL_DQA_ISSUES_DIR,
    GENERAL_DQA_SCORECARDS_DIR,
    GENERAL_DQA_VISUALIZATIONS_TABLES_DIR,
    GENERAL_DQA_VISUALIZATIONS_HTML_DIR,
    GENERAL_DQA_VISUALIZATIONS_DIR,
    DQA_SCORECARD_FILE,
    DQA_ISSUES_FILE,
    GENERAL_DQA_OUTPUT_DIR
    )

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR / "templates"

SCORECARD_BY_TABLE_PATH = GENERAL_DQA_SCORECARDS_DIR / DQA_SCORECARD_FILE
ISSUES_ALL_TABLES_PATH = GENERAL_DQA_ISSUES_DIR / DQA_ISSUES_FILE

QUALITY_COLOR_MAP = {
    "green": "#2ca02c",
    "yellow": "#ffbf00",
    "red": "#d62728",
    "not_applicable": "#9e9e9e",
}

QUALITY_ORDER = ["green", "yellow", "red", "not_applicable"]

DIMENSION_SCORE_COLUMNS = [
    "completeness_score",
    "uniqueness_score",
    "validity_score",
    "consistency_score",
    "accuracy_plausibility_score",
    "timeliness_score",
    "referential_integrity_score",
]

DIMENSION_LABELS = {
    "completeness_score": "Completeness",
    "uniqueness_score": "Uniqueness",
    "validity_score": "Validity",
    "consistency_score": "Consistency",
    "accuracy_plausibility_score": "Accuracy / Plausibility",
    "timeliness_score": "Timeliness",
    "referential_integrity_score": "Referential Integrity",
}


# ============================================================
# HELPERS
# ============================================================


def save_fig(fig: go.Figure, filename: str) -> Path:
    path = GENERAL_DQA_VISUALIZATIONS_HTML_DIR / filename
    fig.write_html(path, include_plotlyjs="cdn", full_html=True)
    print(f"[OK] Saved figure: {path}")
    return path


def score_status(score: float | int | None) -> str:
    if pd.isna(score):
        return "not_applicable"
    if float(score) >= 0.95:
        return "green"
    if float(score) >= 0.80:
        return "yellow"
    return "red"


def html_escape(text: object) -> str:
    value = "" if pd.isna(text) else str(text)
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def style_status_columns(df: pd.DataFrame) -> pd.DataFrame:
    styled = df.copy()

    for col in styled.columns:
        if col.lower() in {"status", "severity"}:
            styled[col] = styled[col].apply(
                lambda x: f'<span class="status-{html_escape(x)}">{html_escape(x)}</span>'
            )

    return styled


def render_template(template_name: str, context: dict[str, object]) -> str:
    template_path = TEMPLATE_DIR / template_name

    if not template_path.exists():
        raise FileNotFoundError(f"Missing HTML template: {template_path}")

    template_text = template_path.read_text(encoding="utf-8")

    safe_context = {
        key: "" if value is None else str(value)
        for key, value in context.items()
    }

    return Template(template_text).substitute(safe_context)



def dataframe_to_interactive_html_table(df: pd.DataFrame, title: str, path: Path) -> None:

    if df.empty:
        html_table = "<p>No data available.</p>"
    else:
        html_table = df.to_html(
            index=False,
            classes="display compact",
            table_id="data-table",
            escape=False,
        )

    html = render_template(
        "dqa_table_template.html",
        {
            "title": html_escape(title),
            "subtitle": "Interactive table generated from the General Data Quality Assessment outputs.",
            "html_table": html_table,
        },
    )

    path.write_text(html, encoding="utf-8")
    print(f"[OK] Saved interactive table: {path}")






def plot_overall_score_by_table(scorecard_df: pd.DataFrame) -> go.Figure:
    """
    Main summary chart.
    It shows which tables have the best and worst overall DQA score.
    """

    df = scorecard_df.copy()

    if "status" not in df.columns:
        df["status"] = df["overall_score"].apply(score_status)

    df = df.sort_values("overall_score", ascending=True)

    hover_cols = ["issue_count"] if "issue_count" in df.columns else None

    fig = px.bar(
        df,
        x="overall_score",
        y="table_name",
        orientation="h",
        color="status",
        color_discrete_map=QUALITY_COLOR_MAP,
        category_orders={"status": QUALITY_ORDER},
        hover_data=hover_cols,
        title="Overall Data Quality Score by Table",
        labels={
            "overall_score": "Overall score",
            "table_name": "Table",
            "status": "Status",
        },
        text="overall_score",
    )

    fig.update_traces(texttemplate="%{text:.3f}", textposition="outside")
    fig.update_layout(
        xaxis=dict(range=[0, 1.05], tickformat=".0%"),
        yaxis_title="",
        height=max(450, 36 * len(df)),
        template="plotly_white",
        legend_title_text="Quality status",
        margin=dict(l=120, r=40, t=80, b=60),
    )

    fig.add_vline(x=0.80, line_dash="dash", line_color="#d62728", opacity=0.6)
    fig.add_vline(x=0.95, line_dash="dash", line_color="#2ca02c", opacity=0.6)

    return fig


def plot_dimension_score_heatmap(scorecard_df: pd.DataFrame) -> go.Figure:
    """
    Diagnostic chart.
    It shows the quality score for each table and each quality dimension.
    """

    available_cols = [col for col in DIMENSION_SCORE_COLUMNS if col in scorecard_df.columns]

    if not available_cols:
        raise ValueError("No dimension score columns found in dq_scorecard_by_table.csv")

    heatmap_df = scorecard_df[["table_name"] + available_cols].copy()
    heatmap_df = heatmap_df.set_index("table_name")
    heatmap_df = heatmap_df.rename(columns=DIMENSION_LABELS)

    fig = px.imshow(
        heatmap_df,
        x=heatmap_df.columns,
        y=heatmap_df.index,
        zmin=0,
        zmax=1,
        text_auto=".2f",
        aspect="auto",
        title="Data Quality Score Heatmap: Table × Dimension",
        labels=dict(x="Quality dimension", y="Table", color="Score"),
        color_continuous_scale=[
            [0.0, "#d62728"],
            [0.80, "#ffbf00"],
            [0.95, "#2ca02c"],
            [1.0, "#2ca02c"],
        ],
    )

    fig.update_layout(
        template="plotly_white",
        height=max(500, 40 * len(heatmap_df)),
        margin=dict(l=120, r=40, t=80, b=100),
    )

    return fig


def plot_issues_by_dimension(issues_df: pd.DataFrame) -> go.Figure:
    """
    Cleaning-priority chart.
    It shows which quality dimensions generate more issues.
    """

    if issues_df.empty:
        df = pd.DataFrame({"dimension": ["No issues"], "issue_count": [0]})
    else:
        df = (
            issues_df
            .groupby("dimension", as_index=False)
            .size()
            .rename(columns={"size": "issue_count"})
            .sort_values("issue_count", ascending=False)
        )

    fig = px.bar(
        df,
        x="dimension",
        y="issue_count",
        title="Number of Data Quality Issues by Dimension",
        labels={
            "issue_count": "Issue count",
            "dimension": "Quality dimension",
        },
        text="issue_count",
    )

    fig.update_traces(textposition="outside")
    fig.update_layout(
        template="plotly_white",
        xaxis_tickangle=-30,
        height=520,
        margin=dict(l=60, r=40, t=80, b=130),
    )

    return fig


# ============================================================
# DASHBOARD
# ============================================================

def create_dashboard(
    scorecard_df: pd.DataFrame,
    issues_df: pd.DataFrame,
    generated_files: dict[str, Path],
) -> None:
    num_tables = len(scorecard_df) if not scorecard_df.empty else 0

    avg_score = (
        scorecard_df["overall_score"].mean()
        if "overall_score" in scorecard_df.columns
        else float("nan")
    )

    total_issues = len(issues_df) if not issues_df.empty else 0

    worst_table = "N/A"
    worst_score = float("nan")

    if not scorecard_df.empty and "overall_score" in scorecard_df.columns:
        worst_row = scorecard_df.sort_values("overall_score", ascending=True).head(1)
        if not worst_row.empty:
            worst_table = str(worst_row.iloc[0]["table_name"])
            worst_score = float(worst_row.iloc[0]["overall_score"])

    def link(label: str, path: Path) -> str:
        rel = path.relative_to(GENERAL_DQA_VISUALIZATIONS_HTML_DIR)
        return f'<li><a href="{rel.as_posix()}">{html_escape(label)}</a></li>'

    links = "\n".join(
        [
            link("Overall score by table", generated_files["overall_score_by_table"]),
            link("Table × dimension heatmap", generated_files["dimension_score_heatmap"]),
            link("Issues by dimension", generated_files["issues_by_dimension"]),
            '<li><a href="../tables/scorecard_by_table_styled.html">Interactive scorecard table</a></li>',
            '<li><a href="../tables/issues_all_tables_styled.html">Interactive issues table</a></li>',
        ]
    )

    avg_score_text = "N/A" if pd.isna(avg_score) else f"{avg_score:.3f}"
    worst_score_text = "N/A" if pd.isna(worst_score) else f"{worst_score:.3f}"

    html = render_template(
        "dqa_dashboard_template.html",
        {
            "num_tables": num_tables,
            "avg_score_text": avg_score_text,
            "total_issues": total_issues,
            "worst_score_text": worst_score_text,
            "worst_table": html_escape(worst_table),
            "links": links,
        },
    )

    dashboard_path = GENERAL_DQA_VISUALIZATIONS_HTML_DIR / "dqa_general_dashboard.html"
    dashboard_path.write_text(html, encoding="utf-8")
    print(f"[OK] Saved dashboard: {dashboard_path}")

# ============================================================
# MAIN
# ============================================================

def main() -> None:
    paths : list[Path] = [
        GENERAL_DQA_VISUALIZATIONS_HTML_DIR,
        GENERAL_DQA_VISUALIZATIONS_TABLES_DIR,
    ]
    ensure_dirs(paths)

    print("[INFO] Starting minimal General DQA visualization script")
    print(f"[INFO] Input directory: {GENERAL_DQA_OUTPUT_DIR}")
    print(f"[INFO] Output directory: {GENERAL_DQA_VISUALIZATIONS_DIR}")

    scorecard_df = read_csv(SCORECARD_BY_TABLE_PATH)
    issues_df = read_csv(ISSUES_ALL_TABLES_PATH)

    if scorecard_df.empty:
        raise RuntimeError(
            "dq_scorecard_by_table.csv is missing or empty. "
            "Run 01_general_dqa.py before this visualization script."
        )

    if "overall_score" in scorecard_df.columns:
        scorecard_df["overall_score"] = pd.to_numeric(
            scorecard_df["overall_score"],
            errors="coerce",
        )

    for col in DIMENSION_SCORE_COLUMNS:
        if col in scorecard_df.columns:
            scorecard_df[col] = pd.to_numeric(scorecard_df[col], errors="coerce")

    generated_files: dict[str, Path] = {}

    fig = plot_overall_score_by_table(scorecard_df)
    generated_files["overall_score_by_table"] = save_fig(
        fig,
        "overall_score_by_table.html",
    )

    fig = plot_dimension_score_heatmap(scorecard_df)
    generated_files["dimension_score_heatmap"] = save_fig(
        fig,
        "dimension_score_heatmap.html",
    )

    fig = plot_issues_by_dimension(issues_df)
    generated_files["issues_by_dimension"] = save_fig(
        fig,
        "issues_by_dimension.html",
    )

    dataframe_to_interactive_html_table(
        style_status_columns(scorecard_df),
        title="General DQA Scorecard by Table",
        path=GENERAL_DQA_VISUALIZATIONS_TABLES_DIR / "scorecard_by_table_styled.html",
    )

    dataframe_to_interactive_html_table(
        style_status_columns(issues_df),
        title="General DQA Issues",
        path=GENERAL_DQA_VISUALIZATIONS_TABLES_DIR / "issues_all_tables_styled.html",
    )

    create_dashboard(
        scorecard_df=scorecard_df,
        issues_df=issues_df,
        generated_files=generated_files,
    )

    print("\n[OK] Minimal General DQA visualizations completed.")
    print("[INFO] Open this file in your browser:")
    print(f"       {GENERAL_DQA_VISUALIZATIONS_HTML_DIR / 'dqa_general_dashboard.html'}")


if __name__ == "__main__":
    main()
