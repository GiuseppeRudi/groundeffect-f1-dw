from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

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
    if total <= 0:
        return None
    return round(float(passed) / float(total), 6)


def as_records(items: list[Any]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def missing_columns(df: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if c not in df.columns]


def value_in_allowed(value: Any, allowed_values: set[Any]) -> bool:
    """Compare values using stripped string representations.

    This allows domains such as {1, 2, 4} to match values loaded as 1.0 or "1".
    """
    if pd.isna(value):
        return False

    value_str = str(value).strip()
    allowed_str = {str(v).strip() for v in allowed_values}

    if value_str in allowed_str:
        return True

    # Support values like 1.0 matching integer domain value 1.
    try:
        value_int_str = str(int(float(value_str)))
        return value_int_str in allowed_str
    except Exception:
        return False


def make_row_identifier(row: pd.Series, rules: dict[str, Any], fallback_index: Any) -> str:
    """Build a readable row identifier for issue files.

    Prefer the primary key when all PK values are present; otherwise use the dataframe index.
    """
    pk = rules.get("primary_key") or []

    if pk and all(c in row.index for c in pk) and all(pd.notna(row[c]) for c in pk):
        return ";".join(f"{c}={row[c]}" for c in pk)

    return f"row_index={fallback_index}"


def empty_applicability(index: pd.Index) -> tuple[pd.Series, pd.Series]:
    mask = pd.Series(False, index=index)
    return mask, mask.copy()


# ============================================================
# CUSTOM CONSISTENCY / PLAUSIBILITY CHECKS
# ============================================================

def custom_season_dates_order(table_name, df, all_tables, rules, check):
    needed = ["season_start_date", "season_end_date"]
    if missing_columns(df, needed):
        return empty_applicability(df.index)

    start = pd.to_datetime(df["season_start_date"], errors="coerce")
    end = pd.to_datetime(df["season_end_date"], errors="coerce")

    applicable = start.notna() & end.notna()
    failing = applicable & (start > end)
    return applicable, failing


def custom_season_dates_match_year(table_name, df, all_tables, rules, check):
    needed = ["season_year", "season_start_date", "season_end_date"]
    if missing_columns(df, needed):
        return empty_applicability(df.index)

    year = pd.to_numeric(df["season_year"], errors="coerce")
    start = pd.to_datetime(df["season_start_date"], errors="coerce")
    end = pd.to_datetime(df["season_end_date"], errors="coerce")

    applicable = year.notna() & (start.notna() | end.notna())
    failing = pd.Series(False, index=df.index)

    start_applicable = applicable & start.notna()
    end_applicable = applicable & end.notna()

    failing.loc[start_applicable] = start.loc[start_applicable].dt.year != year.loc[start_applicable]
    failing.loc[end_applicable] = failing.loc[end_applicable] | (
        end.loc[end_applicable].dt.year != year.loc[end_applicable]
    )

    return applicable, failing


def custom_grand_prix_event_date_matches_season_year(table_name, df, all_tables, rules, check):
    needed = ["season_year", "event_date"]
    if missing_columns(df, needed):
        return empty_applicability(df.index)

    year = pd.to_numeric(df["season_year"], errors="coerce")
    event_date = pd.to_datetime(df["event_date"], errors="coerce")

    applicable = year.notna() & event_date.notna()
    failing = applicable & (event_date.dt.year != year)
    return applicable, failing


def custom_session_date_near_grand_prix_date(table_name, df, all_tables, rules, check):
    needed = ["grand_prix_id", "session_date"]
    if missing_columns(df, needed):
        return empty_applicability(df.index)

    grand_prix = all_tables.get("grand_prix")
    if grand_prix is None or missing_columns(grand_prix, ["grand_prix_id", "event_date"]):
        return empty_applicability(df.index)

    tmp = df[["grand_prix_id", "session_date"]].copy()
    tmp["_idx"] = df.index

    gp_small = grand_prix[["grand_prix_id", "event_date"]].copy()

    merged = tmp.merge(gp_small, on="grand_prix_id", how="left")

    session_date = pd.to_datetime(merged["session_date"], errors="coerce").dt.normalize()
    event_date = pd.to_datetime(merged["event_date"], errors="coerce").dt.normalize()

    day_delta = (session_date - event_date).dt.days

    applicable_m = session_date.notna() & event_date.notna()

    # In this project, only Q and R sessions are extracted.
    # Race is usually on event_date; Qualifying is normally one or two days before it.
    failing_m = applicable_m & ((day_delta < -2) | (day_delta > 0))

    applicable = pd.Series(False, index=df.index)
    failing = pd.Series(False, index=df.index)

    applicable.loc[merged.loc[applicable_m, "_idx"]] = True
    failing.loc[merged.loc[failing_m, "_idx"]] = True

    return applicable, failing


def custom_lap_sector_sum_matches_lap_time(table_name, df, all_tables, rules, check):
    cols = ["lap_time_ms", "sector1_time_ms", "sector2_time_ms", "sector3_time_ms"]
    if missing_columns(df, cols):
        return empty_applicability(df.index)

    lap = pd.to_numeric(df["lap_time_ms"], errors="coerce")
    s1 = pd.to_numeric(df["sector1_time_ms"], errors="coerce")
    s2 = pd.to_numeric(df["sector2_time_ms"], errors="coerce")
    s3 = pd.to_numeric(df["sector3_time_ms"], errors="coerce")

    applicable = lap.notna() & s1.notna() & s2.notna() & s3.notna()

    # Pit in/out laps are special laps and can distort sector/lap-time interpretation.
    for pit_col in ["pit_out_time_ms", "pit_in_time_ms"]:
        if pit_col in df.columns:
            applicable = applicable & df[pit_col].isna()

    tolerance = int(check.get("tolerance_ms", 1000))
    failing = applicable & (((s1 + s2 + s3) - lap).abs() > tolerance)
    return applicable, failing


def custom_driver_age_plausibility(table_name, df, all_tables, rules, check):
    if "date_of_birth" not in df.columns:
        return empty_applicability(df.index)

    dob = pd.to_datetime(df["date_of_birth"], errors="coerce")
    applicable = dob.notna()

    min_age = int(check.get("min_age", 15))
    max_age = int(check.get("max_age", 60))

    age_2021 = 2021 - dob.dt.year
    age_2022 = 2022 - dob.dt.year

    failing = applicable & ((age_2021 < min_age) | (age_2022 > max_age))
    return applicable, failing


def custom_weather_track_air_temp_difference(table_name, df, all_tables, rules, check):
    needed = ["track_temp", "air_temp"]
    if missing_columns(df, needed):
        return empty_applicability(df.index)

    track = pd.to_numeric(df["track_temp"], errors="coerce")
    air = pd.to_numeric(df["air_temp"], errors="coerce")

    applicable = track.notna() & air.notna()
    max_difference = float(check.get("max_difference", 35))
    failing = applicable & ((track - air).abs() > max_difference)
    return applicable, failing


def custom_track_status_message_mapping(table_name, df, all_tables, rules, check):
    needed = ["status", "message"]
    if missing_columns(df, needed):
        return empty_applicability(df.index)

    mapping = check.get("mapping", {})

    applicable = df["status"].notna() & df["message"].notna()
    failing = pd.Series(False, index=df.index)

    for idx, row in df.loc[applicable, ["status", "message"]].iterrows():
        try:
            status_int = int(float(row["status"]))
        except Exception:
            status_int = None

        expected_message = mapping.get(status_int)
        if expected_message is None or str(row["message"]).strip() != expected_message:
            failing.loc[idx] = True

    return applicable, failing


CUSTOM_CHECKS: dict[str, Callable[..., tuple[pd.Series, pd.Series]]] = {
    "season_dates_order": custom_season_dates_order,
    "season_dates_match_year": custom_season_dates_match_year,
    "grand_prix_event_date_matches_season_year": custom_grand_prix_event_date_matches_season_year,
    "session_date_near_grand_prix_date": custom_session_date_near_grand_prix_date,
    "lap_sector_sum_matches_lap_time": custom_lap_sector_sum_matches_lap_time,
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
                results.append(
                    CheckResult(
                        table_name=table_name,
                        dimension="Completeness",
                        check_id="table_exists",
                        check_description=f"Table {table_name} must exist.",
                        passed_count=0,
                        failed_count=1,
                        total_count=1,
                        score=0.0,
                        status="red",
                    )
                )
                issues.append(
                    Issue(
                        table_name=table_name,
                        row_identifier="__table__",
                        dimension="Completeness",
                        check_id="table_exists",
                        issue_code="MISSING_TABLE",
                        issue_description=f"Table {table_name} was not found.",
                        severity="red",
                    )
                )
                continue

            table_results, table_issues = self.run_for_table(table_name, df, all_tables, rules)
            results.extend(table_results)
            issues.extend(table_issues)

        check_df = pd.DataFrame(as_records(results))
        issues_df = pd.DataFrame(as_records(issues))
        scorecard_df = self.build_scorecard_by_table(check_df, issues_df)

        return check_df, scorecard_df, issues_df

    def run_for_table(
        self,
        table_name: str,
        df: pd.DataFrame,
        all_tables: dict[str, pd.DataFrame],
        rules: dict[str, Any],
    ) -> tuple[list[CheckResult], list[Issue]]:
        results: list[CheckResult] = []
        issues: list[Issue] = []

        # Completeness: required groups only.
        for group in rules.get("required_groups", []):
            result, new_issues = self.check_required_group(table_name, df, rules, group)
            results.append(result)
            issues.extend(new_issues)

        # Uniqueness: duplicate complete keys only.
        pk = rules.get("primary_key")
        if pk:
            result, new_issues = self.check_unique_key(
                table_name=table_name,
                df=df,
                rules=rules,
                key_cols=pk,
                check_id="primary_key_unique",
                description=f"Primary key {pk} must be unique among complete key values.",
            )
            results.append(result)
            issues.extend(new_issues)

        for n, key in enumerate(rules.get("natural_keys", []), start=1):
            if pk and list(key) == list(pk):
                continue

            result, new_issues = self.check_unique_key(
                table_name=table_name,
                df=df,
                rules=rules,
                key_cols=key,
                check_id=f"natural_key_{n}_unique",
                description=f"Natural key {key} should be unique among complete key values.",
            )
            results.append(result)
            issues.extend(new_issues)

        # Validity: present values only.
        for check in rules.get("validity_checks", []):
            result, new_issues = self.check_validity(table_name, df, rules, check)
            results.append(result)
            issues.extend(new_issues)

        # Consistency: semantic custom checks.
        for check in rules.get("consistency_checks", []):
            result, new_issues = self.check_custom(table_name, df, all_tables, rules, check, "Consistency")
            results.append(result)
            issues.extend(new_issues)

        # Accuracy/Plausibility: optional custom checks, only if declared in rules.
        for check in rules.get("plausibility_checks", []):
            result, new_issues = self.check_custom(table_name, df, all_tables, rules, check, "Accuracy/Plausibility")
            results.append(result)
            issues.extend(new_issues)

        # Referential Integrity: non-null child FK values must exist in parent table.
        for fk in rules.get("foreign_keys", []):
            result, new_issues = self.check_foreign_key(table_name, df, all_tables, rules, fk)
            results.append(result)
            issues.extend(new_issues)

        return results, issues


    def check_required_group(
        self,
        table_name: str,
        df: pd.DataFrame,
        rules: dict[str, Any],
        group: dict[str, Any],
    ) -> tuple[CheckResult, list[Issue]]:
        cols = group.get("columns", [])
        check_id = group.get("check_id", "required_columns")
        description = group.get("description", "Required columns must be present and non-null.")
        issue_code = group.get("issue_code", "MISSING_REQUIRED_VALUE")

        issues: list[Issue] = []
        missing = missing_columns(df, cols)

        if missing:
            total = max(len(df), 1) * max(len(cols), 1)
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier="__table__",
                    dimension="Completeness",
                    check_id=check_id,
                    issue_code="MISSING_REQUIRED_COLUMN",
                    issue_description=f"Missing required columns: {missing}",
                    severity="red",
                )
            )
            return CheckResult(
                table_name=table_name,
                dimension="Completeness",
                check_id=check_id,
                check_description=description,
                passed_count=0,
                failed_count=total,
                total_count=total,
                score=0.0,
                status="red",
            ), issues


        applicable_rows = pd.Series(True, index=df.index)     
        applicable_count = int(applicable_rows.sum())

        if applicable_count == 0:
            return CheckResult(
                table_name=table_name,
                dimension="Completeness",
                check_id=check_id,
                check_description=description,
                passed_count=0,
                failed_count=0,
                total_count=0,
                score=None,
                status="not_applicable",
            ), issues

        total = int(applicable_count * len(cols))
        passed = int(df.loc[applicable_rows, cols].notna().sum().sum())
        failed = total - passed
        score = safe_score(passed, total)

        bad_rows = applicable_rows & df[cols].isna().any(axis=1)

        for idx, row in df.loc[bad_rows].iterrows():
            missing_values = [c for c in cols if pd.isna(row[c])]
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier=make_row_identifier(row, rules, idx),
                    dimension="Completeness",
                    check_id=check_id,
                    issue_code=issue_code,
                    issue_description=f"Missing required values in columns: {missing_values}",
                    severity="red" if score is not None and score < 0.80 else "yellow",
                )
            )

        return CheckResult(
            table_name=table_name,
            dimension="Completeness",
            check_id=check_id,
            check_description=description,
            passed_count=passed,
            failed_count=failed,
            total_count=total,
            score=score,
            status=status_from_score(score),
        ), issues

    def check_unique_key(
        self,
        table_name: str,
        df: pd.DataFrame,
        rules: dict[str, Any],
        key_cols: list[str],
        check_id: str,
        description: str,
    ) -> tuple[CheckResult, list[Issue]]:
        issues: list[Issue] = []
        missing = missing_columns(df, key_cols)

        if missing:
            # Missing key columns are treated as a structural completeness problem
            # when they appear in required_groups. Do not duplicate the issue here.
            return CheckResult(
                table_name=table_name,
                dimension="Uniqueness",
                check_id=check_id,
                check_description=description,
                passed_count=0,
                failed_count=0,
                total_count=0,
                score=None,
                status="not_applicable",
            ), issues

        complete_key_mask = ~df[key_cols].isna().any(axis=1)
        applicable_df = df.loc[complete_key_mask]
        total = int(len(applicable_df))

        if total == 0:
            return CheckResult(
                table_name=table_name,
                dimension="Uniqueness",
                check_id=check_id,
                check_description=description,
                passed_count=0,
                failed_count=0,
                total_count=0,
                score=None,
                status="not_applicable",
            ), issues

        duplicated_subset = applicable_df.duplicated(subset=key_cols, keep=False)
        failing = pd.Series(False, index=df.index)
        failing.loc[applicable_df.index] = duplicated_subset

        failed = int(failing.sum())
        passed = total - failed
        score = safe_score(passed, total)

        for idx, row in df.loc[failing].iterrows():
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier=make_row_identifier(row, rules, idx),
                    dimension="Uniqueness",
                    check_id=check_id,
                    issue_code="DUPLICATED_KEY",
                    issue_description=f"Key {key_cols} is duplicated among complete key values.",
                    severity="red",
                )
            )

        return CheckResult(
            table_name=table_name,
            dimension="Uniqueness",
            check_id=check_id,
            check_description=description,
            passed_count=passed,
            failed_count=failed,
            total_count=total,
            score=score,
            status=status_from_score(score),
        ), issues

    def check_validity(
        self,
        table_name: str,
        df: pd.DataFrame,
        rules: dict[str, Any],
        check: dict[str, Any],
    ) -> tuple[CheckResult, list[Issue]]:
        check_type = check["type"]
        check_id = check["check_id"]
        description = check.get("description", check_id)

        cols = as_list(check.get("columns")) or as_list(check.get("column"))
        issues: list[Issue] = []

        missing = missing_columns(df, cols)
        if missing:
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier="__table__",
                    dimension="Validity",
                    check_id=check_id,
                    issue_code="MISSING_VALIDITY_COLUMN",
                    issue_description=f"Missing columns for validity check: {missing}",
                    severity="red",
                )
            )
            return CheckResult(
                table_name=table_name,
                dimension="Validity",
                check_id=check_id,
                check_description=description,
                passed_count=0,
                failed_count=1,
                total_count=1,
                score=0.0,
                status="red",
            ), issues

        # Missing values are not validity failures in this simplified engine.
        # They are handled by Completeness through required_groups.
        applicable = pd.Series(False, index=df.index)
        failing = pd.Series(False, index=df.index)

        for col in cols:
            s = df[col]
            app = s.notna()

            if check_type == "domain":
                allowed = set(check.get("allowed_values", set()))
                fail = app & ~s.apply(lambda x: value_in_allowed(x, allowed))

            elif check_type == "numeric_range":
                num = pd.to_numeric(s, errors="coerce")
                fail = app & num.isna()

                if "min_value" in check:
                    fail = fail | (app & (num < float(check["min_value"])))

                if "max_value" in check:
                    fail = fail | (app & (num > float(check["max_value"])))

            elif check_type == "url_format":
                text = s.astype("string").str.strip()
                fail = app & ~text.str.match(r"^https?://", na=False)

            elif check_type == "regex":
                text = s.astype("string").str.strip()
                fail = app & ~text.str.match(check["pattern"], na=False)

            else:
                raise ValueError(
                    "Unsupported validity check type in simplified DQA engine: "
                    f"{check_type}. Supported types are: domain, numeric_range, url_format, regex."
                )

            applicable = applicable | app
            failing = failing | fail

        total = int(applicable.sum())
        failed = int(failing.sum())
        passed = total - failed
        score = safe_score(passed, total)

        for idx, row in df.loc[failing].iterrows():
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier=make_row_identifier(row, rules, idx),
                    dimension="Validity",
                    check_id=check_id,
                    issue_code="INVALID_VALUE",
                    issue_description=description,
                    severity="red" if score is not None and score < 0.80 else "yellow",
                )
            )

        return CheckResult(
            table_name=table_name,
            dimension="Validity",
            check_id=check_id,
            check_description=description,
            passed_count=passed,
            failed_count=failed,
            total_count=total,
            score=score,
            status=status_from_score(score),
        ), issues

    def check_custom(
        self,
        table_name: str,
        df: pd.DataFrame,
        all_tables: dict[str, pd.DataFrame],
        rules: dict[str, Any],
        check: dict[str, Any],
        dimension: str,
    ) -> tuple[CheckResult, list[Issue]]:
        check_id = check["check_id"]
        description = check.get("description", check_id)
        fn_name = check["function"]

        if fn_name not in CUSTOM_CHECKS:
            raise ValueError(f"Unknown custom check: {fn_name}")

        applicable, failing = CUSTOM_CHECKS[fn_name](table_name, df, all_tables, rules, check)
        applicable = applicable.astype(bool)
        failing = failing.astype(bool)

        total = int(applicable.sum())
        failed = int(failing.sum())
        passed = total - failed
        score = safe_score(passed, total)

        issues: list[Issue] = []
        for idx, row in df.loc[failing].iterrows():
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier=make_row_identifier(row, rules, idx),
                    dimension=dimension,
                    check_id=check_id,
                    issue_code=check_id.upper(),
                    issue_description=description,
                    severity="red" if score is not None and score < 0.80 else "yellow",
                )
            )

        return CheckResult(
            table_name=table_name,
            dimension=dimension,
            check_id=check_id,
            check_description=description,
            passed_count=passed,
            failed_count=failed,
            total_count=total,
            score=score,
            status=status_from_score(score),
        ), issues

    def check_foreign_key(
        self,
        table_name: str,
        df: pd.DataFrame,
        all_tables: dict[str, pd.DataFrame],
        rules: dict[str, Any],
        fk: dict[str, str],
    ) -> tuple[CheckResult, list[Issue]]:
        child_col = fk["child_column"]
        parent_table = fk["parent_table"]
        parent_col = fk["parent_column"]

        check_id = f"fk_{table_name}_{child_col}_to_{parent_table}_{parent_col}"
        description = f"{table_name}.{child_col} must reference {parent_table}.{parent_col}."
        issues: list[Issue] = []

        if child_col not in df.columns:
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier="__table__",
                    dimension="Referential Integrity",
                    check_id=check_id,
                    issue_code="MISSING_CHILD_FK_COLUMN",
                    issue_description=f"Missing child FK column: {child_col}",
                    severity="red",
                )
            )
            return CheckResult(table_name, "Referential Integrity", check_id, description, 0, 1, 1, 0.0, "red"), issues

        parent_df = all_tables.get(parent_table)
        if parent_df is None or parent_col not in parent_df.columns:
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier="__table__",
                    dimension="Referential Integrity",
                    check_id=check_id,
                    issue_code="MISSING_PARENT_TABLE_OR_COLUMN",
                    issue_description=f"Missing parent: {parent_table}.{parent_col}",
                    severity="red",
                )
            )
            return CheckResult(table_name, "Referential Integrity", check_id, description, 0, 1, 1, 0.0, "red"), issues

        child_values = df[child_col]
        applicable = child_values.notna()

        parent_values = set(parent_df[parent_col].dropna().astype(str).str.strip())
        failing = applicable & ~child_values.astype(str).str.strip().isin(parent_values)

        total = int(applicable.sum())
        failed = int(failing.sum())
        passed = total - failed
        score = safe_score(passed, total)

        for idx, row in df.loc[failing].iterrows():
            issues.append(
                Issue(
                    table_name=table_name,
                    row_identifier=make_row_identifier(row, rules, idx),
                    dimension="Referential Integrity",
                    check_id=check_id,
                    issue_code="BROKEN_FOREIGN_KEY",
                    issue_description=f"{child_col}={row[child_col]} does not exist in {parent_table}.{parent_col}.",
                    severity="red",
                )
            )

        return CheckResult(
            table_name=table_name,
            dimension="Referential Integrity",
            check_id=check_id,
            check_description=description,
            passed_count=passed,
            failed_count=failed,
            total_count=total,
            score=score,
            status=status_from_score(score),
        ), issues

    def build_scorecard_by_table(self, check_df: pd.DataFrame, issues_df: pd.DataFrame) -> pd.DataFrame:
        if check_df.empty:
            return pd.DataFrame()

        applicable = check_df.dropna(subset=["score"]).copy()
        if applicable.empty:
            return pd.DataFrame()

        dim_scores = applicable.groupby(["table_name", "dimension"], as_index=False)["score"].mean()
        pivot = dim_scores.pivot(index="table_name", columns="dimension", values="score").reset_index()

        for dimension in self.quality_dimensions:
            if dimension not in pivot.columns:
                pivot[dimension] = pd.NA

        score_cols = [dimension for dimension in self.quality_dimensions if dimension in pivot.columns]
        for col in score_cols:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")

        pivot["overall_score"] = pivot[score_cols].mean(axis=1, skipna=True).round(6)
        pivot["status"] = pivot["overall_score"].apply(status_from_score)

        if issues_df is not None and not issues_df.empty:
            counts = issues_df.groupby("table_name").size().rename("issue_count").reset_index()
            pivot = pivot.merge(counts, on="table_name", how="left")
            pivot["issue_count"] = pivot["issue_count"].fillna(0).astype(int)
        else:
            pivot["issue_count"] = 0

        rename = {dimension: self._dimension_col(dimension) + "_score" for dimension in self.quality_dimensions}
        pivot = pivot.rename(columns=rename)

        ordered = ["table_name", "overall_score", "status", "issue_count"] + [
            rename[dimension]
            for dimension in self.quality_dimensions
            if rename[dimension] in pivot.columns
        ]

        return pivot[ordered].sort_values("table_name").reset_index(drop=True)

    @staticmethod
    def _dimension_col(dimension: str) -> str:
        return dimension.lower().replace("/", "_").replace(" ", "_").replace("-", "_")
