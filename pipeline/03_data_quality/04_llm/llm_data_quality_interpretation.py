from __future__ import annotations

import argparse
import json
import math
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
import pandas as pd

PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "artifacts").exists():
    raise RuntimeError( "This script must be executed from the project root directory.\n"    )


sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.utils.output_utils import ensure_dirs, write_json, write_text
from pipeline.utils.input_utils import read_csv, safe_records


from pipeline.config.llm_config import (
    OLLAMA_HOST,
    LLM_MODEL_NAME,
    LLM_TEMPERATURE,
    LLM_NUM_CTX,
    MAX_ISSUES_IN_PROMPT,
    MAX_FAILED_CHECKS_IN_PROMPT,
    MAX_RI_ISSUES_IN_PROMPT,
    MAX_MISSING_FLAGS_IN_PROMPT,
    MAX_OUTLIER_SUMMARY_ROWS_IN_PROMPT,
    MAX_OUTLIER_FLAGS_IN_PROMPT,
)


from pipeline.utils.file_names import (

    GENERAL_DQA_SCORECARDS_DIR,
    GENERAL_DQA_ISSUES_DIR,

    DQA_SCORECARD_FILE,
    DQA_ISSUES_FILE,
    DQA_CHECK_RESULTS_FILE,
    REFERENTIAL_INTEGRITY_ISSUES_FILE,

    LLM_INPUT_JSON_PATH,
    LLM_PROMPT_PATH,
    LLM_FULL_OUTPUT_PATH,

    LLM_OUTPUT_DIR,
    GENERAL_DQA_OUTPUT_DIR,
    MISSING_VALUES_OUTPUT_DIR,
    OUTLIER_DETECTION_OUTPUT_DIR,

    FOCUSED_MISSING_SUMMARY_PATH,
    FOCUSED_MISSING_ROW_FLAGS_PATH,
    OUTLIER_SUMMARY_PATH,
    LAP_OUTLIER_FLAGS_PATH,

    INPUT_DIR_NAME,
    OUTPUTS_DIR_NAME,
    PROMPTS_DIR_NAME
)


SCORECARD_BY_TABLE_PATH = GENERAL_DQA_SCORECARDS_DIR / DQA_SCORECARD_FILE
CHECK_RESULTS_PATH = GENERAL_DQA_SCORECARDS_DIR / DQA_CHECK_RESULTS_FILE
ISSUES_ALL_TABLES_PATH = GENERAL_DQA_ISSUES_DIR / DQA_ISSUES_FILE
RI_ISSUES_PATH = GENERAL_DQA_ISSUES_DIR / REFERENTIAL_INTEGRITY_ISSUES_FILE


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "item") and callable(value.item):
        return json_safe(value.item())

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


def numeric_column(df: pd.DataFrame, column_name: str) -> pd.Series:
    if column_name not in df.columns:
        return pd.Series(dtype="float64")

    return pd.to_numeric(df[column_name], errors="coerce")


def ollama_cli_exists() -> bool:
    return shutil.which("ollama") is not None


def run_command(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"[INFO] Running command: {' '.join(command)}")
    return subprocess.run(command, check=check, text=True)


def ollama_request(endpoint: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    url = f"{OLLAMA_HOST}{endpoint}"
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")

    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")

    if not raw.strip():
        return {}
    return json.loads(raw)


def ollama_server_is_running() -> bool:
    try:
        ollama_request("/api/tags", timeout=3)
        return True
    except Exception:
        return False


def start_ollama_server(wait_seconds: int = 15) -> subprocess.Popen | None:

    if ollama_server_is_running():
        print("[INFO] Ollama server is already running.")
        return None

    if not ollama_cli_exists():
        raise RuntimeError("Ollama CLI was not found. Install Ollama")

    print("[INFO] Starting Ollama server...")
    process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    start = time.time()
    while time.time() - start < wait_seconds:

        if ollama_server_is_running():
            print("[INFO] Ollama server is running.")
            return process
        time.sleep(1)

    raise RuntimeError("Ollama server did not start within the expected time.")


def get_installed_models() -> set[str]:
    response = ollama_request("/api/tags", timeout=10)
    models = response.get("models", [])
    return {m.get("name") for m in models if m.get("name")}


def pull_model(model_name: str) -> None:
    installed = get_installed_models()

    if model_name in installed:
        print(f"[INFO] Model already installed: {model_name}")
        return

    print(f"[INFO] Pulling local model: {model_name}")
    print("[INFO] This may take several minutes the first time.")

    if ollama_cli_exists():
        run_command(["ollama", "pull", model_name])
        return

    ollama_request("/api/pull", payload={"name": model_name, "stream": False}, timeout=1800)


def generate_with_ollama(model_name: str, prompt: str) -> str:
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": LLM_TEMPERATURE,
            "num_ctx": LLM_NUM_CTX,
        },
    }
    response = ollama_request("/api/generate", payload=payload, timeout=1800)
    return response.get("response", "").strip()




def build_general_dqa_input(
    scorecard_df: pd.DataFrame,
    check_df: pd.DataFrame,
    issues_df: pd.DataFrame,
    ri_issues_df: pd.DataFrame,
) -> dict[str, Any]:
    """Build compact input from the general DQA outputs."""
    summary: dict[str, Any] = {}

    if not scorecard_df.empty:
        scorecard = scorecard_df.copy()
        if "overall_score" in scorecard.columns:
            scorecard["overall_score"] = pd.to_numeric(scorecard["overall_score"], errors="coerce")

        summary["num_tables_assessed"] = int(len(scorecard))

        if "overall_score" in scorecard.columns:
            summary["average_overall_score"] = float(round(scorecard["overall_score"].mean(), 6))
            summary["worst_tables"] = safe_records(scorecard.sort_values("overall_score").head(5))
            summary["best_tables"] = safe_records(scorecard.sort_values("overall_score", ascending=False).head(5))

        summary["scorecard_by_table"] = safe_records(scorecard)

    if not check_df.empty:
        summary["num_checks"] = int(len(check_df))

        failed_or_warning = check_df[
            check_df["status"].astype(str).str.lower().isin(["red", "yellow"])
        ].copy()

        if "score" in failed_or_warning.columns:
            failed_or_warning["score"] = pd.to_numeric(failed_or_warning["score"], errors="coerce")
            failed_or_warning = failed_or_warning.sort_values(["status", "score"], ascending=[False, True])

        summary["failed_or_warning_checks"] = safe_records(failed_or_warning, max_rows=MAX_FAILED_CHECKS_IN_PROMPT)

        if "dimension" in check_df.columns and "status" in check_df.columns:
            status_by_dimension = (
                check_df.groupby(["dimension", "status"], as_index=False)
                .size()
                .rename(columns={"size": "num_checks"})
            )
            summary["check_status_by_dimension"] = safe_records(status_by_dimension)

    if not issues_df.empty:
        summary["num_issues"] = int(len(issues_df))
        issues_by_table = (
            issues_df.groupby("table_name", as_index=False)
            .size()
            .rename(columns={"size": "num_issues"})
            .sort_values("num_issues", ascending=False)
        )
        issues_by_dimension = (
            issues_df.groupby("dimension", as_index=False)
            .size()
            .rename(columns={"size": "num_issues"})
            .sort_values("num_issues", ascending=False)
        )
        summary["issues_by_table"] = safe_records(issues_by_table)
        summary["issues_by_dimension"] = safe_records(issues_by_dimension)
        summary["sample_issues"] = safe_records(issues_df, max_rows=MAX_ISSUES_IN_PROMPT)
    else:
        summary["num_issues"] = 0
        summary["issues_by_table"] = []
        summary["issues_by_dimension"] = []
        summary["sample_issues"] = []

    if not ri_issues_df.empty:
        ri_by_check = (
            ri_issues_df.groupby("check_id", as_index=False)
            .size()
            .rename(columns={"size": "num_issues"})
            .sort_values("num_issues", ascending=False)
        )
        summary["referential_integrity_issues"] = safe_records(ri_by_check, max_rows=MAX_RI_ISSUES_IN_PROMPT)
    else:
        summary["referential_integrity_issues"] = []


    return summary


def build_missing_values_input(
    missing_summary_df: pd.DataFrame,
    missing_flags_df: pd.DataFrame,
) -> dict[str, Any]:
    """Build compact input from the focused missing-value outputs."""
    summary: dict[str, Any] = {
        "summary_rows": [],
        "missing_by_table": [],
        "missing_by_information_area": [],
        "missing_by_severity": [],
        "critical_missing_patterns": [],
        "sample_high_priority_missing_flags": [],
    }

    if not missing_summary_df.empty:
        missing_summary = missing_summary_df.copy()
        numeric_columns = [
            "total_rows",
            "missing_count",
            "missing_percentage",
            "explained_null_count",
            "suspicious_null_count",
        ]

        for column in numeric_columns:
            if column in missing_summary.columns:
                missing_summary[column] = pd.to_numeric(missing_summary[column], errors="coerce")

        summary["num_missing_summary_rows"] = int(len(missing_summary))
        summary["total_missing_values"] = int(numeric_column(missing_summary, "missing_count").sum())
        summary["total_explained_nulls"] = int(numeric_column(missing_summary, "explained_null_count").sum())
        summary["total_suspicious_nulls"] = int(numeric_column(missing_summary, "suspicious_null_count").sum())

        if {"table_name", "missing_count", "suspicious_null_count", "explained_null_count"}.issubset(missing_summary.columns):
            missing_by_table = (
                missing_summary.groupby("table_name", as_index=False)
                .agg(
                    missing_count=("missing_count", "sum"),
                    suspicious_null_count=("suspicious_null_count", "sum"),
                    explained_null_count=("explained_null_count", "sum"),
                )
                .sort_values(["suspicious_null_count", "missing_count"], ascending=[False, False])
            )
            summary["missing_by_table"] = safe_records(missing_by_table)

        area_columns = [
            column
            for column in missing_summary.columns
            if column.endswith("_count")
            and column not in {"missing_count", "explained_null_count", "suspicious_null_count"}
        ]

        if area_columns:
            area_rows = []
            for column in area_columns:
                count = numeric_column(missing_summary, column).sum()
                if count > 0:
                    area_rows.append(
                        {
                            "missing_information_area": column.removesuffix("_count").upper(),
                            "missing_count": int(count),
                        }
                    )

            area_df = pd.DataFrame(area_rows)
            if not area_df.empty:
                area_df = area_df.sort_values("missing_count", ascending=False)
                summary["missing_by_information_area"] = safe_records(area_df)

        sort_columns = [column for column in ["suspicious_null_count", "missing_count"] if column in missing_summary.columns]
        if sort_columns:
            top_missing = missing_summary.sort_values(sort_columns, ascending=[False] * len(sort_columns))
        else:
            top_missing = missing_summary

        summary["summary_rows"] = safe_records(top_missing, max_rows=MAX_MISSING_FLAGS_IN_PROMPT)

    if not missing_flags_df.empty:
        missing_flags = missing_flags_df.copy()

        summary["num_missing_row_flags"] = int(len(missing_flags))

        if "severity" in missing_flags.columns:
            severity_counts = (
                missing_flags.groupby("severity", as_index=False)
                .size()
                .rename(columns={"size": "num_flags"})
                .sort_values("num_flags", ascending=False)
            )
            summary["missing_by_severity"] = safe_records(severity_counts)

        required_columns = {
            "table_name",
            "column_name",
            "missing_class",
            "missing_information_area",
            "severity",
        }

        if required_columns.issubset(missing_flags.columns):
            severity_order = {"red": 0, "yellow": 1, "green": 2}
            critical_patterns = (
                missing_flags.groupby(
                    [
                        "table_name",
                        "column_name",
                        "missing_class",
                        "missing_information_area",
                        "severity",
                    ],
                    as_index=False,
                )
                .size()
                .rename(columns={"size": "num_flags"})
            )
            critical_patterns["severity_rank"] = critical_patterns["severity"].map(severity_order).fillna(9)
            critical_patterns = critical_patterns.sort_values(
                ["severity_rank", "num_flags"],
                ascending=[True, False],
            ).drop(columns=["severity_rank"])
            summary["critical_missing_patterns"] = safe_records(
                critical_patterns,
                max_rows=MAX_MISSING_FLAGS_IN_PROMPT,
            )

        if "severity" in missing_flags.columns:
            high_priority_flags = missing_flags[
                missing_flags["severity"].astype(str).str.lower().isin(["red", "yellow"])
            ]
            summary["sample_high_priority_missing_flags"] = safe_records(
                high_priority_flags,
                max_rows=MAX_MISSING_FLAGS_IN_PROMPT,
            )

    return summary


def build_outlier_detection_input(
    outlier_summary_df: pd.DataFrame,
    outlier_flags_df: pd.DataFrame,
) -> dict[str, Any]:
    """Build compact input from the focused lap outlier outputs."""
    summary: dict[str, Any] = {
        "summary_rows": [],
        "outliers_by_metric": [],
        "top_outlier_sessions": [],
        "outlier_flags_by_interpretation": [],
        "strong_consensus_by_metric": [],
        "sample_strong_consensus_outliers": [],
    }

    if not outlier_summary_df.empty:
        outlier_summary = outlier_summary_df.copy()
        numeric_columns = [
            "tested_values",
            "iqr_outliers",
            "modified_z_outliers",
            "consensus_outliers",
        ]

        for column in numeric_columns:
            if column in outlier_summary.columns:
                outlier_summary[column] = pd.to_numeric(outlier_summary[column], errors="coerce")

        summary["num_outlier_summary_rows"] = int(len(outlier_summary))
        summary["total_tested_values"] = int(numeric_column(outlier_summary, "tested_values").sum())
        summary["total_iqr_outliers"] = int(numeric_column(outlier_summary, "iqr_outliers").sum())
        summary["total_modified_z_outliers"] = int(numeric_column(outlier_summary, "modified_z_outliers").sum())
        summary["total_consensus_outliers"] = int(numeric_column(outlier_summary, "consensus_outliers").sum())

        if {"metric", "tested_values", "iqr_outliers", "modified_z_outliers", "consensus_outliers"}.issubset(outlier_summary.columns):
            by_metric = (
                outlier_summary.groupby("metric", as_index=False)
                .agg(
                    tested_values=("tested_values", "sum"),
                    iqr_outliers=("iqr_outliers", "sum"),
                    modified_z_outliers=("modified_z_outliers", "sum"),
                    consensus_outliers=("consensus_outliers", "sum"),
                )
                .sort_values("consensus_outliers", ascending=False)
            )
            summary["outliers_by_metric"] = safe_records(by_metric)

        if {"session_id", "metric", "consensus_outliers"}.issubset(outlier_summary.columns):
            top_sessions = outlier_summary.sort_values("consensus_outliers", ascending=False)
            summary["top_outlier_sessions"] = safe_records(
                top_sessions,
                max_rows=MAX_OUTLIER_SUMMARY_ROWS_IN_PROMPT,
            )

        sort_columns = [column for column in ["consensus_outliers", "modified_z_outliers", "iqr_outliers"] if column in outlier_summary.columns]
        if sort_columns:
            top_summary = outlier_summary.sort_values(sort_columns, ascending=[False] * len(sort_columns))
        else:
            top_summary = outlier_summary

        summary["summary_rows"] = safe_records(
            top_summary,
            max_rows=MAX_OUTLIER_SUMMARY_ROWS_IN_PROMPT,
        )

    if not outlier_flags_df.empty:
        outlier_flags = outlier_flags_df.copy()

        if "consensus_score" in outlier_flags.columns:
            outlier_flags["consensus_score"] = pd.to_numeric(outlier_flags["consensus_score"], errors="coerce")

        summary["num_outlier_row_flags"] = int(len(outlier_flags))
        summary["strong_consensus_flag_count"] = int((numeric_column(outlier_flags, "consensus_score") >= 2).sum())
        summary["weak_anomaly_flag_count"] = int((numeric_column(outlier_flags, "consensus_score") == 1).sum())

        if "interpretation" in outlier_flags.columns:
            by_interpretation = (
                outlier_flags.groupby("interpretation", as_index=False)
                .size()
                .rename(columns={"size": "num_flags"})
                .sort_values("num_flags", ascending=False)
            )
            summary["outlier_flags_by_interpretation"] = safe_records(by_interpretation)

        if {"metric", "consensus_score"}.issubset(outlier_flags.columns):
            strong_flags = outlier_flags[outlier_flags["consensus_score"] >= 2]
            strong_by_metric = (
                strong_flags.groupby("metric", as_index=False)
                .size()
                .rename(columns={"size": "num_strong_consensus_flags"})
                .sort_values("num_strong_consensus_flags", ascending=False)
            )
            summary["strong_consensus_by_metric"] = safe_records(strong_by_metric)
            summary["sample_strong_consensus_outliers"] = safe_records(
                strong_flags.sort_values(["consensus_score", "metric"], ascending=[False, True]),
                max_rows=MAX_OUTLIER_FLAGS_IN_PROMPT,
            )

    return summary


def build_llm_input(
    scorecard_df: pd.DataFrame,
    check_df: pd.DataFrame,
    issues_df: pd.DataFrame,
    ri_issues_df: pd.DataFrame,
    missing_summary_df: pd.DataFrame,
    missing_flags_df: pd.DataFrame,
    outlier_summary_df: pd.DataFrame,
    outlier_flags_df: pd.DataFrame,
) -> dict[str, Any]:
    """Build compact input for the LLM. Raw database tables are not included."""
    llm_input = {
        "general_dqa": build_general_dqa_input(
            scorecard_df=scorecard_df,
            check_df=check_df,
            issues_df=issues_df,
            ri_issues_df=ri_issues_df,
        ),
        "focused_missing_values": build_missing_values_input(
            missing_summary_df=missing_summary_df,
            missing_flags_df=missing_flags_df,
        ),
        "focused_outlier_detection": build_outlier_detection_input(
            outlier_summary_df=outlier_summary_df,
            outlier_flags_df=outlier_flags_df,
        ),
    }

    return json_safe(llm_input)



PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "prompt"
    / "data_quality_interpretation_prompt_template.txt"
)


def build_prompt(llm_input: dict[str, Any]) -> str:
    input_json = json.dumps(llm_input, indent=2, ensure_ascii=False, allow_nan=False)

    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    return template.replace("{{DATA_QUALITY_INPUT_JSON}}", input_json)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local LLM explanations for complete data quality outputs.")
    parser.add_argument("--model", default=LLM_MODEL_NAME, help="Ollama model name, for example qwen2.5:3b")
    parser.add_argument("--auto-install-ollama", action="store_true", help="Try to install Ollama automatically if it is missing.")
    parser.add_argument("--skip-model-pull", action="store_true", help="Do not pull the model automatically.")
    return parser.parse_args()



def main() -> None:
    args = parse_args()

    print("[INFO] Starting local LLM interpretation for complete data quality results")
    print(f"[INFO] General DQA input directory: {GENERAL_DQA_OUTPUT_DIR}")
    print(f"[INFO] Missing values input directory: {MISSING_VALUES_OUTPUT_DIR}")
    print(f"[INFO] Outlier detection input directory: {OUTLIER_DETECTION_OUTPUT_DIR}")
    print(f"[INFO] LLM output directory: {LLM_OUTPUT_DIR}")
    print(f"[INFO] Selected model: {args.model}")

    paths: list[Path] = [
        Path(LLM_OUTPUT_DIR),
        Path(LLM_OUTPUT_DIR / INPUT_DIR_NAME),
        Path(LLM_OUTPUT_DIR / PROMPTS_DIR_NAME),
        Path(LLM_OUTPUT_DIR / OUTPUTS_DIR_NAME),
    ]

    ensure_dirs(paths)

    scorecard_df = read_csv(Path(SCORECARD_BY_TABLE_PATH), required=True)
    check_df = read_csv(Path(CHECK_RESULTS_PATH), required=True)
    issues_df = read_csv(Path(ISSUES_ALL_TABLES_PATH), required=False)
    ri_issues_df = read_csv(Path(RI_ISSUES_PATH), required=False)
    missing_summary_df = read_csv(Path(FOCUSED_MISSING_SUMMARY_PATH), required=True)
    missing_flags_df = read_csv(Path(FOCUSED_MISSING_ROW_FLAGS_PATH), required=True)
    outlier_summary_df = read_csv(Path(OUTLIER_SUMMARY_PATH), required=True)
    outlier_flags_df = read_csv(Path(LAP_OUTLIER_FLAGS_PATH), required=True)

    llm_input = build_llm_input(
        scorecard_df=scorecard_df,
        check_df=check_df,
        issues_df=issues_df,
        ri_issues_df=ri_issues_df,
        missing_summary_df=missing_summary_df,
        missing_flags_df=missing_flags_df,
        outlier_summary_df=outlier_summary_df,
        outlier_flags_df=outlier_flags_df,
    )

    write_json(LLM_INPUT_JSON_PATH, llm_input)

    prompt = build_prompt(llm_input)
    write_text(LLM_PROMPT_PATH, prompt)

    # Ollama is optional: keep the auditable input and prompt even when the
    # local model runtime is not available.
    if not ollama_cli_exists():
        print("[WARNING] Ollama CLI was not found.")
        print("[WARNING] LLM input and prompt were generated, but local LLM interpretation was skipped.")
        return

    server_process = None

    try:
        server_process = start_ollama_server()

        if not args.skip_model_pull:
            pull_model(args.model)

        full_output = generate_with_ollama(
            model_name=args.model,
            prompt=prompt,
        )

        if not full_output:
            print("[WARNING] Ollama returned an empty response.")
            print("[WARNING] Local LLM interpretation skipped.")
            return

        write_text(LLM_FULL_OUTPUT_PATH, full_output)

        print("\n[OK] LLM interpretation completed.")
        print(f"[INFO] Main output file: {LLM_FULL_OUTPUT_PATH}")

    except Exception as exc:
        print(f"[WARNING] Local LLM interpretation skipped: {exc}")
        return

    finally:
        if server_process is not None:
            print("[INFO] Ollama server was started by this script and is left running for reuse.")

if __name__ == "__main__":
    main()
