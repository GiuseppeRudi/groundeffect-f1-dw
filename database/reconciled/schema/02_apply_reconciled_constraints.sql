ALTER TABLE season
ADD CONSTRAINT pk_season
PRIMARY KEY (season_year);

ALTER TABLE circuit
ADD CONSTRAINT pk_circuit
PRIMARY KEY (circuit_id);

ALTER TABLE driver
ADD CONSTRAINT pk_driver
PRIMARY KEY (driver_id);

ALTER TABLE team
ADD CONSTRAINT pk_team
PRIMARY KEY (team_id);

ALTER TABLE grand_prix
ADD CONSTRAINT pk_grand_prix
PRIMARY KEY (grand_prix_id);

ALTER TABLE session
ADD CONSTRAINT pk_session
PRIMARY KEY (session_id);

ALTER TABLE result
ADD CONSTRAINT pk_result
PRIMARY KEY (result_id);

ALTER TABLE lap
ADD CONSTRAINT pk_lap
PRIMARY KEY (lap_id);

ALTER TABLE weather
ADD CONSTRAINT pk_weather
PRIMARY KEY (weather_id);

ALTER TABLE track_status
ADD CONSTRAINT pk_track_status
PRIMARY KEY (track_status_id);

ALTER TABLE grand_prix
ADD CONSTRAINT uq_grand_prix_natural
UNIQUE (season_year, round_number);

ALTER TABLE session
ADD CONSTRAINT uq_session_natural
UNIQUE (grand_prix_id, session_type);

ALTER TABLE result
ADD CONSTRAINT uq_result_natural
UNIQUE (session_id, driver_id);

ALTER TABLE lap
ADD CONSTRAINT uq_lap_natural
UNIQUE (session_id, driver_id, lap_number);

ALTER TABLE weather
ADD CONSTRAINT uq_weather_natural
UNIQUE (session_id, time_ms);

ALTER TABLE track_status
ADD CONSTRAINT uq_track_status_natural
UNIQUE (session_id, time_ms);

ALTER TABLE grand_prix
ADD CONSTRAINT fk_grand_prix_season
FOREIGN KEY (season_year)
REFERENCES season (season_year);

ALTER TABLE grand_prix
ADD CONSTRAINT fk_grand_prix_circuit
FOREIGN KEY (circuit_id)
REFERENCES circuit (circuit_id);

ALTER TABLE session
ADD CONSTRAINT fk_session_grand_prix
FOREIGN KEY (grand_prix_id)
REFERENCES grand_prix (grand_prix_id);

ALTER TABLE result
ADD CONSTRAINT fk_result_session
FOREIGN KEY (session_id)
REFERENCES session (session_id);

ALTER TABLE result
ADD CONSTRAINT fk_result_driver
FOREIGN KEY (driver_id)
REFERENCES driver (driver_id);

ALTER TABLE result
ADD CONSTRAINT fk_result_team
FOREIGN KEY (team_id)
REFERENCES team (team_id);

ALTER TABLE lap
ADD CONSTRAINT fk_lap_session
FOREIGN KEY (session_id)
REFERENCES session (session_id);

ALTER TABLE lap
ADD CONSTRAINT fk_lap_driver
FOREIGN KEY (driver_id)
REFERENCES driver (driver_id);

ALTER TABLE lap
ADD CONSTRAINT fk_lap_team
FOREIGN KEY (team_id)
REFERENCES team (team_id);

ALTER TABLE weather
ADD CONSTRAINT fk_weather_session
FOREIGN KEY (session_id)
REFERENCES session (session_id);

ALTER TABLE track_status
ADD CONSTRAINT fk_track_status_session
FOREIGN KEY (session_id)
REFERENCES session (session_id);

ALTER TABLE session
ADD CONSTRAINT ck_session_type
CHECK (session_type IN ('Q', 'R'));

ALTER TABLE grand_prix
ADD CONSTRAINT ck_grand_prix_round_positive
CHECK (round_number > 0);

ALTER TABLE lap
ADD CONSTRAINT ck_lap_number_positive
CHECK (lap_number > 0);

ALTER TABLE lap
ADD CONSTRAINT ck_lap_time_positive
CHECK (lap_time_ms IS NULL OR lap_time_ms > 0);

ALTER TABLE result
ADD CONSTRAINT ck_result_points_non_negative
CHECK (points IS NULL OR points >= 0);

ALTER TABLE weather
ADD CONSTRAINT ck_weather_wind_speed_non_negative
CHECK (wind_speed IS NULL OR wind_speed >= 0);