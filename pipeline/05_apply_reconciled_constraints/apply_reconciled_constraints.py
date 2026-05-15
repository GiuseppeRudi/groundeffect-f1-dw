from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine


# ============================================================
# CONFIG
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABASE_URL = "postgresql+psycopg://postgres:rudi@localhost:5432/f1_project"

SQL_FILE = (
    PROJECT_ROOT
    / "database"
    / "reconciled"
    / "schema"
    / "03_apply_reconciled_constraints.sql"
)


# ============================================================
# HELPERS
# ============================================================

def execute_sql_file(conn, sql_path: Path) -> None:
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    print(f"EXECUTING SQL FILE: {sql_path.relative_to(PROJECT_ROOT)}")

    sql = sql_path.read_text(encoding="utf-8")

    if not sql.strip():
        raise ValueError(f"SQL file is empty: {sql_path}")

    conn.exec_driver_sql(sql)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        execute_sql_file(conn, SQL_FILE)

    print("\nDONE: RECONCILED DATABASE CONSTRAINTS APPLIED.")


if __name__ == "__main__":
    main()