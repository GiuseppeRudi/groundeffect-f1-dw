from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


def read_table(
    engine: Engine,
    schema_name: str,
    table_name: str
) -> pd.DataFrame:
    """
    Read a full table from PostgreSQL and return it as a pandas DataFrame.
    """

    query = text(f'SELECT * FROM "{schema_name}"."{table_name}"')

    with engine.connect() as conn:
        return pd.read_sql_query(query, conn)


def read_tables(
    engine: Engine,
    schema_name: str,
    table_names: list[str]
) -> dict[str, pd.DataFrame]:

    tables: dict[str, pd.DataFrame] = {}

    for table_name in table_names:
        print(f"[INFO] Reading table: {schema_name}.{table_name}")
        tables[table_name] = read_table(
            engine=engine,
            schema_name=schema_name,
            table_name=table_name,
        )

    return tables


def read_configured_tables(
    engine: Engine,
    schema_name: str,
    table_rules: dict
) -> dict[str, pd.DataFrame]:

    return read_tables(
        engine=engine,
        schema_name=schema_name,
        table_names=list(table_rules.keys()),
    )



def load_tables(
    engine,
    schema: str,
    table_names: list[str],
) -> dict[str, pd.DataFrame]:

    tables: dict[str, pd.DataFrame] = {}

    with engine.connect() as conn:
        for table_name in table_names:
            query = text(f'SELECT * FROM "{schema}"."{table_name}"')

            try:
                df = pd.read_sql(query, conn)
                tables[table_name] = df
                print(f"LOADED: {schema}.{table_name} ({len(df)} rows)")

            except Exception as e:
                print(f"WARNING: could not load {schema}.{table_name}")
                print(f"Reason: {e}")

    return tables
