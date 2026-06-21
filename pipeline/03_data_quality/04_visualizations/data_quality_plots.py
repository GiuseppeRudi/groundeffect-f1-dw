from __future__ import annotations

from html import escape
import math
import os
from pathlib import Path
import sys
from typing import Callable

import pandas as pd


PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "artifacts").exists():
    raise RuntimeError("This script must be executed from the project root directory.")

sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.utils.input_utils import read_csv
from pipeline.utils.output_utils import ensure_dirs
from pipeline.utils.file_names import (
    DATA_QUALITY_FIGURES_DIR,
    DATA_QUALITY_VISUALIZATIONS_HTML_DIR,
    DATA_QUALITY_VISUALIZATIONS_TABLES_DIR,
    DATA_QUALITY_VISUALIZATIONS_OUTPUT_DIR,
    GENERAL_DQA_SCORECARDS_DIR,
    GENERAL_DQA_ISSUES_DIR,
    DQA_SCORECARD_FILE,
    DQA_CHECK_RESULTS_FILE,
    DQA_ISSUES_FILE,
    FOCUSED_MISSING_SUMMARY_PATH,
    FOCUSED_MISSING_ROW_FLAGS_PATH,
    OUTLIER_SUMMARY_PATH,
    LAP_OUTLIER_FLAGS_PATH,
)


SCORECARD_BY_TABLE_PATH = GENERAL_DQA_SCORECARDS_DIR / DQA_SCORECARD_FILE
CHECK_RESULTS_PATH = GENERAL_DQA_SCORECARDS_DIR / DQA_CHECK_RESULTS_FILE
ISSUES_ALL_TABLES_PATH = GENERAL_DQA_ISSUES_DIR / DQA_ISSUES_FILE

MAX_TABLE_ROWS = 500

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

FIGURE_FILES = {
    "dqa_score_by_table": "General DQA overall score by table",
    "dqa_issues_by_table": "General DQA issues by table",
    "dqa_dimension_heatmap": "General DQA score heatmap",
    "missing_class_distribution": "Missing value distribution by class",
    "missing_information_area": "Missing values by information area",
    "outlier_by_metric": "Consensus outliers by metric",
    "outlier_rate_by_metric": "Consensus outlier rate by metric",
    "outlier_methods_by_metric": "Outlier detection methods by metric",
}


def to_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def finite_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def format_int(value: object) -> str:
    return f"{int(round(finite_float(value))):,}"


def format_float(value: object, digits: int = 3) -> str:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(out):
        return "N/A"
    return f"{out:.{digits}f}"


def write_svg(filename: str, body: str, width: int, height: int) -> Path:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .title {{ font: 700 20px Arial, sans-serif; fill: #20242a; }}
    .axis {{ font: 12px Arial, sans-serif; fill: #4d5968; }}
    .label {{ font: 12px Arial, sans-serif; fill: #20242a; }}
    .value {{ font: 700 12px Arial, sans-serif; fill: #20242a; }}
    .small {{ font: 11px Arial, sans-serif; fill: #667085; }}
    .grid {{ stroke: #d9dee7; stroke-width: 1; stroke-dasharray: 4 4; }}
  </style>
  <rect width="100%" height="100%" fill="#ffffff"/>
{body}
</svg>
"""
    path = DATA_QUALITY_FIGURES_DIR / filename
    path.write_text(svg, encoding="utf-8")
    print(f"[OK] Saved figure: {path}")
    return path


def scale(value: float, minimum: float, maximum: float, width: float) -> float:
    if maximum <= minimum:
        return 0.0
    return (value - minimum) / (maximum - minimum) * width


def horizontal_bar_chart(
    *,
    title: str,
    labels: list[str],
    values: list[float],
    filename: str,
    value_formatter: Callable[[float], str],
    color: str,
    minimum: float = 0.0,
    maximum: float | None = None,
    x_axis_label: str = "",
) -> Path:
    clean_values = [finite_float(value) for value in values]
    if maximum is None:
        maximum = max(clean_values + [1.0]) * 1.18
    if maximum <= minimum:
        maximum = minimum + 1.0

    width = 1100
    row_height = 34
    top = 74
    bottom = 54
    left = min(max(max((len(label) for label in labels), default=8) * 7 + 42, 160), 330)
    right = 170
    plot_width = width - left - right
    height = top + bottom + row_height * max(len(labels), 1)

    parts = [
        f'<text class="title" x="28" y="34">{escape(title)}</text>',
        f'<text class="axis" x="{left + plot_width / 2:.1f}" y="{height - 14}" text-anchor="middle">{escape(x_axis_label)}</text>',
    ]

    for tick_index in range(6):
        tick = minimum + (maximum - minimum) * tick_index / 5
        x = left + scale(tick, minimum, maximum, plot_width)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 16}" x2="{x:.1f}" y2="{height - bottom + 6}"/>')
        parts.append(f'<text class="small" x="{x:.1f}" y="{height - 32}" text-anchor="middle">{escape(value_formatter(tick))}</text>')

    for row_index, (label, value) in enumerate(zip(labels, clean_values)):
        y = top + row_index * row_height
        bar_width = max(scale(value, minimum, maximum, plot_width), 0)
        label_y = y + 19
        parts.append(f'<text class="label" x="{left - 12}" y="{label_y}" text-anchor="end">{escape(label)}</text>')
        parts.append(f'<rect x="{left}" y="{y + 4}" width="{bar_width:.1f}" height="22" rx="3" fill="{color}"/>')

        value_label = value_formatter(value)
        outside_x = left + bar_width + 8
        if outside_x + 88 > left + plot_width and bar_width > 80:
            text_x = left + bar_width - 8
            anchor = "end"
            fill = "#ffffff"
        else:
            text_x = outside_x
            anchor = "start"
            fill = "#20242a"
        parts.append(
            f'<text class="value" x="{text_x:.1f}" y="{label_y}" text-anchor="{anchor}" fill="{fill}">{escape(value_label)}</text>'
        )

    return write_svg(filename, "\n".join(parts), width, height)


def score_color(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "#e5e7eb"
    if value >= 0.95:
        return "#79b66c"
    if value >= 0.80:
        return "#f1c75b"
    return "#d46a6a"


def heatmap_chart(scorecard_df: pd.DataFrame) -> Path | None:
    available_cols = [column for column in DIMENSION_SCORE_COLUMNS if column in scorecard_df.columns]
    if not available_cols:
        print("[WARN] No dimension score columns found. Skipping heatmap.")
        return None

    df = to_numeric(scorecard_df[["table_name"] + available_cols], available_cols)
    labels = [DIMENSION_LABELS[column] for column in available_cols]
    rows = df["table_name"].astype(str).tolist()

    cell_width = 132
    cell_height = 38
    left = 166
    top = 92
    width = left + cell_width * len(labels) + 38
    height = top + cell_height * len(rows) + 64

    parts = [f'<text class="title" x="28" y="34">{escape("General DQA Score Heatmap")}</text>']
    for col_index, label in enumerate(labels):
        x = left + col_index * cell_width + cell_width / 2
        parts.append(
            f'<text class="axis" x="{x:.1f}" y="68" text-anchor="middle">{escape(label)}</text>'
        )

    for row_index, row_label in enumerate(rows):
        y = top + row_index * cell_height
        parts.append(
            f'<text class="label" x="{left - 12}" y="{y + 24}" text-anchor="end">{escape(row_label)}</text>'
        )
        for col_index, column in enumerate(available_cols):
            raw_value = df.iloc[row_index][column]
            value = None if pd.isna(raw_value) else finite_float(raw_value, default=float("nan"))
            color = score_color(value)
            x = left + col_index * cell_width
            display = "n/a" if value is None or not math.isfinite(value) else f"{value:.3f}"
            text_color = "#20242a" if value is None or value >= 0.92 else "#ffffff"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_width - 2}" height="{cell_height - 2}" fill="{color}" stroke="#ffffff"/>')
            parts.append(
                f'<text x="{x + cell_width / 2:.1f}" y="{y + 24}" text-anchor="middle" font="700 12px Arial, sans-serif" fill="{text_color}">{escape(display)}</text>'
            )

    return write_svg("dqa_dimension_heatmap.svg", "\n".join(parts), width, height)


def grouped_horizontal_bar_chart(
    *,
    title: str,
    data: pd.DataFrame,
    filename: str,
    colors: list[str],
) -> Path:
    metrics = data.index.astype(str).tolist()
    columns = data.columns.astype(str).tolist()
    max_value = max([finite_float(v) for v in data.to_numpy().flatten()] + [1.0])

    width = 1120
    row_height = 54
    bar_height = 12
    top = 86
    bottom = 58
    left = min(max(max((len(metric) for metric in metrics), default=8) * 7 + 46, 160), 280)
    right = 190
    plot_width = width - left - right
    height = top + bottom + row_height * max(len(metrics), 1)

    parts = [
        f'<text class="title" x="28" y="34">{escape(title)}</text>',
    ]

    legend_x = left
    for idx, (column, color) in enumerate(zip(columns, colors)):
        x = legend_x + idx * 170
        parts.append(f'<rect x="{x}" y="52" width="12" height="12" fill="{color}"/>')
        parts.append(f'<text class="small" x="{x + 18}" y="63">{escape(column)}</text>')

    axis_max = max_value * 1.20
    for tick_index in range(6):
        tick = axis_max * tick_index / 5
        x = left + scale(tick, 0, axis_max, plot_width)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{height - bottom + 4}"/>')
        parts.append(f'<text class="small" x="{x:.1f}" y="{height - 30}" text-anchor="middle">{escape(format_int(tick))}</text>')

    for row_index, metric in enumerate(metrics):
        row_y = top + row_index * row_height
        parts.append(f'<text class="label" x="{left - 12}" y="{row_y + 28}" text-anchor="end">{escape(metric)}</text>')
        for col_index, (column, color) in enumerate(zip(columns, colors)):
            value = finite_float(data.loc[metric, column])
            y = row_y + 5 + col_index * (bar_height + 3)
            bar_width = scale(value, 0, axis_max, plot_width)
            parts.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="{bar_height}" rx="2" fill="{color}"/>')

    return write_svg(filename, "\n".join(parts), width, height)


def plot_dqa_score_by_table(scorecard_df: pd.DataFrame) -> Path:
    df = to_numeric(scorecard_df, ["overall_score"]).dropna(subset=["overall_score"])
    df = df.sort_values("overall_score", ascending=True)
    min_score = float(df["overall_score"].min())
    max_score = float(df["overall_score"].max())
    span = max(max_score - min_score, 0.0005)
    return horizontal_bar_chart(
        title="General DQA Overall Score by Table",
        labels=df["table_name"].astype(str).tolist(),
        values=df["overall_score"].tolist(),
        filename="dqa_score_by_table.svg",
        value_formatter=lambda value: f"{value:.6f}",
        color="#2f6f73",
        minimum=max(0.0, min_score - span * 0.35),
        maximum=min(1.0005, max_score + span * 0.90),
        x_axis_label="Overall score",
    )


def plot_dqa_issues_by_table(scorecard_df: pd.DataFrame) -> Path:
    df = to_numeric(scorecard_df, ["issue_count"]).copy()
    if "issue_count" not in df.columns:
        df["issue_count"] = 0
    df["issue_count"] = df["issue_count"].fillna(0)
    df = df.sort_values("issue_count", ascending=True)
    return horizontal_bar_chart(
        title="General DQA Issues by Table",
        labels=df["table_name"].astype(str).tolist(),
        values=df["issue_count"].tolist(),
        filename="dqa_issues_by_table.svg",
        value_formatter=format_int,
        color="#7b4f9d",
        x_axis_label="Detected issues",
    )


def plot_missing_class_distribution(missing_summary_df: pd.DataFrame) -> Path:
    df = to_numeric(missing_summary_df, ["explained_null_count", "suspicious_null_count"])
    class_counts = pd.Series(
        {
            "Explained null": df.get("explained_null_count", pd.Series(dtype="float64")).sum(),
            "Suspicious null": df.get("suspicious_null_count", pd.Series(dtype="float64")).sum(),
        }
    ).sort_values(ascending=True)
    return horizontal_bar_chart(
        title="Missing Value Distribution by Class",
        labels=class_counts.index.astype(str).tolist(),
        values=class_counts.tolist(),
        filename="missing_class_distribution.svg",
        value_formatter=format_int,
        color="#b65f5f",
        x_axis_label="Missing values",
    )


def plot_missing_information_area(missing_summary_df: pd.DataFrame) -> Path | None:
    area_columns = [
        column
        for column in missing_summary_df.columns
        if column.endswith("_information_count") or column == "none_count"
    ]
    if not area_columns:
        print("[WARN] No missing information area columns found. Skipping plot.")
        return None

    df = to_numeric(missing_summary_df, area_columns)
    info_counts = df[area_columns].sum()
    info_counts.index = (
        info_counts.index.to_series()
        .str.replace("_information_count", "", regex=False)
        .str.replace("_count", "", regex=False)
        .str.replace("_", " ")
        .str.title()
    )
    info_counts = info_counts[info_counts > 0].sort_values(ascending=True)
    return horizontal_bar_chart(
        title="Missing Values by Information Area",
        labels=info_counts.index.astype(str).tolist(),
        values=info_counts.tolist(),
        filename="missing_information_area.svg",
        value_formatter=format_int,
        color="#3f7c9a",
        x_axis_label="Missing values",
    )


def completed_outlier_summary(outlier_summary_df: pd.DataFrame) -> pd.DataFrame:
    df = outlier_summary_df.copy()
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.lower().eq("completed")].copy()
    return to_numeric(
        df,
        ["tested_values", "iqr_outliers", "modified_z_outliers", "consensus_outliers"],
    ).fillna(
        {
            "tested_values": 0,
            "iqr_outliers": 0,
            "modified_z_outliers": 0,
            "consensus_outliers": 0,
        }
    )


def plot_outlier_by_metric(outlier_summary_df: pd.DataFrame) -> Path:
    df = completed_outlier_summary(outlier_summary_df)
    metric_counts = (
        df.groupby("metric", as_index=True)["consensus_outliers"]
        .sum()
        .sort_values(ascending=True)
    )
    return horizontal_bar_chart(
        title="Consensus Outliers by Metric",
        labels=metric_counts.index.astype(str).tolist(),
        values=metric_counts.tolist(),
        filename="outlier_by_metric.svg",
        value_formatter=format_int,
        color="#b77945",
        x_axis_label="Consensus outliers",
    )


def plot_outlier_rate_by_metric(outlier_summary_df: pd.DataFrame) -> Path:
    df = completed_outlier_summary(outlier_summary_df)
    metric_totals = df.groupby("metric", as_index=True)[
        ["tested_values", "consensus_outliers"]
    ].sum()
    denominator = metric_totals["tested_values"].replace(0, pd.NA)
    metric_totals["consensus_outlier_rate"] = (
        metric_totals["consensus_outliers"] / denominator * 100
    ).fillna(0)
    metric_rates = metric_totals["consensus_outlier_rate"].sort_values(ascending=True)
    return horizontal_bar_chart(
        title="Consensus Outlier Rate by Metric",
        labels=metric_rates.index.astype(str).tolist(),
        values=metric_rates.tolist(),
        filename="outlier_rate_by_metric.svg",
        value_formatter=lambda value: f"{value:.2f}%",
        color="#4d779c",
        x_axis_label="Consensus outliers over tested values (%)",
    )


def plot_outlier_methods_by_metric(outlier_summary_df: pd.DataFrame) -> Path:
    df = completed_outlier_summary(outlier_summary_df)
    method_counts = (
        df.groupby("metric", as_index=True)[
            ["iqr_outliers", "modified_z_outliers", "consensus_outliers"]
        ]
        .sum()
        .sort_values("consensus_outliers", ascending=True)
    )
    method_counts = method_counts.rename(
        columns={
            "iqr_outliers": "IQR",
            "modified_z_outliers": "Modified Z-score",
            "consensus_outliers": "Consensus",
        }
    )
    return grouped_horizontal_bar_chart(
        title="Outlier Detection Methods by Metric",
        data=method_counts,
        filename="outlier_methods_by_metric.svg",
        colors=["#9a6fb0", "#4f8c8f", "#cf7f4f"],
    )


def html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #20242a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #2f6f73;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }}
    h1, h2, h3 {{ margin: 0; }}
    h1 {{ font-size: 26px; letter-spacing: 0; }}
    h2 {{ font-size: 20px; margin: 30px 0 14px; }}
    h3 {{ font-size: 15px; margin: 0 0 10px; }}
    main {{ padding: 0 32px 40px; }}
    .subtitle {{ color: var(--muted); margin-top: 8px; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px 16px;
    }}
    .card span {{
      color: var(--muted);
      display: block;
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .card strong {{ font-size: 22px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap: 18px;
    }}
    .figure, .table-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
    }}
    .figure img {{
      width: 100%;
      height: auto;
      display: block;
      border: 1px solid #eef1f5;
      border-radius: 4px;
      background: #fff;
    }}
    .links {{ margin-top: 8px; color: var(--muted); }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 12px;
      background: #fff;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #eef3f4;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 72vh;
      border: 1px solid var(--line);
      border-radius: 4px;
    }}
    .note {{ color: var(--muted); margin: 0 0 12px; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def dataframe_to_html_table(df: pd.DataFrame, title: str, filename: str) -> Path:
    row_count = len(df)
    table_df = df.head(MAX_TABLE_ROWS).copy()
    table_html = table_df.to_html(index=False, escape=True, classes="data-table")
    note = ""
    if row_count > MAX_TABLE_ROWS:
        note = (
            f'<p class="note">Showing first {MAX_TABLE_ROWS:,} of '
            f"{row_count:,} rows. The CSV remains the authoritative full file.</p>"
        )

    body = f"""
<header>
  <h1>{escape(title)}</h1>
  <p class="subtitle">Generated from the data quality pipeline artifacts.</p>
</header>
<main>
  {note}
  <div class="table-wrap">{table_html}</div>
</main>
"""
    path = DATA_QUALITY_VISUALIZATIONS_TABLES_DIR / filename
    path.write_text(html_page(title, body), encoding="utf-8")
    print(f"[OK] Saved table: {path}")
    return path


def build_dashboard_cards(
    scorecard_df: pd.DataFrame,
    issues_df: pd.DataFrame,
    missing_summary_df: pd.DataFrame,
    outlier_summary_df: pd.DataFrame,
) -> list[tuple[str, str]]:
    scorecard = to_numeric(scorecard_df, ["overall_score"])
    missing = to_numeric(
        missing_summary_df,
        ["missing_count", "explained_null_count", "suspicious_null_count"],
    )
    outliers = completed_outlier_summary(outlier_summary_df)

    avg_score = scorecard["overall_score"].mean() if "overall_score" in scorecard else pd.NA
    worst_table = "N/A"
    if "overall_score" in scorecard and not scorecard.empty:
        worst_row = scorecard.sort_values("overall_score", ascending=True).head(1)
        if not worst_row.empty:
            worst_table = str(worst_row.iloc[0].get("table_name", "N/A"))

    top_missing_area = "N/A"
    area_columns = [
        column
        for column in missing.columns
        if column.endswith("_information_count") or column == "none_count"
    ]
    if area_columns:
        area_counts = missing[area_columns].sum().sort_values(ascending=False)
        if not area_counts.empty:
            top_missing_area = (
                str(area_counts.index[0])
                .replace("_information_count", "")
                .replace("_count", "")
                .replace("_", " ")
                .title()
            )

    top_outlier_metric = "N/A"
    if {"metric", "consensus_outliers"}.issubset(outliers.columns):
        by_metric = outliers.groupby("metric")["consensus_outliers"].sum()
        if not by_metric.empty:
            top_outlier_metric = str(by_metric.sort_values(ascending=False).index[0])

    return [
        ("Tables assessed", format_int(len(scorecard))),
        ("Average DQA score", format_float(avg_score, digits=6)),
        ("Worst DQA table", worst_table),
        ("General DQA issues", format_int(len(issues_df))),
        ("Missing values", format_int(missing.get("missing_count", pd.Series(dtype="float64")).sum())),
        ("Suspicious nulls", format_int(missing.get("suspicious_null_count", pd.Series(dtype="float64")).sum())),
        ("Top missing area", top_missing_area),
        ("Consensus outliers", format_int(outliers.get("consensus_outliers", pd.Series(dtype="float64")).sum())),
        ("Top outlier metric", top_outlier_metric),
    ]


def relative_to_html(path: Path) -> str:
    return os.path.relpath(path, DATA_QUALITY_VISUALIZATIONS_HTML_DIR).replace(os.sep, "/")


def create_dashboard(
    scorecard_df: pd.DataFrame,
    issues_df: pd.DataFrame,
    missing_summary_df: pd.DataFrame,
    outlier_summary_df: pd.DataFrame,
    table_files: dict[str, Path],
) -> Path:
    cards = build_dashboard_cards(
        scorecard_df=scorecard_df,
        issues_df=issues_df,
        missing_summary_df=missing_summary_df,
        outlier_summary_df=outlier_summary_df,
    )
    cards_html = "\n".join(
        f'<div class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in cards
    )

    figure_cards = []
    for base_name, title in FIGURE_FILES.items():
        svg_path = DATA_QUALITY_FIGURES_DIR / f"{base_name}.svg"
        if not svg_path.exists():
            continue
        figure_cards.append(
            f"""
      <section class="figure">
        <h3>{escape(title)}</h3>
        <img src="{relative_to_html(svg_path)}" alt="{escape(title)}">
        <div class="links"><a href="{relative_to_html(svg_path)}">Open SVG</a></div>
      </section>
"""
        )

    table_links = "\n".join(
        f'<li><a href="{relative_to_html(path)}">{escape(label)}</a></li>'
        for label, path in table_files.items()
    )

    body = f"""
<header>
  <h1>Complete Data Quality Dashboard</h1>
  <p class="subtitle">Global view across the general DQA, missing-value analysis, and lap outlier detection.</p>
  <div class="cards">{cards_html}</div>
</header>
<main>
  <h2>Plots</h2>
  <div class="grid">
    {''.join(figure_cards)}
  </div>

  <h2>CSV Tables</h2>
  <section class="table-panel">
    <h3>Generated HTML tables</h3>
    <ul>{table_links}</ul>
  </section>
</main>
"""
    dashboard_path = DATA_QUALITY_VISUALIZATIONS_HTML_DIR / "data_quality_dashboard.html"
    dashboard_path.write_text(html_page("Complete Data Quality Dashboard", body), encoding="utf-8")
    print(f"[OK] Saved dashboard: {dashboard_path}")
    return dashboard_path


def main() -> None:
    ensure_dirs(
        [
            DATA_QUALITY_VISUALIZATIONS_OUTPUT_DIR,
            DATA_QUALITY_FIGURES_DIR,
            DATA_QUALITY_VISUALIZATIONS_HTML_DIR,
            DATA_QUALITY_VISUALIZATIONS_TABLES_DIR,
        ]
    )

    print("[INFO] Starting complete data quality visualization script")
    print(f"[INFO] Output directory: {DATA_QUALITY_VISUALIZATIONS_OUTPUT_DIR}")

    scorecard_df = read_csv(SCORECARD_BY_TABLE_PATH, required=True)
    check_results_df = read_csv(CHECK_RESULTS_PATH, required=True)
    issues_df = read_csv(ISSUES_ALL_TABLES_PATH, required=False)
    missing_summary_df = read_csv(FOCUSED_MISSING_SUMMARY_PATH, required=True)
    missing_flags_df = read_csv(FOCUSED_MISSING_ROW_FLAGS_PATH, required=True)
    outlier_summary_df = read_csv(OUTLIER_SUMMARY_PATH, required=True)
    outlier_flags_df = read_csv(LAP_OUTLIER_FLAGS_PATH, required=True)

    if scorecard_df.empty:
        raise RuntimeError("DQA scorecard is empty. Run the general DQA step first.")
    if missing_summary_df.empty:
        raise RuntimeError("Missing-value summary is empty. Run the missing-values step first.")
    if outlier_summary_df.empty:
        raise RuntimeError("Outlier summary is empty. Run the outlier detection step first.")

    plot_dqa_score_by_table(scorecard_df)
    plot_dqa_issues_by_table(scorecard_df)
    heatmap_chart(scorecard_df)
    plot_missing_class_distribution(missing_summary_df)
    plot_missing_information_area(missing_summary_df)
    plot_outlier_by_metric(outlier_summary_df)
    plot_outlier_rate_by_metric(outlier_summary_df)
    plot_outlier_methods_by_metric(outlier_summary_df)

    table_files = {
        "DQA scorecard by table": dataframe_to_html_table(
            scorecard_df,
            "DQA Scorecard by Table",
            "dqa_scorecard_by_table.html",
        ),
        "DQA check results": dataframe_to_html_table(
            check_results_df,
            "DQA Check Results",
            "dqa_check_results.html",
        ),
        "DQA issues": dataframe_to_html_table(
            issues_df,
            "DQA Issues",
            "dqa_issues.html",
        ),
        "Focused missing summary": dataframe_to_html_table(
            missing_summary_df,
            "Focused Missing Summary",
            "focused_missing_summary.html",
        ),
        "Focused missing row flags": dataframe_to_html_table(
            missing_flags_df,
            "Focused Missing Row Flags",
            "focused_missing_row_flags.html",
        ),
        "Outlier summary": dataframe_to_html_table(
            outlier_summary_df,
            "Outlier Summary",
            "outlier_summary.html",
        ),
        "Lap outlier flags": dataframe_to_html_table(
            outlier_flags_df,
            "Lap Outlier Flags",
            "lap_outlier_flags.html",
        ),
    }

    dashboard_path = create_dashboard(
        scorecard_df=scorecard_df,
        issues_df=issues_df,
        missing_summary_df=missing_summary_df,
        outlier_summary_df=outlier_summary_df,
        table_files=table_files,
    )

    print("\n[OK] Complete data quality visualizations completed.")
    print("[INFO] Open this file in your browser:")
    print(f"       {dashboard_path}")


if __name__ == "__main__":
    main()
