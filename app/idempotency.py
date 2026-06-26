from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from psycopg import Cursor
from psycopg.types.json import Json


MAX_IDEMPOTENCY_KEY_LENGTH = 128


class MissingIdempotencyKey(Exception):
    pass


class InvalidIdempotencyKey(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


@dataclass
class IdempotencyResult:
    is_duplicate: bool
    status_code: int | None = None
    response_body: dict[str, Any] | None = None


def validate_idempotency_key(idempotency_key: str | None) -> str:
    if idempotency_key is None or not idempotency_key.strip():
        raise MissingIdempotencyKey("Idempotency-Key header is required.")

    clean_key = idempotency_key.strip()

    if len(clean_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidIdempotencyKey("Idempotency-Key is too long.")

    return clean_key


def hash_request_body(request_body: dict[str, Any]) -> str:
    canonical = json.dumps(
        request_body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def begin_idempotent_request(
    cur: Cursor,
    *,
    idempotency_key: str,
    method: str,
    endpoint: str,
    request_body: dict[str, Any],
) -> IdempotencyResult:
    request_hash = hash_request_body(request_body)

    cur.execute(
        """
        INSERT INTO idempotency_requests (
            idempotency_key,
            method,
            endpoint,
            request_hash,
            status
        )
        VALUES (%s, %s, %s, %s, 'processing')
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING idempotency_key;
        """,
        (idempotency_key, method, endpoint, request_hash),
    )

    inserted = cur.fetchone()

    if inserted is not None:
        return IdempotencyResult(is_duplicate=False)

    cur.execute(
        """
        SELECT
            method,
            endpoint,
            request_hash,
            status,
            status_code,
            response_body
        FROM idempotency_requests
        WHERE idempotency_key = %s
        FOR UPDATE;
        """,
        (idempotency_key,),
    )

    existing = cur.fetchone()

    if existing is None:
        raise IdempotencyConflict("Idempotency state could not be read.")

    same_request = (
        existing["method"] == method
        and existing["endpoint"] == endpoint
        and existing["request_hash"] == request_hash
    )

    if not same_request:
        raise IdempotencyConflict(
            "Idempotency-Key was already used for a different request."
        )

    if existing["status"] != "completed":
        raise IdempotencyConflict("Request is still processing. Retry shortly.")

    return IdempotencyResult(
        is_duplicate=True,
        status_code=existing["status_code"],
        response_body=existing["response_body"],
    )


def complete_idempotent_request(
    cur: Cursor,
    *,
    idempotency_key: str,
    status_code: int,
    response_body: dict[str, Any],
) -> None:
    cur.execute(
        """
        UPDATE idempotency_requests
        SET
            status = 'completed',
            status_code = %s,
            response_body = %s,
            updated_at = now()
        WHERE idempotency_key = %s;
        """,
        (status_code, Json(response_body), idempotency_key),
    )