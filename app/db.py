from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg import Connection


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://economy:economy@localhost:5432/economy",
)


def get_connection() -> Connection:
    return psycopg.connect(DATABASE_URL)


def wait_for_db(max_attempts: int = 20, delay_seconds: float = 1.0) -> None:
    last_error = None

    for _ in range(max_attempts):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
            return
        except Exception as error:
            last_error = error
            time.sleep(delay_seconds)

    raise RuntimeError(f"Database did not become ready: {last_error}")


def init_db() -> None:
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    wait_for_db()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()