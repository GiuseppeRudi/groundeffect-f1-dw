CREATE TABLE season (
    season_year BIGINT,
    season_start_date TIMESTAMP,
    season_end_date TIMESTAMP,
    number_of_events BIGINT,
    champion_driver TEXT,
    champion_team TEXT
);

CREATE TABLE circuit (
    circuit_id TEXT,
    circuit_name TEXT,
    country TEXT,
    location TEXT,
    seasons_present TEXT,
    global_circuit_category TEXT,
    sector1_category TEXT,
    sector2_category TEXT,
    sector3_category TEXT
);

CREATE TABLE driver (
    driver_id TEXT,
    permanent_number DOUBLE PRECISION,
    abbreviation TEXT,
    first_name TEXT,
    last_name TEXT,
    date_of_birth TIMESTAMP,
    nationality TEXT,
    driver_url TEXT
);

CREATE TABLE team (
    team_id TEXT,
    team_name TEXT,
    nationality TEXT,
    team_url TEXT
);

CREATE TABLE grand_prix (
    grand_prix_id BIGINT,
    season_year BIGINT,
    round_number BIGINT,
    event_name TEXT,
    official_event_name TEXT,
    country TEXT,
    location TEXT,
    event_date TIMESTAMP,
    event_format TEXT,
    f1_api_support BOOLEAN,
    circuit_id TEXT
);

CREATE TABLE session (
    session_id BIGINT,
    grand_prix_id BIGINT,
    session_type TEXT,
    session_name TEXT,
    session_date TIMESTAMP
);

CREATE TABLE result (
    result_id BIGINT,
    session_id BIGINT,
    driver_id TEXT,
    team_id TEXT,
    position DOUBLE PRECISION,
    classified_position TEXT,
    grid_position DOUBLE PRECISION,
    q1_ms BIGINT,
    q2_ms BIGINT,
    q3_ms BIGINT,
    time_ms BIGINT,
    status TEXT,
    points DOUBLE PRECISION,
    laps DOUBLE PRECISION
);

CREATE TABLE lap (
    lap_id BIGINT,
    time_ms BIGINT,
    driver TEXT,
    driver_number BIGINT,
    lap_time_ms BIGINT,
    lap_number DOUBLE PRECISION,
    stint DOUBLE PRECISION,
    pit_out_time_ms BIGINT,
    pit_in_time_ms BIGINT,
    sector1_time_ms BIGINT,
    sector2_time_ms BIGINT,
    sector3_time_ms BIGINT,
    sector1_session_time_ms BIGINT,
    sector2_session_time_ms BIGINT,
    sector3_session_time_ms BIGINT,
    speed_i1 DOUBLE PRECISION,
    speed_i2 DOUBLE PRECISION,
    speed_fl DOUBLE PRECISION,
    speed_st DOUBLE PRECISION,
    is_personal_best BOOLEAN,
    compound TEXT,
    tyre_life DOUBLE PRECISION,
    fresh_tyre BOOLEAN,
    team TEXT,
    lap_start_time_ms BIGINT,
    lap_start_date TIMESTAMP,
    track_status TEXT,
    position DOUBLE PRECISION,
    deleted BOOLEAN,
    deleted_reason TEXT,
    fast_f1_generated BOOLEAN,
    is_accurate BOOLEAN,
    session_id BIGINT,
    driver_id TEXT,
    team_id TEXT
);

CREATE TABLE weather (
    weather_id BIGINT,
    time_ms BIGINT,
    air_temp DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    pressure DOUBLE PRECISION,
    rainfall BOOLEAN,
    track_temp DOUBLE PRECISION,
    wind_direction DOUBLE PRECISION,
    wind_speed DOUBLE PRECISION,
    session_id BIGINT
);

CREATE TABLE track_status (
    track_status_id BIGINT,
    time_ms BIGINT,
    status TEXT,
    message TEXT,
    session_id BIGINT
);