INPUT_SCHEMA = "reconciled"
OUTPUT_SCHEMA = "reconciled_clean"

DROP_OUTPUT_SCHEMA_BEFORE_LOAD = True
RUN_POST_CLEANING_DQA_COMPARISON = False

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

SECTOR_METRICS = {
    "sector1_time_ms",
    "sector2_time_ms",
    "sector3_time_ms",
}

SPEED_METRICS = {
    "speed_i1",
    "speed_i2",
    "speed_fl",
    "speed_st",
}

QUALITY_FLAG_COLUMNS: dict[str, dict[str, str]] = {
    "lap": {
        "SECTOR_INFORMATION": "has_sector_information_issue",
        "SPEED_INFORMATION": "has_speed_information_issue",
        "TYRE_INFORMATION": "has_tyre_information_issue",
        "WEATHER_INFORMATION": "has_weather_information_issue",
        "TRACK_STATUS_INFORMATION": "has_track_status_information_issue",
        "PIT_INFORMATION": "has_pit_information_issue",
    },
    "result": {
        "QUALIFYING_INFORMATION": "has_qualifying_information_issue",
        "RACE_CONTEXT_INFORMATION": "has_race_context_information_issue",
    },
}