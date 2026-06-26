CREATE TABLE IF NOT EXISTS wallets (
    player_id TEXT PRIMARY KEY,
    balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL REFERENCES wallets(player_id),
    entry_type TEXT NOT NULL,
    amount BIGINT NOT NULL,
    reason TEXT,
    item_id TEXT,
    reward_id TEXT,
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL REFERENCES wallets(player_id),
    item_id TEXT NOT NULL,
    source_idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claimed_rewards (
    player_id TEXT NOT NULL REFERENCES wallets(player_id),
    reward_id TEXT NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, reward_id)
);

CREATE TABLE IF NOT EXISTS idempotency_requests (
    idempotency_key TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status_code INT NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);