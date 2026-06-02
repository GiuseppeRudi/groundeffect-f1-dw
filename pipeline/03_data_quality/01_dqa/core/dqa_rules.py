from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path.cwd()

if not (PROJECT_ROOT / "database").exists() or not (PROJECT_ROOT / "pipeline").exists():
    raise RuntimeError(
        "This script must be executed from the project root directory.\n"
    )

sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config.domain_constants import *

QUALITY_DIMENSIONS = [
    "Completeness",
    "Uniqueness",
    "Validity",
    "Consistency",
    "Accuracy/Plausibility",
    "Timeliness",
    "Referential Integrity",
]

TABLE_RULES = {
   
   "season": {
    "primary_key": ["season_year"],
    "natural_keys": [["season_year"]],

    "required_groups": [
        {
            "check_id": "season_required_structural_columns",
            "description": "season_year must be present because it is the structural identifier of the season.",
            "columns": ["season_year"],
        }
    ],

    "validity_checks": [
        {
            "check_id": "season_year_formula1_domain",
            "description": "season_year must be compatible with the Formula 1 historical domain, starting from 1950.",
            "type": "numeric_range",
            "column": "season_year",
            "min_value": 1950,
            "when_present": False,
        },
        {
            "check_id": "number_of_events_positive",
            "description": "number_of_events must be greater than zero when present.",
            "type": "numeric_range",
            "column": "number_of_events",
            "min_value": 1,
            "when_present": True,
        },
    ],

    "consistency_checks": [
        {
            "check_id": "season_dates_order",
            "description": "season_start_date must be before season_end_date when both are present.",
            "function": "season_dates_order",
        },
        {
            "check_id": "season_dates_match_year",
            "description": "The year component of season dates must be coherent with season_year.",
            "function": "season_dates_match_year",
        },
    ],

    "foreign_keys": [],
    },

    "team": {
    "primary_key": ["team_id"],
    "natural_keys": [],

    "required_groups": [
        {
            "check_id": "team_required_identification_columns",
            "description": "team_id and team_name must be present.",
            "columns": ["team_id", "team_name"],
        }
    ],

    "validity_checks": [
        {
            "check_id": "team_url_format",
            "description": "team_url must have a valid URL format when present.",
            "type": "url_format",
            "column": "team_url",
            "when_present": True,
        },
    ],

    "consistency_checks": [],

    "foreign_keys": [],
    },

   
    "grand_prix": {
        "primary_key": ["grand_prix_id"],
        "natural_keys": [["season_year", "round_number"]],

        "required_groups": [
            {
                "check_id": "grand_prix_required_structural_columns",
                "description": "grand_prix_id, season_year, round_number, event_name, event_format, and circuit_id must be present.",
                "columns": [
                    "grand_prix_id",
                    "season_year",
                    "round_number",
                    "event_name",
                    "event_format",
                    "circuit_id",
                ],
            }
        ],

        "validity_checks": [
            {
                "check_id": "round_number_positive",
                "description": "round_number must be greater than zero.",
                "type": "numeric_range",
                "column": "round_number",
                "min_value": 1,
                "when_present": False,
            },
            {
                "check_id": "event_format_domain",
                "description": "event_format must belong to the allowed Grand Prix event format domain.",
                "type": "domain",
                "column": "event_format",
                "allowed_values": EVENT_FORMATS,
                "when_present": False,
            },
        ],

        "consistency_checks": [
            {
                "check_id": "grand_prix_event_date_matches_season_year",
                "description": "event_date must be coherent with season_year when present.",
                "function": "grand_prix_event_date_matches_season_year",
            }
        ],

        "foreign_keys": [
            {
                "child_column": "season_year",
                "parent_table": "season",
                "parent_column": "season_year",
            },
            {
                "child_column": "circuit_id",
                "parent_table": "circuit",
                "parent_column": "circuit_id",
            },
        ],
    },

    "session": {
        "primary_key": ["session_id"],
        "natural_keys": [["grand_prix_id", "session_type"]],

        "required_groups": [
            {
                "check_id": "session_required_structural_columns",
                "description": "session_id, grand_prix_id, and session_type must be present.",
                "columns": ["session_id", "grand_prix_id", "session_type"],
            }
        ],

        "validity_checks": [
            {
                "check_id": "session_type_domain",
                "description": "session_type must belong to the allowed session domain for this project: Q or R.",
                "type": "domain",
                "column": "session_type",
                "allowed_values": SESSION_TYPES,
                "when_present": False,
            },
        ],

        "consistency_checks": [
            {
                "check_id": "session_date_near_grand_prix_date",
                "description": "session_date should be coherent with the corresponding Grand Prix event_date. For Q and R sessions, it should normally fall between event_date minus two days and event_date.",
                "function": "session_date_near_grand_prix_date",
            }
        ],

        "foreign_keys": [
            {
                "child_column": "grand_prix_id",
                "parent_table": "grand_prix",
                "parent_column": "grand_prix_id",
            }
        ],
    },

    
    "result": {
        "primary_key": ["result_id"],
        "natural_keys": [["session_id", "driver_id"]],

        "required_groups": [
            {
                "check_id": "result_required_structural_columns",
                "description": "result_id, session_id, driver_id, and team_id must be present.",
                "columns": ["result_id", "session_id", "driver_id", "team_id"],
            },
        ],

        "validity_checks": [
            {
                "check_id": "result_position_positive",
                "description": "position must be greater than zero when present.",
                "type": "numeric_range",
                "column": "position",
                "min_value": 1,
                "when_present": True,
            },
            {
                "check_id": "result_points_non_negative",
                "description": "points must be greater than or equal to zero when present.",
                "type": "numeric_range",
                "column": "points",
                "min_value": 0,
                "when_present": True,
            },
            {
                "check_id": "result_laps_non_negative",
                "description": "laps must be greater than or equal to zero when present.",
                "type": "numeric_range",
                "column": "laps",
                "min_value": 0,
                "when_present": True,
            },
            {
                "check_id": "result_grid_position_non_negative",
                "description": "grid_position must be greater than or equal to zero when present.",
                "type": "numeric_range",
                "column": "grid_position",
                "min_value": 0,
                "when_present": True,
            },
        ],

        "consistency_checks": [],

        "foreign_keys": [
            {"child_column": "session_id", "parent_table": "session", "parent_column": "session_id"},
            {"child_column": "driver_id", "parent_table": "driver", "parent_column": "driver_id"},
            {"child_column": "team_id", "parent_table": "team", "parent_column": "team_id"},
        ],
    },

    "lap": {
        "primary_key": ["lap_id"],
        "natural_keys": [["session_id", "driver_id", "lap_number"]],

        "required_groups": [
            {
                "check_id": "lap_required_structural_columns",
                "description": "Structural lap identifiers and timeline attribute must be present.",
                "columns": [
                    "lap_id",
                    "session_id",
                    "driver_id",
                    "team_id",
                    "lap_number",
                    "time_ms",
                ],
            },
        ],

        "validity_checks": [
            {
                "check_id": "lap_number_positive",
                "description": "lap_number must be greater than zero.",
                "type": "numeric_range",
                "column": "lap_number",
                "min_value": 1,
                "when_present": False,
            },
            {
                "check_id": "lap_time_positive",
                "description": "lap_time_ms must be positive when present.",
                "type": "numeric_range",
                "column": "lap_time_ms",
                "min_value": 1,
                "when_present": True,
            },
            {
                "check_id": "lap_sector_times_positive",
                "description": "Sector times must be positive when present.",
                "type": "numeric_range",
                "columns": [
                    "sector1_time_ms",
                    "sector2_time_ms",
                    "sector3_time_ms",
                ],
                "min_value": 1,
                "when_present": True,
            },
            {
                "check_id": "lap_speeds_positive",
                "description": "Speed attributes must be positive when present.",
                "type": "numeric_range",
                "columns": [
                    "speed_i1",
                    "speed_i2",
                    "speed_fl",
                    "speed_st",
                ],
                "min_value": 1,
                "when_present": True,
            },
            {
                "check_id": "stint_positive",
                "description": "stint must be positive when present.",
                "type": "numeric_range",
                "column": "stint",
                "min_value": 1,
                "when_present": True,
            },
            {
                "check_id": "tyre_life_positive",
                "description": "tyre_life must be positive when present.",
                "type": "numeric_range",
                "column": "tyre_life",
                "min_value": 1,
                "when_present": True,
            },
            {
                "check_id": "compound_domain",
                "description": "compound must belong to the expected tyre compound domain when present.",
                "type": "domain",
                "column": "compound",
                "allowed_values": TYRE_COMPOUNDS,
                "when_present": True,
            },
        ],

        "consistency_checks": [
            {
                "check_id": "lap_sector_sum_matches_lap_time",
                "description": "For timed laps with complete sector information, the sum of sector times should be coherent with lap_time_ms.",
                "function": "lap_sector_sum_matches_lap_time",
                "tolerance_ms": 1000,
            },
        ],

        "foreign_keys": [
            {
                "child_column": "session_id",
                "parent_table": "session",
                "parent_column": "session_id",
            },
            {
                "child_column": "driver_id",
                "parent_table": "driver",
                "parent_column": "driver_id",
            },
            {
                "child_column": "team_id",
                "parent_table": "team",
                "parent_column": "team_id",
            },
        ],
    },


    "weather": {
        "primary_key": ["weather_id"],
        "natural_keys": [["session_id", "time_ms"]],

        "required_groups": [
            {
                "check_id": "weather_required_columns",
                "description": "Weather identifier, session timeline, and main weather measures must be present.",
                "columns": [
                    "weather_id",
                    "session_id",
                    "time_ms",
                    "air_temp",
                    "track_temp",
                    "rainfall",
                    "wind_speed",
                ],
            }
        ],

        "validity_checks": [
            {
                "check_id": "weather_time_non_negative",
                "description": "time_ms must be greater than or equal to zero.",
                "type": "numeric_range",
                "column": "time_ms",
                "min_value": 0,
                "when_present": False,
            },
            {
                "check_id": "air_temp_broad_domain_range",
                "description": "air_temp must be within a broad Formula 1 weather domain range when present.",
                "type": "numeric_range",
                "column": "air_temp",
                "min_value": -5,
                "max_value": 50,
                "when_present": True,
            },
            {
                "check_id": "track_temp_broad_domain_range",
                "description": "track_temp must be within a broad Formula 1 track temperature domain range when present.",
                "type": "numeric_range",
                "column": "track_temp",
                "min_value": -5,
                "max_value": 80,
                "when_present": True,
            },
            {
                "check_id": "humidity_range",
                "description": "humidity must be between 0 and 100 when present.",
                "type": "numeric_range",
                "column": "humidity",
                "min_value": 0,
                "max_value": 100,
                "when_present": True,
            },
            {
                "check_id": "pressure_range",
                "description": "pressure must be within a broad realistic atmospheric range when present.",
                "type": "numeric_range",
                "column": "pressure",
                "min_value": 650,
                "max_value": 1100,
                "when_present": True,
            },
            {
                "check_id": "wind_direction_range",
                "description": "wind_direction must be a degree value between 0 and 360 when present.",
                "type": "numeric_range",
                "column": "wind_direction",
                "min_value": 0,
                "max_value": 360,
                "when_present": True,
            },
            {
                "check_id": "wind_speed_non_negative",
                "description": "wind_speed must be greater than or equal to zero when present.",
                "type": "numeric_range",
                "column": "wind_speed",
                "min_value": 0,
                "when_present": True,
            },
        ],

        "consistency_checks": [
            {
                "check_id": "weather_track_air_temp_difference",
                "description": "track_temp should be reasonably coherent with air_temp.",
                "function": "weather_track_air_temp_difference",
                "max_difference": 50,
            }
        ],

        "foreign_keys": [
            {
                "child_column": "session_id",
                "parent_table": "session",
                "parent_column": "session_id",
            }
        ],
    },

  "track_status": {
        "primary_key": ["track_status_id"],
        "natural_keys": [["session_id", "time_ms"]],

        "required_groups": [
            {
                "check_id": "track_status_required_columns",
                "description": "Track status identifier, session timeline, status, and message must be present.",
                "columns": [
                    "track_status_id",
                    "session_id",
                    "time_ms",
                    "status",
                    "message",
                ],
            }
        ],

        "validity_checks": [
            {
                "check_id": "track_status_time_non_negative",
                "description": "time_ms must be greater than or equal to zero.",
                "type": "numeric_range",
                "column": "time_ms",
                "min_value": 0,
                "when_present": False,
            },
            {
                "check_id": "track_status_code_domain",
                "description": "status must belong to the documented track status code domain.",
                "type": "domain",
                "column": "status",
                "allowed_values": set(TRACK_STATUS_MAPPING.keys()),
                "when_present": False,
            },
            {
                "check_id": "track_status_message_domain",
                "description": "message must belong to the documented track status message domain.",
                "type": "domain",
                "column": "message",
                "allowed_values": set(TRACK_STATUS_MAPPING.values()),
                "when_present": False,
            },
        ],

        "consistency_checks": [
            {
                "check_id": "track_status_message_mapping",
                "description": "The numerical status code must correspond to the expected textual message.",
                "function": "track_status_message_mapping",
                "mapping": TRACK_STATUS_MAPPING,
            }
        ],

        "foreign_keys": [
            {
                "child_column": "session_id",
                "parent_table": "session",
                "parent_column": "session_id",
            }
        ],
    },


    "circuit": {
        "primary_key": ["circuit_id"],
        "natural_keys": [],

        "required_groups": [
            {
                "check_id": "circuit_required_analytical_columns",
                "description": "Circuit identifier and analytical classification columns must be present.",
                "columns": [
                    "circuit_id",
                    "global_circuit_category",
                    "sector1_category",
                    "sector2_category",
                    "sector3_category",
                ],
            }
        ],

        "validity_checks": [
            {
                "check_id": "global_circuit_category_domain",
                "description": "global_circuit_category must belong to the allowed global circuit category domain.",
                "type": "domain",
                "column": "global_circuit_category",
                "allowed_values": GLOBAL_CIRCUIT_CATEGORIES,
                "when_present": True,
            },
            {
                "check_id": "sector1_category_domain",
                "description": "sector1_category must belong to the allowed sector category domain.",
                "type": "domain",
                "column": "sector1_category",
                "allowed_values": SECTOR_CATEGORIES,
                "when_present": True,
            },
            {
                "check_id": "sector2_category_domain",
                "description": "sector2_category must belong to the allowed sector category domain.",
                "type": "domain",
                "column": "sector2_category",
                "allowed_values": SECTOR_CATEGORIES,
                "when_present": True,
            },
            {
                "check_id": "sector3_category_domain",
                "description": "sector3_category must belong to the allowed sector category domain.",
                "type": "domain",
                "column": "sector3_category",
                "allowed_values": SECTOR_CATEGORIES,
                "when_present": True,
            },
        ],

        "consistency_checks": [],

        "foreign_keys": [],
    },

    "driver": {
        "primary_key": ["driver_id"],
        "natural_keys": [],

        "required_groups": [
            {
                "check_id": "driver_required_identification_columns",
                "description": "driver_id, abbreviation, and last_name must be present.",
                "columns": ["driver_id", "abbreviation", "last_name"],
            }
        ],

        "validity_checks": [
            {
                "check_id": "driver_abbreviation_format",
                "description": "abbreviation must be a three-letter uppercase driver code.",
                "type": "regex",
                "column": "abbreviation",
                "pattern": r"^[A-Z]{3}$",
                "when_present": True,
            },
            {
                "check_id": "driver_url_format",
                "description": "driver_url must have a valid URL format when present.",
                "type": "url_format",
                "column": "driver_url",
                "when_present": True,
            },
            {
                "check_id": "permanent_number_range",
                "description": "permanent_number must be between 1 and 99 when present.",
                "type": "numeric_range",
                "column": "permanent_number",
                "min_value": 1,
                "max_value": 99,
                "when_present": True,
            },
        ],

        "consistency_checks": [],

        "plausibility_checks": [
            {
                "check_id": "driver_age_plausible_2021_2022",
                "description": "Driver age during the selected 2021--2022 seasons should be within a broad plausible Formula 1 range.",
                "function": "driver_age_plausibility",
                "min_age": 15,
                "max_age": 60,
            }
        ],

        "foreign_keys": [],
    }
}
