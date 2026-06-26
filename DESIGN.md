
## Overview

This service is a small authoritative game economy backend. It supports:

* Crediting a player's wallet
* Purchasing an item from a shop
* Claiming a one-time reward
* Reading wallet state

The main priority is correctness under retries, duplicate requests, crashes, and concurrent requests on the same wallet.

## Stack

* FastAPI for HTTP APIs
* PostgreSQL for durable storage
* psycopg for explicit SQL transactions
* Docker Compose for local runtime
* pytest/httpx for tests

The API process is stateless. All durable state lives in PostgreSQL.

## Datastore Choice

I chose PostgreSQL because this service needs durable transactions, row-level locking, unique constraints, and auditability.

PostgreSQL gives:

* Atomic commits and rollbacks
* WAL-backed durability
* `SELECT ... FOR UPDATE` for wallet locking
* Unique constraints for idempotency and claim-once rewards
* JSONB storage for saved idempotency responses

This is a better fit than in-memory storage because player money and items must survive process crashes.

## Schema

Main tables:

* `wallets`: current balance per player
* `ledger_entries`: append-only audit trail of credits, purchases, and rewards
* `inventory_items`: granted items
* `claimed_rewards`: rewards claimed by each player
* `idempotency_requests`: saved idempotency state and responses

Important constraints:

* `wallets.player_id` is the primary key
* `claimed_rewards` has `PRIMARY KEY (player_id, reward_id)`
* `idempotency_requests.idempotency_key` is the primary key
* `wallets.balance` has a non-negative check

## API Contract

Mutating endpoints:

* `POST /v1/wallets/{playerId}/credit`
* `POST /v1/wallets/{playerId}/purchase`
* `POST /v1/rewards/{rewardId}/claim`

Read endpoint:

* `GET /v1/wallets/{playerId}`

All mutating endpoints require an `Idempotency-Key` header.

Status codes:

* `200`: success or replayed duplicate response
* `400`: missing/invalid idempotency key
* `404`: unknown item or reward
* `409`: idempotency conflict, insufficient funds, price mismatch, already-claimed reward, or balance limit issue
* `422`: invalid request body

Currency and prices are integer units. Floating point values are not used.

## Server Authority

The server owns balances, item prices, rewards, and inventory grants.

The purchase request includes a `price` because the required API contract includes it, but the server verifies it against the server-side item catalog. If the submitted price does not match the server price, the purchase is rejected.

## Idempotency Strategy

Each mutating request is identified by:

* `Idempotency-Key`
* HTTP method
* Endpoint path
* SHA-256 hash of the canonical JSON body

If the same key is retried with the same method, endpoint, and body, the service returns the saved status code and response body without applying the effect again.

If the same key is reused for a different request, the service returns `409 Conflict`.

Idempotency records are retained indefinitely in this implementation. In production, I would choose a retention period based on expected client retry windows and audit requirements.

## Atomicity and Durability

Each mutating operation runs inside one PostgreSQL transaction.

### Credit

Credit creates or locks the wallet, updates balance, writes a ledger entry, stores the idempotency response, and commits.

### Purchase

Purchase verifies the item and price, locks the wallet row, checks balance, debits the wallet, grants the item, writes a ledger entry, stores the idempotency response, and commits.

The debit and item grant happen in the same transaction, so there is no committed state where a player is debited without receiving the item or receives the item without being debited.

### Reward Claim

Reward claim locks the wallet, inserts into `claimed_rewards`, grants currency/item, writes a ledger entry, stores the idempotency response, and commits.

The unique key on `(player_id, reward_id)` enforces claim-once behavior.

## Concurrency Strategy

Wallet updates use:

```sql
SELECT player_id, balance
FROM wallets
WHERE player_id = %s
FOR UPDATE;
```

This serializes balance-changing operations for the same player.

If two purchases race on a wallet that can afford only one, one transaction commits first. The second transaction then sees the updated balance and rejects with insufficient funds. This prevents double-spend, lost updates, and negative balances.

## Isolation Level

The service relies on PostgreSQL's default `READ COMMITTED` isolation level plus explicit row-level locks and unique constraints.

This is sufficient for this slice because every balance mutation locks the wallet row before reading and writing the balance.

## Crash Behavior

If the process is killed before commit, PostgreSQL rolls back the transaction. No partial wallet update, item grant, reward claim, ledger entry, or completed idempotency response is committed.

If the process is killed after commit but before the client receives the response, the operation and saved idempotency response are durable. A retry with the same key returns the saved response and does not apply the effect twice.

## Input Validation and Limits

FastAPI/Pydantic validates requests at the boundary.

Limits include:

* Amount and price must be positive integers
* Amount and price are capped
* Wallet balance has a maximum cap
* Text fields are length-limited
* Malformed JSON, missing fields, negative values, and oversized values are rejected before business logic runs

## Tests

The test suite covers:

* Duplicate credit applies once
* Same idempotency key with different body returns conflict
* Duplicate purchase debits and grants once
* Concurrent purchases do not double-spend
* Reward claim is once per player
* Invalid negative credit is rejected

## Tradeoffs

Item and reward catalogs are code constants to keep the assessment focused. In production, I would store them in a versioned database table.

The service stores both current balance and ledger entries. Balance makes reads simple, while the ledger supports audit and reconciliation.

Inventory is local in this implementation, so one database transaction can protect purchase correctness. If inventory moves to a separate service, I would use the outbox/saga approach described in `RESILIENCE.md`.
