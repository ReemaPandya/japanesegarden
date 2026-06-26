from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx


BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def unique_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def wait_for_service() -> None:
    for _ in range(30):
        try:
            response = httpx.get(f"{BASE_URL}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass

        time.sleep(1)

    raise RuntimeError("Service did not become ready.")


def post(path: str, body: dict, key: str) -> httpx.Response:
    return httpx.post(
        f"{BASE_URL}{path}",
        json=body,
        headers={"Idempotency-Key": key},
        timeout=10.0,
    )


def get_wallet(player_id: str) -> dict:
    response = httpx.get(
        f"{BASE_URL}/v1/wallets/{player_id}",
        timeout=10.0,
    )
    assert response.status_code == 200
    return response.json()


def test_duplicate_credit_applies_once_and_returns_same_response() -> None:
    wait_for_service()

    player_id = unique_id("dup-credit-player")
    idem_key = unique_id("credit-key")
    body = {
        "amount": 100,
        "reason": "battle_payout",
    }

    first = post(f"/v1/wallets/{player_id}/credit", body, idem_key)
    second = post(f"/v1/wallets/{player_id}/credit", body, idem_key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    wallet = get_wallet(player_id)

    assert wallet["balance"] == 100
    assert wallet["inventory"] == []
    assert wallet["claimedRewards"] == []


def test_same_idempotency_key_with_different_body_is_rejected() -> None:
    wait_for_service()

    player_id = unique_id("conflict-player")
    idem_key = unique_id("conflict-key")

    first = post(
        f"/v1/wallets/{player_id}/credit",
        {"amount": 100, "reason": "battle_payout"},
        idem_key,
    )

    second = post(
        f"/v1/wallets/{player_id}/credit",
        {"amount": 200, "reason": "battle_payout"},
        idem_key,
    )

    assert first.status_code == 200
    assert second.status_code == 409

    wallet = get_wallet(player_id)
    assert wallet["balance"] == 100


def test_duplicate_purchase_debits_and_grants_once() -> None:
    wait_for_service()

    player_id = unique_id("dup-purchase-player")

    credit_response = post(
        f"/v1/wallets/{player_id}/credit",
        {"amount": 500, "reason": "battle_payout"},
        unique_id("credit-key"),
    )
    assert credit_response.status_code == 200

    purchase_body = {
        "itemId": "iron_sword",
        "price": 100,
    }
    purchase_key = unique_id("purchase-key")

    first = post(f"/v1/wallets/{player_id}/purchase", purchase_body, purchase_key)
    second = post(f"/v1/wallets/{player_id}/purchase", purchase_body, purchase_key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    wallet = get_wallet(player_id)

    assert wallet["balance"] == 400
    assert wallet["inventory"] == ["iron_sword"]


def test_concurrent_purchases_on_same_wallet_do_not_double_spend() -> None:
    wait_for_service()

    player_id = unique_id("race-player")

    credit_response = post(
        f"/v1/wallets/{player_id}/credit",
        {"amount": 100, "reason": "battle_payout"},
        unique_id("credit-key"),
    )
    assert credit_response.status_code == 200

    purchase_body = {
        "itemId": "iron_sword",
        "price": 100,
    }

    def buy_once(index: int) -> httpx.Response:
        return post(
            f"/v1/wallets/{player_id}/purchase",
            purchase_body,
            unique_id(f"race-purchase-key-{index}"),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(buy_once, [1, 2]))

    status_codes = sorted(response.status_code for response in results)

    assert status_codes == [200, 409]

    wallet = get_wallet(player_id)

    assert wallet["balance"] == 0
    assert wallet["inventory"].count("iron_sword") == 1


def test_reward_claim_once_per_player() -> None:
    wait_for_service()

    player_id = unique_id("reward-player")
    body = {
        "playerId": player_id,
    }

    first_key = unique_id("reward-key")
    first = post("/v1/rewards/starter-pack/claim", body, first_key)
    duplicate = post("/v1/rewards/starter-pack/claim", body, first_key)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json() == duplicate.json()

    second_claim = post(
        "/v1/rewards/starter-pack/claim",
        body,
        unique_id("reward-key-second"),
    )

    assert second_claim.status_code == 409

    wallet = get_wallet(player_id)

    assert wallet["balance"] == 100
    assert wallet["inventory"] == ["potion"]
    assert wallet["claimedRewards"] == ["starter-pack"]


def test_invalid_negative_credit_is_rejected() -> None:
    wait_for_service()

    player_id = unique_id("invalid-player")

    response = post(
        f"/v1/wallets/{player_id}/credit",
        {"amount": -5, "reason": "bad_credit"},
        unique_id("invalid-credit-key"),
    )

    assert response.status_code == 422

    wallet = get_wallet(player_id)
    assert wallet["balance"] == 0