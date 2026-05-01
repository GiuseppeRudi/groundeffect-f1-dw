from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


# ============================================================
# CONFIG
# ============================================================

CSV_DIR = Path("f1_data_reconciled")
DATABASE_URL = "postgresql+psycopg://postgres:rudi@localhost:5432/f1_reconciled"

DROP_EXISTING_TABLES = True

TABLE_FILES = {
    "season": "season.csv",
    "grand_prix": "grand_prix.csv",
    "session": "session.csv",
    "driver": "driver.csv",
    "team": "team.csv",
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
                df[col] = pd.to_datetime(df[col])
            except Exception:
                pass

    return df


def load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = normalize_columns(df)
    df = try_parse_dates(df)
    return df


def drop_all_tables(conn, schema: str = "public") -> None:
    result = conn.execute(
        text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = :schema
        """),
        {"schema": schema}
    )

    table_names = [row[0] for row in result]

    if not table_names:
        print(f"No tables found in schema '{schema}'")
        return

    qualified_tables = ", ".join(
        f'"{schema}"."{table_name}"' for table_name in table_names
    )

    print(f"DROPPING ALL TABLES IN SCHEMA {schema}")
    conn.execute(text(f"DROP TABLE {qualified_tables} CASCADE"))


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    engine = create_engine(DATABASE_URL)

    load_order = [
        "season",
        "driver",
        "team",
        "grand_prix",
        "session",
        "result",
        "lap",
        "weather",
        "track_status",
    ]

    with engine.begin() as conn:
        if DROP_EXISTING_TABLES:
            drop_all_tables(conn)

    with engine.begin() as conn:
        for table_name in load_order:
            filename = TABLE_FILES[table_name]
            csv_path = CSV_DIR / filename

            if not csv_path.exists():
                print(f"SKIP: {filename} not found")
                continue

            print(f"LOADING {filename} -> {table_name}")
            df = load_csv(csv_path)

            print(f"  shape = {df.shape}")

            df.to_sql(
                table_name,
                conn,
                if_exists="fail",
                index=False,
                chunksize=100,
            )

    print("\nDONE: ALL TABLES LOADED.")


if __name__ == "__main__":
    main()