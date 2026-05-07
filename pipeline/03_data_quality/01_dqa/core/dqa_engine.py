"""
Reusable engine for the first General Data Quality Assessment script.

Input:
- pandas DataFrames loaded from the reconciled PostgreSQL database;
- declarative rules from dqa_rules.py.

Output:
- check-level scorecard;
- table-level scorecard;
- row-level issue files.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable
import re

import pandas as pd


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class CheckResult:
    table_name: str
    dimension: str
    check_id: str
    check_description: str
    passed_count: int
    failed_count: int
    total_count: int
    score: float | None
    status: str


@dataclass
class Issue:
    table_name: str
    row_identifier: str
    dimension: str
    check_id: str
    issue_code: str
    issue_description: str
    severity: str


# ============================================================
# GENERIC HELPERS
# ============================================================

def status_from_score(score: float | None) -> str:
    if score is None or pd.isna(score):
        return "not_applicable"
    if score >= 0.95:
        return "green"
    if score >= 0.80:
        return "yellow"
    return "red"


def safe_score(passed: int, total: int) -> float | None:

    # avoid division by zero 
    if total <= 0:
        return None

    # rounded to four decimal places 
    return round(float(passed) / float(total), 6)



def as_records(items: list[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def missing_columns(df: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if c not in df.columns]


def normalize_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.notna()
    normalized = series.astype("string").str.strip().str.lower()
    return normalized.isin({"true", "false", "1", "0"})


def value_in_allowed(value: Any, allowed_values: set[Any]) -> bool:
    if pd.isna(value):
        return False

    value_str = str(value).strip()
    allowed_str = {str(v).strip() for v in allowed_values}

    return value_str in allowed_str


def make_row_identifier(row: pd.Series, rules: dict[str, Any], fallback_index: Any) -> str:
    
    # to indentify the row try to find the primary key
    pk = rules.get("primary_key") or []

    # first check if the primary key lists is not empty 
    # check if all the primary key columns are present in the problematic row
    # check if all the primary key values in the row are not null
    if pk and all(c in row.index for c in pk) and all(pd.notna(row[c]) for c in pk):
        
        return ";".join(f"{c}={row[c]}" for c in pk)

    return f"row_index={fallback_index}"

# ============================================================
# CUSTOM CHECKS
# ============================================================

def custom_season_dates_order(table_name, df, all_tables, rules, check):
    needed = ["season_start_date", "season_end_date"]
    if missing_columns(df, needed):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    start = pd.to_datetime(df["season_start_date"], errors="coerce")
    end = pd.to_datetime(df["season_end_date"], errors="coerce")
    applicable = start.notna() & end.notna()
    failing = applicable & (start > end)
    return applicable, failing


def custom_season_dates_match_year(table_name, df, all_tables, rules, check):
    needed = ["season_year", "season_start_date", "season_end_date"]
    if missing_columns(df, needed):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    year = pd.to_numeric(df["season_year"], errors="coerce")
    start = pd.to_datetime(df["season_start_date"], errors="coerce")
    end = pd.to_datetime(df["season_end_date"], errors="coerce")
    applicable = year.notna() & (start.notna() | end.notna())
    failing = pd.Series(False, index=df.index)
    start_app = applicable & start.notna()
    end_app = applicable & end.notna()
    failing.loc[start_app] = start.loc[start_app].dt.year != year.loc[start_app]
    failing.loc[end_app] = failing.loc[end_app] | (end.loc[end_app].dt.year != year.loc[end_app])
    return applicable, failing


def custom_grand_prix_event_date_matches_season_year(table_name, df, all_tables, rules, check):
    if missing_columns(df, ["season_year", "event_date"]):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    year = pd.to_numeric(df["season_year"], errors="coerce")
    event_date = pd.to_datetime(df["event_date"], errors="coerce")
    applicable = year.notna() & event_date.notna()
    failing = applicable & (event_date.dt.year != year)
    return applicable, failing


def custom_grand_prix_circuit_match_present(table_name, df, all_tables, rules, check):
    if "circuit_id" not in df.columns:
        mask = pd.Series(False, index=df.index)
        return mask, mask
    applicable = pd.Series(True, index=df.index)
    failing = df["circuit_id"].isna() | (df["circuit_id"].astype("string").str.strip() == "")
    circuit = all_tables.get("circuit")
    if circuit is not None and "circuit_id" in circuit.columns:
        valid_ids = set(circuit["circuit_id"].dropna().astype(str).str.strip())
        failing = failing | ~df["circuit_id"].astype(str).str.strip().isin(valid_ids)
    return applicable, failing


def custom_session_date_near_grand_prix_date(table_name, df, all_tables, rules, check):
    if missing_columns(df, ["grand_prix_id", "session_date"]):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    gp = all_tables.get("grand_prix")
    if gp is None or missing_columns(gp, ["grand_prix_id", "event_date"]):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    tmp = df[["grand_prix_id", "session_date"]].copy()
    tmp["_idx"] = df.index
    gp_small = gp[["grand_prix_id", "event_date"]].copy()
    merged = tmp.merge(gp_small, on="grand_prix_id", how="left")
    session_date = pd.to_datetime(merged["session_date"], errors="coerce")
    event_date = pd.to_datetime(merged["event_date"], errors="coerce")
    app_m = session_date.notna() & event_date.notna()
    fail_m = app_m & ((session_date - event_date).dt.days.abs() > 7)
    applicable = pd.Series(False, index=df.index)
    failing = pd.Series(False, index=df.index)
    applicable.loc[merged.loc[app_m, "_idx"]] = True
    failing.loc[merged.loc[fail_m, "_idx"]] = True
    return applicable, failing


def custom_lap_sector_sum_matches_lap_time(table_name, df, all_tables, rules, check):
    cols = ["lap_time_ms", "sector1_time_ms", "sector2_time_ms", "sector3_time_ms"]
    if missing_columns(df, cols):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    lap = pd.to_numeric(df["lap_time_ms"], errors="coerce")
    s1 = pd.to_numeric(df["sector1_time_ms"], errors="coerce")
    s2 = pd.to_numeric(df["sector2_time_ms"], errors="coerce")
    s3 = pd.to_numeric(df["sector3_time_ms"], errors="coerce")
    applicable = lap.notna() & s1.notna() & s2.notna() & s3.notna()
    for pit_col in ["pit_out_time_ms", "pit_in_time_ms"]:
        if pit_col in df.columns:
            applicable = applicable & df[pit_col].isna()
    tolerance = int(check.get("tolerance_ms", 1000))
    failing = applicable & (((s1 + s2 + s3) - lap).abs() > tolerance)
    return applicable, failing


def custom_lap_team_matches_result(table_name, df, all_tables, rules, check):
    needed = ["session_id", "driver_id", "team_id"]
    if missing_columns(df, needed):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    result = all_tables.get("result")
    if result is None or missing_columns(result, needed):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    tmp = df[needed].copy()
    tmp["_idx"] = df.index
    res = result[needed].drop_duplicates(subset=["session_id", "driver_id"]).rename(columns={"team_id": "team_id_result"})
    merged = tmp.merge(res, on=["session_id", "driver_id"], how="left")
    app_m = merged["team_id"].notna() & merged["team_id_result"].notna()
    fail_m = app_m & (merged["team_id"].astype(str).str.strip() != merged["team_id_result"].astype(str).str.strip())
    applicable = pd.Series(False, index=df.index)
    failing = pd.Series(False, index=df.index)
    applicable.loc[merged.loc[app_m, "_idx"]] = True
    failing.loc[merged.loc[fail_m, "_idx"]] = True
    return applicable, failing


def custom_lap_basic_performance_plausibility(table_name, df, all_tables, rules, check):
    checks = []
    if "lap_time_ms" in df.columns:
        lap = pd.to_numeric(df["lap_time_ms"], errors="coerce")
        checks.append((lap.notna(), (lap < 30000) | (lap > 600000)))
    for col in ["sector1_time_ms", "sector2_time_ms", "sector3_time_ms"]:
        if col in df.columns:
            val = pd.to_numeric(df[col], errors="coerce")
            checks.append((val.notna(), (val < 5000) | (val > 300000)))
    for col in ["speed_i1", "speed_i2", "speed_fl", "speed_st"]:
        if col in df.columns:
            val = pd.to_numeric(df[col], errors="coerce")
            checks.append((val.notna(), (val < 1) | (val > 400)))
    if not checks:
        mask = pd.Series(False, index=df.index)
        return mask, mask
    applicable = pd.Series(False, index=df.index)
    failing = pd.Series(False, index=df.index)
    for app, fail in checks:
        applicable = applicable | app
        failing = failing | (app & fail)
    return applicable, failing


def custom_driver_age_plausibility(table_name, df, all_tables, rules, check):
    if "date_of_birth" not in df.columns:
        mask = pd.Series(False, index=df.index)
        return mask, mask
    dob = pd.to_datetime(df["date_of_birth"], errors="coerce")
    applicable = dob.notna()
    age_2021 = 2021 - dob.dt.year
    age_2022 = 2022 - dob.dt.year
    failing = applicable & ((age_2021 < 16) | (age_2022 > 60))
    return applicable, failing


def custom_weather_track_air_temp_difference(table_name, df, all_tables, rules, check):
    if missing_columns(df, ["track_temp", "air_temp"]):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    track = pd.to_numeric(df["track_temp"], errors="coerce")
    air = pd.to_numeric(df["air_temp"], errors="coerce")
    applicable = track.notna() & air.notna()
    max_difference = float(check.get("max_difference", 60))
    failing = applicable & ((track - air).abs() > max_difference)
    return applicable, failing


def custom_track_status_message_mapping(table_name, df, all_tables, rules, check):
    if missing_columns(df, ["status", "message"]):
        mask = pd.Series(False, index=df.index)
        return mask, mask
    mapping = check.get("mapping", {})
    applicable = df["status"].notna() & df["message"].notna()
    failing = pd.Series(False, index=df.index)
    for idx, row in df.loc[applicable, ["status", "message"]].iterrows():
        try:
            status_int = int(float(row["status"]))
        except Exception:
            status_int = None
        expected = mapping.get(status_int)
        if expected is None or str(row["message"]).strip() != expected:
            failing.loc[idx] = True
    return applicable, failing


CUSTOM_CHECKS: dict[str, Callable[..., tuple[pd.Series, pd.Series]]] = {
    "season_dates_order": custom_season_dates_order,
    "season_dates_match_year": custom_season_dates_match_year,
    "grand_prix_event_date_matches_season_year": custom_grand_prix_event_date_matches_season_year,
    "grand_prix_circuit_match_present": custom_grand_prix_circuit_match_present,
    "session_date_near_grand_prix_date": custom_session_date_near_grand_prix_date,
    "lap_sector_sum_matches_lap_time": custom_lap_sector_sum_matches_lap_time,
    "lap_team_matches_result": custom_lap_team_matches_result,
    "lap_basic_performance_plausibility": custom_lap_basic_performance_plausibility,
    "driver_age_plausibility": custom_driver_age_plausibility,
    "weather_track_air_temp_difference": custom_weather_track_air_temp_difference,
    "track_status_message_mapping": custom_track_status_message_mapping,
}


# ============================================================
# ENGINE
# ============================================================

class DQAEngine:
    def __init__(self, table_rules: dict[str, dict[str, Any]], quality_dimensions: list[str]):
        self.table_rules = table_rules
        self.quality_dimensions = quality_dimensions

    def run(self, all_tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        
        results: list[CheckResult] = []
        issues: list[Issue] = []
        
        for table_name, rules in self.table_rules.items():
            df = all_tables.get(table_name)
            
            if df is None:
                results.append(CheckResult(table_name, "Completeness", "table_exists", f"Table {table_name} must exist.", 0, 1, 1, 0.0, "red"))
                issues.append(Issue(table_name, "__table__", "Completeness", "table_exists", "MISSING_TABLE", f"Table {table_name} was not found.", "red"))
                continue

            table_results, table_issues = self.run_for_table(table_name, df, all_tables, rules)
            results.extend(table_results)
            issues.extend(table_issues)

        check_df = pd.DataFrame(as_records(results))
        issues_df = pd.DataFrame(as_records(issues))

        scorecard_df = self.build_scorecard_by_table(check_df, issues_df)
        return check_df, scorecard_df, issues_df


    def run_for_table(self, table_name: str, df: pd.DataFrame, all_tables: dict[str, pd.DataFrame], rules: dict[str, Any]):
        
        results: list[CheckResult] = []
        issues: list[Issue] = []

        for group in rules.get("required_groups", []):
            r, i = self.check_required_group(table_name, df, rules, group)
            results.append(r); issues.extend(i)


        pk = rules.get("primary_key")
        if pk:
            r, i = self.check_unique_key(table_name, df, rules, pk, "primary_key_unique", f"Primary key {pk} must be unique and non-null.")
            results.append(r); issues.extend(i)
        
        for n, key in enumerate(rules.get("natural_keys", []), start=1):
            # This foreign key is the same as the primary key
            if pk and list(key) == list(pk):
                continue
            r, i = self.check_unique_key(table_name, df, rules, key, f"natural_key_{n}_unique", f"Natural key {key} should be unique.")
            results.append(r); issues.extend(i)
        
        for check in rules.get("validity_checks", []):
            r, i = self.check_validity(table_name, df, rules, check)
            results.append(r); issues.extend(i)
        
        for check in rules.get("consistency_checks", []):
            r, i = self.check_custom(table_name, df, all_tables, rules, check, "Consistency")
            results.append(r); issues.extend(i)
        
        for check in rules.get("plausibility_checks", []):
            r, i = self.check_custom(table_name, df, all_tables, rules, check, "Accuracy/Plausibility")
            results.append(r); issues.extend(i)
        
        for fk in rules.get("foreign_keys", []):
            r, i = self.check_foreign_key(table_name, df, all_tables, rules, fk)
            results.append(r); issues.extend(i)
        
        return results, issues

    def check_required_group(self, table_name, df, rules, group):
        
        cols = group.get("columns", [])
        check_id = group.get("check_id", "required_columns")
        description = group.get("description", "Required columns must be present and non-null.")
        
        issues: list[Issue] = []
        missing = missing_columns(df, cols)

        # Structural check: before checking for null values, ensure that all required columns are present
        if missing:
            total = max(len(df), 1) * max(len(cols), 1)
            issues.append(Issue(table_name, "__table__", "Completeness", check_id, "MISSING_REQUIRED_COLUMN", f"Missing required columns: {missing}", "red"))
            return CheckResult(table_name, "Completeness", check_id, description, 0, total, total, 0.0, "red"), issues
        
        # number of rows * cols 
        total = int(len(df) * len(cols))

        # count how many of the required column values are non-null
        passed = int(df[cols].notna().sum().sum())

        failed = total - passed

        score = safe_score(passed, total)


        # boolean mask : for each row 
        # True if at least one colum has null values 
        # False if all the columns have not null values 
        bad_rows = df[cols].isna().any(axis=1)

        # df.loc filter and takes only the true rows (problematic)

        # idx = row index , rows = pd.series
        for idx, row in df.loc[bad_rows].iterrows():
             
            # for each row miss contains the name of cols where there is a null values
            miss = [c for c in cols if pd.isna(row[c])]

            issues.append(Issue(table_name, make_row_identifier(row, rules, idx), "Completeness", check_id, "MISSING_REQUIRED_VALUE", f"Missing required values in columns: {miss}", "red" if score is not None and score < 0.80 else "yellow"))
        
        return CheckResult(table_name, "Completeness", check_id, description, passed, failed, total, score, status_from_score(score)), issues




    def check_unique_key(self, table_name, df, rules, key_cols, check_id, description):
        
        issues: list[Issue] = []
        missing = missing_columns(df, key_cols)
        
        if missing:
            return CheckResult( table_name, "Uniqueness", check_id, description, 0, 0, 0, None, "skipped"), issues

        
        null_key = df[key_cols].isna().any(axis=1)

        # check if two different rows have the same subset of key coles 
        # keep = false mark all the rows with the duplication problem instead of the first occurenc
        duplicated = df.duplicated(subset=key_cols, keep=False)
        
        # a specific failed is there are null key values or duplicated values 
        failing = null_key | duplicated

        # how many rows have the valid key respect to the total number of rows 
        total = int(len(df)); failed = int(failing.sum()); passed = total - failed
        score = safe_score(passed, total)
        
        # for each problematic rows insert it in the issues table
        for idx, row in df.loc[failing].iterrows():
            code = "NULL_KEY" if null_key.loc[idx] else "DUPLICATED_KEY"
            issues.append(Issue(table_name, make_row_identifier(row, rules, idx), "Uniqueness", check_id, code, f"Key {key_cols} is null or duplicated.", "red"))
        
        return CheckResult(table_name, "Uniqueness", check_id, description, passed, failed, total, score, status_from_score(score)), issues

    def check_validity(self, table_name, df, rules, check):

        check_type = check["type"]
        check_id = check["check_id"]
        description = check.get("description", check_id)

        cols = as_list(check.get("columns")) or as_list(check.get("column"))
       
        when_present = bool(check.get("when_present", True))
        
        issues: list[Issue] = []
        
        missing = missing_columns(df, cols)
        
        if missing:
            issues.append(Issue(table_name, "__table__", "Validity", check_id, "MISSING_VALIDITY_COLUMN", f"Missing columns for validity check: {missing}", "red"))
            return CheckResult(table_name, "Validity", check_id, description, 0, 1, 1, 0.0, "red"), issues
        
        
        # boolean mask 

        # applicable = True for rows where the check should be applied (e.g. non-null values if when_present is True)
        # failing = True for rows where the check fails among the applicable ones
        applicable = pd.Series(False, index=df.index) 
        failing = pd.Series(False, index=df.index)
        

        # when_present is foundamental 
        # True => check only the rows where the values exists means where the values is not null 
        # False => check all the rows also the null one 

        for col in cols:
            s = df[col]
            app = s.notna() if when_present else pd.Series(True, index=df.index)
            
            if check_type == "domain":
                allowed = set(check.get("allowed_values", set()))
                fail = app & ~s.apply(lambda x: value_in_allowed(x, allowed))

                # A row fails if:
                # - the check applies to that row
                # - the value does not belong to the permitted domain
            
            elif check_type == "forbidden_values":
                forbidden = set(check.get("forbidden_values", set()))
                fail = app & s.apply(lambda x: value_in_allowed(x, forbidden))
            
            elif check_type == "numeric_range":
                num = pd.to_numeric(s, errors="coerce")
                fail = app & num.isna()
                if "min_value" in check:
                    fail = fail | (app & (num < float(check["min_value"])))
                if "max_value" in check:
                    fail = fail | (app & (num > float(check["max_value"])))
            
            elif check_type == "date_parseable":
                parsed = pd.to_datetime(s, errors="coerce")
                fail = app & parsed.isna()
            
            elif check_type == "url_format":
                text = s.astype("string").str.strip()
                fail = app & ~text.str.match(r"^https?://", na=False)
            
            elif check_type == "regex":
                text = s.astype("string").str.strip()
                fail = app & ~text.str.match(check["pattern"], na=False)
            
            elif check_type == "boolean":
                fail = app & ~normalize_bool_series(s)
            
            elif check_type == "non_empty_text":
                text = s.astype("string").str.strip()
                fail = app & (text.fillna("") == "")
            
            else:
                raise ValueError(f"Unsupported validity check type: {check_type}")
            
            applicable = applicable | app
            failing = failing | fail
        
        total = int(applicable.sum()); failed = int(failing.sum()); passed = total - failed
        score = safe_score(passed, total)
        
        for idx, row in df.loc[failing].iterrows():
            issues.append(Issue(table_name, make_row_identifier(row, rules, idx), "Validity", check_id, "INVALID_VALUE", description, "red" if score is not None and score < 0.80 else "yellow"))
        
        return CheckResult(table_name, "Validity", check_id, description, passed, failed, total, score, status_from_score(score)), issues


    def check_custom(self, table_name, df, all_tables, rules, check, dimension):
        
        check_id = check["check_id"]
        description = check.get("description", check_id)
        fn_name = check["function"]
        
        if fn_name not in CUSTOM_CHECKS:
            raise ValueError(f"Unknown custom check: {fn_name}")
        
        applicable, failing = CUSTOM_CHECKS[fn_name](table_name, df, all_tables, rules, check)
        
        total = int(applicable.sum()); failed = int(failing.sum()); passed = total - failed
        score = safe_score(passed, total)
        
        issues: list[Issue] = []
        
        for idx, row in df.loc[failing].iterrows():
            issues.append(Issue(table_name, make_row_identifier(row, rules, idx), dimension, check_id, check_id.upper(), description, "red" if score is not None and score < 0.80 else "yellow"))
        
        return CheckResult(table_name, dimension, check_id, description, passed, failed, total, score, status_from_score(score)), issues

    def check_foreign_key(self, table_name, df, all_tables, rules, fk):
        
        child_col = fk["child_column"]
        parent_table = fk["parent_table"]
        parent_col = fk["parent_column"]

        check_id = f"fk_{table_name}_{child_col}_to_{parent_table}_{parent_col}"
        description = f"{table_name}.{child_col} must reference {parent_table}.{parent_col}."
        issues: list[Issue] = []
       
        if child_col not in df.columns:
            issues.append(Issue(table_name, "__table__", "Referential Integrity", check_id, "MISSING_CHILD_FK_COLUMN", f"Missing child FK column: {child_col}", "red"))
            return CheckResult(table_name, "Referential Integrity", check_id, description, 0, 1, 1, 0.0, "red"), issues
        
        parent_df = all_tables.get(parent_table)
        
        if parent_df is None or parent_col not in parent_df.columns:
            issues.append(Issue(table_name, "__table__", "Referential Integrity", check_id, "MISSING_PARENT_TABLE_OR_COLUMN", f"Missing parent: {parent_table}.{parent_col}", "red"))
            return CheckResult(table_name, "Referential Integrity", check_id, description, 0, 1, 1, 0.0, "red"), issues
        
        child_values = df[child_col]
        applicable = child_values.notna()
        
        parent_values = set(parent_df[parent_col].dropna().astype(str).str.strip())
        failing = applicable & ~child_values.astype(str).str.strip().isin(parent_values)
        
        total = int(applicable.sum()); failed = int(failing.sum()); passed = total - failed
        score = safe_score(passed, total)
        
        for idx, row in df.loc[failing].iterrows():
            issues.append(Issue(table_name, make_row_identifier(row, rules, idx), "Referential Integrity", check_id, "BROKEN_FOREIGN_KEY", f"{child_col}={row[child_col]} does not exist in {parent_table}.{parent_col}.", "red"))
        
        return CheckResult(table_name, "Referential Integrity", check_id, description, passed, failed, total, score, status_from_score(score)), issues

    def build_scorecard_by_table(self, check_df: pd.DataFrame, issues_df: pd.DataFrame) -> pd.DataFrame:
        
        if check_df.empty:
            return pd.DataFrame()
        
        applicable = check_df.dropna(subset=["score"]).copy()
        if applicable.empty:
            return pd.DataFrame()
        
        dim_scores = applicable.groupby(["table_name", "dimension"], as_index=False)["score"].mean()
        pivot = dim_scores.pivot(index="table_name", columns="dimension", values="score").reset_index()
        for dim in self.quality_dimensions:
            if dim not in pivot.columns:
                pivot[dim] = pd.NA
        
        score_cols = [dim for dim in self.quality_dimensions if dim in pivot.columns]

        # Force score columns to numeric.
        # Non-applicable dimensions remain NaN and are ignored in the mean.
        for col in score_cols:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

        pivot["overall_score"] = pivot[score_cols].mean(axis=1, skipna=True)
        pivot["overall_score"] = pivot["overall_score"].round(6)

        pivot["status"] = pivot["overall_score"].apply(status_from_score)
        
        if issues_df is not None and not issues_df.empty:
            counts = issues_df.groupby("table_name").size().rename("issue_count").reset_index()
            pivot = pivot.merge(counts, on="table_name", how="left")
            pivot["issue_count"] = pivot["issue_count"].fillna(0).astype(int)
        else:
            pivot["issue_count"] = 0
        
        rename = {dim: self._dimension_col(dim) + "_score" for dim in self.quality_dimensions}
        pivot = pivot.rename(columns=rename)
        ordered = ["table_name", "overall_score", "status", "issue_count"] + [rename[d] for d in self.quality_dimensions if rename[d] in pivot.columns]
        
        return pivot[ordered].sort_values("table_name").reset_index(drop=True)

    @staticmethod
    def _dimension_col(dimension: str) -> str:
        return dimension.lower().replace("/", "_").replace(" ", "_").replace("-", "_")
