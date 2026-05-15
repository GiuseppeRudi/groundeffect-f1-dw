from __future__ import annotations

import re
from pathlib import Path

import sys
import pandas as pd

PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "pipeline").exists():
    raise RuntimeError(
        "This script must be executed from the project root directory.\n"
    )

sys.path.insert(0, str(PROJECT_ROOT))

from database.db_config import get_engine


# ============================================================
# CONFIG
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CSV_DIR = PROJECT_ROOT / "data" / "reconciled"

SQL_DIR = PROJECT_ROOT / "database" / "reconciled" / "schema"
DROP_SQL_FILE = SQL_DIR / "00_drop_reconciled_tables.sql"
CREATE_SQL_FILE = SQL_DIR / "01_create_reconciled_tables.sql"


DROP_EXISTING_TABLES = True

TABLE_FILES = {
    "season": "season.csv",
    "circuit": "circuit.csv",
    "driver": "driver.csv",
    "team": "team.csv",
    "grand_prix": "grand_prix.csv",
    "session": "session.csv",
    "result": "result.csv",
    "lap": "lap.csv",
    "weather": "weather.csv",
    "track_status": "track_status.csv",
}


# ============================================================
# HELPERS
# ============================================================

def to_snake_case(name: str) -> str:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    name = re.sub(r"[^\w]+", "_", name)
    return name.strip("_").lower()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [to_snake_case(c) for c in df.columns]
    return df


def try_parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in df.columns:
        if "date" in col:
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce")
            except Exception:
                pass

    return df


def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = normalize_columns(df)
    df = try_parse_dates(df)
    return df


def execute_sql_file(conn, sql_path: Path) -> None:
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    print(f"EXECUTING SQL FILE: {sql_path.relative_to(PROJECT_ROOT)}")

    sql = sql_path.read_text(encoding="utf-8")
    conn.exec_driver_sql(sql)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    engine, schema = get_engine("reconciled")

    load_order = [
        "season",
        "circuit",
        "driver",
        "team",
        "grand_prix",
        "session",
        "result",
        "lap",
        "weather",
        "track_status",
    ]

    # --------------------------------------------------------
    # DROP + CREATE TABLES FROM SQL FILES
    # --------------------------------------------------------
    with engine.begin() as conn:
        if DROP_EXISTING_TABLES:
            execute_sql_file(conn, DROP_SQL_FILE)

        execute_sql_file(conn, CREATE_SQL_FILE)

    # --------------------------------------------------------
    # LOAD CSV DATA INTO EXISTING TABLES
    # --------------------------------------------------------
    with engine.begin() as conn:
        for table_name in load_order:
            filename = TABLE_FILES[table_name]
            csv_path = CSV_DIR / filename

            if not csv_path.exists():
                print(f"SKIP: {filename} not found in {CSV_DIR}")
                continue

            print(f"LOADING {filename} -> {table_name}")

            df = load_csv(csv_path)

            print(f"  shape = {df.shape}")

            df.to_sql(
                table_name,
                conn,
                if_exists="append",
                index=False,
                chunksize=100,
                method="multi",
            )

    print("\nDONE: ALL RECONCILED TABLES LOADED.")


if __name__ == "__main__":
    main()