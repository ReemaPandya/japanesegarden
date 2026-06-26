
A small backend wallet/economy service for a game. The service supports earning currency, purchasing shop items, claiming one-time rewards, and reading wallet state.

The design focuses on:

* Exactly-once behavior for duplicate mutating requests
* Crash-durable storage using PostgreSQL
* Atomic purchase behavior: debit currency and grant item in one transaction
* Concurrency correctness on the same wallet
* Input validation and safe error handling

## Tech Stack

* Python 3.12
* FastAPI
* PostgreSQL 16
* psycopg
* Docker Compose
* pytest

## Run the Service

Build and start the API and database:

```bash
docker compose up --build
```

The API will be available at:

```text
http://localhost:8000
```

Health check:

```bash
curl.exe http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Database health check:

```bash
curl.exe http://localhost:8000/db-health
```

Expected response:

```json
{"status":"ok","db":1}
```

## API Contract

All mutating requests require an `Idempotency-Key` header.

A duplicate request using the same `Idempotency-Key`, same endpoint, and same body returns the same saved response and applies the effect only once.

Reusing the same `Idempotency-Key` with a different request body returns `409 Conflict`.

Currency values are integer units. Negative, zero, oversized, malformed, or missing required values are rejected by request validation.

## Endpoints

### Credit Wallet

```http
POST /v1/wallets/{playerId}/credit
```

Body:

```json
{
  "amount": 100,
  "reason": "battle_payout"
}
```

Example:

```bash
curl.exe -X POST http://localhost:8000/v1/wallets/player-1/credit ^
  -H "Content-Type: application/json" ^
  -H "Idempotency-Key: credit-player-1-001" ^
  -d "{\"amount\":100,\"reason\":\"battle_payout\"}"
```

Example success response:

```json
{
  "playerId": "player-1",
  "credited": 100,
  "reason": "battle_payout",
  "balance": 100
}
```

Running the same command again returns the same response and does not credit the wallet a second time.

### Purchase Item

```http
POST /v1/wallets/{playerId}/purchase
```

Body:

```json
{
  "itemId": "iron_sword",
  "price": 100
}
```

Example:

```bash
curl.exe -X POST http://localhost:8000/v1/wallets/player-1/purchase ^
  -H "Content-Type: application/json" ^
  -H "Idempotency-Key: purchase-player-1-001" ^
  -d "{\"itemId\":\"iron_sword\",\"price\":100}"
```

Example success response:

```json
{
  "playerId": "player-1",
  "itemId": "iron_sword",
  "price": 100,
  "balance": 0,
  "inventoryGranted": true
}
```

If the wallet does not have enough balance, the service returns `409 Conflict` and does not grant the item.

If the submitted price does not match the server-side catalog price, the service returns `409 Conflict`. The server is authoritative for item prices.

Current server-side item catalog:

```text
potion: 25
shield: 75
iron_sword: 100
dragon_armor: 300
```

### Claim Reward

```http
POST /v1/rewards/{rewardId}/claim
```

Body:

```json
{
  "playerId": "player-1"
}
```

Example:

```bash
curl.exe -X POST http://localhost:8000/v1/rewards/starter-pack/claim ^
  -H "Content-Type: application/json" ^
  -H "Idempotency-Key: claim-player-1-starter-001" ^
  -d "{\"playerId\":\"player-1\"}"
```

Example success response:

```json
{
  "playerId": "player-1",
  "rewardId": "starter-pack",
  "currencyGranted": 100,
  "itemGranted": "potion",
  "balance": 100,
  "claimed": true
}
```

A reward can be claimed once per player. A second claim with a new idempotency key returns `409 Conflict`.

Current server-side reward catalog:

```text
daily-login: 50 currency
starter-pack: 100 currency + potion
founder-gift: 250 currency + shield
```

### Get Wallet State

```http
GET /v1/wallets/{playerId}
```

Example:

```bash
curl.exe http://localhost:8000/v1/wallets/player-1
```

Example response:

```json
{
  "balance": 100,
  "inventory": ["potion"],
  "claimedRewards": ["starter-pack"]
}
```

For a player with no wallet activity, the service returns an empty wallet state:

```json
{
  "balance": 0,
  "inventory": [],
  "claimedRewards": []
}
```

## Run Tests

Start the service first:

```bash
docker compose up --build
```

In another terminal, run:

```bash
docker compose exec api pytest -q
```

The test suite covers:

* Duplicate credit requests
* Idempotency-key conflict handling
* Duplicate purchase requests
* Concurrent purchases on the same wallet
* Claim-once rewards
* Invalid negative credit input

## Reset Local Database

To remove the local PostgreSQL volume and start fresh:

```bash
docker compose down -v
docker compose up --build
```

## Important Design Notes

* PostgreSQL is used for durable state.
* Each mutating operation runs inside a database transaction.
* Wallet rows are locked with `SELECT ... FOR UPDATE` before balance changes.
* Purchase debit and item grant happen in the same transaction.
* Idempotency responses are stored in the database and replayed for duplicate retries.
* The database outlives the API process through the Docker Compose PostgreSQL volume.
