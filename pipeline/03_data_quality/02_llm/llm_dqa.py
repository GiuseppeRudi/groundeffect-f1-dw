from __future__ import annotations

import argparse
import json
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

    INPUT_DIR_NAME,
    OUTPUTS_DIR_NAME,
    PROMPTS_DIR_NAME
)


SCORECARD_BY_TABLE_PATH = GENERAL_DQA_SCORECARDS_DIR / DQA_SCORECARD_FILE
CHECK_RESULTS_PATH = GENERAL_DQA_SCORECARDS_DIR / DQA_CHECK_RESULTS_FILE
ISSUES_ALL_TABLES_PATH = GENERAL_DQA_ISSUES_DIR / DQA_ISSUES_FILE
RI_ISSUES_PATH = GENERAL_DQA_ISSUES_DIR / REFERENTIAL_INTEGRITY_ISSUES_FILE


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




def build_llm_input(scorecard_df: pd.DataFrame, check_df: pd.DataFrame, issues_df: pd.DataFrame, ri_issues_df: pd.DataFrame) -> dict[str, Any]:
    """Build compact input for the LLM. Raw database rows are not included."""
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



PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "prompt"
    / "dqa_interpretation_prompt_template.txt"
)


def build_prompt(llm_input: dict[str, Any]) -> str:
    input_json = json.dumps(llm_input, indent=2, ensure_ascii=False)

    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    return template.replace("{{DQA_INPUT_JSON}}", input_json)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local LLM explanations for General DQA outputs.")
    parser.add_argument("--model", default=LLM_MODEL_NAME, help="Ollama model name, for example qwen2.5:3b")
    parser.add_argument("--auto-install-ollama", action="store_true", help="Try to install Ollama automatically if it is missing.")
    parser.add_argument("--skip-model-pull", action="store_true", help="Do not pull the model automatically.")
    return parser.parse_args()



def main() -> None:

    print("[INFO] Starting local LLM interpretation for General DQA")
    print(f"[INFO] General DQA input directory: {GENERAL_DQA_OUTPUT_DIR}")
    print(f"[INFO] LLM output directory: {LLM_OUTPUT_DIR}")
    print(f"[INFO] Selected model: {LLM_MODEL_NAME}")

    # Ollama is optional.
    # If it is not installed, skip the LLM phase without raising an error.
    if not ollama_cli_exists():
        print("[WARNING] Ollama CLI was not found.")
        print("[WARNING] Local LLM interpretation skipped.")
        return

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

    llm_input = build_llm_input(
        scorecard_df=scorecard_df,
        check_df=check_df,
        issues_df=issues_df,
        ri_issues_df=ri_issues_df,
    )

    write_json(LLM_INPUT_JSON_PATH, llm_input)

    prompt = build_prompt(llm_input)
    write_text(LLM_PROMPT_PATH, prompt)

    server_process = None

    try:
        server_process = start_ollama_server()

        pull_model(LLM_MODEL_NAME)

        full_output = generate_with_ollama(
            model_name=LLM_MODEL_NAME,
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
