from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import fastf1
from fastf1.ergast import Ergast

# ============================================================
# CONFIG
# ============================================================

OUTPUT_DIR_RECONCILED = Path("f1_data_reconciled")
OUTPUT_DIR_RAW        = Path("f1_raw_api_data")
LOG = Path("")


INPUT_EXTERNAL_DATA = Path("f1_extern_data")

CACHE_DIR = Path("fastf1_cache")


# ============================================================
# HELPERS
# ============================================================

def ensure_dirs() -> None:
    OUTPUT_DIR_RAW.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR_RECONCILED.mkdir(parents=True , exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

def read_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)

    else : 
        raise FileNotFoundError(f"File not found: {path}")


def normalize_timedelta_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    CONVERT TIMEDDELTA COLUMNS TO INTEGER MILLISECONDS
    AND RENAME THEM WITH _MS SUFFIX FOR DATABASE CLARITY.
    """
    df = df.copy()

    rename_map = {}

    for col in df.columns:
        if pd.api.types.is_timedelta64_dtype(df[col]):
            df[col] = (df[col].dt.total_seconds() * 1000).round().astype("Int64")
            rename_map[col] = f"{col}_ms"

    df = df.rename(columns=rename_map)
    return df


def normalize_text_for_match(value: object) -> str:

    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text

def export_dataframe(df: pd.DataFrame, name: str, output_dir : Path) -> None:
    path = output_dir / f"{name}.csv"
    df.to_csv(path, index=False)



def load_ergast_masterdata(seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:

    ergast = Ergast(
        result_type="pandas",
        auto_cast=True,
        limit=1000
    )

    # DF RECONCILED 

    driver_reconciled_dfs: list[pd.DataFrame] = []
    constructor_reconciled_dfs: list[pd.DataFrame] = []

    # DF RAW 
    driver_raw_dfs : list[pd.DataFrame] = []
    constructor_raw_dfs : list[pd.DataFrame] = []

    for season in seasons:

        # -----------------------------
        # DRIVERS
        # -----------------------------
        driver = ergast.get_driver_info(season=season).copy()

        # print(driver.columns)

        # 'driverId', 'driverNumber', 'driverCode', 'driverUrl', 'givenName',
        # 'familyName', 'dateOfBirth', 'driverNationality'

        driver_reconciled_dfs.append(driver)
        driver_raw_dfs.append(driver)

        # -----------------------------
        # TEAMS
        # -----------------------------

        constructor = ergast.get_constructor_info(season=season).copy()

        # print(constructor.columns)
        #  'constructorId', 'constructorUrl', 'constructorName',
        #  'constructorNationality'


        constructor_reconciled_dfs.append(constructor)
        constructor_raw_dfs.append(constructor)


    driver_reconciled_df = (
        pd.concat(driver_reconciled_dfs, ignore_index=True)
        .drop_duplicates(subset=["driverId"])
        .rename(columns={
            "driverId": "DriverId",
            "driverNumber": "PermanentNumber",
            "driverCode": "Abbreviation",
            "givenName": "FirstName",
            "familyName": "LastName",
            "dateOfBirth": "DateOfBirth",
            "driverNationality": "Nationality",
            "driverUrl": "DriverUrl"
        })
        .sort_values(by=["DriverId"], kind="stable")
        .reset_index(drop=True)
    )

    team_reconciled_df = (
        pd.concat(constructor_reconciled_dfs, ignore_index=True)
        .drop_duplicates(subset=["constructorId"])
        .rename(columns={
            "constructorId": "TeamId",
            "constructorName": "TeamName",
            "constructorNationality": "Nationality",
            "constructorUrl": "TeamUrl"
        })
        .sort_values(by=["TeamId"], kind="stable")
        .reset_index(drop=True)
    )



    driver_raw_df = pd.concat(driver_raw_dfs, ignore_index=True)
    constructor_raw_df = pd.concat(constructor_raw_dfs, ignore_index=True)

    return driver_reconciled_df, team_reconciled_df, driver_raw_df, constructor_raw_df


def enrich_laps_with_ids(
    laps_df: pd.DataFrame,
    results_df: pd.DataFrame
) -> pd.DataFrame:

    out = laps_df.copy()

    required_lap_cols = {"SessionId", "DriverNumber"}
    required_result_cols = {"SessionId", "DriverNumber", "DriverId", "TeamId"}

    if not required_lap_cols.issubset(out.columns):
        raise ValueError(f"laps_df missing columns: {required_lap_cols - set(out.columns)}")

    if not required_result_cols.issubset(results_df.columns):
        raise ValueError(f"results_df missing columns: {required_result_cols - set(results_df.columns)}")

    map_by_number = results_df[
        ["SessionId", "DriverNumber", "DriverId", "TeamId"]
    ].drop_duplicates()

    out = out.merge(
        map_by_number,
        on=["SessionId", "DriverNumber"],
        how="left",
        validate="m:1"
    )

    return out


def enrich_events_with_circuit_id(
    event_df: pd.DataFrame,
    circuit_df: pd.DataFrame
) -> pd.DataFrame:


    events = event_df.copy()
    circuits = circuit_df.copy()

    # normalize join keys
    events["Country_match"] = events["Country"].apply(normalize_text_for_match)
    events["Location_match"] = events["Location"].apply(normalize_text_for_match)

    circuits["Country_match"] = circuits["Country"].apply(normalize_text_for_match)
    circuits["Location_match"] = circuits["Location"].apply(normalize_text_for_match)

    # keep only needed columns from circuit
    circuit_lookup = circuits[
        ["CircuitId", "Country_match", "Location_match"]
    ].drop_duplicates()

    enriched = events.merge(
        circuit_lookup,
        on=["Country_match", "Location_match"],
        how="left",
        validate="m:1"
    )

    # drop technical columns
    enriched = enriched.drop(columns=["Country_match", "Location_match"])

    return enriched



def main() -> None:


    # check if the directory already exists 
    ensure_dirs()

    # enable FastF1 cache
    fastf1.Cache.enable_cache(str(CACHE_DIR))

    seasons_df = read_csv(INPUT_EXTERNAL_DATA / "season.csv")

    
    # 1 - We load the ‘season’ table from the CSV file 
    # 2 - For each row, we extract the ‘year’ column 
    # 3 - We save the file back to the ‘output_dir_reconciled’ directory as is 
    # 4 - We use all the years listed in the ‘season’ row to retrieve data from the API

    YEARS = seasons_df["SeasonYear"].tolist()

    circuit_df = read_csv(INPUT_EXTERNAL_DATA / "circuit.csv")

    driver_reconciled_df, team_reconciled_df, driver_raw_df, constructor_raw_df = load_ergast_masterdata(YEARS)

    # Raw DF 
    schedule_raw_dfs : list[pd.DataFrame] = []
    result_raw_dfs : list[pd.DataFrame] = []
    lap_raw_dfs: list[pd.DataFrame] = []
    weather_raw_dfs : list[pd.DataFrame] = []
    track_status_raw_dfs : list[pd.DataFrame] = []

    # Reconciled DF
    grand_prix_reconciled_dfs : list[pd.DataFrame] = []
    session_reconciled_dfs : list[pd.DataFrame] = []
    result_reconciled_dfs : list[pd.DataFrame] = []
    lap_reconciled_dfs: list[pd.DataFrame] = []
    weather_reconciled_dfs : list[pd.DataFrame] = []
    track_status_reconciled_dfs : list[pd.DataFrame] = []

    # LOG 
    extraction_log_rows: list[dict[str, Any]] = []

    GRAND_PRIX_COLUMNS = [
        "SeasonYear",
        "RoundNumber",
        "EventName",
        "OfficialEventName",
        "Country",
        "Location",
        "EventDate",
        "EventFormat",
        "F1ApiSupport",
        "CircuitId"
    ]

    SESSION_TYPES = ["Q", "R"]


    grand_prix_id = 1
    session_id = 1
    result_id = 1
    lap_id = 1
    weather_id = 1
    track_status_id = 1

    for year in YEARS:
        print(f"\n=== Loading event schedule for {year} ===")

        # return all the schedule for each year 
        schedule_raw_df = fastf1.get_event_schedule(year).copy()
        # schedule_raw_df.shape(numbers of events , columns = 23 )  numbers of event in 2021 = 23 , 2022 = 24 

        # schedule_raw_df.columns() => 
        #     'RoundNumber', 'Country', 'Location', 'OfficialEventName', 'EventDate',
        #     'EventName', 'EventFormat', 'Session1', 'Session1Date',
        #     'Session1DateUtc', 'Session2', 'Session2Date', 'Session2DateUtc',
        #     'Session3', 'Session3Date', 'Session3DateUtc', 'Session4',
        #     'Session4Date', 'Session4DateUtc', 'Session5', 'Session5Date',
        #     'Session5DateUtc', 'F1ApiSupport']

        # print(schedule_raw_df.shape)
        # print(schedule_raw_df.head())
        # print(schedule_raw_df.tail())
        # print(schedule_raw_df.columns)

        schedule_raw_dfs.append(schedule_raw_df)

        # after we add another columns that contain the season year 
        schedule_reconciled_df = schedule_raw_df.copy()

        schedule_reconciled_df["SeasonYear"] = year

        schedule_reconciled_df = schedule_reconciled_df[
            schedule_reconciled_df["EventFormat"].str.lower() != "testing"
        ].copy()
        
        schedule_reconciled_df = enrich_events_with_circuit_id(
            schedule_reconciled_df,
            circuit_df
        )

        # Manually Check
        missing_circuit = schedule_reconciled_df[schedule_reconciled_df["CircuitId"].isna()]

        if not missing_circuit.empty:
            print("WARNING: some events have no CircuitId match")
            print(missing_circuit[["SeasonYear", "RoundNumber", "EventName", "Country", "Location"]])

        grand_prix_df = schedule_reconciled_df[GRAND_PRIX_COLUMNS].copy()


        num_grand_prix = len(grand_prix_df)

        grand_prix_df.insert(
            0,
            "GrandPrixId",
            range(grand_prix_id, grand_prix_id + num_grand_prix)
        )

        grand_prix_id += num_grand_prix
        
        grand_prix_reconciled_dfs.append(grand_prix_df)

        # ---------------------------------
        # Session 
        # ---------------------------------
        for _, grand_prix_row in grand_prix_df.iterrows():

            round_number = int(grand_prix_row["RoundNumber"])
            event_format = str(grand_prix_row["EventFormat"])
            grand_prix_id = int(grand_prix_row["GrandPrixId"])
            
            for session_type in SESSION_TYPES:

                log_record = {
                            "GrandPrixId": grand_prix_id,
                            "SeasonYear": year,
                            "RoundNumber": round_number,
                            "EventFormat": event_format,
                            "SessionType": session_type,
                            "Status": "STARTED",
                            "Error": None,
                        }

                print(f"  -> {year} | Round {round_number:02d} | {session_type}")

                try:
     
                    session = fastf1.get_session(year, round_number, session_type)

                    # print(session.columns())
                    session.load(
                        laps=True,
                        telemetry=False,
                        weather=True,
                        messages=False,
                    )


                    session_df = pd.DataFrame([{
                        "SessionId" : session_id,
                        "GrandPrixId": grand_prix_id,
                        "SessionType": session_type,
                        "SessionName": session.name,
                        "SessionDate": session.date
                    }])

                    session_reconciled_dfs.append(session_df)


                    # --------------------------
                    # SessionResult
                    # --------------------------
                    results_raw_df = session.results.copy()

                    #print(results_raw_df.columns) 
                    # 'DriverNumber', 'BroadcastName', 'Abbreviation', 'DriverId', 'TeamName',
                    # 'TeamColor', 'TeamId', 'FirstName', 'LastName', 'FullName',
                    # 'HeadshotUrl', 'CountryCode', 'Position', 'ClassifiedPosition',
                    # 'GridPosition', 'Q1', 'Q2', 'Q3', 'Time', 'Status', 'Points', 'Laps'

                    result_raw_dfs.append(results_raw_df)
                    
                    results_tmp_df = results_raw_df.copy()


                    results_tmp_df = normalize_timedelta_columns(results_tmp_df)
                    results_tmp_df = results_tmp_df.reset_index(drop=True)
    
                    results_tmp_df["SessionId"] = session_id

                    num_results = len(results_tmp_df)

                    results_tmp_df.insert(
                        0,
                        "ResultId",
                        range(result_id, result_id + num_results)
                    )

                    result_id += num_results
            
                    results_reconciled_df = results_tmp_df[
                        [
                            "ResultId",
                            "SessionId",
                            "DriverId",
                            "TeamId",
                            "Position",
                            "ClassifiedPosition",
                            "GridPosition",
                            "Q1_ms",
                            "Q2_ms",
                            "Q3_ms",
                            "Time_ms",
                            "Status",
                            "Points",
                            "Laps",
                        ]
                    ].copy()

                    result_reconciled_dfs.append(results_reconciled_df)

                    # --------------------------
                    # Laps 
                    # --------------------------

                    laps_raw_df = session.laps.copy()

                    lap_raw_dfs.append(laps_raw_df)

                    laps_reconciled_df = normalize_timedelta_columns(laps_raw_df)

                    # print(laps_reconciled_df.columns)

                    # 'Time_ms', 'Driver', 'DriverNumber', 'LapTime_ms', 'LapNumber', 'Stint',
                    # 'PitOutTime_ms', 'PitInTime_ms', 'Sector1Time_ms', 'Sector2Time_ms',
                    # 'Sector3Time_ms', 'Sector1SessionTime_ms', 'Sector2SessionTime_ms',
                    # 'Sector3SessionTime_ms', 'SpeedI1', 'SpeedI2', 'SpeedFL', 'SpeedST',
                    # 'IsPersonalBest', 'Compound', 'TyreLife', 'FreshTyre', 'Team',
                    # 'LapStartTime_ms', 'LapStartDate', 'TrackStatus', 'Position', 'Deleted',
                    # 'DeletedReason', 'FastF1Generated', 'IsAccurate'

   
                    laps_reconciled_df["SessionId"] = session_id


                    num_results = len(laps_reconciled_df)

                    laps_reconciled_df.insert(
                        0,
                        "LapId",
                        range(lap_id, lap_id + num_results)
                    )

                    lap_id += num_results
                    
                    laps_reconciled_df = enrich_laps_with_ids(laps_reconciled_df, results_tmp_df)


                    # list of laps dataframe for all the session of all the event weekend in a certain season
                    lap_reconciled_dfs.append(laps_reconciled_df)

                    # --------------------------
                    # Weather
                    # --------------------------
                
                    
                    weather_raw = session.weather_data.copy()

                    #print(weather_raw.columns)
                    
                    # 'Time', 'AirTemp', 'Humidity', 'Pressure', 'Rainfall', 'TrackTemp',
                    # 'WindDirection', 'WindSpeed'

                    weather_raw_dfs.append(weather_raw)


                    weather_reconciled = weather_raw.copy()
                    weather_reconciled = normalize_timedelta_columns(weather_reconciled)

                    weather_reconciled["SessionId"] = session_id
                    num_results = len(weather_reconciled)


                    weather_reconciled.insert(
                        0,
                        "WeatherId",
                        range(weather_id, weather_id + num_results)
                    )

                    weather_id += num_results

                    # list of weather dataframe for all the session of all the event weekend in a certain season
                    weather_reconciled_dfs.append(weather_reconciled)

                    # --------------------------
                    # Track status
                    # --------------------------

                    track_status_raw = session.track_status.copy()

                    # print(track_status_raw.columns)
                    # 'Time', 'Status', 'Message'
                    
                    track_status_raw_dfs.append(track_status_raw)

                    track_status_reconciled = track_status_raw.copy()
                    track_status_reconciled = normalize_timedelta_columns(track_status_reconciled)

                    track_status_reconciled["SessionId"] = session_id
                    
                    num_results = len(track_status_reconciled)

                    track_status_reconciled.insert(
                        0,
                        "TrackStatusId",
                        range(track_status_id, track_status_id + num_results)
                    )

                    track_status_id += num_results

                    # list of track status dataframe for all the session of all the event weekend in a certain season
                    track_status_reconciled_dfs.append(track_status_reconciled)

                    
                    session_id += 1    

                    log_record["Status"] = "OK"

                except Exception as exc:
                    log_record["Status"] = "FAILED"
                    log_record["Error"] = repr(exc)
                    print(f"     FAILED: {exc}")

                extraction_log_rows.append(log_record)

    # ============================================================
    # BUILD FINAL TABLES
    # ============================================================

    # RECONCILED DF 
    grand_prix_df = pd.concat(grand_prix_reconciled_dfs, ignore_index= True)
    sessions_df = pd.concat(session_reconciled_dfs, ignore_index=True)
    session_results_reconciled_df = pd.concat(result_reconciled_dfs, ignore_index= True)
    laps_reconciled_df = pd.concat(lap_reconciled_dfs, ignore_index=True)
    weather_reconciled_df = pd.concat(weather_reconciled_dfs, ignore_index= True)
    track_status_reconciled_df = pd.concat(track_status_reconciled_dfs, ignore_index= True)

    # RAW DF 
    schedules_df = pd.concat(schedule_raw_dfs, ignore_index=True)
    session_results_raw_df = pd.concat(result_raw_dfs, ignore_index= True)
    laps_raw_df = pd.concat(lap_raw_dfs, ignore_index=True)
    weather_raw_df = pd.concat(weather_raw_dfs,ignore_index= True)
    track_status_raw_df = pd.concat(track_status_raw_dfs, ignore_index= True)

    # LOG
    extraction_log_df = pd.DataFrame(extraction_log_rows)

    # ============================================================
    # EXPORT
    # ============================================================

    # RAW 
    export_dataframe(schedules_df, "schedule_raw", OUTPUT_DIR_RAW)
    export_dataframe(driver_raw_df, "driver_raw", OUTPUT_DIR_RAW)
    export_dataframe(constructor_raw_df, "team_raw", OUTPUT_DIR_RAW)
    export_dataframe(session_results_raw_df,  "result_raw", OUTPUT_DIR_RAW)
    export_dataframe(laps_raw_df, "lap_raw", OUTPUT_DIR_RAW)
    export_dataframe(weather_raw_df, "weather_raw", OUTPUT_DIR_RAW)
    export_dataframe(track_status_raw_df, "track_status_raw", OUTPUT_DIR_RAW)

    # RECONCILED

    # Domain Knowlodge Tables
    export_dataframe(seasons_df, "season", OUTPUT_DIR_RECONCILED)
    export_dataframe(circuit_df, "circuit", OUTPUT_DIR_RECONCILED)

    export_dataframe(grand_prix_df, "grand_prix", OUTPUT_DIR_RECONCILED)
    export_dataframe(sessions_df, "session" , OUTPUT_DIR_RECONCILED)


    export_dataframe(driver_reconciled_df, "driver", OUTPUT_DIR_RECONCILED)
    export_dataframe(team_reconciled_df, "team", OUTPUT_DIR_RECONCILED)

    export_dataframe(session_results_reconciled_df, "result", OUTPUT_DIR_RECONCILED)
    export_dataframe(laps_reconciled_df, "lap", OUTPUT_DIR_RECONCILED)
    export_dataframe(weather_reconciled_df, "weather", OUTPUT_DIR_RECONCILED)
    export_dataframe(track_status_reconciled_df, "track_status",OUTPUT_DIR_RECONCILED)


    # LOG 
    export_dataframe(extraction_log_df, "extraction_log", LOG)


    print("\n=== DONE ===")

if __name__ == "__main__":
    main()