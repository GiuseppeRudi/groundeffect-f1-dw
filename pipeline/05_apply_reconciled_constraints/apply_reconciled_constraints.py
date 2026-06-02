from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "database").exists():
    raise RuntimeError(
        "This script must be executed from the project root directory.\n"
        "The project root must contain the database/ package."
    )

sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.utils.input_utils import execute_sql_file
from pipeline.utils.file_names import CONSTRAINTS_SQL_RECONCILED_CLEAN_FILE
from database.db_config import get_engine



def main() -> None:
    engine, schema = get_engine("reconciled_clean")

    with engine.begin() as conn:
        execute_sql_file(conn, CONSTRAINTS_SQL_RECONCILED_CLEAN_FILE)

    print("\nDONE: RECONCILED DATABASE CONSTRAINTS APPLIED.")


if __name__ == "__main__":
    main()