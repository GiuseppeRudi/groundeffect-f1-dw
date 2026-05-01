from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

# This script is expected to be located in:
# F1_DW/etl_pipeline/run_pipeline.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PipelineStep:
    number: int
    name: str
    script_path: Path
    required: bool = True


STEPS = [
    PipelineStep(
        1,
        "Extraction and re-engineering",
        PROJECT_ROOT / "etl_pipeline" / "01_extraction_reengineering" / "extract_fastf1_sources.py",
    ),
    PipelineStep(
        2,
        "Load reconciled PostgreSQL database",
        PROJECT_ROOT / "etl_pipeline" / "02_load_reconciled_db" / "load_reconciled_tables.py",
    ),
    PipelineStep(
        3,
        "Data quality assessment",
        PROJECT_ROOT / "etl_pipeline" / "03_data_quality" / "data_quality_assessment.py",
    ),
    PipelineStep(
        4,
        "Data cleaning",
        PROJECT_ROOT / "etl_pipeline" / "04_data_cleaning" / "data_cleaning.py",
    ),
    PipelineStep(
        5,
        "Apply reconciled database constraints",
        PROJECT_ROOT / "etl_pipeline" / "05_apply_reconciled_constraints" / "apply_reconciled_constraints.py",
    ),
    PipelineStep(
        6,
        "Build derived attributes",
        PROJECT_ROOT / "etl_pipeline" / "06_derived_attributes" / "build_derived_attributes.py",
    ),
    PipelineStep(
        7,
        "Load data warehouse",
        PROJECT_ROOT / "etl_pipeline" / "07_load_data_warehouse" / "load_data_warehouse.py",
    ),
    PipelineStep(
        8,
        "Export data for visualization",
        PROJECT_ROOT / "etl_pipeline" / "08_export_for_visualization" / "export_dw_to_tableau_csv.py",
    ),
]


# ============================================================
# HELPERS
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full F1 Data Warehouse pipeline step by step."
    )

    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip pipeline steps whose script file does not exist yet.",
    )

    parser.add_argument(
        "--start-at",
        type=int,
        default=1,
        help="First step number to run. Default: 1.",
    )

    parser.add_argument(
        "--stop-at",
        type=int,
        default=len(STEPS),
        help=f"Last step number to run. Default: {len(STEPS)}.",
    )

    return parser.parse_args()


def run_step(step: PipelineStep, skip_missing: bool) -> None:
    relative_script = step.script_path.relative_to(PROJECT_ROOT)

    print("\n" + "=" * 80)
    print(f"STEP {step.number}: {step.name}")
    print(f"SCRIPT: {relative_script}")
    print("=" * 80)

    if not step.script_path.exists():
        message = f"Missing pipeline script: {relative_script}"

        if skip_missing:
            print(f"SKIPPED: {message}")
            return

        raise FileNotFoundError(message)

    subprocess.run(
        [sys.executable, str(step.script_path)],
        cwd=PROJECT_ROOT,
        check=True,
    )

    print(f"COMPLETED: STEP {step.number} - {step.name}")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    args = parse_args()

    if args.start_at < 1:
        raise ValueError("--start-at must be greater than or equal to 1")

    if args.stop_at > len(STEPS):
        raise ValueError(f"--stop-at must be lower than or equal to {len(STEPS)}")

    if args.start_at > args.stop_at:
        raise ValueError("--start-at cannot be greater than --stop-at")

    print("\nF1 DATA WAREHOUSE PIPELINE")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Running steps from {args.start_at} to {args.stop_at}")

    for step in STEPS:
        if args.start_at <= step.number <= args.stop_at:
            run_step(step, skip_missing=args.skip_missing)

    print("\n" + "=" * 80)
    print("FULL PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    main()
