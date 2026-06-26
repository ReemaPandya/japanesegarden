from __future__ import annotations

from fastapi import FastAPI

from app.db import get_connection, init_db


app = FastAPI(
    title="Durable Game Economy Service",
    description="Wallet/economy service focused on idempotency, durability, and concurrency correctness.",
    version="0.1.0",
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/db-health")
def db_health() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            result = cur.fetchone()

    return {
        "status": "ok",
        "db": result[0],
    }