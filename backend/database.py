
from __future__ import annotations

import os
import sqlite3

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg

from dotenv import load_dotenv
from psycopg.rows import dict_row


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent

# Load environment variables from backend/.env.
load_dotenv(ROOT / ".env")

DATA_DIR = Path(
    os.getenv("DATA_DIR", str(ROOT / "data"))
).resolve()

DB_PATH = DATA_DIR / "bugfix.sqlite3"

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "",
).strip()

USE_POSTGRES = bool(DATABASE_URL)


# ============================================================
# DATABASE CONNECTION
# ============================================================

@contextmanager
def get_db() -> Iterator[Any]:
    """
    Open a database connection.

    PostgreSQL:
        Connects to Neon using DATABASE_URL.
        Uses Psycopg 3 and dictionary-style rows.
        Commits successful transactions and rolls back failures.

    SQLite:
        Uses the local database file.
        Primarily retained for legacy data migration and local
        development when DATABASE_URL is not configured.

    A configured PostgreSQL connection failure raises an error.
    The application never silently falls back to SQLite.
    """

    if USE_POSTGRES:

        connection = psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
            connect_timeout=10,
        )

    else:

        connection = sqlite3.connect(
            str(DB_PATH),
            timeout=30,
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA busy_timeout = 30000"
        )

    try:

        yield connection

        connection.commit()

    except Exception:

        connection.rollback()

        raise

    finally:

        connection.close()


# ============================================================
# SQL PLACEHOLDER
# ============================================================

def placeholder() -> str:
    """
    Return the parameter placeholder for the active database.

    PostgreSQL uses %s.
    SQLite uses ?.
    """

    return "%s" if USE_POSTGRES else "?"


# ============================================================
# DATABASE SCHEMA
# ============================================================

def create_cases_table(connection: Any) -> None:
    """
    Create the cases table if it does not already exist.

    This schema is compatible with the fields used by app.py.
    """

    if USE_POSTGRES:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id BIGSERIAL PRIMARY KEY,

                title TEXT NOT NULL,

                url TEXT NOT NULL DEFAULT '',

                technology TEXT NOT NULL DEFAULT '',

                summary TEXT NOT NULL DEFAULT '',

                problem TEXT NOT NULL,

                diagnosis TEXT NOT NULL DEFAULT '',

                solution TEXT NOT NULL,

                result TEXT NOT NULL DEFAULT '',

                image_paths TEXT NOT NULL DEFAULT '[]',

                published BOOLEAN NOT NULL DEFAULT TRUE,

                created_at BIGINT NOT NULL,

                updated_at BIGINT NOT NULL
            )
            """
        )

        # Update an existing PostgreSQL table if url is missing.
        connection.execute(
            """
            ALTER TABLE cases
            ADD COLUMN IF NOT EXISTS url TEXT NOT NULL DEFAULT ''
            """
        )

    else:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                title TEXT NOT NULL,

                url TEXT NOT NULL DEFAULT '',

                technology TEXT NOT NULL DEFAULT '',

                summary TEXT NOT NULL DEFAULT '',

                problem TEXT NOT NULL,

                diagnosis TEXT NOT NULL DEFAULT '',

                solution TEXT NOT NULL,

                result TEXT NOT NULL DEFAULT '',

                image_paths TEXT NOT NULL DEFAULT '[]',

                published INTEGER NOT NULL DEFAULT 1,

                created_at INTEGER NOT NULL,

                updated_at INTEGER NOT NULL
            )
            """
        )

        # CREATE TABLE IF NOT EXISTS does not add columns to
        # a table that already exists. Check before altering it.
        columns = connection.execute(
            "PRAGMA table_info(cases)"
        ).fetchall()

        column_names = {
            row["name"]
            for row in columns
        }

        if "url" not in column_names:

            connection.execute(
                """
                ALTER TABLE cases
                ADD COLUMN url TEXT NOT NULL DEFAULT ''
                """
            )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db() -> None:
    """
    Initialize the database schema.

    Called by app.py when FastAPI starts.

    If DATABASE_URL is configured, Neon PostgreSQL is used.
    Otherwise, the local SQLite database is initialized.
    """

    with get_db() as connection:

        create_cases_table(connection)


# ============================================================
# DATABASE HEALTH CHECK
# ============================================================

def database_status() -> dict[str, str]:
    """
    Verify that the configured database can execute a query.

    Returns a simple status dictionary without exposing
    connection credentials.
    """

    database_type = (
        "postgresql"
        if USE_POSTGRES
        else "sqlite"
    )

    with get_db() as connection:

        connection.execute(
            "SELECT 1"
        ).fetchone()

    return {
        "database": database_type,
        "status": "connected",
    }

