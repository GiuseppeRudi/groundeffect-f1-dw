from pathlib import Path
import sys
from typing import Any

import pandas as pd


PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "database").exists():
    raise RuntimeError(
        "This script must be executed from the project root directory.\n"
        "The project root must contain the database/ package."
    )

sys.path.insert(0, str(PROJECT_ROOT))

def read_csv(path: Path, required: bool = True) -> pd.DataFrame:
    """
    Read a CSV file safely and normalize column names by removing
    leading/trailing spaces.
    """
    if not path.exists():
        message = f"Missing input file: {path}"
        if required:
            raise FileNotFoundError(message)

        print(f"[WARN] {message}")
        return pd.DataFrame()

    print(f"[INFO] Reading: {path}")

    df = pd.read_csv(path)

    # Remove spaces before/after column names
    df.columns = df.columns.astype(str).str.strip()

    # Optional: remove duplicated spaces inside column names
    df.columns = df.columns.str.replace(r"\s+", " ", regex=True)

    return df

def safe_records(df: pd.DataFrame, max_rows: int | None = None) -> list[dict[str, Any]]:
    if df.empty:
        return []

    tmp = df.copy()
    if max_rows is not None:
        tmp = tmp.head(max_rows)

    tmp = tmp.where(pd.notna(tmp), None)
    return tmp.to_dict(orient="records")



def execute_sql_file(conn, sql_path: Path) -> None:
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    print(f"EXECUTING SQL FILE: {sql_path.relative_to(PROJECT_ROOT)}")

    sql = sql_path.read_text(encoding="utf-8")

    if not sql.strip():
        raise ValueError(f"SQL file is empty: {sql_path}")

    conn.exec_driver_sql(sql)
