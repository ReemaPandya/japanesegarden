from __future__ import annotations

from typing import Any

from app.db import get_connection
from app.idempotency import begin_idempotent_request, complete_idempotent_request
from app.schemas import CreditRequest


MAX_WALLET_BALANCE = 1_000_000_000_000


def credit_wallet(
    *,
    player_id: str,
    request: CreditRequest,
    idempotency_key: str,
) -> tuple[int, dict[str, Any]]:
    endpoint = f"/v1/wallets/{player_id}/credit"
    request_body = request.model_dump()

    with get_connection() as conn:
        with conn.cursor() as cur:
            idem = begin_idempotent_request(
                cur,
                idempotency_key=idempotency_key,
                method="POST",
                endpoint=endpoint,
                request_body=request_body,
            )

            if idem.is_duplicate:
                return idem.status_code or 200, idem.response_body or {}

            cur.execute(
                """
                INSERT INTO wallets (player_id, balance)
                VALUES (%s, 0)
                ON CONFLICT (player_id) DO NOTHING;
                """,
                (player_id,),
            )

            cur.execute(
                """
                SELECT player_id, balance
                FROM wallets
                WHERE player_id = %s
                FOR UPDATE;
                """,
                (player_id,),
            )

            wallet = cur.fetchone()

            if wallet is None:
                response_body = {
                    "error": "wallet_not_found",
                    "message": "Wallet could not be created or loaded.",
                }

                complete_idempotent_request(
                    cur,
                    idempotency_key=idempotency_key,
                    status_code=500,
                    response_body=response_body,
                )

                return 500, response_body

            current_balance = int(wallet["balance"])
            new_balance = current_balance + request.amount

            if new_balance > MAX_WALLET_BALANCE:
                response_body = {
                    "error": "balance_limit_exceeded",
                    "message": "Credit would exceed the maximum allowed wallet balance.",
                    "balance": current_balance,
                }

                complete_idempotent_request(
                    cur,
                    idempotency_key=idempotency_key,
                    status_code=409,
                    response_body=response_body,
                )

                return 409, response_body

            cur.execute(
                """
                UPDATE wallets
                SET balance = %s, updated_at = now()
                WHERE player_id = %s;
                """,
                (new_balance, player_id),
            )

            cur.execute(
                """
                INSERT INTO ledger_entries (
                    player_id,
                    entry_type,
                    amount,
                    reason,
                    idempotency_key
                )
                VALUES (%s, 'credit', %s, %s, %s);
                """,
                (
                    player_id,
                    request.amount,
                    request.reason,
                    idempotency_key,
                ),
            )

            response_body = {
                "playerId": player_id,
                "credited": request.amount,
                "reason": request.reason,
                "balance": new_balance,
            }

            complete_idempotent_request(
                cur,
                idempotency_key=idempotency_key,
                status_code=200,
                response_body=response_body,
            )

            return 200, response_body