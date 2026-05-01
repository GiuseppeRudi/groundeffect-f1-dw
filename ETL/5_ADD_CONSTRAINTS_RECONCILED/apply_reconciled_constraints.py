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


def safe_execute(conn, sql: str, label: str) -> None:
    print(f"APPLYING: {label}")
    conn.execute(text(sql))


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:

        # ----------------------------------------------------
        # PRIMARY KEYS
        # ----------------------------------------------------
        if table_exists(conn, "season"):
            safe_execute(conn, """
                ALTER TABLE season
                ADD PRIMARY KEY (season_year)
            """, "pk_season")

        if table_exists(conn, "driver"):
            safe_execute(conn, """
                ALTER TABLE driver
                ADD PRIMARY KEY (driver_id)
            """, "pk_driver")

        if table_exists(conn, "team"):
            safe_execute(conn, """
                ALTER TABLE team
                ADD PRIMARY KEY (team_id)
            """, "pk_team")

        if table_exists(conn, "grand_prix"):
            safe_execute(conn, """
                ALTER TABLE grand_prix
                ADD PRIMARY KEY (season_year, round_number)
            """, "pk_grand_prix")

        if table_exists(conn, "session"):
            safe_execute(conn, """
                ALTER TABLE session
                ADD PRIMARY KEY (season_year, round_number, session_type)
            """, "pk_session")

        if table_exists(conn, "season_driver"):
            safe_execute(conn, """
                ALTER TABLE season_driver
                ADD PRIMARY KEY (season_year, driver_id)
            """, "pk_season_driver")

        if table_exists(conn, "season_team"):
            safe_execute(conn, """
                ALTER TABLE season_team
                ADD PRIMARY KEY (season_year, team_id)
            """, "pk_season_team")

        if table_exists(conn, "result"):
            safe_execute(conn, """
                ALTER TABLE result
                ADD PRIMARY KEY (season_year, round_number, session_type, driver_id)
            """, "pk_result")

        if table_exists(conn, "lap"):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD PRIMARY KEY (season_year, round_number, session_type, driver_id, lap_number)
            """, "pk_lap")

        if table_exists(conn, "weather"):
            safe_execute(conn, """
                ALTER TABLE weather
                ADD PRIMARY KEY (season_year, round_number, session_type, time_ms)
            """, "pk_weather")

        if table_exists(conn, "track_status"):
            safe_execute(conn, """
                ALTER TABLE track_status
                ADD PRIMARY KEY (season_year, round_number, session_type, time_ms)
            """, "pk_track_status")

        # ----------------------------------------------------
        # FOREIGN KEYS
        # ----------------------------------------------------
        if table_exists(conn, "grand_prix") and table_exists(conn, "season"):
            safe_execute(conn, """
                ALTER TABLE grand_prix
                ADD CONSTRAINT fk_grand_prix_season
                FOREIGN KEY (season_year)
                REFERENCES season (season_year)
            """, "fk_grand_prix_season")

        if table_exists(conn, "session") and table_exists(conn, "grand_prix"):
            safe_execute(conn, """
                ALTER TABLE session
                ADD CONSTRAINT fk_session_grand_prix
                FOREIGN KEY (season_year, round_number)
                REFERENCES grand_prix (season_year, round_number)
            """, "fk_session_grand_prix")

        if table_exists(conn, "season_driver") and table_exists(conn, "season"):
            safe_execute(conn, """
                ALTER TABLE season_driver
                ADD CONSTRAINT fk_season_driver_season
                FOREIGN KEY (season_year)
                REFERENCES season (season_year)
            """, "fk_season_driver_season")

        if table_exists(conn, "season_driver") and table_exists(conn, "driver"):
            safe_execute(conn, """
                ALTER TABLE season_driver
                ADD CONSTRAINT fk_season_driver_driver
                FOREIGN KEY (driver_id)
                REFERENCES driver (driver_id)
            """, "fk_season_driver_driver")

        if table_exists(conn, "season_team") and table_exists(conn, "season"):
            safe_execute(conn, """
                ALTER TABLE season_team
                ADD CONSTRAINT fk_season_team_season
                FOREIGN KEY (season_year)
                REFERENCES season (season_year)
            """, "fk_season_team_season")

        if table_exists(conn, "season_team") and table_exists(conn, "team"):
            safe_execute(conn, """
                ALTER TABLE season_team
                ADD CONSTRAINT fk_season_team_team
                FOREIGN KEY (team_id)
                REFERENCES team (team_id)
            """, "fk_season_team_team")

        if table_exists(conn, "result") and table_exists(conn, "session"):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT fk_result_session
                FOREIGN KEY (season_year, round_number, session_type)
                REFERENCES session (season_year, round_number, session_type)
            """, "fk_result_session")

        if table_exists(conn, "result") and table_exists(conn, "driver"):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT fk_result_driver
                FOREIGN KEY (driver_id)
                REFERENCES driver (driver_id)
            """, "fk_result_driver")

        if table_exists(conn, "result") and table_exists(conn, "team"):
            safe_execute(conn, """
                ALTER TABLE result
                ADD CONSTRAINT fk_result_team
                FOREIGN KEY (team_id)
                REFERENCES team (team_id)
            """, "fk_result_team")

        if table_exists(conn, "lap") and table_exists(conn, "session"):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT fk_lap_session
                FOREIGN KEY (season_year, round_number, session_type)
                REFERENCES session (season_year, round_number, session_type)
            """, "fk_lap_session")

        if table_exists(conn, "lap") and table_exists(conn, "driver"):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT fk_lap_driver
                FOREIGN KEY (driver_id)
                REFERENCES driver (driver_id)
            """, "fk_lap_driver")

        if table_exists(conn, "lap") and table_exists(conn, "team"):
            safe_execute(conn, """
                ALTER TABLE lap
                ADD CONSTRAINT fk_lap_team
                FOREIGN KEY (team_id)
                REFERENCES team (team_id)
            """, "fk_lap_team")

        if table_exists(conn, "weather") and table_exists(conn, "session"):
            safe_execute(conn, """
                ALTER TABLE weather
                ADD CONSTRAINT fk_weather_session
                FOREIGN KEY (season_year, round_number, session_type)
                REFERENCES session (season_year, round_number, session_type)
            """, "fk_weather_session")

        if table_exists(conn, "track_status") and table_exists(conn, "session"):
            safe_execute(conn, """
                ALTER TABLE track_status
                ADD CONSTRAINT fk_track_status_session
                FOREIGN KEY (season_year, round_number, session_type)
                REFERENCES session (season_year, round_number, session_type)
            """, "fk_track_status_session")

    print("\nDONE: CONSTRAINTS APPLIED.")


if __name__ == "__main__":
    main()