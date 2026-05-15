from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import re
import sys

import pandas as pd

PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "database").exists():
    raise RuntimeError( "This script must be executed from the project root directory.\n"    )


sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================
# CONFIG
# ============================================================

INPUT_SCHEMA = "reconciled"
OUTPUT_DIR = Path("artifacts") / "03_data_quality" / "03_missing_values"

MISSING_SUMMARY_FILE = OUTPUT_DIR / "focused_missing_summary.csv"
MISSING_ROW_FLAGS_FILE = OUTPUT_DIR / "focused_missing_row_flags.csv"

# If True, the script writes row-level flags also for explained expected nulls
# with missing_information_area = NONE. This can generate many rows, especially
# for pit-related columns.
INCLUDE_EXPLAINED_NONE_ROW_FLAGS = False

RESULT_INFORMATION_AREAS = [
    "NONE",
    "CLASSIFICATION_INFORMATION",
    "QUALIFYING_INFORMATION",
    "RACE_CONTEXT_INFORMATION",
]

LAP_INFORMATION_AREAS = [
    "NONE",
    "LAP_TIME_INFORMATION",
    "SECTOR_INFORMATION",
    "SPEED_INFORMATION",
    "TYRE_INFORMATION",
    "WEATHER_INFORMATION",
    "TRACK_STATUS_INFORMATION",
    "PIT_INFORMATION",
]

ALL_INFORMATION_AREAS = sorted(set(RESULT_INFORMATION_AREAS + LAP_INFORMATION_AREAS))

DERIVED_WEATHER_COLUMNS = [
    "air_temp",
    "track_temp",
    "rainfall",
    "rain_flag",
    "wind_speed",
]


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
class MissingFlag:
    table_name: str
    row_identifier: str
    column_name: str
    missing_class: str
    missing_information_area: str
    explanation: str
    severity: str


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


def is_missing(value: Any) -> bool:
    return pd.isna(value)


def make_row_identifier(row: pd.Series, table_name: str) -> str:
    pk_map = {
        "lap": "lap_id",
        "result": "result_id",
    }

    pk = pk_map.get(table_name)

    if pk and pk in row.index and pd.notna(row[pk]):
        return f"{pk}={row[pk]}"

    return f"row_index={row.name}"


def severity_from_flag(missing_class: str, missing_information_area: str) -> str:
    if missing_information_area == "NONE":
        return "green"

    if missing_class == "EXPLAINED_NULL":
        return "yellow"

    critical_areas = {
        "CLASSIFICATION_INFORMATION",
        "QUALIFYING_INFORMATION",
        "LAP_TIME_INFORMATION",
        "TYRE_INFORMATION",
    }

    if missing_information_area in critical_areas:
        return "red"

    return "yellow"


def add_flag(
    flags: list[MissingFlag],
    table_name: str,
    row: pd.Series,
    column_name: str,
    missing_class: str,
    missing_information_area: str,
    explanation: str,
) -> None:
    if (
        missing_class == "EXPLAINED_NULL"
        and missing_information_area == "NONE"
        and not INCLUDE_EXPLAINED_NONE_ROW_FLAGS
    ):
        return

    flags.append(
        MissingFlag(
            table_name=table_name,
            row_identifier=make_row_identifier(row, table_name),
            column_name=column_name,
            missing_class=missing_class,
            missing_information_area=missing_information_area,
            explanation=explanation,
            severity=severity_from_flag(missing_class, missing_information_area),
        )
    )


def prepare_result_table(result_df: pd.DataFrame, session_df: pd.DataFrame) -> pd.DataFrame:
    result_df = snake_case_columns(result_df)
    session_df = snake_case_columns(session_df)

    if "session_type" not in result_df.columns:
        if not {"session_id", "session_type"}.issubset(set(session_df.columns)):
            raise RuntimeError("session table must contain session_id and session_type.")

        result_df = result_df.merge(
            session_df[["session_id", "session_type"]],
            on="session_id",
            how="left",
        )

    return result_df


# ============================================================
# RESULT TABLE MISSING VALUE LOGIC
# ============================================================

def classify_result_missing_values(result_df: pd.DataFrame) -> list[MissingFlag]:
    flags: list[MissingFlag] = []
    result_df = snake_case_columns(result_df)

    if "session_type" not in result_df.columns:
        raise RuntimeError("result table must contain session_type or must be joined with session table.")

    qualifying_cols = ["q1_ms", "q2_ms", "q3_ms"]
    qualifying_race_context_cols = [
        "classified_position",
        "status",
        "points",
        "laps",
        "time_ms",
        "grid_position",
    ]

    race_context_cols = [
        "grid_position",
        "status",
        "points",
        "laps",
        "time_ms",
    ]

    for _, row in result_df.iterrows():
        session_type = str(row.get("session_type", "")).strip()
        position = pd.to_numeric(row.get("position"), errors="coerce")

        if session_type == "R":
            # Qualifying times are expected nulls in Race sessions.
            for col in qualifying_cols:
                if col in row.index and is_missing(row[col]):
                    add_flag(
                        flags,
                        "result",
                        row,
                        col,
                        "EXPLAINED_NULL",
                        "NONE",
                        f"{col} is not applicable in a Race session.",
                    )

            # Classification information is critical in Race sessions.
            for col in ["position", "classified_position"]:
                if col in row.index and is_missing(row[col]):
                    add_flag(
                        flags,
                        "result",
                        row,
                        col,
                        "SUSPICIOUS_NULL",
                        "CLASSIFICATION_INFORMATION",
                        f"{col} is expected in a Race session and is missing.",
                    )

            # Other race-related attributes are grouped as race context.
            for col in race_context_cols:
                if col in row.index and is_missing(row[col]):
                    add_flag(
                        flags,
                        "result",
                        row,
                        col,
                        "SUSPICIOUS_NULL",
                        "RACE_CONTEXT_INFORMATION",
                        f"{col} is race-context information and is missing in a Race session.",
                    )

        elif session_type == "Q":
            # Position is needed to interpret qualifying progression.
            if "position" in row.index and is_missing(row["position"]):
                add_flag(
                    flags,
                    "result",
                    row,
                    "position",
                    "SUSPICIOUS_NULL",
                    "CLASSIFICATION_INFORMATION",
                    "position is missing in a Qualifying session, so qualifying progression cannot be interpreted reliably.",
                )

            # Race-specific attributes are expected nulls in Qualifying sessions.
            for col in qualifying_race_context_cols:
                if col in row.index and is_missing(row[col]):
                    add_flag(
                        flags,
                        "result",
                        row,
                        col,
                        "EXPLAINED_NULL",
                        "NONE",
                        f"{col} is race-related and is not central in a Qualifying session.",
                    )

            # Q1 should normally be present in a Qualifying session.
            if "q1_ms" in row.index and is_missing(row["q1_ms"]):
                add_flag(
                    flags,
                    "result",
                    row,
                    "q1_ms",
                    "SUSPICIOUS_NULL",
                    "QUALIFYING_INFORMATION",
                    "q1_ms is missing in a Qualifying session.",
                )

            # Q2 is expected to be missing only for positions outside the top 15.
            if "q2_ms" in row.index and is_missing(row["q2_ms"]):
                if pd.notna(position) and position > 15:
                    add_flag(
                        flags,
                        "result",
                        row,
                        "q2_ms",
                        "EXPLAINED_NULL",
                        "NONE",
                        "q2_ms is missing because the driver was classified outside the top 15 and normally did not reach Q2.",
                    )
                else:
                    add_flag(
                        flags,
                        "result",
                        row,
                        "q2_ms",
                        "SUSPICIOUS_NULL",
                        "QUALIFYING_INFORMATION",
                        "q2_ms is missing although the position does not clearly explain elimination before Q2.",
                    )

            # Q3 is expected to be missing only for positions outside the top 10.
            if "q3_ms" in row.index and is_missing(row["q3_ms"]):
                if pd.notna(position) and position > 10:
                    add_flag(
                        flags,
                        "result",
                        row,
                        "q3_ms",
                        "EXPLAINED_NULL",
                        "NONE",
                        "q3_ms is missing because the driver was classified outside the top 10 and normally did not reach Q3.",
                    )
                else:
                    add_flag(
                        flags,
                        "result",
                        row,
                        "q3_ms",
                        "SUSPICIOUS_NULL",
                        "QUALIFYING_INFORMATION",
                        "q3_ms is missing although the position does not clearly explain elimination before Q3.",
                    )

    return flags


# ============================================================
# LAP TABLE MISSING VALUE LOGIC
# ============================================================

def lap_has_pit_in(row: pd.Series) -> bool:
    return "pit_in_time_ms" in row.index and pd.notna(row["pit_in_time_ms"])


def lap_has_pit_out(row: pd.Series) -> bool:
    return "pit_out_time_ms" in row.index and pd.notna(row["pit_out_time_ms"])


def lap_is_deleted(row: pd.Series) -> bool:
    if "deleted" not in row.index:
        return False
    return parse_bool(row["deleted"]) is True


def classify_sector_missing(row: pd.Series, column_name: str) -> tuple[str, str]:
    # Conservative rule from the report:
    # only sector3 missing with pit_in_time_ms is explained by pit entry.
    if column_name == "sector3_time_ms" and lap_has_pit_in(row):
        return (
            "EXPLAINED_NULL",
            "sector3_time_ms is missing and pit_in_time_ms is present, so the lap is an in-lap.",
        )

    return (
        "SUSPICIOUS_NULL",
        f"{column_name} is missing without a direct sector-specific explanation.",
    )


def classify_speed_missing(row: pd.Series, column_name: str) -> tuple[str, str]:
    # Conservative rule from the report:
    # pit information explains only selected speed attributes.
    pit_explainable_speeds = {"speed_i1", "speed_fl", "speed_st"}

    if column_name in pit_explainable_speeds and (lap_has_pit_in(row) or lap_has_pit_out(row)):
        return (
            "EXPLAINED_NULL",
            f"{column_name} is missing and pit information is present.",
        )

    return (
        "SUSPICIOUS_NULL",
        f"{column_name} is missing without a direct pit-related explanation.",
    )


def classify_lap_missing_values(lap_df: pd.DataFrame) -> list[MissingFlag]:
    flags: list[MissingFlag] = []
    lap_df = snake_case_columns(lap_df)

    for _, row in lap_df.iterrows():
        # Pit timestamps are normally null when the lap is not an in-lap/out-lap.
        for col, explanation in {
            "pit_in_time_ms": "pit_in_time_ms is missing because the lap is treated as not being an in-lap.",
            "pit_out_time_ms": "pit_out_time_ms is missing because the lap is treated as not being an out-lap.",
        }.items():
            if col in row.index and is_missing(row[col]):
                add_flag(flags, "lap", row, col, "EXPLAINED_NULL", "NONE", explanation)

        # deleted_reason is expected to be null when the lap is not deleted.
        if "deleted_reason" in row.index and is_missing(row["deleted_reason"]) and not lap_is_deleted(row):
            add_flag(
                flags,
                "lap",
                row,
                "deleted_reason",
                "EXPLAINED_NULL",
                "NONE",
                "deleted_reason is missing because deleted = false.",
            )

        # Core lap time information.
        # The revised report does not use pit information or is_accurate as an automatic explanation.
        if "lap_time_ms" in row.index and is_missing(row["lap_time_ms"]):
            add_flag(
                flags,
                "lap",
                row,
                "lap_time_ms",
                "SUSPICIOUS_NULL",
                "LAP_TIME_INFORMATION",
                "lap_time_ms is missing, so the row lacks the main lap time information.",
            )

        # Sector information.
        for col in ["sector1_time_ms", "sector2_time_ms", "sector3_time_ms"]:
            if col in row.index and is_missing(row[col]):
                missing_class, explanation = classify_sector_missing(row, col)
                add_flag(flags, "lap", row, col, missing_class, "SECTOR_INFORMATION", explanation)

        # Speed information.
        for col in ["speed_i1", "speed_i2", "speed_fl", "speed_st"]:
            if col in row.index and is_missing(row[col]):
                missing_class, explanation = classify_speed_missing(row, col)
                add_flag(flags, "lap", row, col, missing_class, "SPEED_INFORMATION", explanation)

        # Tyre information.
        if "compound" in row.index and is_missing(row["compound"]):
            add_flag(
                flags,
                "lap",
                row,
                "compound",
                "SUSPICIOUS_NULL",
                "TYRE_INFORMATION",
                "compound is missing, so tyre information is incomplete.",
            )

        if "tyre_life" in row.index and is_missing(row["tyre_life"]):
            add_flag(
                flags,
                "lap",
                row,
                "tyre_life",
                "SUSPICIOUS_NULL",
                "TYRE_INFORMATION",
                "tyre_life is missing, so tyre degradation information is incomplete.",
            )

        # Track status information.
        if "track_status" in row.index and is_missing(row["track_status"]):
            add_flag(
                flags,
                "lap",
                row,
                "track_status",
                "SUSPICIOUS_NULL",
                "TRACK_STATUS_INFORMATION",
                "track_status is missing, so track condition information is incomplete.",
            )

        # Optional future derived weather attributes, if they exist in the lap table.
        for col in DERIVED_WEATHER_COLUMNS:
            if col in row.index and is_missing(row[col]):
                add_flag(
                    flags,
                    "lap",
                    row,
                    col,
                    "SUSPICIOUS_NULL",
                    "WEATHER_INFORMATION",
                    f"{col} is missing, so weather context information is incomplete.",
                )

    return flags


# ============================================================
# SUMMARY
# ============================================================

def build_missing_summary(flags_df: pd.DataFrame, table_sizes: dict[str, int]) -> pd.DataFrame:
    base_columns = [
        "table_name",
        "column_name",
        "total_rows",
        "missing_count",
        "missing_percentage",
        "explained_null_count",
        "suspicious_null_count",
        "main_missing_class",
        "main_missing_information_area",
    ]

    area_columns = [f"{area.lower()}_count" for area in ALL_INFORMATION_AREAS]
    columns = base_columns + area_columns

    if flags_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    for (table_name, column_name), group in flags_df.groupby(["table_name", "column_name"], dropna=False):
        total_rows = table_sizes.get(table_name, 0)
        missing_count = int(len(group))

        class_counts = group["missing_class"].value_counts()
        area_counts = group["missing_information_area"].value_counts()

        row = {
            "table_name": table_name,
            "column_name": column_name,
            "total_rows": total_rows,
            "missing_count": missing_count,
            "missing_percentage": round(missing_count / total_rows, 6) if total_rows else None,
            "explained_null_count": int(class_counts.get("EXPLAINED_NULL", 0)),
            "suspicious_null_count": int(class_counts.get("SUSPICIOUS_NULL", 0)),
            "main_missing_class": class_counts.idxmax() if not class_counts.empty else None,
            "main_missing_information_area": area_counts.idxmax() if not area_counts.empty else None,
        }

        for area in ALL_INFORMATION_AREAS:
            row[f"{area.lower()}_count"] = int(area_counts.get(area, 0))

        rows.append(row)

    return pd.DataFrame(rows)[columns].sort_values(["table_name", "column_name"]).reset_index(drop=True)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    engine, schema = get_engine_and_schema(INPUT_SCHEMA)

    lap_df = snake_case_columns(read_table("lap", engine, schema))
    result_df = read_table("result", engine, schema)
    session_df = read_table("session", engine, schema)
    result_df = prepare_result_table(result_df, session_df)

    flags: list[MissingFlag] = []
    flags.extend(classify_result_missing_values(result_df))
    flags.extend(classify_lap_missing_values(lap_df))

    flags_df = pd.DataFrame([asdict(flag) for flag in flags])

    if flags_df.empty:
        flags_df = pd.DataFrame(
            columns=[
                "table_name",
                "row_identifier",
                "column_name",
                "missing_class",
                "missing_information_area",
                "explanation",
                "severity",
            ]
        )

    table_sizes = {
        "lap": len(lap_df),
        "result": len(result_df),
    }

    summary_df = build_missing_summary(flags_df, table_sizes)

    flags_df.to_csv(MISSING_ROW_FLAGS_FILE, index=False)
    summary_df.to_csv(MISSING_SUMMARY_FILE, index=False)

    print(f"Missing row flags written to: {MISSING_ROW_FLAGS_FILE}")
    print(f"Missing summary written to: {MISSING_SUMMARY_FILE}")


if __name__ == "__main__":
    main()
