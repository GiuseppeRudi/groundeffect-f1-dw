from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import re

import sys
import numpy as np
import pandas as pd



PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "database").exists():
    raise RuntimeError( "This script must be executed from the project root directory.\n"    )


sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# CONFIG
# ============================================================

INPUT_SCHEMA = "reconciled"
OUTPUT_DIR = Path("artifacts") / "03_data_quality" / "04_outlier_detection"

LAP_OUTLIER_FLAGS_FILE = OUTPUT_DIR / "lap_outlier_flags.csv"
OUTLIER_SUMMARY_FILE = OUTPUT_DIR / "outlier_summary.csv"

METRICS = [
    "lap_time_ms",
    "sector1_time_ms",
    "sector2_time_ms",
    "sector3_time_ms",
    "speed_i1",
    "speed_i2",
    "speed_fl",
    "speed_st",
]

MIN_GROUP_SIZE = 10
IQR_K = 1.5
MODIFIED_Z_THRESHOLD = 3.5


# ============================================================
# DATABASE HELPERS
# ============================================================

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(identifier: str) -> str:
    if not isinstance(identifier, str) or not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")
    return identifier


def get_engine_and_schema(schema: str):
    """
    Uses database_utils.get_engine.

    Expected behavior:
        engine, schema_name = get_engine("reconciled")

    The fallback supports older versions where get_engine returns only the engine.
    """
    from database.db_config import get_engine

    result = get_engine(schema)

    if isinstance(result, tuple):
        return result

    return result, schema


def read_table(table_name: str, engine, schema: str) -> pd.DataFrame:
    table_name = validate_identifier(table_name)
    schema = validate_identifier(schema)
    query = f'SELECT * FROM "{schema}"."{table_name}"'
    return pd.read_sql_query(query, engine)


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class OutlierFlag:
    table_name: str
    row_identifier: str
    session_id: Any
    metric: str
    value: float
    iqr_flag: bool
    modified_z_flag: bool
    consensus_score: int
    interpretation: str
    q1: float | None
    q3: float | None
    iqr_lower_bound: float | None
    iqr_upper_bound: float | None
    median: float | None
    mad: float | None
    modified_z_score: float | None


# ============================================================
# GENERIC HELPERS
# ============================================================

def snake_case_columns(df: pd.DataFrame) -> pd.DataFrame:
    def to_snake(name: str) -> str:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", str(name)).lower()
        return re.sub(r"_+", "_", name).strip("_")

    out = df.copy()
    out.columns = [to_snake(c) for c in out.columns]
    return out


def parse_bool(value: Any) -> bool | None:
    if pd.isna(value):
        return None

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"true", "1", "t", "yes", "y"}:
        return True

    if text in {"false", "0", "f", "no", "n"}:
        return False

    return None


def numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def make_row_identifier(row: pd.Series) -> str:
    if "lap_id" in row.index and pd.notna(row["lap_id"]):
        return f"lap_id={row['lap_id']}"

    return f"row_index={row.name}"


def is_track_all_clear(value: Any) -> bool:
    if pd.isna(value):
        return False

    text = str(value).strip()
    return text in {"1", "1.0"}


# ============================================================
# DRY SESSION SELECTION
# ============================================================

def dry_sessions_from_weather(weather_df: pd.DataFrame) -> set[Any]:
    weather_df = snake_case_columns(weather_df)

    if not {"session_id", "rainfall"}.issubset(set(weather_df.columns)):
        raise RuntimeError("weather table must contain session_id and rainfall.")

    tmp = weather_df[["session_id", "rainfall"]].copy()
    tmp["rainfall_bool"] = tmp["rainfall"].apply(parse_bool)

    # Conservative rule from the report:
    # a session is dry only if no weather observation has rainfall = true.
    session_rain = (
        tmp.groupby("session_id")["rainfall_bool"]
        .apply(lambda s: bool((s == True).any()))
        .reset_index(name="has_rain")
    )

    dry = session_rain.loc[~session_rain["has_rain"], "session_id"]
    return set(dry.tolist())


# ============================================================
# CLEAN LAP SELECTION
# ============================================================

def select_clean_laps(
    lap_df: pd.DataFrame,
    dry_session_ids: set[Any],
    race_session_ids: set[Any],
) -> pd.DataFrame:
    lap_df = snake_case_columns(lap_df).copy()

    required = {
        "session_id",
        "lap_time_ms",
        "compound",
        "pit_in_time_ms",
        "pit_out_time_ms",
        "track_status",
    }

    missing = required - set(lap_df.columns)

    if missing:
        raise RuntimeError(f"lap table is missing required columns for outlier filtering: {missing}")

    lap_df["lap_time_ms"] = numeric_series(lap_df["lap_time_ms"])
    lap_df["track_all_clear"] = lap_df["track_status"].apply(is_track_all_clear)

    mask = (
    lap_df["lap_time_ms"].notna()
    & lap_df["compound"].notna()
    & lap_df["pit_in_time_ms"].isna()
    & lap_df["pit_out_time_ms"].isna()
    & lap_df["track_all_clear"].eq(True)
    & lap_df["session_id"].isin(dry_session_ids)
    & lap_df["session_id"].isin(race_session_ids)
    )

    return lap_df.loc[mask].copy()


# ============================================================
# OUTLIER METHODS
# ============================================================

def compute_iqr_flags(values: pd.Series) -> tuple[pd.Series, float | None, float | None, float | None, float | None]:
    values = numeric_series(values)

    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1

    if pd.isna(iqr) or iqr == 0:
        flags = pd.Series(False, index=values.index)
        return flags, None, None, None, None

    lower = q1 - IQR_K * iqr
    upper = q3 + IQR_K * iqr
    flags = (values < lower) | (values > upper)

    return flags.fillna(False), float(q1), float(q3), float(lower), float(upper)


def compute_modified_z_flags(values: pd.Series) -> tuple[pd.Series, pd.Series, float | None, float | None]:
    values = numeric_series(values)

    median = values.median()
    mad = (values - median).abs().median()

    if pd.isna(mad) or mad == 0:
        flags = pd.Series(False, index=values.index)
        z_scores = pd.Series(np.nan, index=values.index)
        return flags, z_scores, None, None

    z_scores = 0.6745 * (values - median) / mad
    flags = z_scores.abs() > MODIFIED_Z_THRESHOLD

    return flags.fillna(False), z_scores, float(median), float(mad)


def interpretation_from_consensus(score: int) -> str:
    if score >= 2:
        return "STRONG_CONSENSUS_OUTLIER"

    if score == 1:
        return "WEAK_ANOMALY"

    return "NORMAL"


# ============================================================
# LAP OUTLIER DETECTION
# ============================================================


def race_sessions_from_session(session_df: pd.DataFrame) -> set[Any]:
    session_df = snake_case_columns(session_df)

    if not {"session_id", "session_type"}.issubset(set(session_df.columns)):
        raise RuntimeError("session table must contain session_id and session_type.")

    race_sessions = session_df.loc[
        session_df["session_type"].astype("string").str.strip().eq("R"),
        "session_id",
    ]

    return set(race_sessions.tolist())

def detect_lap_outliers(clean_laps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    flags: list[OutlierFlag] = []
    summary_rows: list[dict[str, Any]] = []

    available_metrics = [metric for metric in METRICS if metric in clean_laps.columns]

    for session_id, session_df in clean_laps.groupby("session_id"):
        for metric in available_metrics:
            metric_values = numeric_series(session_df[metric]).dropna()
            tested_values = int(len(metric_values))

            if tested_values < MIN_GROUP_SIZE:
                summary_rows.append(
                    {
                        "table_name": "lap",
                        "session_id": session_id,
                        "metric": metric,
                        "tested_values": tested_values,
                        "iqr_outliers": 0,
                        "modified_z_outliers": 0,
                        "consensus_outliers": 0,
                        "status": "skipped_too_few_values",
                    }
                )
                continue

            iqr_flags, q1, q3, lower, upper = compute_iqr_flags(metric_values)
            z_flags, z_scores, median, mad = compute_modified_z_flags(metric_values)

            consensus = iqr_flags.astype(int) + z_flags.astype(int)
            flagged_indices = metric_values.index[consensus > 0]

            for idx in flagged_indices:
                row = clean_laps.loc[idx]
                consensus_score = int(consensus.loc[idx])

                flags.append(
                    OutlierFlag(
                        table_name="lap",
                        row_identifier=make_row_identifier(row),
                        session_id=session_id,
                        metric=metric,
                        value=float(metric_values.loc[idx]),
                        iqr_flag=bool(iqr_flags.loc[idx]),
                        modified_z_flag=bool(z_flags.loc[idx]),
                        consensus_score=consensus_score,
                        interpretation=interpretation_from_consensus(consensus_score),
                        q1=q1,
                        q3=q3,
                        iqr_lower_bound=lower,
                        iqr_upper_bound=upper,
                        median=median,
                        mad=mad,
                        modified_z_score=float(z_scores.loc[idx]) if pd.notna(z_scores.loc[idx]) else None,
                    )
                )

            summary_rows.append(
                {
                    "table_name": "lap",
                    "session_id": session_id,
                    "metric": metric,
                    "tested_values": tested_values,
                    "iqr_outliers": int(iqr_flags.sum()),
                    "modified_z_outliers": int(z_flags.sum()),
                    "consensus_outliers": int((consensus >= 2).sum()),
                    "status": "completed",
                }
            )

    flags_df = pd.DataFrame([asdict(flag) for flag in flags])

    if flags_df.empty:
        flags_df = pd.DataFrame(
            columns=[
                "table_name",
                "row_identifier",
                "session_id",
                "metric",
                "value",
                "iqr_flag",
                "modified_z_flag",
                "consensus_score",
                "interpretation",
                "q1",
                "q3",
                "iqr_lower_bound",
                "iqr_upper_bound",
                "median",
                "mad",
                "modified_z_score",
            ]
        )

    summary_df = pd.DataFrame(summary_rows)
    return flags_df, summary_df


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    engine, schema = get_engine_and_schema(INPUT_SCHEMA)

    lap_df = snake_case_columns(read_table("lap", engine, schema))
    weather_df = snake_case_columns(read_table("weather", engine, schema))
    session_df = snake_case_columns(read_table("session", engine, schema))

    dry_session_ids = dry_sessions_from_weather(weather_df)
    race_session_ids = race_sessions_from_session(session_df)

    clean_laps = select_clean_laps(
        lap_df,
        dry_session_ids=dry_session_ids,
        race_session_ids=race_session_ids,
    )

    flags_df, summary_df = detect_lap_outliers(clean_laps)

    flags_df.to_csv(LAP_OUTLIER_FLAGS_FILE, index=False)
    summary_df.to_csv(OUTLIER_SUMMARY_FILE, index=False)

    print(f"Race sessions available: {len(race_session_ids)}")
    print(f"Dry sessions available: {len(dry_session_ids)}")
    print(f"Clean race candidate laps used for outlier detection: {len(clean_laps)}")
    print(f"Lap outlier flags written to: {LAP_OUTLIER_FLAGS_FILE}")
    print(f"Outlier summary written to: {OUTLIER_SUMMARY_FILE}")

if __name__ == "__main__":
    main()
