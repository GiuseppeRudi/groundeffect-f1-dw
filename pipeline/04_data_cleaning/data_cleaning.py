from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import importlib.util
import json
import re
import sys
from time import perf_counter

import pandas as pd
from sqlalchemy import text


# ============================================================
# PROJECT PATH
# ============================================================

PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "database").exists():
    raise RuntimeError(
        "This script must be executed from the project root directory.\n"
        "The project root must contain the database/ package."
    )

sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# CONFIG
# ============================================================

INPUT_SCHEMA = "reconciled"
OUTPUT_SCHEMA = "reconciled_clean"

DROP_OUTPUT_SCHEMA_BEFORE_LOAD = True
RUN_POST_CLEANING_DQA_COMPARISON = False

OUTPUT_DIR = Path("artifacts") / "04_data_cleaning"
CLEANED_TABLES_DIR = OUTPUT_DIR / "cleaned_tables"

CLEANING_ACTION_LOG_FILE = OUTPUT_DIR / "cleaning_action_log.csv"
CLEANING_SUMMARY_BY_TABLE_FILE = OUTPUT_DIR / "cleaning_summary_by_table.csv"
CLEANING_SUMMARY_BY_DECISION_FILE = OUTPUT_DIR / "cleaning_summary_by_decision.csv"
REJECTED_ROWS_FILE = OUTPUT_DIR / "rejected_rows.csv"
BEFORE_AFTER_SCORECARD_FILE = OUTPUT_DIR / "before_after_scorecard.csv"

DQA_ISSUE_CANDIDATES = [
    Path("artifacts") / "03_data_quality" / "01_dqa" / "issues" / "issues_all_tables.csv",
]

MISSING_FLAGS_CANDIDATES = [
    Path("artifacts") / "03_data_quality" / "03_missing_values" / "focused_missing_row_flags.csv",
]

OUTLIER_FLAGS_CANDIDATES = [
    Path("artifacts") / "03_data_quality" / "04_outlier_detection" / "lap_outlier_flags.csv",
]

TABLE_ORDER = [
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

PRIMARY_KEYS: dict[str, list[str]] = {
    "season": ["season_year"],
    "circuit": ["circuit_id"],
    "driver": ["driver_id"],
    "team": ["team_id"],
    "grand_prix": ["grand_prix_id"],
    "session": ["session_id"],
    "result": ["result_id"],
    "lap": ["lap_id"],
    "weather": ["weather_id"],
    "track_status": ["track_status_id"],
}

FOREIGN_KEYS: dict[str, list[tuple[str, str, str]]] = {
    "grand_prix": [
        ("season_year", "season", "season_year"),
        ("circuit_id", "circuit", "circuit_id"),
    ],
    "session": [
        ("grand_prix_id", "grand_prix", "grand_prix_id"),
    ],
    "result": [
        ("session_id", "session", "session_id"),
        ("driver_id", "driver", "driver_id"),
        ("team_id", "team", "team_id"),
    ],
    "lap": [
        ("session_id", "session", "session_id"),
        ("driver_id", "driver", "driver_id"),
        ("team_id", "team", "team_id"),
    ],
    "weather": [
        ("session_id", "session", "session_id"),
    ],
    "track_status": [
        ("session_id", "session", "session_id"),
    ],
}

GLOBAL_CIRCUIT_CATEGORIES = {"Street", "PowerSensitive", "AeroSensitive", "Mixed"}
SECTOR_CATEGORIES = {"Power", "FastCorners", "SlowCorners", "Technical"}
SESSION_TYPES = {"Q", "R"}
EVENT_FORMATS = {"conventional", "sprint"}
TYRE_COMPOUNDS = {"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"}

TRACK_STATUS_MAPPING = {
    1: "AllClear",
    2: "Yellow",
    4: "SCDeployed",
    5: "Red",
    6: "VSCDeployed",
    7: "VSCEnding",
}

VALID_MISSING_INFORMATION_AREAS = {
    "NONE",
    "LAP_TIME_INFORMATION",
    "SECTOR_INFORMATION",
    "SPEED_INFORMATION",
    "TYRE_INFORMATION",
    "WEATHER_INFORMATION",
    "TRACK_STATUS_INFORMATION",
    "PIT_INFORMATION",
    "CLASSIFICATION_INFORMATION",
    "QUALIFYING_INFORMATION",
    "RACE_CONTEXT_INFORMATION",
}

SECTOR_METRICS = {"sector1_time_ms", "sector2_time_ms", "sector3_time_ms"}
SPEED_METRICS = {"speed_i1", "speed_i2", "speed_fl", "speed_st"}


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class CleaningAction:
    source: str
    table_name: str
    row_identifier: str | None
    target_column: str | None
    check_id: str | None
    issue_code: str | None
    missing_class: str | None
    missing_information_area: str | None
    outlier_metric: str | None
    outlier_consensus_score: int | None
    cleaning_action: str
    old_value: str | None
    new_value: str | None
    reason: str


@dataclass
class RejectedRow:
    table_name: str
    row_identifier: str
    reasons: str
    row_data_json: str


# ============================================================
# DATABASE HELPERS
# ============================================================

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(identifier: str) -> str:
    if not isinstance(identifier, str) or not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")
    return identifier


def get_engine_and_schema(schema: str):
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


def prepare_output_schema(engine, schema: str) -> None:
    schema = validate_identifier(schema)

    with engine.begin() as conn:
        if DROP_OUTPUT_SCHEMA_BEFORE_LOAD:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def write_tables_to_schema(tables: dict[str, pd.DataFrame], engine, schema: str) -> None:
    for table_name in TABLE_ORDER:
        if table_name not in tables:
            continue

        df = tables[table_name].copy()

        df.to_sql(
            table_name,
            engine,
            schema=schema,
            if_exists="replace",
            index=False,
            method="multi",
            chunksize=1000,
        )


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


def find_first_existing(candidates: list[Path]) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


def read_csv_optional(candidates: list[Path], required: bool, name: str) -> pd.DataFrame:
    path = find_first_existing(candidates)

    if path is None:
        if required:
            raise FileNotFoundError(
                f"Could not find {name}. Tried: "
                + ", ".join(str(p) for p in candidates)
            )

        print(f"[WARNING] {name} not found. This input will be skipped.")
        return pd.DataFrame()

    print(f"Reading {name}: {path}")
    return pd.read_csv(path)


def serialize_value(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    return str(value)


def normalize_for_compare(value: Any) -> str:
    if pd.isna(value):
        return "__NA__"

    text_value = str(value).strip()

    try:
        numeric = float(text_value)

        if numeric.is_integer():
            return str(int(numeric))

        return str(numeric)

    except Exception:
        return text_value


def row_identifier_for_row(table_name: str, row: pd.Series, fallback_index: Any) -> str:
    pk = PRIMARY_KEYS.get(table_name, [])

    if pk and all(col in row.index for col in pk) and all(pd.notna(row[col]) for col in pk):
        return ";".join(f"{col}={row[col]}" for col in pk)

    return f"row_index={fallback_index}"


def internal_row_id_for_row(table_name: str, row: pd.Series, fallback_index: Any) -> str:
    pk = PRIMARY_KEYS.get(table_name, [])

    if pk and all(col in row.index for col in pk) and all(pd.notna(row[col]) for col in pk):
        return ";".join(
            f"{col}={normalize_for_compare(row[col])}"
            for col in pk
        )

    return f"row_index={fallback_index}"


def parse_row_identifier(row_identifier: Any) -> dict[str, str] | None:
    if pd.isna(row_identifier):
        return None

    text_id = str(row_identifier).strip()

    if text_id in {"", "__table__"}:
        return None

    if text_id.startswith("row_index="):
        return {"__row_index__": text_id.split("=", 1)[1]}

    parts = text_id.split(";")
    parsed: dict[str, str] = {}

    for part in parts:
        if "=" not in part:
            return None

        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()

    return parsed


def canonicalize_row_identifier(row_identifier: Any) -> str | None:
    parsed = parse_row_identifier(row_identifier)

    if not parsed:
        return None

    if "__row_index__" in parsed:
        try:
            idx = int(float(parsed["__row_index__"]))
            return f"row_index={idx}"
        except Exception:
            return None

    return ";".join(
        f"{col}={normalize_for_compare(value)}"
        for col, value in parsed.items()
    )


def mask_from_row_identifier(df: pd.DataFrame, row_identifier: Any) -> pd.Series:
    parsed = parse_row_identifier(row_identifier)
    mask = pd.Series(False, index=df.index)

    if not parsed:
        return mask

    if "__row_index__" in parsed:
        try:
            idx = int(float(parsed["__row_index__"]))
        except Exception:
            return mask

        if idx in df.index:
            mask.loc[idx] = True

        return mask

    mask = pd.Series(True, index=df.index)

    for col, raw_value in parsed.items():
        if col not in df.columns:
            return pd.Series(False, index=df.index)

        wanted = normalize_for_compare(raw_value)
        mask = mask & df[col].apply(normalize_for_compare).eq(wanted)

    return mask.fillna(False)


def add_internal_row_ids(tables: dict[str, pd.DataFrame]) -> None:
    for table_name, df in tables.items():
        df["_clean_row_id"] = [
            internal_row_id_for_row(table_name, row, idx)
            for idx, row in df.iterrows()
        ]


def remove_internal_row_ids(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    cleaned: dict[str, pd.DataFrame] = {}

    for table_name, df in tables.items():
        out = df.copy()

        if "_clean_row_id" in out.columns:
            out = out.drop(columns=["_clean_row_id"])

        cleaned[table_name] = out

    return cleaned


def normalize_area_list(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []

    text_value = str(value).strip()

    if text_value in {"", "NONE"}:
        return []

    return [
        item.strip()
        for item in text_value.split("|")
        if item.strip() and item.strip() != "NONE"
    ]


def append_log(
    actions: list[CleaningAction],
    *,
    source: str,
    table_name: str,
    row_identifier: str | None,
    target_column: str | None,
    check_id: str | None,
    issue_code: str | None,
    missing_class: str | None = None,
    missing_information_area: str | None = None,
    outlier_metric: str | None = None,
    outlier_consensus_score: int | None = None,
    cleaning_action: str,
    old_value: Any = None,
    new_value: Any = None,
    reason: str,
) -> None:
    actions.append(
        CleaningAction(
            source=source,
            table_name=table_name,
            row_identifier=row_identifier,
            target_column=target_column,
            check_id=check_id,
            issue_code=issue_code,
            missing_class=missing_class,
            missing_information_area=missing_information_area,
            outlier_metric=outlier_metric,
            outlier_consensus_score=outlier_consensus_score,
            cleaning_action=cleaning_action,
            old_value=serialize_value(old_value),
            new_value=serialize_value(new_value),
            reason=reason,
        )
    )


def mark_rows_to_drop(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
    table_name: str,
    mask: pd.Series,
    *,
    source: str,
    row_identifier: str | None,
    check_id: str | None,
    issue_code: str | None,
    missing_class: str | None = None,
    missing_information_area: str | None = None,
    outlier_metric: str | None = None,
    outlier_consensus_score: int | None = None,
    reason: str,
) -> None:
    if table_name not in tables:
        return

    df = tables[table_name]

    if table_name not in drop_masks:
        drop_masks[table_name] = pd.Series(False, index=df.index)

    current_drop_mask = drop_masks[table_name]
    new_drop_mask = mask & ~current_drop_mask

    if not new_drop_mask.any():
        return

    for idx in df.loc[new_drop_mask].index:
        drop_masks[table_name].loc[idx] = True

        append_log(
            actions,
            source=source,
            table_name=table_name,
            row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
            target_column=None,
            check_id=check_id,
            issue_code=issue_code,
            missing_class=missing_class,
            missing_information_area=missing_information_area,
            outlier_metric=outlier_metric,
            outlier_consensus_score=outlier_consensus_score,
            cleaning_action="DROP_ROW",
            old_value=None,
            new_value=None,
            reason=reason,
        )


def add_information_area_to_rows(
    tables: dict[str, pd.DataFrame],
    actions: list[CleaningAction],
    table_name: str,
    mask: pd.Series,
    area: str,
    *,
    source: str,
    row_identifier: str | None,
    target_column: str | None,
    check_id: str | None,
    issue_code: str | None,
    missing_class: str | None = None,
    outlier_metric: str | None = None,
    outlier_consensus_score: int | None = None,
    reason: str,
) -> None:
    if area not in VALID_MISSING_INFORMATION_AREAS or area == "NONE":
        return

    if table_name not in {"lap", "result"}:
        return

    if table_name not in tables:
        return

    df = tables[table_name]

    if "missing_information_areas" not in df.columns:
        df["missing_information_areas"] = "NONE"

    for idx in df.loc[mask].index:
        old_value = df.at[idx, "missing_information_areas"]
        areas = normalize_area_list(old_value)

        if area not in areas:
            areas.append(area)

        new_value = "|".join(sorted(areas)) if areas else "NONE"

        if new_value == old_value:
            continue

        df.at[idx, "missing_information_areas"] = new_value

        append_log(
            actions,
            source=source,
            table_name=table_name,
            row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
            target_column=target_column,
            check_id=check_id,
            issue_code=issue_code,
            missing_class=missing_class,
            missing_information_area=area,
            outlier_metric=outlier_metric,
            outlier_consensus_score=outlier_consensus_score,
            cleaning_action="ADD_FLAG",
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )


def set_columns_null(
    tables: dict[str, pd.DataFrame],
    actions: list[CleaningAction],
    table_name: str,
    mask: pd.Series,
    columns: list[str],
    *,
    source: str,
    row_identifier: str | None,
    check_id: str | None,
    issue_code: str | None,
    reason: str,
    flag_area: str | None = None,
) -> None:
    df = tables[table_name]

    for col in columns:
        if col not in df.columns:
            continue

        affected = mask & df[col].notna()

        for idx in df.loc[affected].index:
            old_value = df.at[idx, col]
            df.at[idx, col] = pd.NA

            rid = row_identifier_for_row(table_name, df.loc[idx], idx)

            append_log(
                actions,
                source=source,
                table_name=table_name,
                row_identifier=rid,
                target_column=col,
                check_id=check_id,
                issue_code=issue_code,
                cleaning_action="SET_NULL",
                old_value=old_value,
                new_value=None,
                reason=reason,
            )

            if flag_area is not None:
                single_mask = pd.Series(False, index=df.index)
                single_mask.loc[idx] = True

                add_information_area_to_rows(
                    tables,
                    actions,
                    table_name,
                    single_mask,
                    flag_area,
                    source=source,
                    row_identifier=rid,
                    target_column=col,
                    check_id=check_id,
                    issue_code=issue_code,
                    reason=f"{flag_area} is affected after setting an invalid value to NULL.",
                )


def invalid_numeric_columns(
    df: pd.DataFrame,
    mask: pd.Series,
    columns: list[str],
    min_value=None,
    max_value=None,
) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}

    for col in columns:
        if col not in df.columns:
            continue

        num = pd.to_numeric(df[col], errors="coerce")
        invalid = mask & df[col].notna() & num.isna()

        if min_value is not None:
            invalid = invalid | (mask & df[col].notna() & (num < min_value))

        if max_value is not None:
            invalid = invalid | (mask & df[col].notna() & (num > max_value))

        out[col] = invalid.fillna(False)

    return out


def standardize_value(
    tables: dict[str, pd.DataFrame],
    actions: list[CleaningAction],
    table_name: str,
    idx: Any,
    col: str,
    new_value: Any,
    *,
    source: str,
    check_id: str | None,
    issue_code: str | None,
    reason: str,
) -> None:
    df = tables[table_name]
    old_value = df.at[idx, col]

    if normalize_for_compare(old_value) == normalize_for_compare(new_value):
        return

    df.at[idx, col] = new_value

    append_log(
        actions,
        source=source,
        table_name=table_name,
        row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
        target_column=col,
        check_id=check_id,
        issue_code=issue_code,
        cleaning_action="STANDARDIZE",
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    )


def canonical_map(values: set[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for value in values:
        key = re.sub(r"[^a-z0-9]", "", value.lower())
        mapping[key] = value

    return mapping


# ============================================================
# GENERAL CLEANING
# ============================================================

def apply_general_cleaning(
    tables: dict[str, pd.DataFrame],
    actions: list[CleaningAction],
) -> None:
    for table_name, df in tables.items():
        for col in df.columns:
            if not (
                pd.api.types.is_object_dtype(df[col])
                or pd.api.types.is_string_dtype(df[col])
            ):
                continue

            for idx, value in df[col].items():
                if not isinstance(value, str):
                    continue

                trimmed = value.strip()

                if trimmed != value:
                    old_value = value
                    df.at[idx, col] = trimmed

                    append_log(
                        actions,
                        source="general_cleaning",
                        table_name=table_name,
                        row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
                        target_column=col,
                        check_id="CR_COMMON_1",
                        issue_code="LEADING_OR_TRAILING_SPACES",
                        cleaning_action="STANDARDIZE",
                        old_value=old_value,
                        new_value=trimmed,
                        reason="Trimmed leading or trailing spaces from a textual value.",
                    )

                if trimmed == "":
                    old_value = df.at[idx, col]
                    df.at[idx, col] = pd.NA

                    append_log(
                        actions,
                        source="general_cleaning",
                        table_name=table_name,
                        row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
                        target_column=col,
                        check_id="CR_COMMON_2",
                        issue_code="EMPTY_STRING",
                        cleaning_action="SET_NULL",
                        old_value=old_value,
                        new_value=None,
                        reason="Converted an empty textual value into NULL.",
                    )


# ============================================================
# DQA-DRIVEN CLEANING
# ============================================================

def standardize_domain_or_drop(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
    table_name: str,
    mask: pd.Series,
    col: str,
    allowed_values: set[str],
    *,
    check_id: str,
    issue_code: str | None,
    drop_if_unknown: bool,
    set_null_if_unknown: bool = False,
    flag_area: str | None = None,
) -> None:
    df = tables[table_name]
    cmap = canonical_map(allowed_values)

    for idx in df.loc[mask].index:
        if col not in df.columns or pd.isna(df.at[idx, col]):
            continue

        raw = str(df.at[idx, col]).strip()
        key = re.sub(r"[^a-z0-9]", "", raw.lower())

        if key in cmap:
            standardize_value(
                tables,
                actions,
                table_name,
                idx,
                col,
                cmap[key],
                source="general_dqa",
                check_id=check_id,
                issue_code=issue_code,
                reason=f"Standardized {col} to a known domain value.",
            )

        elif drop_if_unknown:
            one = pd.Series(False, index=df.index)
            one.loc[idx] = True

            mark_rows_to_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                one,
                source="general_dqa",
                row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
                check_id=check_id,
                issue_code=issue_code,
                reason=f"Unknown {col} value cannot be mapped to the allowed domain.",
            )

        elif set_null_if_unknown:
            one = pd.Series(False, index=df.index)
            one.loc[idx] = True

            set_columns_null(
                tables,
                actions,
                table_name,
                one,
                [col],
                source="general_dqa",
                row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
                check_id=check_id,
                issue_code=issue_code,
                reason=f"Unknown {col} value was set to NULL because it cannot be mapped deterministically.",
                flag_area=flag_area,
            )


def apply_dqa_issue(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
    issue: pd.Series,
) -> None:
    table_name = str(issue.get("table_name", "")).strip()
    check_id = str(issue.get("check_id", "")).strip()
    issue_code = None if pd.isna(issue.get("issue_code")) else str(issue.get("issue_code"))
    row_identifier = None if pd.isna(issue.get("row_identifier")) else str(issue.get("row_identifier"))

    if table_name not in tables:
        return

    df = tables[table_name]
    mask = mask_from_row_identifier(df, row_identifier)

    if not mask.any():
        return

    # These result completeness checks are intentionally handled by the focused
    # missing value script, not directly by the General DQA cleaning.
    if check_id == "result_required_race_classification_columns":
        return

    # Generic DROP_ROW decisions.
    if (
        check_id.endswith("required_structural_columns")
        or check_id.endswith("required_identification_columns")
        or check_id == "circuit_required_analytical_columns"
        or check_id in {
            "season_year_formula1_domain",
            "round_number_positive",
            "result_position_positive",
            "lap_number_positive",
            "lap_time_positive",
            "weather_time_non_negative",
            "track_status_time_non_negative",
            "track_status_code_domain",
        }
        or check_id == "primary_key_unique"
        or check_id.startswith("natural_key_")
        or issue_code in {"BROKEN_FOREIGN_KEY", "DUPLICATED_KEY"}
        or check_id.startswith("fk_")
    ):
        mark_rows_to_drop(
            tables,
            drop_masks,
            actions,
            table_name,
            mask,
            source="general_dqa",
            row_identifier=row_identifier,
            check_id=check_id,
            issue_code=issue_code,
            reason="The DQA issue makes the row structurally unusable or unreliable for the cleaned schema.",
        )
        return

    # ------------------------------------------------------------
    # Season
    # ------------------------------------------------------------

    if table_name == "season":
        if check_id == "number_of_events_positive":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["number_of_events"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid descriptive season value set to NULL.",
            )

        elif check_id in {"season_dates_order", "season_dates_match_year"}:
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["season_start_date", "season_end_date"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Inconsistent season dates set to NULL.",
            )

        return

    # ------------------------------------------------------------
    # Circuit
    # ------------------------------------------------------------

    if table_name == "circuit":
        if check_id == "global_circuit_category_domain":
            standardize_domain_or_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                mask,
                "global_circuit_category",
                GLOBAL_CIRCUIT_CATEGORIES,
                check_id=check_id,
                issue_code=issue_code,
                drop_if_unknown=True,
            )

        elif check_id == "sector1_category_domain":
            standardize_domain_or_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                mask,
                "sector1_category",
                SECTOR_CATEGORIES,
                check_id=check_id,
                issue_code=issue_code,
                drop_if_unknown=True,
            )

        elif check_id == "sector2_category_domain":
            standardize_domain_or_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                mask,
                "sector2_category",
                SECTOR_CATEGORIES,
                check_id=check_id,
                issue_code=issue_code,
                drop_if_unknown=True,
            )

        elif check_id == "sector3_category_domain":
            standardize_domain_or_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                mask,
                "sector3_category",
                SECTOR_CATEGORIES,
                check_id=check_id,
                issue_code=issue_code,
                drop_if_unknown=True,
            )

        return

    # ------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------

    if table_name == "driver":
        if check_id == "driver_abbreviation_format":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["abbreviation"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid driver abbreviation set to NULL.",
            )

        elif check_id == "driver_url_format":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["driver_url"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid driver URL set to NULL.",
            )

        elif check_id == "permanent_number_range":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["permanent_number"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid permanent number set to NULL.",
            )

        elif check_id == "driver_age_plausible_2021_2022":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["date_of_birth"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Implausible date of birth set to NULL.",
            )

        return

    # ------------------------------------------------------------
    # Team
    # ------------------------------------------------------------

    if table_name == "team":
        if check_id == "team_url_format":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["team_url"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid team URL set to NULL.",
            )

        return

    # ------------------------------------------------------------
    # Grand Prix
    # ------------------------------------------------------------

    if table_name == "grand_prix":
        if check_id == "event_format_domain":
            standardize_domain_or_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                mask,
                "event_format",
                EVENT_FORMATS,
                check_id=check_id,
                issue_code=issue_code,
                drop_if_unknown=True,
            )

        elif check_id == "grand_prix_event_date_matches_season_year":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["event_date"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Grand Prix event date inconsistent with season year set to NULL.",
            )

        return

    # ------------------------------------------------------------
    # Session
    # ------------------------------------------------------------

    if table_name == "session":
        if check_id == "session_type_domain":
            standardize_domain_or_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                mask,
                "session_type",
                SESSION_TYPES,
                check_id=check_id,
                issue_code=issue_code,
                drop_if_unknown=True,
            )

        elif check_id == "session_date_near_grand_prix_date":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["session_date"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Session date inconsistent with Grand Prix date set to NULL.",
            )

        return

    # ------------------------------------------------------------
    # Result
    # ------------------------------------------------------------

    if table_name == "result":
        if check_id == "result_points_non_negative":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["points"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid points value set to NULL.",
                flag_area="RACE_CONTEXT_INFORMATION",
            )

        elif check_id == "result_laps_non_negative":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["laps"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid completed-laps value set to NULL.",
                flag_area="RACE_CONTEXT_INFORMATION",
            )

        elif check_id == "result_grid_position_non_negative":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["grid_position"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid grid position set to NULL.",
                flag_area="RACE_CONTEXT_INFORMATION",
            )

        elif check_id == "result_qualifying_progression_consistency":
            add_information_area_to_rows(
                tables,
                actions,
                table_name,
                mask,
                "QUALIFYING_INFORMATION",
                source="general_dqa",
                row_identifier=row_identifier,
                target_column=None,
                check_id=check_id,
                issue_code=issue_code,
                reason="Qualifying progression consistency is suspicious.",
            )

        return

    # ------------------------------------------------------------
    # Lap
    # ------------------------------------------------------------

    if table_name == "lap":
        if check_id == "lap_sector_times_positive":
            invalids = invalid_numeric_columns(
                df,
                mask,
                ["sector1_time_ms", "sector2_time_ms", "sector3_time_ms"],
                min_value=1,
            )

            for col, col_mask in invalids.items():
                set_columns_null(
                    tables,
                    actions,
                    table_name,
                    col_mask,
                    [col],
                    source="general_dqa",
                    row_identifier=row_identifier,
                    check_id=check_id,
                    issue_code=issue_code,
                    reason="Invalid sector time set to NULL.",
                    flag_area="SECTOR_INFORMATION",
                )

        elif check_id == "lap_speeds_positive":
            invalids = invalid_numeric_columns(
                df,
                mask,
                ["speed_i1", "speed_i2", "speed_fl", "speed_st"],
                min_value=1,
            )

            for col, col_mask in invalids.items():
                set_columns_null(
                    tables,
                    actions,
                    table_name,
                    col_mask,
                    [col],
                    source="general_dqa",
                    row_identifier=row_identifier,
                    check_id=check_id,
                    issue_code=issue_code,
                    reason="Invalid speed value set to NULL.",
                    flag_area="SPEED_INFORMATION",
                )

        elif check_id == "stint_positive":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["stint"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid stint value set to NULL.",
                flag_area="TYRE_INFORMATION",
            )

        elif check_id == "tyre_life_positive":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["tyre_life"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid tyre life value set to NULL.",
                flag_area="TYRE_INFORMATION",
            )

        elif check_id == "compound_domain":
            standardize_domain_or_drop(
                tables,
                drop_masks,
                actions,
                table_name,
                mask,
                "compound",
                TYRE_COMPOUNDS,
                check_id=check_id,
                issue_code=issue_code,
                drop_if_unknown=False,
                set_null_if_unknown=True,
                flag_area="TYRE_INFORMATION",
            )

        elif check_id == "lap_sector_sum_matches_lap_time":
            add_information_area_to_rows(
                tables,
                actions,
                table_name,
                mask,
                "SECTOR_INFORMATION",
                source="general_dqa",
                row_identifier=row_identifier,
                target_column=None,
                check_id=check_id,
                issue_code=issue_code,
                reason="Sector sum is not coherent with lap time.",
            )

        return

    # ------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------

    if table_name == "weather":
        if check_id == "air_temp_broad_domain_range":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["air_temp"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid air temperature set to NULL.",
            )

        elif check_id == "track_temp_broad_domain_range":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["track_temp"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid track temperature set to NULL.",
            )

        elif check_id == "humidity_range":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["humidity"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid humidity set to NULL.",
            )

        elif check_id == "pressure_range":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["pressure"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid pressure set to NULL.",
            )

        elif check_id == "wind_direction_range":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["wind_direction"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid wind direction set to NULL.",
            )

        elif check_id == "wind_speed_non_negative":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["wind_speed"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Invalid wind speed set to NULL.",
            )

        elif check_id == "weather_track_air_temp_difference":
            set_columns_null(
                tables,
                actions,
                table_name,
                mask,
                ["track_temp"],
                source="general_dqa",
                row_identifier=row_identifier,
                check_id=check_id,
                issue_code=issue_code,
                reason="Implausible track-air temperature relation: track temperature set to NULL.",
            )

        return

    # ------------------------------------------------------------
    # Track Status
    # ------------------------------------------------------------

    if table_name == "track_status":
        if check_id in {"track_status_message_mapping", "track_status_message_domain"}:
            for idx in df.loc[mask].index:
                status_value = df.at[idx, "status"] if "status" in df.columns else pd.NA

                try:
                    status_int = int(float(str(status_value).strip()))
                except Exception:
                    status_int = None

                if status_int in TRACK_STATUS_MAPPING:
                    standardize_value(
                        tables,
                        actions,
                        table_name,
                        idx,
                        "message",
                        TRACK_STATUS_MAPPING[status_int],
                        source="general_dqa",
                        check_id=check_id,
                        issue_code=issue_code,
                        reason="Track status message reconstructed from the numerical status code.",
                    )

                else:
                    one = pd.Series(False, index=df.index)
                    one.loc[idx] = True

                    set_columns_null(
                        tables,
                        actions,
                        table_name,
                        one,
                        ["message"],
                        source="general_dqa",
                        row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
                        check_id=check_id,
                        issue_code=issue_code,
                        reason="Unknown track status message set to NULL because the status code could not reconstruct it.",
                    )

        return


def apply_dqa_cleaning(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
    issues_df: pd.DataFrame,
) -> None:
    if issues_df.empty:
        return

    for _, issue in issues_df.iterrows():
        apply_dqa_issue(tables, drop_masks, actions, issue)


# ============================================================
# MISSING-VALUE-DRIVEN CLEANING - OPTIMIZED
# ============================================================

def apply_missing_value_cleaning(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
    flags_df: pd.DataFrame,
) -> None:
    if flags_df.empty:
        return

    required = {
        "table_name",
        "row_identifier",
        "column_name",
        "missing_class",
        "missing_information_area",
    }

    missing = required - set(flags_df.columns)

    if missing:
        raise RuntimeError(f"Missing value flags file is missing required columns: {missing}")

    flags = flags_df.copy()

    flags["table_name"] = flags["table_name"].astype(str).str.strip()
    flags["column_name"] = flags["column_name"].astype(str).str.strip()
    flags["missing_class"] = flags["missing_class"].astype(str).str.strip()
    flags["missing_information_area"] = flags["missing_information_area"].astype(str).str.strip()
    flags["_clean_row_id"] = flags["row_identifier"].apply(canonicalize_row_identifier)

    flags = flags[
        flags["table_name"].isin(["lap", "result"])
        & flags["missing_information_area"].isin(VALID_MISSING_INFORMATION_AREAS)
        & (flags["missing_information_area"] != "NONE")
        & flags["_clean_row_id"].notna()
    ].copy()

    if flags.empty:
        return

    # ------------------------------------------------------------
    # DROP_ROW decisions
    # ------------------------------------------------------------

    lap_drop_ids = set(
        flags.loc[
            (flags["table_name"] == "lap")
            & (flags["missing_information_area"] == "LAP_TIME_INFORMATION"),
            "_clean_row_id",
        ]
    )

    result_drop_ids = set(
        flags.loc[
            (flags["table_name"] == "result")
            & (flags["missing_information_area"] == "CLASSIFICATION_INFORMATION"),
            "_clean_row_id",
        ]
    )

    if "lap" in tables and lap_drop_ids:
        df = tables["lap"]
        mask = df["_clean_row_id"].isin(lap_drop_ids)

        mark_rows_to_drop(
            tables,
            drop_masks,
            actions,
            "lap",
            mask,
            source="missing_values",
            row_identifier=None,
            check_id=None,
            issue_code=None,
            missing_class=None,
            missing_information_area="LAP_TIME_INFORMATION",
            reason="Rows with missing lap time information are removed from the cleaned lap table.",
        )

    if "result" in tables and result_drop_ids:
        df = tables["result"]
        mask = df["_clean_row_id"].isin(result_drop_ids)

        mark_rows_to_drop(
            tables,
            drop_masks,
            actions,
            "result",
            mask,
            source="missing_values",
            row_identifier=None,
            check_id=None,
            issue_code=None,
            missing_class=None,
            missing_information_area="CLASSIFICATION_INFORMATION",
            reason="Rows with missing classification information are removed from the cleaned result table.",
        )

    # ------------------------------------------------------------
    # ADD_FLAG decisions
    # ------------------------------------------------------------

    add_flags = flags.copy()

    add_flags = add_flags[
        ~(
            (add_flags["table_name"] == "lap")
            & (add_flags["_clean_row_id"].isin(lap_drop_ids))
        )
        & ~(
            (add_flags["table_name"] == "result")
            & (add_flags["_clean_row_id"].isin(result_drop_ids))
        )
    ]

    add_flags = add_flags[
        ~(
            (add_flags["table_name"] == "lap")
            & (add_flags["missing_information_area"] == "LAP_TIME_INFORMATION")
        )
        & ~(
            (add_flags["table_name"] == "result")
            & (add_flags["missing_information_area"] == "CLASSIFICATION_INFORMATION")
        )
    ]

    if add_flags.empty:
        return

    grouped = (
        add_flags
        .groupby(["table_name", "_clean_row_id"], as_index=False)
        .agg(
            missing_information_area=(
                "missing_information_area",
                lambda x: "|".join(sorted(set(x))),
            )
        )
    )

    for table_name, group in grouped.groupby("table_name"):
        if table_name not in tables:
            continue

        df = tables[table_name]

        if "missing_information_areas" not in df.columns:
            df["missing_information_areas"] = "NONE"

        area_map = dict(zip(group["_clean_row_id"], group["missing_information_area"]))
        affected = df["_clean_row_id"].isin(area_map.keys())

        for idx in df.loc[affected].index:
            old_value = df.at[idx, "missing_information_areas"]
            new_areas = normalize_area_list(old_value)

            incoming_areas = normalize_area_list(area_map[df.at[idx, "_clean_row_id"]])

            for area in incoming_areas:
                if area not in new_areas:
                    new_areas.append(area)

            new_value = "|".join(sorted(new_areas)) if new_areas else "NONE"

            if new_value == old_value:
                continue

            df.at[idx, "missing_information_areas"] = new_value

            append_log(
                actions,
                source="missing_values",
                table_name=table_name,
                row_identifier=row_identifier_for_row(table_name, df.loc[idx], idx),
                target_column="missing_information_areas",
                check_id=None,
                issue_code=None,
                missing_class=None,
                missing_information_area=new_value,
                cleaning_action="ADD_FLAG",
                old_value=old_value,
                new_value=new_value,
                reason="Missing information areas aggregated from the focused missing value output.",
            )


# ============================================================
# OUTLIER-DRIVEN CLEANING - OPTIMIZED
# ============================================================

def apply_outlier_cleaning(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
    outlier_df: pd.DataFrame,
) -> None:
    if outlier_df.empty or "lap" not in tables:
        return

    required = {"row_identifier", "metric", "consensus_score"}
    missing = required - set(outlier_df.columns)

    if missing:
        raise RuntimeError(f"Outlier flags file is missing required columns: {missing}")

    outliers = outlier_df.copy()

    outliers["metric"] = outliers["metric"].astype(str).str.strip()
    outliers["consensus_score"] = pd.to_numeric(outliers["consensus_score"], errors="coerce")
    outliers["_clean_row_id"] = outliers["row_identifier"].apply(canonicalize_row_identifier)

    outliers = outliers[
        outliers["_clean_row_id"].notna()
        & outliers["consensus_score"].notna()
        & (outliers["consensus_score"] >= 1)
    ].copy()

    if outliers.empty:
        return

    df = tables["lap"]

    # ------------------------------------------------------------
    # DROP_ROW for strong lap_time_ms outliers
    # ------------------------------------------------------------

    strong_lap_time_ids = set(
        outliers.loc[
            (outliers["metric"] == "lap_time_ms")
            & (outliers["consensus_score"] >= 2),
            "_clean_row_id",
        ]
    )

    if strong_lap_time_ids:
        mask = df["_clean_row_id"].isin(strong_lap_time_ids)

        mark_rows_to_drop(
            tables,
            drop_masks,
            actions,
            "lap",
            mask,
            source="outlier_detection",
            row_identifier=None,
            check_id=None,
            issue_code=None,
            outlier_metric="lap_time_ms",
            outlier_consensus_score=2,
            reason="Rows with strong consensus lap_time_ms outliers are removed because lap time is the core performance measure.",
        )

    # ------------------------------------------------------------
    # ADD_FLAG for sector and speed outliers
    # ------------------------------------------------------------

    flag_rows: list[tuple[str, str]] = []

    sector_ids = outliers.loc[
        outliers["metric"].isin(SECTOR_METRICS)
        & (outliers["consensus_score"] >= 1),
        "_clean_row_id",
    ]

    for row_id in sector_ids:
        if row_id not in strong_lap_time_ids:
            flag_rows.append((row_id, "SECTOR_INFORMATION"))

    speed_ids = outliers.loc[
        outliers["metric"].isin(SPEED_METRICS)
        & (outliers["consensus_score"] >= 1),
        "_clean_row_id",
    ]

    for row_id in speed_ids:
        if row_id not in strong_lap_time_ids:
            flag_rows.append((row_id, "SPEED_INFORMATION"))

    if not flag_rows:
        return

    flag_df = pd.DataFrame(flag_rows, columns=["_clean_row_id", "missing_information_area"])

    grouped = (
        flag_df
        .groupby("_clean_row_id", as_index=False)["missing_information_area"]
        .agg(lambda x: "|".join(sorted(set(x))))
    )

    if "missing_information_areas" not in df.columns:
        df["missing_information_areas"] = "NONE"

    area_map = dict(zip(grouped["_clean_row_id"], grouped["missing_information_area"]))
    affected = df["_clean_row_id"].isin(area_map.keys())

    for idx in df.loc[affected].index:
        old_value = df.at[idx, "missing_information_areas"]
        new_areas = normalize_area_list(old_value)

        incoming_areas = normalize_area_list(area_map[df.at[idx, "_clean_row_id"]])

        for area in incoming_areas:
            if area not in new_areas:
                new_areas.append(area)

        new_value = "|".join(sorted(new_areas)) if new_areas else "NONE"

        if new_value == old_value:
            continue

        df.at[idx, "missing_information_areas"] = new_value

        append_log(
            actions,
            source="outlier_detection",
            table_name="lap",
            row_identifier=row_identifier_for_row("lap", df.loc[idx], idx),
            target_column="missing_information_areas",
            check_id=None,
            issue_code=None,
            outlier_metric=None,
            outlier_consensus_score=None,
            cleaning_action="ADD_FLAG",
            old_value=old_value,
            new_value=new_value,
            reason="Outlier information aggregated into missing_information_areas for sector or speed analysis.",
        )


# ============================================================
# REFERENTIAL CASCADE AFTER DROPS
# ============================================================

def current_df(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    table_name: str,
) -> pd.DataFrame:
    df = tables[table_name]
    mask = drop_masks.get(table_name, pd.Series(False, index=df.index))

    return df.loc[~mask].copy()


def apply_referential_cascade(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
) -> None:
    changed = True

    while changed:
        changed = False

        for child_table, fks in FOREIGN_KEYS.items():
            if child_table not in tables:
                continue

            child_df = tables[child_table]
            child_drop = drop_masks.setdefault(
                child_table,
                pd.Series(False, index=child_df.index),
            )

            for child_col, parent_table, parent_col in fks:
                if (
                    parent_table not in tables
                    or child_col not in child_df.columns
                    or parent_col not in tables[parent_table].columns
                ):
                    continue

                parent_clean = current_df(tables, drop_masks, parent_table)
                valid_parent_values = set(
                    parent_clean[parent_col]
                    .dropna()
                    .apply(normalize_for_compare)
                )

                fk_present = child_df[child_col].notna()
                broken = fk_present & ~child_df[child_col].apply(normalize_for_compare).isin(valid_parent_values)
                new_broken = broken & ~child_drop

                if new_broken.any():
                    changed = True

                    mark_rows_to_drop(
                        tables,
                        drop_masks,
                        actions,
                        child_table,
                        new_broken,
                        source="general_dqa",
                        row_identifier=None,
                        check_id=f"post_cleaning_fk_{child_table}_{child_col}_to_{parent_table}_{parent_col}",
                        issue_code="BROKEN_FOREIGN_KEY_AFTER_CLEANING",
                        reason=(
                            f"Row removed because {child_table}.{child_col} no longer "
                            f"references a valid {parent_table}.{parent_col} after previous cleaning actions."
                        ),
                    )


# ============================================================
# FINALIZATION AND OUTPUTS
# ============================================================

def build_rejected_rows(
    tables_before_drop: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
    actions: list[CleaningAction],
) -> pd.DataFrame:
    drop_reasons: dict[tuple[str, str], list[str]] = {}

    for action in actions:
        if action.cleaning_action != "DROP_ROW" or action.row_identifier is None:
            continue

        key = (action.table_name, action.row_identifier)
        drop_reasons.setdefault(key, []).append(action.reason)

    rows: list[RejectedRow] = []

    for table_name, df in tables_before_drop.items():
        mask = drop_masks.get(table_name, pd.Series(False, index=df.index))

        for idx, row in df.loc[mask].iterrows():
            rid = row_identifier_for_row(table_name, row, idx)
            reasons = " | ".join(drop_reasons.get((table_name, rid), []))

            row_dict = row.where(pd.notna(row), None).to_dict()
            row_dict.pop("_clean_row_id", None)

            rows.append(
                RejectedRow(
                    table_name=table_name,
                    row_identifier=rid,
                    reasons=reasons,
                    row_data_json=json.dumps(row_dict, default=str, ensure_ascii=False),
                )
            )

    return pd.DataFrame([asdict(row) for row in rows])


def apply_final_drops(
    tables: dict[str, pd.DataFrame],
    drop_masks: dict[str, pd.Series],
) -> dict[str, pd.DataFrame]:
    cleaned: dict[str, pd.DataFrame] = {}

    for table_name, df in tables.items():
        mask = drop_masks.get(table_name, pd.Series(False, index=df.index))
        cleaned[table_name] = df.loc[~mask].reset_index(drop=True).copy()

    return cleaned


def write_cleaned_table_csvs(tables: dict[str, pd.DataFrame]) -> None:
    CLEANED_TABLES_DIR.mkdir(parents=True, exist_ok=True)

    for table_name, df in tables.items():
        df.to_csv(CLEANED_TABLES_DIR / f"{table_name}.csv", index=False)


def write_metadata_outputs(
    actions: list[CleaningAction],
    rejected_rows_df: pd.DataFrame,
    before_after_df: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    actions_df = pd.DataFrame([asdict(action) for action in actions])

    if actions_df.empty:
        actions_df = pd.DataFrame(
            columns=[
                "source",
                "table_name",
                "row_identifier",
                "target_column",
                "check_id",
                "issue_code",
                "missing_class",
                "missing_information_area",
                "outlier_metric",
                "outlier_consensus_score",
                "cleaning_action",
                "old_value",
                "new_value",
                "reason",
            ]
        )

    actions_df.to_csv(CLEANING_ACTION_LOG_FILE, index=False)

    if not actions_df.empty:
        summary_by_table = (
            actions_df
            .groupby(["table_name", "cleaning_action"], dropna=False)
            .size()
            .reset_index(name="action_count")
            .sort_values(["table_name", "cleaning_action"])
        )
    else:
        summary_by_table = pd.DataFrame(
            columns=["table_name", "cleaning_action", "action_count"]
        )

    summary_by_table.to_csv(CLEANING_SUMMARY_BY_TABLE_FILE, index=False)

    decision_cols = [
        "source",
        "check_id",
        "missing_information_area",
        "outlier_metric",
        "cleaning_action",
    ]

    if not actions_df.empty:
        summary_by_decision = (
            actions_df
            .groupby(decision_cols, dropna=False)
            .size()
            .reset_index(name="action_count")
            .sort_values(decision_cols)
        )
    else:
        summary_by_decision = pd.DataFrame(columns=decision_cols + ["action_count"])

    summary_by_decision.to_csv(CLEANING_SUMMARY_BY_DECISION_FILE, index=False)

    if rejected_rows_df.empty:
        rejected_rows_df = pd.DataFrame(
            columns=["table_name", "row_identifier", "reasons", "row_data_json"]
        )

    rejected_rows_df.to_csv(REJECTED_ROWS_FILE, index=False)

    if before_after_df.empty:
        before_after_df = pd.DataFrame(
            columns=[
                "table_name",
                "issue_count_before",
                "issue_count_after",
                "overall_score_before",
                "overall_score_after",
            ]
        )

    before_after_df.to_csv(BEFORE_AFTER_SCORECARD_FILE, index=False)


# ============================================================
# OPTIONAL POST-CLEANING DQA
# ============================================================

def import_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {module_name} from {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


def find_project_file(filename: str) -> Path | None:
    candidates = list(PROJECT_ROOT.rglob(filename))

    if not candidates:
        return None

    clean_candidates = [
        p for p in candidates
        if "artifacts" not in p.parts
        and "__pycache__" not in p.parts
        and ".venv" not in p.parts
    ]

    return clean_candidates[0] if clean_candidates else candidates[0]


def try_build_before_after_scorecard(
    original_tables: dict[str, pd.DataFrame],
    cleaned_tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    engine_path = find_project_file("dqa_engine.py")
    rules_path = find_project_file("dqa_rules.py")

    if engine_path is None or rules_path is None:
        print("[WARNING] dqa_engine.py or dqa_rules.py not found. before_after_scorecard.csv will be empty.")
        return pd.DataFrame()

    try:
        dqa_engine_module = import_module_from_path("_cleaning_dqa_engine", engine_path)
        dqa_rules_module = import_module_from_path("_cleaning_dqa_rules", rules_path)

        dqa = dqa_engine_module.DQAEngine(
            dqa_rules_module.TABLE_RULES,
            dqa_rules_module.QUALITY_DIMENSIONS,
        )

        _, before_scorecard, _ = dqa.run(original_tables)
        _, after_scorecard, _ = dqa.run(cleaned_tables)

        before = before_scorecard[["table_name", "overall_score", "issue_count"]].rename(
            columns={
                "overall_score": "overall_score_before",
                "issue_count": "issue_count_before",
            }
        )

        after = after_scorecard[["table_name", "overall_score", "issue_count"]].rename(
            columns={
                "overall_score": "overall_score_after",
                "issue_count": "issue_count_after",
            }
        )

        out = before.merge(after, on="table_name", how="outer")

        return out[
            [
                "table_name",
                "issue_count_before",
                "issue_count_after",
                "overall_score_before",
                "overall_score_after",
            ]
        ]

    except Exception as exc:
        print(f"[WARNING] Could not run before/after DQA comparison: {exc}")
        return pd.DataFrame()


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    input_engine, input_schema = get_engine_and_schema(INPUT_SCHEMA)
    output_engine, output_schema = get_engine_and_schema(OUTPUT_SCHEMA)

    print(f"Reading source tables from schema: {input_schema}")

    original_tables: dict[str, pd.DataFrame] = {}

    for table_name in TABLE_ORDER:
        try:
            original_tables[table_name] = snake_case_columns(
                read_table(table_name, input_engine, input_schema)
            )
            print(f"Loaded table {table_name}: {len(original_tables[table_name])} rows")

        except Exception as exc:
            print(f"[WARNING] Could not read table {table_name}: {exc}")

    tables = {
        name: df.copy()
        for name, df in original_tables.items()
    }

    actions: list[CleaningAction] = []

    drop_masks: dict[str, pd.Series] = {
        table_name: pd.Series(False, index=df.index)
        for table_name, df in tables.items()
    }

    for table_name in ["lap", "result"]:
        if table_name in tables and "missing_information_areas" not in tables[table_name].columns:
            tables[table_name]["missing_information_areas"] = "NONE"

    t0 = perf_counter()
    apply_general_cleaning(tables, actions)
    print(f"General cleaning completed in {perf_counter() - t0:.2f}s")

    # Internal technical identifiers used for fast matching with CSV flags.
    add_internal_row_ids(tables)

    dqa_issues_df = read_csv_optional(
        DQA_ISSUE_CANDIDATES,
        required=False,
        name="General DQA issues",
    )

    missing_flags_df = read_csv_optional(
        MISSING_FLAGS_CANDIDATES,
        required=False,
        name="Focused missing value row flags",
    )

    outlier_flags_df = read_csv_optional(
        OUTLIER_FLAGS_CANDIDATES,
        required=False,
        name="Lap outlier flags",
    )

    t0 = perf_counter()
    apply_dqa_cleaning(tables, drop_masks, actions, dqa_issues_df)
    print(f"DQA-driven cleaning completed in {perf_counter() - t0:.2f}s")

    t0 = perf_counter()
    apply_missing_value_cleaning(tables, drop_masks, actions, missing_flags_df)
    print(f"Missing-value-driven cleaning completed in {perf_counter() - t0:.2f}s")

    t0 = perf_counter()
    apply_outlier_cleaning(tables, drop_masks, actions, outlier_flags_df)
    print(f"Outlier-driven cleaning completed in {perf_counter() - t0:.2f}s")

    t0 = perf_counter()
    apply_referential_cascade(tables, drop_masks, actions)
    print(f"Referential cascade completed in {perf_counter() - t0:.2f}s")

    rejected_rows_df = build_rejected_rows(tables, drop_masks, actions)

    cleaned_tables = apply_final_drops(tables, drop_masks)
    cleaned_tables = remove_internal_row_ids(cleaned_tables)

    if RUN_POST_CLEANING_DQA_COMPARISON:
        t0 = perf_counter()
        before_after_df = try_build_before_after_scorecard(original_tables, cleaned_tables)
        print(f"Before/after DQA comparison completed in {perf_counter() - t0:.2f}s")
    else:
        before_after_df = pd.DataFrame()
        print("Before/after DQA comparison skipped.")

    write_cleaned_table_csvs(cleaned_tables)
    write_metadata_outputs(actions, rejected_rows_df, before_after_df)

    print(f"Writing cleaned tables to schema: {output_schema}")

    prepare_output_schema(output_engine, output_schema)
    write_tables_to_schema(cleaned_tables, output_engine, output_schema)

    print("Data Cleaning completed.")
    print(f"Cleaned schema: {output_schema}")
    print(f"Cleaned CSV tables: {CLEANED_TABLES_DIR}")
    print(f"Cleaning action log: {CLEANING_ACTION_LOG_FILE}")
    print(f"Rejected rows: {REJECTED_ROWS_FILE}")
    print(f"Summary by table: {CLEANING_SUMMARY_BY_TABLE_FILE}")
    print(f"Summary by decision: {CLEANING_SUMMARY_BY_DECISION_FILE}")
    print(f"Before/after scorecard: {BEFORE_AFTER_SCORECARD_FILE}")


if __name__ == "__main__":
    main()
