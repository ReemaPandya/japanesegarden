from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Path
from fastapi.responses import JSONResponse

from app.db import get_connection, init_db
from app.idempotency import (
    IdempotencyConflict,
    InvalidIdempotencyKey,
    MissingIdempotencyKey,
    validate_idempotency_key,
)
from app.schemas import CreditRequest, MAX_TEXT_LENGTH
from app.service import credit_wallet


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
            cur.execute("SELECT 1 AS ok;")
            result = cur.fetchone()

    return {
        "status": "ok",
        "db": result["ok"],
    }


@app.post("/v1/wallets/{playerId}/credit")
def credit_player_wallet(
    playerId: Annotated[str, Path(min_length=1, max_length=MAX_TEXT_LENGTH)],
    body: CreditRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    try:
        clean_key = validate_idempotency_key(idempotency_key)
    except MissingIdempotencyKey as error:
        raise HTTPException(status_code=400, detail=str(error))
    except InvalidIdempotencyKey as error:
        raise HTTPException(status_code=400, detail=str(error))

    try:
        status_code, response_body = credit_wallet(
            player_id=playerId,
            request=body,
            idempotency_key=clean_key,
        )
    except IdempotencyConflict as error:
        raise HTTPException(status_code=409, detail=str(error))

    return JSONResponse(status_code=status_code, content=response_body)