from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


# ============================================================
# DATABASE URLS
# ============================================================

RECONCILED_DATABASE_URL = os.getenv(
    "RECONCILED_DATABASE_URL",
    "postgresql+psycopg://postgres:rudi@localhost:5432/f1_reconciled",
)

DW_DATABASE_URL = os.getenv(
    "DW_DATABASE_URL",
    "postgresql+psycopg://postgres:rudi@localhost:5432/f1_dw",
)


# ============================================================
# SCHEMAS
# ============================================================

RECONCILED_SCHEMA = os.getenv("RECONCILED_SCHEMA", "public")

DW_SCHEMA = os.getenv("DW_SCHEMA", "public")


# ============================================================
# CONNECTION HELPERS
# ============================================================

def get_reconciled_engine() -> Engine:
    return create_engine(RECONCILED_DATABASE_URL)


def get_dw_engine() -> Engine:
    return create_engine(DW_DATABASE_URL)


def get_reconciled_schema() -> str:
    return RECONCILED_SCHEMA


def get_dw_schema() -> str:
    return DW_SCHEMA



def get_engine(database: str) -> Engine:

    if database == "reconciled":
        return get_reconciled_engine()

    if database == "dw":
        return get_dw_engine()

    raise ValueError("database must be either 'reconciled' or 'dw'")


def get_schema(database: str) -> str:
    if database == "reconciled":
        return get_reconciled_schema()

    if database == "dw":
        return get_dw_schema()

    raise ValueError("database must be either 'reconciled' or 'dw'")