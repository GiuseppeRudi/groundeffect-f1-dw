from __future__ import annotations

from pathlib import Path
import pandas as pd
import sys

PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "database").exists() or not (PROJECT_ROOT / "pipeline").exists():
    raise RuntimeError(
        "This script must be executed from the project root directory.\n"
    )

sys.path.insert(0, str(PROJECT_ROOT))

from database.db_config import get_engine
from core.dqa_rules import TABLE_RULES, QUALITY_DIMENSIONS
from core.dqa_engine import DQAEngine
from database.db_utils import load_tables


from pipeline.utils.file_names import (
    GENERAL_DQA_OUTPUT_DIR,

    DQA_CHECK_RESULTS_FILE,
    DQA_SCORECARD_FILE,
    DQA_ISSUES_FILE,
    REFERENTIAL_INTEGRITY_ISSUES_FILE,

    GENERAL_DQA_SCORECARDS_DIR,
    GENERAL_DQA_ISSUES_DIR,
    GENERAL_DQA_ISSUES_BY_TABLE_DIR
)

from pipeline.utils.output_utils import (
    write_csv,
    write_partitioned_csv,
)

GENERAL_DQA_ISSUE_COLUMNS = [
    "table_name",
    "row_identifier",
    "dimension",
    "check_id",
    "issue_code",
    "issue_description",
    "severity",
]


def normalize_issues_df(issues_df: pd.DataFrame) -> pd.DataFrame:

    if issues_df.empty:
        return pd.DataFrame(columns=GENERAL_DQA_ISSUE_COLUMNS)

    for column in GENERAL_DQA_ISSUE_COLUMNS:
        if column not in issues_df.columns:
            issues_df[column] = pd.NA

    return issues_df[GENERAL_DQA_ISSUE_COLUMNS]


def export_general_dqa_outputs(
    check_df: pd.DataFrame,
    scorecard_df: pd.DataFrame,
    issues_df: pd.DataFrame,
) -> None:

    check_path = GENERAL_DQA_SCORECARDS_DIR / DQA_CHECK_RESULTS_FILE
    scorecard_path = GENERAL_DQA_SCORECARDS_DIR / DQA_SCORECARD_FILE
    issues_all_path = GENERAL_DQA_ISSUES_DIR / DQA_ISSUES_FILE
    ri_issues_path = GENERAL_DQA_ISSUES_DIR / REFERENTIAL_INTEGRITY_ISSUES_FILE

    issues_df = normalize_issues_df(issues_df)

    write_csv(check_df, check_path)
    write_csv(scorecard_df, scorecard_path)
    write_csv(issues_df, issues_all_path)

    ri_issues_df = issues_df[
        issues_df["dimension"] == "Referential Integrity"
    ].copy()

    write_csv(ri_issues_df, ri_issues_path)

    write_partitioned_csv(
        df=issues_df,
        partition_column="table_name",
        output_dir=GENERAL_DQA_ISSUES_BY_TABLE_DIR,
        filename_prefix="issues",
    )

    print("\n[OK] General DQA export completed")
    print(f"  - {check_path}")
    print(f"  - {scorecard_path}")
    print(f"  - {issues_all_path}")
    print(f"  - {ri_issues_path}")
    print(f"  - {GENERAL_DQA_ISSUES_BY_TABLE_DIR}")


def main() -> None:
    output_dir = Path(GENERAL_DQA_OUTPUT_DIR)
    engine, schema = get_engine("reconciled")

    print("[INFO] Starting General Data Quality Assessment")
    print(f"[INFO] Schema: {schema}")
    print(f"[INFO] Output directory: {output_dir}")

    table_names = list(TABLE_RULES.keys())
    all_tables = load_tables(
        engine=engine,
        schema=schema,
        table_names=table_names,
    )

    dqa = DQAEngine(table_rules=TABLE_RULES, quality_dimensions=QUALITY_DIMENSIONS)

    check_df, scorecard_df, issues_df = dqa.run(all_tables)

    export_general_dqa_outputs(
        check_df=check_df,
        scorecard_df=scorecard_df,
        issues_df=issues_df,
    )



if __name__ == "__main__":
    main()
