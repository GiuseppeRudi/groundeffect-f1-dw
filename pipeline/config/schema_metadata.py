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