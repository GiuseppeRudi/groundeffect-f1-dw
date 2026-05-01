from __future__ import annotations

from sqlalchemy import create_engine, text


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = "postgresql+psycopg://postgres:rudi@localhost:5432/f1_reconciled"


# ============================================================
# HELPERS
# ============================================================

def table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = :table_name
            )
        """),
        {"table_name": table_name}
    )
    return bool(result.scalar())


def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = :column_name
            )
        """),
        {"table_name": table_name, "column_name": column_name}
    )
    return bool(result.scalar())


def constraint_exists(conn, constraint_name: str) -> bool:
    result = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                  AND constraint_name = :constraint_name
            )
        """),
        {"constraint_name": constraint_name}
    )
    return bool(result.scalar())


def has_columns(conn, table_name: str, columns: list[str]) -> bool:
    return all(column_exists(conn, table_name, col) for col in columns)


def safe_execute(conn, sql: str, label: str) -> None:
    if constraint_exists(conn, label):
        print(f"SKIP: {label} already exists")
        return

    print(f"APPLYING: {label}")
    conn.execute(text(sql))


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:

        # ====================================================
        # PRIMARY KEYS
        # ====================================================

        if table_exists(conn, "season") and has_columns(conn, "season", ["season_year"]):
            safe_execute(conn, """
                ALTER TABLE season
                ADD CONSTRAINT pk_season
                PRIMARY KEY (season_year)
            """, "pk_season")

        if table_exists(conn, "circuit") and has_columns(conn, "circuit", ["circuit_id"]):
            safe_execute(conn, """
                ALTER TABLE circuit
                ADD CONSTRAINT pk_circuit
                PRIMARY KEY (circuit_id)
            """, "pk_circuit")

        if table_exists(conn, "driver") and has_columns(conn, "driver", ["driver_id"]):
            safe_execute(conn, """
                ALTER TABLE driver
                ADD CONSTRAINT pk_driver
                PRIMARY KEY (driver_id)
            """, "pk_driver")

        if table_exists(conn, "team") and has_columns(conn, "team", ["team_id"]):
            safe_execute(conn, """
                ALTER TABLE team
                ADD CONSTRAINT pk_team
                PRIMARY KEY (team_id)
            """, "pk_team")

        if table_exists(conn, "grand_prix") and has_columns(conn, "grand_prix", ["grand_prix_id"]):
            safe_execute(conn, """
                ALTER TABLE grand_prix
                ADD CONSTRAINT pk_grand_prix
                PRIMARY KEY (grand_prix_id)
            """, "pk_grand_prix")

        if table_exists(conn, "session") and has_columns(conn, "session", ["session_id"]):
            safe_execute(conn, """
                ALTER TABLE session
                ADD CONSTRAINT pk_session
                PRIMARY KEY (session_id)
            """, "pk_session")

        if table_exists(conn, "result") and has_columns(conn, "result", ["result_id"]):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT pk_result
                PRIMARY KEY (result_id)
            """, "pk_result")

        if table_exists(conn, "lap") and has_columns(conn, "lap", ["lap_id"]):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT pk_lap
                PRIMARY KEY (lap_id)
            """, "pk_lap")

        if table_exists(conn, "weather") and has_columns(conn, "weather", ["weather_id"]):
            safe_execute(conn, """
                ALTER TABLE weather
                ADD CONSTRAINT pk_weather
                PRIMARY KEY (weather_id)
            """, "pk_weather")

        if table_exists(conn, "track_status") and has_columns(conn, "track_status", ["track_status_id"]):
            safe_execute(conn, """
                ALTER TABLE track_status
                ADD CONSTRAINT pk_track_status
                PRIMARY KEY (track_status_id)
            """, "pk_track_status")

        # Optional bridge tables, only if you still export them
        if table_exists(conn, "season_driver") and has_columns(conn, "season_driver", ["season_year", "driver_id"]):
            safe_execute(conn, """
                ALTER TABLE season_driver
                ADD CONSTRAINT pk_season_driver
                PRIMARY KEY (season_year, driver_id)
            """, "pk_season_driver")

        if table_exists(conn, "season_team") and has_columns(conn, "season_team", ["season_year", "team_id"]):
            safe_execute(conn, """
                ALTER TABLE season_team
                ADD CONSTRAINT pk_season_team
                PRIMARY KEY (season_year, team_id)
            """, "pk_season_team")

        # ====================================================
        # NATURAL UNIQUE KEYS
        # ====================================================
        # These are not the main PKs anymore.
        # They are useful to preserve the original business meaning.

        if table_exists(conn, "grand_prix") and has_columns(conn, "grand_prix", ["season_year", "round_number"]):
            safe_execute(conn, """
                ALTER TABLE grand_prix
                ADD CONSTRAINT uq_grand_prix_natural
                UNIQUE (season_year, round_number)
            """, "uq_grand_prix_natural")

        if table_exists(conn, "session") and has_columns(conn, "session", ["grand_prix_id", "session_type"]):
            safe_execute(conn, """
                ALTER TABLE session
                ADD CONSTRAINT uq_session_natural
                UNIQUE (grand_prix_id, session_type)
            """, "uq_session_natural")

        if table_exists(conn, "result") and has_columns(conn, "result", ["session_id", "driver_id"]):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT uq_result_natural
                UNIQUE (session_id, driver_id)
            """, "uq_result_natural")

        if table_exists(conn, "lap") and has_columns(conn, "lap", ["session_id", "driver_id", "lap_number"]):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT uq_lap_natural
                UNIQUE (session_id, driver_id, lap_number)
            """, "uq_lap_natural")

        if table_exists(conn, "weather") and has_columns(conn, "weather", ["session_id", "time_ms"]):
            safe_execute(conn, """
                ALTER TABLE weather
                ADD CONSTRAINT uq_weather_natural
                UNIQUE (session_id, time_ms)
            """, "uq_weather_natural")

        if table_exists(conn, "track_status") and has_columns(conn, "track_status", ["session_id", "time_ms"]):
            safe_execute(conn, """
                ALTER TABLE track_status
                ADD CONSTRAINT uq_track_status_natural
                UNIQUE (session_id, time_ms)
            """, "uq_track_status_natural")

        # ====================================================
        # FOREIGN KEYS
        # ====================================================

        if (
            table_exists(conn, "grand_prix")
            and table_exists(conn, "season")
            and has_columns(conn, "grand_prix", ["season_year"])
            and has_columns(conn, "season", ["season_year"])
        ):
            safe_execute(conn, """
                ALTER TABLE grand_prix
                ADD CONSTRAINT fk_grand_prix_season
                FOREIGN KEY (season_year)
                REFERENCES season (season_year)
            """, "fk_grand_prix_season")

        if (
            table_exists(conn, "grand_prix")
            and table_exists(conn, "circuit")
            and has_columns(conn, "grand_prix", ["circuit_id"])
            and has_columns(conn, "circuit", ["circuit_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE grand_prix
                ADD CONSTRAINT fk_grand_prix_circuit
                FOREIGN KEY (circuit_id)
                REFERENCES circuit (circuit_id)
            """, "fk_grand_prix_circuit")

        if (
            table_exists(conn, "session")
            and table_exists(conn, "grand_prix")
            and has_columns(conn, "session", ["grand_prix_id"])
            and has_columns(conn, "grand_prix", ["grand_prix_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE session
                ADD CONSTRAINT fk_session_grand_prix
                FOREIGN KEY (grand_prix_id)
                REFERENCES grand_prix (grand_prix_id)
            """, "fk_session_grand_prix")

        if (
            table_exists(conn, "result")
            and table_exists(conn, "session")
            and has_columns(conn, "result", ["session_id"])
            and has_columns(conn, "session", ["session_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT fk_result_session
                FOREIGN KEY (session_id)
                REFERENCES session (session_id)
            """, "fk_result_session")

        if (
            table_exists(conn, "result")
            and table_exists(conn, "driver")
            and has_columns(conn, "result", ["driver_id"])
            and has_columns(conn, "driver", ["driver_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT fk_result_driver
                FOREIGN KEY (driver_id)
                REFERENCES driver (driver_id)
            """, "fk_result_driver")

        if (
            table_exists(conn, "result")
            and table_exists(conn, "team")
            and has_columns(conn, "result", ["team_id"])
            and has_columns(conn, "team", ["team_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT fk_result_team
                FOREIGN KEY (team_id)
                REFERENCES team (team_id)
            """, "fk_result_team")

        if (
            table_exists(conn, "lap")
            and table_exists(conn, "session")
            and has_columns(conn, "lap", ["session_id"])
            and has_columns(conn, "session", ["session_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT fk_lap_session
                FOREIGN KEY (session_id)
                REFERENCES session (session_id)
            """, "fk_lap_session")

        if (
            table_exists(conn, "lap")
            and table_exists(conn, "driver")
            and has_columns(conn, "lap", ["driver_id"])
            and has_columns(conn, "driver", ["driver_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT fk_lap_driver
                FOREIGN KEY (driver_id)
                REFERENCES driver (driver_id)
            """, "fk_lap_driver")

        if (
            table_exists(conn, "lap")
            and table_exists(conn, "team")
            and has_columns(conn, "lap", ["team_id"])
            and has_columns(conn, "team", ["team_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT fk_lap_team
                FOREIGN KEY (team_id)
                REFERENCES team (team_id)
            """, "fk_lap_team")

        if (
            table_exists(conn, "weather")
            and table_exists(conn, "session")
            and has_columns(conn, "weather", ["session_id"])
            and has_columns(conn, "session", ["session_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE weather
                ADD CONSTRAINT fk_weather_session
                FOREIGN KEY (session_id)
                REFERENCES session (session_id)
            """, "fk_weather_session")

        if (
            table_exists(conn, "track_status")
            and table_exists(conn, "session")
            and has_columns(conn, "track_status", ["session_id"])
            and has_columns(conn, "session", ["session_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE track_status
                ADD CONSTRAINT fk_track_status_session
                FOREIGN KEY (session_id)
                REFERENCES session (session_id)
            """, "fk_track_status_session")

        # Optional bridge table foreign keys
        if (
            table_exists(conn, "season_driver")
            and table_exists(conn, "season")
            and has_columns(conn, "season_driver", ["season_year"])
        ):
            safe_execute(conn, """
                ALTER TABLE season_driver
                ADD CONSTRAINT fk_season_driver_season
                FOREIGN KEY (season_year)
                REFERENCES season (season_year)
            """, "fk_season_driver_season")

        if (
            table_exists(conn, "season_driver")
            and table_exists(conn, "driver")
            and has_columns(conn, "season_driver", ["driver_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE season_driver
                ADD CONSTRAINT fk_season_driver_driver
                FOREIGN KEY (driver_id)
                REFERENCES driver (driver_id)
            """, "fk_season_driver_driver")

        if (
            table_exists(conn, "season_team")
            and table_exists(conn, "season")
            and has_columns(conn, "season_team", ["season_year"])
        ):
            safe_execute(conn, """
                ALTER TABLE season_team
                ADD CONSTRAINT fk_season_team_season
                FOREIGN KEY (season_year)
                REFERENCES season (season_year)
            """, "fk_season_team_season")

        if (
            table_exists(conn, "season_team")
            and table_exists(conn, "team")
            and has_columns(conn, "season_team", ["team_id"])
        ):
            safe_execute(conn, """
                ALTER TABLE season_team
                ADD CONSTRAINT fk_season_team_team
                FOREIGN KEY (team_id)
                REFERENCES team (team_id)
            """, "fk_season_team_team")

    print("\nDONE: SURROGATE KEY CONSTRAINTS APPLIED.")


if __name__ == "__main__":
    main()