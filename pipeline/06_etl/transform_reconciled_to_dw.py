from __future__ import annotations

"""
01_transform_reconciled_to_dw_csvs.py

Transform the cleaned reconciled Formula 1 PostgreSQL database into CSV files
ready to be loaded into the analytical Data Warehouse / Star Schema.

This script operationalizes the conceptual DFM decisions:
- pruning  -> final column selection and exclusion of non-analytical raw fields;
- grafting -> controlled joins that preserve useful descendants while hiding
              purely technical intermediate identifiers from the analytical model;
- derived attributes -> transformation of raw/time-dependent attributes into
                        fact-grain analytical attributes.

Expected reconciled tables, using the current project naming convention:
- season
- grand_prix
- session
- driver
- team
- result
- lap
- weather
- track_status

The script also supports older table aliases used during the project:
- event_weekend     -> grand_prix
- session_result    -> result
- lap_performance   -> lap
- session_weather   -> weather

Output CSVs and warehouse tables:
- shared dimensions: dim_driver, dim_team, dim_season, dim_grand_prix, dim_circuit, dim_session
- shared dimensions reuse the stable identifiers already present in the reconciled schema
  (driver_id, team_id, season_year, circuit_id, grand_prix_id, session_id);
- new surrogate keys are created only for derived low-cardinality / junk dimensions
  (tyre_context_key, weather_context_key, lap_data_quality_key, result_outcome_key,
  result_weather_context_key, result_data_quality_key);
- degenerate dimensions kept inside fact_lap_performance: session_type, lap_type, lap_number, track_status_category
- degenerate dimension kept inside fact_session_result: session_type
- facts: fact_lap_performance, fact_session_result
- metadata CSVs: dw_build_log.csv, dw_validation_report.csv
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


# ============================================================
# CONFIG
# ============================================================

# Main PostgreSQL connection. The default database name follows the project request: f1_proejct.
# If your local database is named f1_project instead, set the environment variable
# F1_DATABASE_URL before running the script.
DATABASE_URL = os.getenv(
    "F1_DATABASE_URL",
    "postgresql+psycopg://postgres:rudi@localhost:5432/f1_project",
)

# The cleaned reconciled schema is the source level for the DW ETL.
SOURCE_SCHEMA_NAME = os.getenv("F1_SOURCE_SCHEMA", "reconciled_clean")

# The Star Schema / Data Warehouse is written here.
WAREHOUSE_SCHEMA_NAME = os.getenv("F1_WAREHOUSE_SCHEMA", "warehouse")
DROP_WAREHOUSE_SCHEMA_BEFORE_LOAD = True
LOAD_TO_WAREHOUSE_DB = True
EXPORT_CSVS = True

OUTPUT_DIR = Path(os.getenv("F1_DW_OUTPUT_DIR", "dw_staging_csv"))

# Keep False during development so that the script writes a validation report
# instead of stopping at the first modeling inconsistency.
STRICT_VALIDATION = False

# Used only for the optional DriverAgeClass derived attribute.
# You can change it if you prefer age at the first event date or at each season.
DRIVER_AGE_REFERENCE_DATE = "2022-01-01"

# Current table names plus aliases from previous iterations of the project.
TABLE_ALIASES = {
    "season": ["season"],
    "grand_prix": ["grand_prix", "event_weekend", "event"],
    "session": ["session"],
    "driver": ["driver"],
    "team": ["team"],
    "result": ["result", "session_result"],
    "lap": ["lap", "lap_performance"],
    "weather": ["weather", "session_weather"],
    "track_status": ["track_status", "session_track_status"],
    "circuit": ["circuit"],
}

# Boolean quality attributes created by the Data Cleaning phase and retained in the DW.
# They implement the Lap Data Quality and Result Data Quality junk dimensions described
# in the conceptual report.
LAP_QUALITY_FLAGS = [
    "has_sector_information_issue",
    "has_speed_information_issue",
    "has_tyre_information_issue",
    "has_weather_information_issue",
    "has_track_status_information_issue",
    "has_pit_information_issue",
]

RESULT_QUALITY_FLAGS = [
    "has_qualifying_information_issue",
    "has_race_context_information_issue",
]

LOW_MEDIUM_HIGH_UNKNOWN = {"Low", "Medium", "High", "Unknown"}



# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class ValidationIssue:
    severity: str
    table_name: str
    check_name: str
    message: str
    affected_rows: int | None = None


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def quote_ident(identifier: str) -> str:
    """Safely quote a SQL identifier known by the script."""
    return '"' + identifier.replace('"', '""') + '"'


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:

    import re

    out = df.copy()
    normalized = []
    for col in out.columns:
        name = str(col)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        name = re.sub(r"[^0-9a-zA-Z_]+", "_", name)
        name = name.strip("_").lower()
        normalized.append(name)
    out.columns = normalized
    return out


def existing_columns(df: pd.DataFrame, columns: Iterable[str]) -> list[str]:
    return [col for col in columns if col in df.columns]


def ensure_columns(df: pd.DataFrame, columns: Iterable[str], fill_value=pd.NA) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = fill_value
    return out


def add_surrogate_key(df: pd.DataFrame, key_name: str, start: int = 1) -> pd.DataFrame:
    out = df.reset_index(drop=True).copy()
    out.insert(0, key_name, range(start, start + len(out)))
    return out


def sort_if_possible(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    cols = existing_columns(df, columns)
    if not cols:
        return df.reset_index(drop=True)
    return df.sort_values(cols, kind="stable").reset_index(drop=True)


def dedupe(df: pd.DataFrame, subset: list[str]) -> pd.DataFrame:
    subset = existing_columns(df, subset)
    if not subset:
        return df.drop_duplicates().reset_index(drop=True)
    return df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)


def normalize_bool(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text_value = str(value).strip().lower()
    if text_value in {"true", "t", "1", "yes", "y"}:
        return True
    if text_value in {"false", "f", "0", "no", "n"}:
        return False
    return pd.NA


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def build_composite_id(df: pd.DataFrame, cols: list[str], prefix: str) -> pd.Series:
    available = existing_columns(df, cols)
    if not available:
        return pd.Series([f"{prefix}_{i + 1}" for i in range(len(df))], index=df.index)
    return (
        prefix
        + "_"
        + df[available]
        .astype("string")
        .fillna("unknown")
        .agg("_".join, axis=1)
    )


def normalize_bool_or_false(value: object) -> bool:
    normalized = normalize_bool(value)
    if pd.isna(normalized):
        return False
    return bool(normalized)


def normalize_bool_or_unknown(value: object) -> object:
    normalized = normalize_bool(value)
    if pd.isna(normalized):
        return pd.NA
    return bool(normalized)


def ensure_quality_flag_columns(df: pd.DataFrame, flag_columns: list[str]) -> pd.DataFrame:
    """Ensure data-cleaning-derived quality flags exist and are boolean."""
    out = df.copy()
    for col in flag_columns:
        if col not in out.columns:
            out[col] = False
        else:
            out[col] = out[col].apply(normalize_bool_or_false).astype(bool)
    return out


def fill_unknown_for_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = "Unknown"
        else:
            out[col] = out[col].where(out[col].notna(), "Unknown")
    return out


def build_low_cardinality_dimension(
    source_df: pd.DataFrame,
    attributes: list[str],
    key_name: str,
    *,
    bool_columns: list[str] | None = None,
    sort_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Build a small dimension from a set of low-cardinality attributes."""
    bool_columns = bool_columns or []
    sort_columns = sort_columns or attributes

    work = ensure_columns(source_df, attributes).copy()
    for col in bool_columns:
        if col in work.columns:
            work[col] = work[col].apply(normalize_bool_or_false).astype(bool)

    for col in attributes:
        if col in bool_columns:
            continue
        if col in work.columns:
            work[col] = work[col].where(work[col].notna(), "Unknown")

    dim = work[attributes].drop_duplicates().reset_index(drop=True)
    dim = sort_if_possible(dim, sort_columns)
    return add_surrogate_key(dim, key_name)


def output_table_order(dimensions: dict[str, pd.DataFrame]) -> list[str]:
    preferred = [
        "dim_driver",
        "dim_team",
        "dim_season",
        "dim_circuit",
        "dim_grand_prix",
        "dim_session",
        "dim_tyre_context",
        "dim_weather_context",
        "dim_lap_data_quality",
        "dim_result_outcome",
        "dim_result_weather_context",
        "dim_result_data_quality",
        "fact_lap_performance",
        "fact_session_result",
    ]
    return [name for name in preferred if name in dimensions or name.startswith("fact_")]


# ============================================================
# DATABASE ACCESS
# ============================================================

def connect_to_reconciled_db() -> Engine:
    """Create the SQLAlchemy engine for the reconciled PostgreSQL database."""
    return create_engine(DATABASE_URL)


def list_database_tables(engine: Engine, schema_name: str) -> set[str]:
    inspector = inspect(engine)
    return set(inspector.get_table_names(schema=schema_name))


def resolve_table_name(logical_name: str, available_tables: set[str]) -> str | None:
    for candidate in TABLE_ALIASES[logical_name]:
        if candidate in available_tables:
            return candidate
    return None


def read_table(engine: Engine, table_name: str, schema_name: str) -> pd.DataFrame:
    sql = f"SELECT * FROM {quote_ident(schema_name)}.{quote_ident(table_name)}"
    with engine.connect() as conn:
        df = pd.read_sql_query(text(sql), conn)
    return normalize_columns(df)


def load_source_tables(engine: Engine) -> dict[str, pd.DataFrame]:

    available = list_database_tables(engine, SOURCE_SCHEMA_NAME)
    tables: dict[str, pd.DataFrame] = {}
    missing: list[str] = []

    for logical_name in TABLE_ALIASES:
        physical_name = resolve_table_name(logical_name, available)
        if physical_name is None:
            missing.append(logical_name)
            continue
        tables[logical_name] = read_table(engine, physical_name, SOURCE_SCHEMA_NAME)
        print(
            f"LOADED {SOURCE_SCHEMA_NAME}.{physical_name} -> {logical_name}: "
            f"{len(tables[logical_name]):,} rows"
        )

    if missing:
        raise RuntimeError(
            "Missing expected reconciled tables in schema "
            + SOURCE_SCHEMA_NAME
            + ": "
            + ", ".join(missing)
            + ". Available tables are: "
            + ", ".join(sorted(available))
        )

    return tables


# ============================================================
# JOIN KEY HELPERS
# ============================================================

def session_key_cols_for(left: pd.DataFrame, right: pd.DataFrame) -> list[str]:
    if "session_id" in left.columns and "session_id" in right.columns:
        return ["session_id"]
    natural = ["season_year", "round_number", "session_type"]
    if set(natural).issubset(left.columns) and set(natural).issubset(right.columns):
        return natural
    raise KeyError(
        "Cannot find a valid session join key. Expected session_id or "
        "season_year + round_number + session_type."
    )


def grand_prix_key_cols_for(left: pd.DataFrame, right: pd.DataFrame) -> list[str]:
    if "grand_prix_id" in left.columns and "grand_prix_id" in right.columns:
        return ["grand_prix_id"]
    natural = ["season_year", "round_number"]
    if set(natural).issubset(left.columns) and set(natural).issubset(right.columns):
        return natural
    raise KeyError(
        "Cannot find a valid grand prix join key. Expected grand_prix_id or "
        "season_year + round_number."
    )


def add_session_and_grand_prix_context(
    fact_df: pd.DataFrame,
    session_df: pd.DataFrame,
    grand_prix_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Implement the grafting logic operationally.

    The fact is joined to session and grand_prix so that useful descendants of
    the session branch remain available, while the final analytical fact can use
    dimension keys rather than exposing every technical intermediate column.
    """
    out = fact_df.copy()

    # Add session context.
    sess_cols = existing_columns(
        session_df,
        [
            "session_id",
            "grand_prix_id",
            "season_year",
            "round_number",
            "session_type",
            "session_name",
            "session_date",
        ],
    )
    sess = session_df[sess_cols].drop_duplicates().copy()
    join_cols = session_key_cols_for(out, sess)

    cols_to_add = [col for col in sess.columns if col not in out.columns or col in join_cols]
    out = out.merge(
        sess[cols_to_add].drop_duplicates(),
        on=join_cols,
        how="left",
        validate="m:1",
    )

    # Add grand prix / circuit / season context.
    gp_cols = existing_columns(
        grand_prix_df,
        [
            "grand_prix_id",
            "season_year",
            "round_number",
            "circuit_id",
            "event_name",
            "event_date",
            "event_format",
        ],
    )
    gp = grand_prix_df[gp_cols].drop_duplicates().copy()
    gp_join_cols = grand_prix_key_cols_for(out, gp)
    cols_to_add = [col for col in gp.columns if col not in out.columns or col in gp_join_cols]
    out = out.merge(
        gp[cols_to_add].drop_duplicates(),
        on=gp_join_cols,
        how="left",
        validate="m:1",
    )

    return out


# ============================================================
# DERIVED ATTRIBUTE HELPERS
# ============================================================

def classify_air_temp(value: object) -> str:
    if pd.isna(value):
        return "Unknown"
    value = float(value)
    if value < 20:
        return "Low"
    if value < 28:
        return "Medium"
    return "High"


def classify_track_temp(value: object) -> str:
    if pd.isna(value):
        return "Unknown"
    value = float(value)
    if value < 30:
        return "Low"
    if value < 42:
        return "Medium"
    return "High"


def classify_wind_speed(value: object) -> str:
    if pd.isna(value):
        return "Unknown"
    value = float(value)
    if value < 2:
        return "Low"
    if value < 5:
        return "Medium"
    return "High"


def derive_lap_type(row: pd.Series) -> str:
    pit_out = not pd.isna(row.get("pit_out_time_ms"))
    pit_in = not pd.isna(row.get("pit_in_time_ms"))

    if pit_out and pit_in:
        return "PitAffectedLap"
    if pit_out:
        return "OutLap"
    if pit_in:
        return "InLap"
    return "NormalLap"


def derive_starting_tyre_set_status(value: object) -> str:
    normalized = normalize_bool(value)
    if pd.isna(normalized):
        return "Unknown"
    return "NewSet" if normalized else "UsedSet"


def derive_tyre_life_class(value: object) -> str:
    if pd.isna(value):
        return "Unknown"
    value = float(value)
    if value <= 3:
        return "Low"
    if value <= 15:
        return "Medium"
    return "High"


def derive_driver_age_class(date_of_birth: object) -> str:
    dob = pd.to_datetime(date_of_birth, errors="coerce")
    ref = pd.to_datetime(DRIVER_AGE_REFERENCE_DATE, errors="coerce")
    if pd.isna(dob) or pd.isna(ref):
        return "Unknown"
    age = (ref - dob).days / 365.25
    if age < 25:
        return "Young"
    if age < 32:
        return "Intermediate"
    return "Senior"


def derive_track_status_category(message: object, status: object = None) -> str:
    text_value = "" if pd.isna(message) else str(message).strip().lower()
    status_value = "" if pd.isna(status) else str(status).strip().lower()
    combined = f"{text_value} {status_value}".strip()

    if not combined:
        return "Unknown"
    if "allclear" in combined or "all clear" in combined:
        return "AllClear"
    if "vscending" in combined or "vsc ending" in combined:
        return "VSCEnding"
    if "vscdeployed" in combined or "virtual safety car" in combined or "vsc" in combined:
        return "VSCDeployed"
    if "scdeployed" in combined or "safety car" in combined:
        return "SCDeployed"
    if "yellow" in combined:
        return "Yellow"
    if "red" in combined:
        return "Red"
    return "Other"


def derive_result_classification_category(value: object) -> str:
    if pd.isna(value):
        return "NotApplicable"
    text_value = str(value).strip().upper()
    if text_value.isdigit():
        return "Classified"
    if text_value == "R":
        return "Retired"
    if text_value in {"D", "DQ", "DSQ"}:
        return "Disqualified"
    if text_value == "E":
        return "Excluded"
    if text_value == "W":
        return "Withdrawn"
    if text_value == "F":
        return "FailedToQualify"
    if text_value in {"N", "NC"}:
        return "NotClassified"
    return "Other"


def derive_result_status_category(value: object) -> str:
    if pd.isna(value):
        return "NotApplicable"
    text_value = str(value).strip().lower()

    if text_value == "finished":
        return "Finished"
    if text_value.startswith("+"):
        return "Lapped"
    if "disqualified" in text_value or "excluded" in text_value:
        return "Disqualified"
    if "did not start" in text_value or text_value == "dns":
        return "DidNotStart"
    if "collision" in text_value:
        return "Collision"
    if any(word in text_value for word in ["accident", "spun off", "crash", "damage"]):
        return "Accident"
    if any(word in text_value for word in ["engine", "power unit", "turbo"]):
        return "PowerUnitIssue"
    if any(
        word in text_value
        for word in [
            "gearbox",
            "hydraulic",
            "transmission",
            "brake",
            "brakes",
            "suspension",
            "electrical",
            "fuel",
            "oil",
            "water",
            "exhaust",
            "clutch",
        ]
    ):
        return "MechanicalIssue"
    if "retired" in text_value or "withdrawn" in text_value:
        return "Retired"
    return "Other"


def derive_gap_to_leader_ms(df: pd.DataFrame) -> pd.Series:
    """
    The raw result time_ms is not homogeneous. For race results, FastF1 usually
    stores 0/missing for the leader and gaps for other drivers. This function
    applies the project-level modeling decision:
    - P1 gets 0;
    - other comparable drivers keep time_ms if available;
    - non-comparable rows remain null.
    """
    if "time_ms" not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Int64")

    time_ms = to_numeric(df["time_ms"])
    position = to_numeric(df["position"]) if "position" in df.columns else pd.Series(np.nan, index=df.index)
    gap = time_ms.copy()
    gap[position == 1] = 0
    return gap.astype("Int64")


# ============================================================
# TIME-DEPENDENT CONTEXT ALIGNMENT
# ============================================================

def context_time_col_for_lap(lap_df: pd.DataFrame) -> pd.Series:
    """
    Choose the lap timestamp used for contextual alignment.

    Prefer lap_start_time_ms if available; otherwise use time_ms, which usually
    represents elapsed session time at the lap record / lap completion.
    """
    if "lap_start_time_ms" in lap_df.columns:
        return to_numeric(lap_df["lap_start_time_ms"])
    if "time_ms" in lap_df.columns:
        return to_numeric(lap_df["time_ms"])
    return pd.Series(np.nan, index=lap_df.index)


def merge_asof_by_session(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    left_time_col: str,
    right_time_col: str,
    session_cols: list[str],
    suffix: str,
) -> pd.DataFrame:
    """
    Robust group-wise asof merge for time-dependent session data.

    For each row in left_df, the function finds the nearest previous context row
    in right_df inside the same session.

    If no previous context row exists, it uses the nearest context row in the same
    session as fallback.

    This version avoids boolean-index alignment errors by resetting the temporary
    group indexes before using masks produced by pd.merge_asof.
    """

    if left_df.empty or right_df.empty:
        return left_df.copy()

    missing_left = [
        col for col in session_cols + [left_time_col]
        if col not in left_df.columns
    ]

    missing_right = [
        col for col in session_cols + [right_time_col]
        if col not in right_df.columns
    ]

    if missing_left or missing_right:
        return left_df.copy()

    left_order_col = "__left_original_order__"

    while left_order_col in left_df.columns or left_order_col in right_df.columns:
        left_order_col = "_" + left_order_col

    left_base = left_df.copy()
    left_base[left_order_col] = range(len(left_base))

    pieces: list[pd.DataFrame] = []

    right_grouped = right_df.groupby(
        session_cols,
        dropna=False,
        sort=False,
    )

    for session_key, left_group in left_base.groupby(
        session_cols,
        dropna=False,
        sort=False,
    ):
        try:
            right_group = right_grouped.get_group(session_key)
        except KeyError:
            pieces.append(left_group.copy())
            continue

        left_group = left_group.copy()
        right_group = right_group.copy()

        valid_left_time = left_group[left_time_col].notna()
        valid_right_time = right_group[right_time_col].notna()

        left_without_time = left_group.loc[~valid_left_time].copy()
        left_work = (
            left_group
            .loc[valid_left_time]
            .sort_values(left_time_col, kind="stable")
            .reset_index(drop=True)
            .copy()
        )

        right_work = (
            right_group
            .loc[valid_right_time]
            .sort_values(right_time_col, kind="stable")
            .reset_index(drop=True)
            .copy()
        )

        if left_work.empty:
            if not left_without_time.empty:
                pieces.append(left_without_time)
            continue

        if right_work.empty:
            pieces.append(left_group.copy())
            continue

        merged = pd.merge_asof(
            left_work,
            right_work,
            left_on=left_time_col,
            right_on=right_time_col,
            direction="backward",
            suffixes=("", suffix),
        )

        context_cols = [
            col for col in right_work.columns
            if col not in session_cols
        ]

        if context_cols:
            first_context_col = context_cols[0]

            if first_context_col in merged.columns:
                missing_mask = merged[first_context_col].isna()
            else:
                missing_mask = pd.Series(False, index=merged.index)

            if missing_mask.any():
                nearest_left = left_work.loc[missing_mask].copy()

                nearest = pd.merge_asof(
                    nearest_left,
                    right_work,
                    left_on=left_time_col,
                    right_on=right_time_col,
                    direction="nearest",
                    suffixes=("", suffix),
                )

                nearest.index = merged.index[missing_mask]

                common_cols = [
                    col for col in nearest.columns
                    if col in merged.columns
                ]

                for col in common_cols:
                    merged.loc[missing_mask, col] = nearest[col].to_numpy()

        pieces.append(merged)

        if not left_without_time.empty:
            pieces.append(left_without_time)

    if not pieces:
        out = left_base.copy()
    else:
        out = pd.concat(pieces, ignore_index=True)

    out = (
        out
        .sort_values(left_order_col, kind="stable")
        .drop(columns=[left_order_col])
        .reset_index(drop=True)
    )

    return out

def add_lap_weather_context(lap_df: pd.DataFrame, weather_df: pd.DataFrame) -> pd.DataFrame:
    out = lap_df.copy()
    out["lap_context_time_ms"] = context_time_col_for_lap(out)

    session_cols = session_key_cols_for(out, weather_df)
    keep_cols = session_cols + existing_columns(
        weather_df,
        ["time_ms", "air_temp", "track_temp", "rainfall", "wind_speed"],
    )
    weather = weather_df[keep_cols].copy()

    if "time_ms" not in weather.columns:
        out["air_temp_class"] = "Unknown"
        out["track_temp_class"] = "Unknown"
        out["rain_flag"] = pd.NA
        out["wind_speed_class"] = "Unknown"
        return out

    weather = weather.rename(columns={"time_ms": "weather_time_ms"})
    out = merge_asof_by_session(
        out,
        weather,
        left_time_col="lap_context_time_ms",
        right_time_col="weather_time_ms",
        session_cols=session_cols,
        suffix="_weather",
    )

    out["air_temp_class"] = out.get("air_temp", pd.Series(pd.NA, index=out.index)).apply(classify_air_temp)
    out["track_temp_class"] = out.get("track_temp", pd.Series(pd.NA, index=out.index)).apply(classify_track_temp)
    out["wind_speed_class"] = out.get("wind_speed", pd.Series(pd.NA, index=out.index)).apply(classify_wind_speed)

    if "rainfall" in out.columns:
        out["rain_flag"] = out["rainfall"].apply(normalize_bool)
    else:
        out["rain_flag"] = pd.NA

    return out


def add_lap_track_status_context(lap_df: pd.DataFrame, track_status_df: pd.DataFrame) -> pd.DataFrame:
    out = lap_df.copy()
    if "lap_context_time_ms" not in out.columns:
        out["lap_context_time_ms"] = context_time_col_for_lap(out)

    session_cols = session_key_cols_for(out, track_status_df)
    keep_cols = session_cols + existing_columns(track_status_df, ["time_ms", "status", "message"])
    track = track_status_df[keep_cols].copy()

    if "time_ms" not in track.columns:
        out["track_status_category"] = "Unknown"
        return out

    track = track.rename(columns={"time_ms": "track_status_time_ms"})
    out = merge_asof_by_session(
        out,
        track,
        left_time_col="lap_context_time_ms",
        right_time_col="track_status_time_ms",
        session_cols=session_cols,
        suffix="_track_status",
    )

    message_series = out["message"] if "message" in out.columns else pd.Series(pd.NA, index=out.index)
    status_series = out["status"] if "status" in out.columns else pd.Series(pd.NA, index=out.index)
    out["track_status_category"] = [
        derive_track_status_category(message, status)
        for message, status in zip(message_series, status_series)
    ]
    return out


def build_session_weather_context(weather_df: pd.DataFrame) -> pd.DataFrame:
    session_cols = existing_columns(weather_df, ["session_id"])
    if not session_cols:
        session_cols = existing_columns(weather_df, ["season_year", "round_number", "session_type"])

    if not session_cols:
        return pd.DataFrame()

    work = weather_df.copy()
    for col in ["air_temp", "track_temp", "wind_speed"]:
        if col in work.columns:
            work[col] = to_numeric(work[col])
    if "rainfall" in work.columns:
        work["rainfall_bool"] = work["rainfall"].apply(normalize_bool).fillna(False).astype(bool)
    else:
        work["rainfall_bool"] = False

    agg_map = {"rainfall_bool": "max"}
    if "air_temp" in work.columns:
        agg_map["air_temp"] = "mean"
    if "track_temp" in work.columns:
        agg_map["track_temp"] = "mean"
    if "wind_speed" in work.columns:
        agg_map["wind_speed"] = "mean"

    context = work.groupby(session_cols, dropna=False).agg(agg_map).reset_index()
    context = context.rename(
        columns={
            "rainfall_bool": "rain_flag",
            "air_temp": "avg_air_temp",
            "track_temp": "avg_track_temp",
            "wind_speed": "avg_wind_speed",
        }
    )

    context["avg_air_temp_class"] = context.get("avg_air_temp", pd.Series(pd.NA, index=context.index)).apply(classify_air_temp)
    context["avg_track_temp_class"] = context.get("avg_track_temp", pd.Series(pd.NA, index=context.index)).apply(classify_track_temp)
    context["avg_wind_speed_class"] = context.get("avg_wind_speed", pd.Series(pd.NA, index=context.index)).apply(classify_wind_speed)

    return context


# ============================================================
# DIMENSION BUILDERS
# ============================================================

def build_dim_driver(driver_df: pd.DataFrame) -> pd.DataFrame:
    """Build dim_driver using driver_id as the dimension key.

    No additional driver_key is created, because driver_id is already the
    stable identifier of the driver entity in the reconciled schema.
    """
    work = driver_df.copy()
    if "driver_id" not in work.columns:
        raise KeyError("driver table must contain driver_id")

    if "date_of_birth" in work.columns:
        work["driver_age_class"] = work["date_of_birth"].apply(derive_driver_age_class)
    else:
        work["driver_age_class"] = "Unknown"

    columns = [
        "driver_id",
        "abbreviation",
        "first_name",
        "last_name",
        "nationality",
        "driver_age_class",
    ]
    dim = work[existing_columns(work, columns)].copy()
    dim = dedupe(dim, ["driver_id"])
    dim = sort_if_possible(dim, ["driver_id"])
    return dim

def build_dim_team(team_df: pd.DataFrame) -> pd.DataFrame:
    """Build dim_team using team_id as the dimension key."""
    work = team_df.copy()
    if "team_id" not in work.columns:
        raise KeyError("team table must contain team_id")

    columns = ["team_id", "team_name", "nationality"]
    dim = work[existing_columns(work, columns)].copy()
    dim = dedupe(dim, ["team_id"])
    dim = sort_if_possible(dim, ["team_id"])
    return dim

def build_dim_season(season_df: pd.DataFrame) -> pd.DataFrame:
    """Build dim_season using season_year as the dimension key."""
    work = season_df.copy()
    if "season_year" not in work.columns:
        raise KeyError("season table must contain season_year")

    columns = [
        "season_year",
        "season_start_date",
        "season_end_date",
        "number_of_events",
        "champion_driver",
        "champion_team",
    ]
    dim = work[existing_columns(work, columns)].copy()
    dim = dedupe(dim, ["season_year"])
    dim = sort_if_possible(dim, ["season_year"])
    return dim

def build_dim_circuit(circuit_df: pd.DataFrame) -> pd.DataFrame:
    """Build dim_circuit using circuit_id as the dimension key."""
    work = circuit_df.copy()
    if "circuit_id" not in work.columns:
        raise KeyError("circuit table must contain circuit_id")

    columns = [
        "circuit_id",
        "circuit_name",
        "country",
        "location",
        "global_circuit_category",
        "sector1_category",
        "sector2_category",
        "sector3_category",
    ]
    dim = work[existing_columns(work, columns)].copy()
    dim = dedupe(dim, ["circuit_id"])
    dim = sort_if_possible(dim, ["circuit_id"])
    return dim

def build_dim_grand_prix(
    grand_prix_df: pd.DataFrame,
    dim_season: pd.DataFrame,
    dim_circuit: pd.DataFrame,
) -> pd.DataFrame:
    """Build dim_grand_prix using grand_prix_id as the dimension key.

    The function intentionally does not create grand_prix_key. The foreign keys
    to season and circuit are kept as season_year and circuit_id, because those
    are the identifiers already used by the corresponding dimensions.
    """
    work = grand_prix_df.copy()

    if "grand_prix_id" not in work.columns:
        work["grand_prix_id"] = build_composite_id(
            work,
            ["season_year", "round_number"],
            prefix="grand_prix",
        )

    columns = [
        "grand_prix_id",
        "season_year",
        "round_number",
        "circuit_id",
        "event_name",
        "event_date",
        "event_format",
    ]
    dim = work[existing_columns(work, columns)].copy()
    dim = dedupe(dim, ["grand_prix_id"])
    dim = sort_if_possible(dim, ["season_year", "round_number", "grand_prix_id"])
    return dim

def build_dim_session(
    session_df: pd.DataFrame,
    grand_prix_df: pd.DataFrame,
    dim_grand_prix: pd.DataFrame,
    dim_season: pd.DataFrame,
) -> pd.DataFrame:
    """Build dim_session using session_id as the dimension key.

    session_type remains available as a descriptive attribute of the session
    dimension, but it is also copied into the facts as a degenerate dimension.
    """
    work = session_df.copy()

    if "session_id" not in work.columns:
        work["session_id"] = build_composite_id(
            work,
            ["season_year", "round_number", "session_type"],
            prefix="session",
        )

    # Add grand_prix_id if the session table does not already contain it.
    if "grand_prix_id" not in work.columns and {"season_year", "round_number"}.issubset(work.columns):
        gp_tmp = grand_prix_df.copy()
        if "grand_prix_id" not in gp_tmp.columns:
            gp_tmp["grand_prix_id"] = build_composite_id(
                gp_tmp,
                ["season_year", "round_number"],
                prefix="grand_prix",
            )
        gp_lookup_cols = existing_columns(gp_tmp, ["grand_prix_id", "season_year", "round_number"])
        work = work.merge(
            gp_tmp[gp_lookup_cols].drop_duplicates(),
            on=["season_year", "round_number"],
            how="left",
            validate="m:1",
        )

    columns = [
        "session_id",
        "grand_prix_id",
        "season_year",
        "round_number",
        "session_type",
        "session_name",
        "session_date",
    ]
    dim = work[existing_columns(work, columns)].copy()
    dim = dedupe(dim, ["session_id"])
    dim = sort_if_possible(dim, ["season_year", "round_number", "session_type", "session_id"])
    return dim

def build_shared_dimensions(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    dim_driver = build_dim_driver(tables["driver"])
    dim_team = build_dim_team(tables["team"])
    dim_season = build_dim_season(tables["season"])
    dim_circuit = build_dim_circuit(tables["circuit"])
    dim_grand_prix = build_dim_grand_prix(tables["grand_prix"], dim_season, dim_circuit)
    dim_session = build_dim_session(tables["session"], tables["grand_prix"], dim_grand_prix, dim_season)

    return {
        "dim_driver": dim_driver,
        "dim_team": dim_team,
        "dim_season": dim_season,
        "dim_circuit": dim_circuit,
        "dim_grand_prix": dim_grand_prix,
        "dim_session": dim_session,
    }



def build_lap_specific_dimensions(lap_work: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Build only the real low-cardinality dimensions for the Lap Performance fact.

    Degenerate dimensions are not materialized as separate tables. Therefore,
    the following attributes remain directly inside fact_lap_performance:
    - session_type
    - lap_type
    - lap_number
    - track_status_category
    """
    lap_work = ensure_quality_flag_columns(lap_work, LAP_QUALITY_FLAGS)

    return {
        "dim_tyre_context": build_low_cardinality_dimension(
            lap_work,
            ["compound", "starting_tyre_set_status", "tyre_life_class"],
            "tyre_context_key",
        ),
        "dim_weather_context": build_low_cardinality_dimension(
            lap_work,
            ["rain_flag", "air_temp_class", "track_temp_class", "wind_speed_class"],
            "weather_context_key",
            bool_columns=["rain_flag"],
        ),
        "dim_lap_data_quality": build_low_cardinality_dimension(
            lap_work,
            LAP_QUALITY_FLAGS,
            "lap_data_quality_key",
            bool_columns=LAP_QUALITY_FLAGS,
        ),
    }

def build_result_specific_dimensions(result_work: pd.DataFrame) -> dict[str, pd.DataFrame]:
    result_work = ensure_quality_flag_columns(result_work, RESULT_QUALITY_FLAGS)

    return {
        "dim_result_outcome": build_low_cardinality_dimension(
            result_work,
            ["result_status_category", "result_classification_category"],
            "result_outcome_key",
        ),
        "dim_result_weather_context": build_low_cardinality_dimension(
            result_work,
            ["rain_flag", "avg_air_temp_class", "avg_track_temp_class", "avg_wind_speed_class"],
            "result_weather_context_key",
            bool_columns=["rain_flag"],
        ),
        "dim_result_data_quality": build_low_cardinality_dimension(
            result_work,
            RESULT_QUALITY_FLAGS,
            "result_data_quality_key",
            bool_columns=RESULT_QUALITY_FLAGS,
        ),
    }


# ============================================================
# DIMENSION KEY MAPPING
# ============================================================

def map_dimension_key(
    fact_df: pd.DataFrame,
    dim_df: pd.DataFrame,
    natural_cols: list[str],
    key_col: str,
) -> pd.DataFrame:
    out = fact_df.copy()
    if key_col in out.columns:
        out = out.drop(columns=[key_col])

    available = [col for col in natural_cols if col in out.columns and col in dim_df.columns]
    if not available:
        out[key_col] = pd.NA
        return out

    mapping = dim_df[[key_col] + available].drop_duplicates(subset=available, keep="first")
    out = out.merge(mapping, on=available, how="left", validate="m:1")
    return out


def map_all_shared_dimension_keys(
    fact_df: pd.DataFrame,
    dimensions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Keep shared dimension identifiers directly in the fact.

    For entity dimensions already present in the reconciled schema, this script
    reuses the existing identifiers instead of generating redundant DW keys:
    - driver_id -> dim_driver.driver_id
    - team_id -> dim_team.team_id
    - season_year -> dim_season.season_year
    - circuit_id -> dim_circuit.circuit_id
    - grand_prix_id -> dim_grand_prix.grand_prix_id
    - session_id -> dim_session.session_id

    New surrogate keys are created only later for derived context/junk
    dimensions, such as tyre_context_key and lap_data_quality_key.
    """
    out = fact_df.copy()

    required_ids = [
        "driver_id",
        "team_id",
        "session_id",
        "grand_prix_id",
        "circuit_id",
        "season_year",
    ]
    out = ensure_columns(out, required_ids)
    return out

# ============================================================
# FACT PREPARATION AND BUILDERS
# ============================================================


def prepare_lap_performance_work(
    tables: dict[str, pd.DataFrame],
    dimensions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Prepare the lap-level working table before final Star Schema pruning.

    Derived low-cardinality attributes are kept temporarily. Some of them will
    be mapped to real dimensions; degenerate dimensions remain directly inside
    fact_lap_performance.
    """
    lap = tables["lap"].copy()
    lap = ensure_quality_flag_columns(lap, LAP_QUALITY_FLAGS)

    if "lap_id" not in lap.columns:
        lap["lap_id"] = build_composite_id(
            lap,
            ["season_year", "round_number", "session_type", "driver_id", "lap_number"],
            prefix="lap",
        )

    lap = add_session_and_grand_prix_context(lap, tables["session"], tables["grand_prix"])

    # Derived attributes from pruned/raw attributes.
    lap["lap_type"] = lap.apply(derive_lap_type, axis=1)

    if "fresh_tyre" in lap.columns:
        lap["starting_tyre_set_status"] = lap["fresh_tyre"].apply(derive_starting_tyre_set_status)
    else:
        lap["starting_tyre_set_status"] = "Unknown"

    if "tyre_life" in lap.columns:
        lap["tyre_life_class"] = lap["tyre_life"].apply(derive_tyre_life_class)
    else:
        lap["tyre_life_class"] = "Unknown"

    # Derived lap-level context from time-dependent weather and track-status tables.
    lap = add_lap_weather_context(lap, tables["weather"])
    lap = add_lap_track_status_context(lap, tables["track_status"])

    # Normalize context attributes before dimension construction.
    lap = fill_unknown_for_columns(
        lap,
        [
            "compound",
            "lap_type",
            "starting_tyre_set_status",
            "tyre_life_class",
            "air_temp_class",
            "track_temp_class",
            "wind_speed_class",
            "track_status_category",
            "session_type",
        ],
    )
    if "rain_flag" in lap.columns:
        lap["rain_flag"] = lap["rain_flag"].apply(normalize_bool_or_false).astype(bool)
    else:
        lap["rain_flag"] = False

    # Preserve reused shared dimension identifiers.
    # Degenerate dimensions are kept as columns in the fact:
    # session_type, lap_type, lap_number, track_status_category.
    lap = map_all_shared_dimension_keys(lap, dimensions)
    return lap


def prepare_session_result_work(
    tables: dict[str, pd.DataFrame],
    dimensions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Prepare the result-level working table before final Star Schema pruning.

    session_type is kept directly in fact_session_result as a degenerate dimension.
    """
    result = tables["result"].copy()
    result = ensure_quality_flag_columns(result, RESULT_QUALITY_FLAGS)

    if "result_id" not in result.columns:
        result["result_id"] = build_composite_id(
            result,
            ["season_year", "round_number", "session_type", "driver_id"],
            prefix="result",
        )

    result = add_session_and_grand_prix_context(result, tables["session"], tables["grand_prix"])

    # Derived result-level attributes from pruned/raw attributes.
    if "classified_position" in result.columns:
        result["result_classification_category"] = result["classified_position"].apply(
            derive_result_classification_category
        )
    else:
        result["result_classification_category"] = "Unknown"

    if "status" in result.columns:
        result["result_status_category"] = result["status"].apply(derive_result_status_category)
    else:
        result["result_status_category"] = "Unknown"

    result["gap_to_leader_ms"] = derive_gap_to_leader_ms(result)

    # Session-level weather context: aggregate weather over the whole session.
    session_weather_context = build_session_weather_context(tables["weather"])
    if not session_weather_context.empty:
        join_cols = session_key_cols_for(result, session_weather_context)
        result = result.merge(
            session_weather_context,
            on=join_cols,
            how="left",
            validate="m:1",
        )
    else:
        result["rain_flag"] = False
        result["avg_air_temp_class"] = "Unknown"
        result["avg_track_temp_class"] = "Unknown"
        result["avg_wind_speed_class"] = "Unknown"

    result = fill_unknown_for_columns(
        result,
        [
            "result_classification_category",
            "result_status_category",
            "avg_air_temp_class",
            "avg_track_temp_class",
            "avg_wind_speed_class",
            "session_type",
        ],
    )
    if "rain_flag" in result.columns:
        result["rain_flag"] = result["rain_flag"].apply(normalize_bool_or_false).astype(bool)
    else:
        result["rain_flag"] = False

    # Preserve reused shared dimension identifiers.
    # session_type remains directly in the fact as a degenerate dimension.
    result = map_all_shared_dimension_keys(result, dimensions)
    return result


def finalize_lap_performance_fact(
    lap_work: pd.DataFrame,
    dimensions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Build fact_lap_performance.

    Reused shared dimension identifiers are stored directly in the fact:
    driver_id, team_id, session_id, grand_prix_id, circuit_id, season_year.

    New keys are used only for derived low-cardinality / junk dimensions.
    Degenerate dimensions are stored directly in the fact table:
    - session_type
    - lap_type
    - lap_number
    - track_status_category
    """
    lap = lap_work.copy()

    lap = fill_unknown_for_columns(
        lap,
        ["session_type", "lap_type", "track_status_category"],
    )

    lap = map_dimension_key(
        lap,
        dimensions["dim_tyre_context"],
        ["compound", "starting_tyre_set_status", "tyre_life_class"],
        "tyre_context_key",
    )
    lap = map_dimension_key(
        lap,
        dimensions["dim_weather_context"],
        ["rain_flag", "air_temp_class", "track_temp_class", "wind_speed_class"],
        "weather_context_key",
    )
    lap = map_dimension_key(
        lap,
        dimensions["dim_lap_data_quality"],
        LAP_QUALITY_FLAGS,
        "lap_data_quality_key",
    )

    final_columns = [
        "lap_id",
        # Reused shared dimension identifiers.
        "driver_id",
        "team_id",
        "session_id",
        "grand_prix_id",
        "circuit_id",
        "season_year",
        # New keys only for derived context / junk dimensions.
        "tyre_context_key",
        "weather_context_key",
        "lap_data_quality_key",
        # Degenerate dimensions.
        "session_type",
        "lap_type",
        "lap_number",
        "track_status_category",
        # Measures.
        "lap_time_ms",
        "sector1_time_ms",
        "sector2_time_ms",
        "sector3_time_ms",
        "speed_i1",
        "speed_i2",
        "speed_fl",
        "speed_st",
        "position",
    ]

    lap = ensure_columns(lap, final_columns)
    fact = lap[final_columns].copy()
    fact = add_surrogate_key(fact, "lap_performance_key")
    return fact

def finalize_session_result_fact(
    result_work: pd.DataFrame,
    dimensions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Build fact_session_result.

    Reused shared dimension identifiers are stored directly in the fact.
    New keys are used only for derived result-specific dimensions.
    session_type is stored directly in the fact as a degenerate dimension.
    """
    result = result_work.copy()
    result = fill_unknown_for_columns(result, ["session_type"])

    result = map_dimension_key(
        result,
        dimensions["dim_result_outcome"],
        ["result_status_category", "result_classification_category"],
        "result_outcome_key",
    )
    result = map_dimension_key(
        result,
        dimensions["dim_result_weather_context"],
        ["rain_flag", "avg_air_temp_class", "avg_track_temp_class", "avg_wind_speed_class"],
        "result_weather_context_key",
    )
    result = map_dimension_key(
        result,
        dimensions["dim_result_data_quality"],
        RESULT_QUALITY_FLAGS,
        "result_data_quality_key",
    )

    final_columns = [
        "result_id",
        # Reused shared dimension identifiers.
        "driver_id",
        "team_id",
        "session_id",
        "grand_prix_id",
        "circuit_id",
        "season_year",
        # New keys only for derived context / junk dimensions.
        "result_outcome_key",
        "result_weather_context_key",
        "result_data_quality_key",
        # Degenerate dimension.
        "session_type",
        # Measures.
        "position",
        "grid_position",
        "q1_ms",
        "q2_ms",
        "q3_ms",
        "gap_to_leader_ms",
        "points",
        "laps",
    ]

    result = ensure_columns(result, final_columns)
    fact = result[final_columns].copy()
    fact = add_surrogate_key(fact, "session_result_key")
    return fact

def build_lap_performance_fact(
    tables: dict[str, pd.DataFrame],
    dimensions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    lap_work = prepare_lap_performance_work(tables, dimensions)
    missing = {
        "dim_tyre_context",
        "dim_weather_context",
        "dim_lap_data_quality",
    } - set(dimensions)
    if missing:
        dimensions.update(build_lap_specific_dimensions(lap_work))
    return finalize_lap_performance_fact(lap_work, dimensions)

def build_session_result_fact(
    tables: dict[str, pd.DataFrame],
    dimensions: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    result_work = prepare_session_result_work(tables, dimensions)
    missing = {
        "dim_result_outcome",
        "dim_result_weather_context",
        "dim_result_data_quality",
    } - set(dimensions)
    if missing:
        dimensions.update(build_result_specific_dimensions(result_work))
    return finalize_session_result_fact(result_work, dimensions)


# ============================================================
# VALIDATION
# ============================================================

def add_issue(
    issues: list[ValidationIssue],
    severity: str,
    table_name: str,
    check_name: str,
    message: str,
    affected_rows: int | None = None,
) -> None:
    issues.append(
        ValidationIssue(
            severity=severity,
            table_name=table_name,
            check_name=check_name,
            message=message,
            affected_rows=affected_rows,
        )
    )


def validate_no_duplicates(
    df: pd.DataFrame,
    table_name: str,
    key_cols: list[str],
    issues: list[ValidationIssue],
) -> None:
    key_cols = existing_columns(df, key_cols)
    if not key_cols:
        add_issue(issues, "ERROR", table_name, "duplicate_key", "No key columns available for duplicate check.")
        return

    duplicated = df.duplicated(subset=key_cols, keep=False)
    if duplicated.any():
        add_issue(
            issues,
            "ERROR",
            table_name,
            "duplicate_key",
            f"Duplicated values found for key columns: {key_cols}",
            int(duplicated.sum()),
        )


def validate_no_missing_keys(
    df: pd.DataFrame,
    table_name: str,
    key_cols: list[str],
    issues: list[ValidationIssue],
) -> None:
    for key_col in key_cols:
        if key_col not in df.columns:
            add_issue(issues, "ERROR", table_name, "missing_key_column", f"Column {key_col} is missing.")
            continue
        missing = df[key_col].isna()
        if missing.any():
            add_issue(
                issues,
                "ERROR",
                table_name,
                "missing_dimension_key",
                f"Column {key_col} contains missing values.",
                int(missing.sum()),
            )


def validate_domain(
    df: pd.DataFrame,
    table_name: str,
    column: str,
    allowed_values: set[object],
    issues: list[ValidationIssue],
    allow_null: bool = False,
) -> None:
    if column not in df.columns:
        add_issue(issues, "WARNING", table_name, "missing_domain_column", f"Column {column} is missing.")
        return

    values = df[column]
    if allow_null:
        values = values.dropna()
    invalid = ~values.isin(allowed_values)
    if invalid.any():
        add_issue(
            issues,
            "ERROR",
            table_name,
            "invalid_domain",
            f"Column {column} contains values outside {sorted(allowed_values)}.",
            int(invalid.sum()),
        )


def validate_row_count(
    source_df: pd.DataFrame,
    output_df: pd.DataFrame,
    source_name: str,
    output_name: str,
    issues: list[ValidationIssue],
) -> None:
    if len(output_df) > len(source_df):
        add_issue(
            issues,
            "ERROR",
            output_name,
            "row_count",
            f"Output has more rows than source {source_name}: {len(output_df)} > {len(source_df)}.",
            len(output_df) - len(source_df),
        )



def validate_outputs(
    tables: dict[str, pd.DataFrame],
    dimensions: dict[str, pd.DataFrame],
    fact_lap_performance: pd.DataFrame,
    fact_session_result: pd.DataFrame,
) -> pd.DataFrame:
    issues: list[ValidationIssue] = []

    # Fact identifier checks.
    validate_no_duplicates(fact_lap_performance, "fact_lap_performance", ["lap_id"], issues)
    validate_no_duplicates(fact_session_result, "fact_session_result", ["result_id"], issues)

    # Shared dimensions reuse existing identifiers. They are therefore checked
    # directly with their original key columns, not with artificial DW keys.
    dimension_keys = {
        "dim_driver": ["driver_id"],
        "dim_team": ["team_id"],
        "dim_season": ["season_year"],
        "dim_circuit": ["circuit_id"],
        "dim_grand_prix": ["grand_prix_id"],
        "dim_session": ["session_id"],
        "dim_tyre_context": ["tyre_context_key"],
        "dim_weather_context": ["weather_context_key"],
        "dim_lap_data_quality": ["lap_data_quality_key"],
        "dim_result_outcome": ["result_outcome_key"],
        "dim_result_weather_context": ["result_weather_context_key"],
        "dim_result_data_quality": ["result_data_quality_key"],
    }
    for table_name, key_cols in dimension_keys.items():
        if table_name in dimensions:
            validate_no_duplicates(dimensions[table_name], table_name, key_cols, issues)
            validate_no_missing_keys(dimensions[table_name], table_name, key_cols, issues)

    # Fact foreign-key columns. Degenerate dimensions are not foreign keys.
    lap_fk_cols = [
        "driver_id",
        "team_id",
        "session_id",
        "grand_prix_id",
        "circuit_id",
        "season_year",
        "tyre_context_key",
        "weather_context_key",
        "lap_data_quality_key",
    ]
    result_fk_cols = [
        "driver_id",
        "team_id",
        "session_id",
        "grand_prix_id",
        "circuit_id",
        "season_year",
        "result_outcome_key",
        "result_weather_context_key",
        "result_data_quality_key",
    ]
    validate_no_missing_keys(fact_lap_performance, "fact_lap_performance", lap_fk_cols, issues)
    validate_no_missing_keys(fact_session_result, "fact_session_result", result_fk_cols, issues)

    # Degenerate dimension domain checks.
    validate_domain(
        fact_lap_performance,
        "fact_lap_performance",
        "session_type",
        {"Q", "R", "Unknown"},
        issues,
    )
    validate_domain(
        fact_session_result,
        "fact_session_result",
        "session_type",
        {"Q", "R", "Unknown"},
        issues,
    )
    validate_domain(
        fact_lap_performance,
        "fact_lap_performance",
        "lap_type",
        {"NormalLap", "OutLap", "InLap", "PitAffectedLap", "Unknown"},
        issues,
    )
    validate_domain(
        fact_lap_performance,
        "fact_lap_performance",
        "track_status_category",
        {"AllClear", "Yellow", "SCDeployed", "VSCDeployed", "VSCEnding", "Red", "Other", "Unknown"},
        issues,
    )

    # Dimension-level domain checks.
    if "dim_weather_context" in dimensions:
        dim = dimensions["dim_weather_context"]
        validate_domain(dim, "dim_weather_context", "air_temp_class", LOW_MEDIUM_HIGH_UNKNOWN, issues)
        validate_domain(dim, "dim_weather_context", "track_temp_class", LOW_MEDIUM_HIGH_UNKNOWN, issues)
        validate_domain(dim, "dim_weather_context", "wind_speed_class", LOW_MEDIUM_HIGH_UNKNOWN, issues)

    if "dim_tyre_context" in dimensions:
        dim = dimensions["dim_tyre_context"]
        validate_domain(dim, "dim_tyre_context", "tyre_life_class", LOW_MEDIUM_HIGH_UNKNOWN, issues)
        validate_domain(
            dim,
            "dim_tyre_context",
            "starting_tyre_set_status",
            {"NewSet", "UsedSet", "Unknown"},
            issues,
        )

    if "dim_result_outcome" in dimensions:
        dim = dimensions["dim_result_outcome"]
        validate_domain(
            dim,
            "dim_result_outcome",
            "result_classification_category",
            {"Classified", "Retired", "Withdrawn", "Disqualified", "Excluded", "NotClassified", "FailedToQualify", "NotApplicable", "Other"},
            issues,
        )
        validate_domain(
            dim,
            "dim_result_outcome",
            "result_status_category",
            {
                "Finished",
                "Lapped",
                "Disqualified",
                "DidNotStart",
                "Accident",
                "Collision",
                "PowerUnitIssue",
                "MechanicalIssue",
                "Retired",
                "Other",
                "NotApplicable",
            },
            issues,
        )

    if "dim_result_weather_context" in dimensions:
        dim = dimensions["dim_result_weather_context"]
        validate_domain(dim, "dim_result_weather_context", "avg_air_temp_class", LOW_MEDIUM_HIGH_UNKNOWN, issues)
        validate_domain(dim, "dim_result_weather_context", "avg_track_temp_class", LOW_MEDIUM_HIGH_UNKNOWN, issues)
        validate_domain(dim, "dim_result_weather_context", "avg_wind_speed_class", LOW_MEDIUM_HIGH_UNKNOWN, issues)

    # Row-count coherence.
    validate_row_count(tables["lap"], fact_lap_performance, "lap", "fact_lap_performance", issues)
    validate_row_count(tables["result"], fact_session_result, "result", "fact_session_result", issues)

    report = pd.DataFrame([issue.__dict__ for issue in issues])
    if report.empty:
        report = pd.DataFrame(
            [
                {
                    "severity": "OK",
                    "table_name": "all",
                    "check_name": "all_checks",
                    "message": "No validation issues found.",
                    "affected_rows": 0,
                }
            ]
        )

    if STRICT_VALIDATION and (report["severity"] == "ERROR").any():
        raise RuntimeError(
            "DW staging validation failed. Check dw_validation_report.csv for details."
        )

    return report

# ============================================================
# EXPORT AND WAREHOUSE LOADING
# ============================================================

def export_csv(df: pd.DataFrame, filename: str) -> None:
    path = OUTPUT_DIR / filename
    df.to_csv(path, index=False)
    print(f"EXPORTED {filename}: {len(df):,} rows")


def build_log(output_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    created_at = now_utc_iso()
    for table_name, df in output_tables.items():
        rows.append(
            {
                "table_name": table_name,
                "row_count": len(df),
                "column_count": len(df.columns),
                "created_at_utc": created_at,
                "status": "created",
            }
        )
    return pd.DataFrame(rows)



def collect_output_tables(
    dimensions: dict[str, pd.DataFrame],
    fact_lap_performance: pd.DataFrame,
    fact_session_result: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    output_tables = {
        **dimensions,
        "fact_lap_performance": fact_lap_performance,
        "fact_session_result": fact_session_result,
    }

    preferred_order = [
        "dim_driver",
        "dim_team",
        "dim_season",
        "dim_circuit",
        "dim_grand_prix",
        "dim_session",
        "dim_tyre_context",
        "dim_weather_context",
        "dim_lap_data_quality",
        "dim_result_outcome",
        "dim_result_weather_context",
        "dim_result_data_quality",
        "fact_lap_performance",
        "fact_session_result",
    ]

    ordered = {name: output_tables[name] for name in preferred_order if name in output_tables}
    for name, df in output_tables.items():
        if name not in ordered:
            ordered[name] = df
    return ordered

def export_csvs(
    output_tables: dict[str, pd.DataFrame],
    validation_report: pd.DataFrame,
) -> None:
    ensure_output_dir()

    for table_name, df in output_tables.items():
        export_csv(df, f"{table_name}.csv")

    log_df = build_log(output_tables)
    export_csv(log_df, "dw_build_log.csv")
    export_csv(validation_report, "dw_validation_report.csv")


def prepare_warehouse_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        if DROP_WAREHOUSE_SCHEMA_BEFORE_LOAD:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {quote_ident(WAREHOUSE_SCHEMA_NAME)} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(WAREHOUSE_SCHEMA_NAME)}"))


def load_tables_to_warehouse(engine: Engine, output_tables: dict[str, pd.DataFrame]) -> None:
    prepare_warehouse_schema(engine)

    with engine.begin() as conn:
        for table_name, df in output_tables.items():
            print(f"LOADING {WAREHOUSE_SCHEMA_NAME}.{table_name}: {len(df):,} rows")
            df.to_sql(
                table_name,
                conn,
                schema=WAREHOUSE_SCHEMA_NAME,
                if_exists="replace",
                index=False,
                method="multi",
                chunksize=1000,
            )

    add_warehouse_constraints(engine)


def constraint_exists(conn, constraint_name: str) -> bool:
    result = conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = :schema_name
                  AND constraint_name = :constraint_name
            )
            """
        ),
        {"schema_name": WAREHOUSE_SCHEMA_NAME, "constraint_name": constraint_name},
    )
    return bool(result.scalar())


def table_exists_in_schema(conn, table_name: str) -> bool:
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
        {"schema_name": WAREHOUSE_SCHEMA_NAME, "table_name": table_name},
    )
    return bool(result.scalar())


def column_exists_in_schema(conn, table_name: str, column_name: str) -> bool:
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
            "schema_name": WAREHOUSE_SCHEMA_NAME,
            "table_name": table_name,
            "column_name": column_name,
        },
    )
    return bool(result.scalar())


def safe_add_constraint(conn, sql: str, constraint_name: str) -> None:
    if constraint_exists(conn, constraint_name):
        return
    try:
        conn.execute(text(sql))
    except Exception as exc:
        print(f"[WARNING] Could not add constraint {constraint_name}: {exc}")


def add_primary_key(conn, table_name: str, key_col: str) -> None:
    if not table_exists_in_schema(conn, table_name) or not column_exists_in_schema(conn, table_name, key_col):
        return
    constraint_name = f"pk_{table_name}"
    safe_add_constraint(
        conn,
        f"ALTER TABLE {quote_ident(WAREHOUSE_SCHEMA_NAME)}.{quote_ident(table_name)} "
        f"ADD CONSTRAINT {quote_ident(constraint_name)} PRIMARY KEY ({quote_ident(key_col)})",
        constraint_name,
    )


def add_foreign_key(conn, child_table: str, child_col: str, parent_table: str, parent_col: str) -> None:
    if not table_exists_in_schema(conn, child_table) or not table_exists_in_schema(conn, parent_table):
        return
    if not column_exists_in_schema(conn, child_table, child_col) or not column_exists_in_schema(conn, parent_table, parent_col):
        return
    constraint_name = f"fk_{child_table}_{child_col}_to_{parent_table}_{parent_col}"
    safe_add_constraint(
        conn,
        f"ALTER TABLE {quote_ident(WAREHOUSE_SCHEMA_NAME)}.{quote_ident(child_table)} "
        f"ADD CONSTRAINT {quote_ident(constraint_name)} "
        f"FOREIGN KEY ({quote_ident(child_col)}) "
        f"REFERENCES {quote_ident(WAREHOUSE_SCHEMA_NAME)}.{quote_ident(parent_table)} ({quote_ident(parent_col)})",
        constraint_name,
    )



def add_warehouse_constraints(engine: Engine) -> None:
    """Add warehouse constraints using reused entity identifiers where possible.

    Original identifiers are used as primary/foreign keys for dimensions already
    present in the reconciled schema. New surrogate keys remain only for derived
    context and junk dimensions.
    """
    primary_keys = {
        # Existing identifiers reused from the reconciled schema.
        "dim_driver": "driver_id",
        "dim_team": "team_id",
        "dim_season": "season_year",
        "dim_circuit": "circuit_id",
        "dim_grand_prix": "grand_prix_id",
        "dim_session": "session_id",
        # New keys only for derived context / junk dimensions.
        "dim_tyre_context": "tyre_context_key",
        "dim_weather_context": "weather_context_key",
        "dim_lap_data_quality": "lap_data_quality_key",
        "dim_result_outcome": "result_outcome_key",
        "dim_result_weather_context": "result_weather_context_key",
        "dim_result_data_quality": "result_data_quality_key",
        # Fact technical identifiers.
        "fact_lap_performance": "lap_performance_key",
        "fact_session_result": "session_result_key",
    }

    fact_lap_fks = {
        "driver_id": ("dim_driver", "driver_id"),
        "team_id": ("dim_team", "team_id"),
        "session_id": ("dim_session", "session_id"),
        "grand_prix_id": ("dim_grand_prix", "grand_prix_id"),
        "circuit_id": ("dim_circuit", "circuit_id"),
        "season_year": ("dim_season", "season_year"),
        "tyre_context_key": ("dim_tyre_context", "tyre_context_key"),
        "weather_context_key": ("dim_weather_context", "weather_context_key"),
        "lap_data_quality_key": ("dim_lap_data_quality", "lap_data_quality_key"),
    }

    fact_result_fks = {
        "driver_id": ("dim_driver", "driver_id"),
        "team_id": ("dim_team", "team_id"),
        "session_id": ("dim_session", "session_id"),
        "grand_prix_id": ("dim_grand_prix", "grand_prix_id"),
        "circuit_id": ("dim_circuit", "circuit_id"),
        "season_year": ("dim_season", "season_year"),
        "result_outcome_key": ("dim_result_outcome", "result_outcome_key"),
        "result_weather_context_key": ("dim_result_weather_context", "result_weather_context_key"),
        "result_data_quality_key": ("dim_result_data_quality", "result_data_quality_key"),
    }

    with engine.begin() as conn:
        for table_name, key_col in primary_keys.items():
            add_primary_key(conn, table_name, key_col)

        # Dimension hierarchy constraints using reused identifiers.
        add_foreign_key(conn, "dim_grand_prix", "season_year", "dim_season", "season_year")
        add_foreign_key(conn, "dim_grand_prix", "circuit_id", "dim_circuit", "circuit_id")
        add_foreign_key(conn, "dim_session", "grand_prix_id", "dim_grand_prix", "grand_prix_id")
        add_foreign_key(conn, "dim_session", "season_year", "dim_season", "season_year")

        for child_col, (parent_table, parent_col) in fact_lap_fks.items():
            add_foreign_key(conn, "fact_lap_performance", child_col, parent_table, parent_col)

        for child_col, (parent_table, parent_col) in fact_result_fks.items():
            add_foreign_key(conn, "fact_session_result", child_col, parent_table, parent_col)

# ============================================================
# MAIN
# ============================================================


def main() -> None:
    print("=== DW STAGING BUILD STARTED ===")
    print(f"Database URL: {DATABASE_URL}")
    print(f"Source schema: {SOURCE_SCHEMA_NAME}")
    print(f"Warehouse schema: {WAREHOUSE_SCHEMA_NAME}")
    print(f"Output directory: {OUTPUT_DIR.resolve()}")

    engine = connect_to_reconciled_db()

    print("\n--- Loading source tables from cleaned reconciled DB ---")
    source_tables = load_source_tables(engine)

    print("\n--- Building shared dimensions ---")
    dimensions = build_shared_dimensions(source_tables)

    for name, df in dimensions.items():
        print(f"BUILT {name}: {len(df):,} rows")

    print("\n--- Preparing fact working tables and derived context dimensions ---")
    lap_work = prepare_lap_performance_work(
        tables=source_tables,
        dimensions=dimensions,
    )
    result_work = prepare_session_result_work(
        tables=source_tables,
        dimensions=dimensions,
    )

    lap_dimensions = build_lap_specific_dimensions(lap_work)
    result_dimensions = build_result_specific_dimensions(result_work)
    dimensions.update(lap_dimensions)
    dimensions.update(result_dimensions)

    for name, df in {**lap_dimensions, **result_dimensions}.items():
        print(f"BUILT {name}: {len(df):,} rows")

    print("\n--- Building fact_lap_performance ---")
    fact_lap_performance = finalize_lap_performance_fact(
        lap_work=lap_work,
        dimensions=dimensions,
    )
    print(f"BUILT fact_lap_performance: {len(fact_lap_performance):,} rows")

    print("\n--- Building fact_session_result ---")
    fact_session_result = finalize_session_result_fact(
        result_work=result_work,
        dimensions=dimensions,
    )
    print(f"BUILT fact_session_result: {len(fact_session_result):,} rows")

    print("\n--- Validating outputs ---")
    validation_report = validate_outputs(
        tables=source_tables,
        dimensions=dimensions,
        fact_lap_performance=fact_lap_performance,
        fact_session_result=fact_session_result,
    )
    print(validation_report)

    output_tables = collect_output_tables(
        dimensions=dimensions,
        fact_lap_performance=fact_lap_performance,
        fact_session_result=fact_session_result,
    )

    if EXPORT_CSVS:
        print("\n--- Exporting CSV files ---")
        export_csvs(
            output_tables=output_tables,
            validation_report=validation_report,
        )

    if LOAD_TO_WAREHOUSE_DB:
        print(f"\n--- Loading tables into PostgreSQL schema {WAREHOUSE_SCHEMA_NAME} ---")
        load_tables_to_warehouse(engine, output_tables)

    print("\nDONE: DW staging CSV files created and warehouse schema loaded.")


if __name__ == "__main__":
    main()
