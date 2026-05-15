from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.types import BigInteger, Boolean, DateTime, Float, Integer, String, Text


# ============================================================
# CONFIG
# ============================================================

CSV_DIR = Path("dw_staging_csv")

# postgresql+psycopg://USERNAME:PASSWORD@HOST:PORT/DATABASE
# Use a separate database from the reconciled one.
DATABASE_URL = "postgresql+psycopg://postgres:rudi@localhost:5432/f1_warehouse"

SCHEMA_NAME = "public"
DROP_EXISTING_TABLES = True

# Mandatory star-schema tables.
STAR_TABLE_FILES = {
    "dim_driver": "dim_driver.csv",
    "dim_team": "dim_team.csv",
    "dim_season": "dim_season.csv",
    "dim_circuit": "dim_circuit.csv",
    "dim_grand_prix": "dim_grand_prix.csv",
    "dim_session": "dim_session.csv",
    "fact_lap_performance": "fact_lap_performance.csv",
    "fact_session_result": "fact_session_result.csv",
}

# Optional technical/audit tables produced by the previous script.
AUDIT_TABLE_FILES = {
    "dw_build_log": "dw_build_log.csv",
    "dw_validation_report": "dw_validation_report.csv",
}

TABLE_FILES = {**STAR_TABLE_FILES, **AUDIT_TABLE_FILES}

# Dimensions must be loaded before facts because facts reference dimension keys.
LOAD_ORDER = [
    "dim_driver",
    "dim_team",
    "dim_season",
    "dim_circuit",
    "dim_grand_prix",
    "dim_session",
    "fact_lap_performance",
    "fact_session_result",
    "dw_build_log",
    "dw_validation_report",
]

# Drop in reverse dependency order.
DROP_ORDER = [
    "fact_lap_performance",
    "fact_session_result",
    "dim_session",
    "dim_grand_prix",
    "dim_circuit",
    "dim_season",
    "dim_team",
    "dim_driver",
    "dw_validation_report",
    "dw_build_log",
]


# ============================================================
# GENERAL HELPERS
# ============================================================

def to_snake_case(name: object) -> str:
    value = str(name)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^0-9a-zA-Z_]+", "_", value)
    return value.strip("_").lower()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [to_snake_case(c) for c in out.columns]
    return out


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def q_table(table_name: str) -> str:
    return f"{quote_ident(SCHEMA_NAME)}.{quote_ident(table_name)}"


def table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
            )
            """
        ),
        {"schema_name": SCHEMA_NAME, "table_name": table_name},
    )
    return bool(result.scalar())


def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = :table_name
                  AND column_name = :column_name
            )
            """
        ),
        {
            "schema_name": SCHEMA_NAME,
            "table_name": table_name,
            "column_name": column_name,
        },
    )
    return bool(result.scalar())


def constraint_exists(conn, constraint_name: str) -> bool:
    result = conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE constraint_schema = :schema_name
                  AND constraint_name = :constraint_name
            )
            """
        ),
        {"schema_name": SCHEMA_NAME, "constraint_name": constraint_name},
    )
    return bool(result.scalar())


def existing_columns(conn, table_name: str, columns: Iterable[str]) -> list[str]:
    return [col for col in columns if column_exists(conn, table_name, col)]


def safe_execute(conn, sql: str) -> None:
    conn.execute(text(sql))


def connect_to_warehouse_db() -> Engine:
    return create_engine(DATABASE_URL)


def ensure_schema_exists(conn) -> None:
    safe_execute(conn, f"CREATE SCHEMA IF NOT EXISTS {quote_ident(SCHEMA_NAME)}")


# ============================================================
# CSV READING AND TYPE NORMALIZATION
# ============================================================

def parse_bool_series(series: pd.Series) -> pd.Series:
    def parse_value(value: object) -> object:
        if pd.isna(value):
            return pd.NA
        if isinstance(value, bool):
            return value
        text_value = str(value).strip().lower()
        if text_value in {"true", "t", "1", "yes", "y"}:
            return True
        if text_value in {"false", "f", "0", "no", "n"}:
            return False
        return pd.NA

    return series.apply(parse_value).astype("boolean")


def cast_integer_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    return out


def cast_float_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def cast_string_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].astype("string")
    return out


def parse_datetime_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col.endswith("_date") or col.endswith("_at_utc") or col in {"event_date", "session_date", "created_at_utc"}:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def normalize_table_types(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Normalize DataFrame dtypes before loading into PostgreSQL."""
    out = normalize_columns(df)

    integer_cols = [
        col
        for col in out.columns
        if col.endswith("_key")
        or col in {
            "season_year",
            "round_number",
            "number_of_events",
            "lap_number",
            "position",
            "grid_position",
            "q1_ms",
            "q2_ms",
            "q3_ms",
            "time_ms",
            "gap_to_leader_ms",
            "laps",
            "lap_time_ms",
            "sector1_time_ms",
            "sector2_time_ms",
            "sector3_time_ms",
            "speed_i1",
            "speed_i2",
            "speed_fl",
            "speed_st",
            "row_count",
            "column_count",
            "affected_rows",
        }
    ]

    float_cols = ["points"]
    string_cols = [
        col
        for col in out.columns
        if col.endswith("_id")
        or col in {
            "driver_id",
            "team_id",
            "circuit_id",
            "grand_prix_id",
            "session_id",
            "lap_id",
            "result_id",
        }
    ]
    bool_cols = ["rain_flag"]

    out = cast_string_columns(out, string_cols)
    out = cast_integer_columns(out, integer_cols)
    out = cast_float_columns(out, float_cols)

    for col in bool_cols:
        if col in out.columns:
            out[col] = parse_bool_series(out[col])

    out = parse_datetime_columns(out)
    return out


def read_csv_table(table_name: str, mandatory: bool = True) -> pd.DataFrame | None:
    csv_path = CSV_DIR / TABLE_FILES[table_name]

    if not csv_path.exists():
        if mandatory:
            raise FileNotFoundError(f"Missing mandatory CSV file: {csv_path}")
        print(f"SKIP optional file not found: {csv_path}")
        return None

    df = pd.read_csv(csv_path)
    df = normalize_table_types(table_name, df)
    return df


# ============================================================
# SQL TYPES FOR to_sql
# ============================================================

def dtype_for_table(table_name: str, df: pd.DataFrame) -> dict[str, object]:
    """
    Provide explicit SQL types for stable PostgreSQL schemas.
    Only columns present in the DataFrame are included.
    """
    dtype: dict[str, object] = {}

    big_int_cols = {
        "driver_key",
        "team_key",
        "season_key",
        "circuit_key",
        "grand_prix_key",
        "session_key",
        "lap_performance_key",
        "session_result_key",
        "q1_ms",
        "q2_ms",
        "q3_ms",
        "time_ms",
        "gap_to_leader_ms",
        "lap_time_ms",
        "sector1_time_ms",
        "sector2_time_ms",
        "sector3_time_ms",
    }

    int_cols = {
        "season_year",
        "round_number",
        "number_of_events",
        "lap_number",
        "position",
        "grid_position",
        "laps",
        "speed_i1",
        "speed_i2",
        "speed_fl",
        "speed_st",
        "row_count",
        "column_count",
        "affected_rows",
    }

    float_cols = {"points"}
    bool_cols = {"rain_flag"}

    date_time_cols = {
        "season_start_date",
        "season_end_date",
        "event_date",
        "session_date",
        "created_at_utc",
    }

    text_cols = {"message"}

    # Reasonable varchar sizes for identifiers and categorical values.
    varchar_80_cols = {
        "driver_id",
        "team_id",
        "circuit_id",
        "grand_prix_id",
        "session_id",
        "abbreviation",
        "driver_age_class",
        "global_circuit_category",
        "sector1_category",
        "sector2_category",
        "sector3_category",
        "session_type",
        "compound",
        "lap_type",
        "starting_tyre_set_status",
        "tyre_life_class",
        "air_temp_class",
        "track_temp_class",
        "wind_speed_class",
        "track_status_category",
        "result_classification_category",
        "result_status_category",
        "avg_air_temp_class",
        "avg_track_temp_class",
        "avg_wind_speed_class",
        "severity",
        "status",
        "check_name",
    }

    varchar_255_cols = {
        "lap_id",
        "result_id",
        "first_name",
        "last_name",
        "nationality",
        "team_name",
        "champion_driver",
        "champion_team",
        "circuit_name",
        "country",
        "location",
        "event_name",
        "event_format",
        "session_name",
        "table_name",
    }

    for col in df.columns:
        if col in big_int_cols or col.endswith("_key"):
            dtype[col] = BigInteger()
        elif col in int_cols:
            dtype[col] = Integer()
        elif col in float_cols:
            dtype[col] = Float()
        elif col in bool_cols:
            dtype[col] = Boolean()
        elif col in date_time_cols:
            dtype[col] = DateTime()
        elif col in text_cols or col == "message":
            dtype[col] = Text()
        elif col in varchar_80_cols:
            dtype[col] = String(80)
        elif col in varchar_255_cols or col.endswith("_id"):
            dtype[col] = String(255)
        else:
            dtype[col] = Text()

    return dtype


# ============================================================
# LOAD TABLES
# ============================================================

def drop_existing_tables(conn) -> None:
    for table_name in DROP_ORDER:
        if table_exists(conn, table_name):
            print(f"DROPPING {table_name}")
            safe_execute(conn, f"DROP TABLE IF EXISTS {q_table(table_name)} CASCADE")


def load_dataframe(engine: Engine, table_name: str, df: pd.DataFrame) -> None:
    print(f"LOADING {table_name}: {len(df):,} rows")
    df.to_sql(
        table_name,
        engine,
        schema=SCHEMA_NAME,
        if_exists="fail",
        index=False,
        method="multi",
        chunksize=1000,
        dtype=dtype_for_table(table_name, df),
    )


def load_csvs_to_postgres(engine: Engine) -> dict[str, pd.DataFrame]:
    loaded: dict[str, pd.DataFrame] = {}

    for table_name in LOAD_ORDER:
        mandatory = table_name in STAR_TABLE_FILES
        if table_name not in TABLE_FILES:
            continue

        df = read_csv_table(table_name, mandatory=mandatory)
        if df is None:
            continue

        load_dataframe(engine, table_name, df)
        loaded[table_name] = df

    return loaded


# ============================================================
# CONSTRAINT HELPERS
# ============================================================

def add_primary_key(conn, table_name: str, columns: list[str]) -> None:
    cols = existing_columns(conn, table_name, columns)
    if cols != columns:
        print(f"SKIP PK on {table_name}: missing columns {set(columns) - set(cols)}")
        return

    constraint_name = f"pk_{table_name}"
    if constraint_exists(conn, constraint_name):
        return

    col_sql = ", ".join(quote_ident(c) for c in columns)
    safe_execute(
        conn,
        f"ALTER TABLE {q_table(table_name)} ADD CONSTRAINT {quote_ident(constraint_name)} PRIMARY KEY ({col_sql})",
    )


def add_unique(conn, table_name: str, columns: list[str], suffix: str | None = None) -> None:
    cols = existing_columns(conn, table_name, columns)
    if cols != columns:
        print(f"SKIP UNIQUE on {table_name}({columns}): missing columns {set(columns) - set(cols)}")
        return

    suffix = suffix or "_".join(columns)
    constraint_name = f"uq_{table_name}_{suffix}"
    if constraint_exists(conn, constraint_name):
        return

    col_sql = ", ".join(quote_ident(c) for c in columns)
    safe_execute(
        conn,
        f"ALTER TABLE {q_table(table_name)} ADD CONSTRAINT {quote_ident(constraint_name)} UNIQUE ({col_sql})",
    )


def add_foreign_key(
    conn,
    table_name: str,
    column: str,
    ref_table: str,
    ref_column: str,
    on_delete: str | None = None,
) -> None:
    if not table_exists(conn, table_name) or not table_exists(conn, ref_table):
        print(f"SKIP FK {table_name}.{column}: table missing")
        return

    if not column_exists(conn, table_name, column) or not column_exists(conn, ref_table, ref_column):
        print(f"SKIP FK {table_name}.{column}: column missing")
        return

    constraint_name = f"fk_{table_name}_{column}"
    if constraint_exists(conn, constraint_name):
        return

    delete_sql = f" ON DELETE {on_delete}" if on_delete else ""
    safe_execute(
        conn,
        f"""
        ALTER TABLE {q_table(table_name)}
        ADD CONSTRAINT {quote_ident(constraint_name)}
        FOREIGN KEY ({quote_ident(column)})
        REFERENCES {q_table(ref_table)} ({quote_ident(ref_column)})
        {delete_sql}
        """,
    )


def set_not_null(conn, table_name: str, columns: Iterable[str]) -> None:
    for col in columns:
        if column_exists(conn, table_name, col):
            safe_execute(
                conn,
                f"ALTER TABLE {q_table(table_name)} ALTER COLUMN {quote_ident(col)} SET NOT NULL",
            )


def add_check_in(
    conn,
    table_name: str,
    column: str,
    allowed_values: set[str],
    allow_null: bool = True,
) -> None:
    if not table_exists(conn, table_name) or not column_exists(conn, table_name, column):
        print(f"SKIP CHECK {table_name}.{column}: table/column missing")
        return

    constraint_name = f"chk_{table_name}_{column}"
    if constraint_exists(conn, constraint_name):
        return

    allowed_sql = ", ".join("'" + value.replace("'", "''") + "'" for value in sorted(allowed_values))
    null_sql = f"{quote_ident(column)} IS NULL OR " if allow_null else ""

    safe_execute(
        conn,
        f"""
        ALTER TABLE {q_table(table_name)}
        ADD CONSTRAINT {quote_ident(constraint_name)}
        CHECK ({null_sql}{quote_ident(column)} IN ({allowed_sql}))
        """,
    )


# ============================================================
# CONSTRAINT APPLICATION
# ============================================================

def add_primary_keys(conn) -> None:
    add_primary_key(conn, "dim_driver", ["driver_key"])
    add_primary_key(conn, "dim_team", ["team_key"])
    add_primary_key(conn, "dim_season", ["season_key"])
    add_primary_key(conn, "dim_circuit", ["circuit_key"])
    add_primary_key(conn, "dim_grand_prix", ["grand_prix_key"])
    add_primary_key(conn, "dim_session", ["session_key"])
    add_primary_key(conn, "fact_lap_performance", ["lap_performance_key"])
    add_primary_key(conn, "fact_session_result", ["session_result_key"])


def add_unique_constraints(conn) -> None:
    add_unique(conn, "dim_driver", ["driver_id"])
    add_unique(conn, "dim_team", ["team_id"])
    add_unique(conn, "dim_season", ["season_year"])
    add_unique(conn, "dim_circuit", ["circuit_id"])
    add_unique(conn, "dim_grand_prix", ["grand_prix_id"])
    add_unique(conn, "dim_session", ["session_id"])
    add_unique(conn, "fact_lap_performance", ["lap_id"])
    add_unique(conn, "fact_session_result", ["result_id"])


def add_not_null_constraints(conn) -> None:
    set_not_null(conn, "dim_driver", ["driver_key", "driver_id"])
    set_not_null(conn, "dim_team", ["team_key", "team_id"])
    set_not_null(conn, "dim_season", ["season_key", "season_year"])
    set_not_null(conn, "dim_circuit", ["circuit_key", "circuit_id"])
    set_not_null(conn, "dim_grand_prix", ["grand_prix_key", "grand_prix_id", "season_key", "circuit_key"])
    set_not_null(conn, "dim_session", ["session_key", "session_id", "grand_prix_key", "season_key"])

    shared_fact_keys = [
        "driver_key",
        "team_key",
        "session_key",
        "grand_prix_key",
        "circuit_key",
        "season_key",
    ]
    set_not_null(conn, "fact_lap_performance", ["lap_performance_key", "lap_id", *shared_fact_keys])
    set_not_null(conn, "fact_session_result", ["session_result_key", "result_id", *shared_fact_keys])


def add_foreign_keys(conn) -> None:
    # Snowflaked/shared dimension links.
    add_foreign_key(conn, "dim_grand_prix", "season_key", "dim_season", "season_key")
    add_foreign_key(conn, "dim_grand_prix", "circuit_key", "dim_circuit", "circuit_key")
    add_foreign_key(conn, "dim_session", "grand_prix_key", "dim_grand_prix", "grand_prix_key")
    add_foreign_key(conn, "dim_session", "season_key", "dim_season", "season_key")

    # Lap Performance fact links.
    for fk_col, ref_table in {
        "driver_key": "dim_driver",
        "team_key": "dim_team",
        "session_key": "dim_session",
        "grand_prix_key": "dim_grand_prix",
        "circuit_key": "dim_circuit",
        "season_key": "dim_season",
    }.items():
        add_foreign_key(conn, "fact_lap_performance", fk_col, ref_table, fk_col)

    # Session Result fact links.
    for fk_col, ref_table in {
        "driver_key": "dim_driver",
        "team_key": "dim_team",
        "session_key": "dim_session",
        "grand_prix_key": "dim_grand_prix",
        "circuit_key": "dim_circuit",
        "season_key": "dim_season",
    }.items():
        add_foreign_key(conn, "fact_session_result", fk_col, ref_table, fk_col)


def add_domain_checks(conn) -> None:
    temp_classes = {"Low", "Medium", "High", "Unknown"}

    add_check_in(conn, "dim_driver", "driver_age_class", {"Young", "Intermediate", "Senior", "Unknown"})

    add_check_in(conn, "fact_lap_performance", "lap_type", {"NormalLap", "OutLap", "InLap", "PitAffectedLap"})
    add_check_in(conn, "fact_lap_performance", "starting_tyre_set_status", {"NewTyreSet", "UsedTyreSet", "Unknown"})
    add_check_in(conn, "fact_lap_performance", "tyre_life_class", temp_classes)
    add_check_in(conn, "fact_lap_performance", "air_temp_class", temp_classes)
    add_check_in(conn, "fact_lap_performance", "track_temp_class", temp_classes)
    add_check_in(conn, "fact_lap_performance", "wind_speed_class", temp_classes)
    add_check_in(
        conn,
        "fact_lap_performance",
        "track_status_category",
        {"AllClear", "Yellow", "SCDeployed", "VSCDeployed", "VSCEnding", "Red", "Other", "Unknown"},
    )

    add_check_in(
        conn,
        "fact_session_result",
        "result_classification_category",
        {"Classified", "Retired", "Withdrawn", "Disqualified", "NotClassified", "Other", "Unknown"},
    )
    add_check_in(
        conn,
        "fact_session_result",
        "result_status_category",
        {
            "Finished",
            "ClassifiedGap",
            "Disqualified",
            "DidNotStart",
            "IncidentRetirement",
            "MechanicalRetirement",
            "Retirement",
            "Other",
            "Unknown",
        },
    )
    add_check_in(conn, "fact_session_result", "avg_air_temp_class", temp_classes)
    add_check_in(conn, "fact_session_result", "avg_track_temp_class", temp_classes)
    add_check_in(conn, "fact_session_result", "avg_wind_speed_class", temp_classes)


def add_all_constraints(engine: Engine) -> None:
    with engine.begin() as conn:
        print("ADDING NOT NULL constraints")
        add_not_null_constraints(conn)

        print("ADDING PRIMARY KEY constraints")
        add_primary_keys(conn)

        print("ADDING UNIQUE constraints")
        add_unique_constraints(conn)

        print("ADDING FOREIGN KEY constraints")
        add_foreign_keys(conn)

        print("ADDING CHECK constraints")
        add_domain_checks(conn)


# ============================================================
# POST-LOAD SUMMARY
# ============================================================

def print_loaded_table_summary(engine: Engine) -> None:
    inspector = inspect(engine)
    available = set(inspector.get_table_names(schema=SCHEMA_NAME))

    print("\n=== LOADED TABLE SUMMARY ===")
    with engine.connect() as conn:
        for table_name in LOAD_ORDER:
            if table_name not in available:
                continue
            result = conn.execute(text(f"SELECT COUNT(*) FROM {q_table(table_name)}"))
            row_count = result.scalar()
            print(f"{table_name}: {row_count:,} rows")


def print_final_message() -> None:
    print("\nDONE: Data Warehouse loaded successfully.")
    print(f"Database URL: {DATABASE_URL}")
    print(f"Schema: {SCHEMA_NAME}")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print("=== DATA WAREHOUSE LOAD STARTED ===")
    print(f"Input CSV directory: {CSV_DIR.resolve()}")

    if not CSV_DIR.exists():
        raise FileNotFoundError(
            f"Input directory not found: {CSV_DIR}. Run 01_transform_reconciled_to_dw_csvs.py first."
        )

    engine = connect_to_warehouse_db()

    with engine.begin() as conn:
        ensure_schema_exists(conn)
        if DROP_EXISTING_TABLES:
            drop_existing_tables(conn)

    print("\n--- Loading CSV files into PostgreSQL ---")
    loaded_tables = load_csvs_to_postgres(engine)

    print("\n--- Applying warehouse constraints ---")
    add_all_constraints(engine)

    print_loaded_table_summary(engine)
    print_final_message()


if __name__ == "__main__":
    main()
