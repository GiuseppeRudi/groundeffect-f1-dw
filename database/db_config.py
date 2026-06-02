from __future__ import annotations

import os
import re
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.getenv(
    "F1_PROJECT_DATABASE_URL",
    "postgresql+psycopg://postgres:rudi@localhost:5432/f1_project",
)


# ============================================================
# PROJECT SCHEMAS
# ============================================================

SCHEMAS = {
    "raw": "raw",
    "reconciled": "reconciled",
    "reconciled_clean": "reconciled_clean",
    "warehouse": "warehouse",
}


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")



def normalize_schema(schema: str) -> str:
    """
    Return the real PostgreSQL schema name.

    Accepted values:
    - raw
    - reconciled
    - reconciled_clean
    - warehouse
    """
    key = schema.strip().lower()

    if key not in SCHEMAS:
        raise ValueError(
            f"Unknown schema {schema!r}. "
            f"Allowed schemas are: {list(SCHEMAS.keys())}"
        )

    return SCHEMAS[key]


def quote_identifier(identifier: str) -> str:
    """
    Safely quote a PostgreSQL identifier.
    """
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")

    return f'"{identifier}"'


def drop_public_schema_if_exists(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))


@lru_cache(maxsize=1)
def get_base_engine() -> Engine:
    """
    Return the base engine connected to the physical database.
    """
    return create_engine(DATABASE_URL)


def create_schema_if_not_exists(schema: str) -> str:
    """
    Create the selected schema if it does not already exist.
    """
    schema_name = normalize_schema(schema)

    with get_base_engine().begin() as conn:
        conn.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(schema_name)}")
        )

    return schema_name


@lru_cache(maxsize=None)
def get_engine(schema: str) -> tuple[Engine, str]:
    """
    Return a tuple containing:

    - the SQLAlchemy engine connected to the project database;
    - the selected PostgreSQL schema name.

    Example:
        engine, schema = get_engine("raw")
        engine, schema = get_engine("reconciled")
        engine, schema = get_engine("reconciled_clean")
        engine, schema = get_engine("data_warehouse")
    """
    drop_public_schema_if_exists
    schema_name = create_schema_if_not_exists(schema)

    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "options": f"-csearch_path={schema_name}"
        },
    )
    return engine, schema_name
