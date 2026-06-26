# Resilience Notes

## External Inventory Service Scenario

In the current implementation, wallet debit and item grant happen in one PostgreSQL transaction. That gives strong atomicity.

If item granting moves to a separate inventory service over HTTP, the wallet service and inventory service cannot share one local transaction. A simple flow like “debit wallet, call inventory service, return success” is unsafe because the network call can time out, fail, or succeed without the wallet service receiving the response.

The main partial-failure window is:

```text
Wallet debit committed locally, but inventory grant result is unknown.
```

The inventory service may have granted the item, but the wallet service may not know because of a timeout or crash.

## Proposed Approach: Transactional Outbox

I would use a transactional outbox pattern.

Inside the wallet database transaction:

1. Validate idempotency.
2. Lock the wallet row.
3. Check funds.
4. Debit or reserve the currency.
5. Create a purchase record with status `inventory_grant_pending`.
6. Insert an outbox event for the inventory grant.
7. Commit.

The important point is that the wallet update and the durable intent to grant inventory are committed together.

A background outbox worker then reads pending events and calls the inventory service.

If the wallet service crashes after commit, the outbox event is still stored and can be retried after restart.

## Idempotent Inventory API

The inventory service must support idempotency using a stable operation ID, for example:

```text
purchase:{purchase_id}:grant:{item_id}
```

The wallet service should retry inventory grants using the same operation ID every time.

If the inventory request times out, the result should be treated as unknown, not failed. The worker should retry or query the inventory service for the operation status.

This prevents duplicate item grants when the inventory service processed the first request but the response was lost.

## Purchase States

With an external inventory service, purchases should have explicit states such as:

* `pending`
* `inventory_grant_pending`
* `completed`
* `failed`
* `compensated`

Timeouts should keep the purchase pending or retrying. They should not immediately trigger compensation, because the inventory grant may already have succeeded.

If the inventory service returns a permanent failure, the wallet service should create a compensating wallet credit or release a reservation.

## Reserve vs Debit

For a production system, I would consider reserving currency first instead of immediately finalizing the debit.

Flow:

1. Move funds from available balance to reserved balance.
2. Send inventory grant through the outbox.
3. If the grant succeeds, finalize the debit.
4. If the grant permanently fails, release the reservation.

This makes pending purchases easier to reason about.

## Reconciliation

A reconciliation job should compare:

* Wallet purchase records
* Outbox event status
* Inventory service grant status
* Ledger entries

It should detect cases like:

* Purchase completed but item missing
* Item granted but purchase not completed
* Wallet debit without confirmed inventory grant
* Outbox event stuck retrying too long

Repairs should be done through idempotent APIs or compensating ledger entries, not silent manual database edits.

## Double-Granted Currency Bug

If a bug double-granted currency to players, I would detect it through the ledger.

Look for duplicate grant patterns:

* Same player
* Same source event or reason
* Same amount
* Same time window
* More credits than expected

I would also compare wallet balances to ledger-derived balances:

```text
expected_balance = sum(ledger_entries.amount for player)
```

To correct the issue without downtime, I would run a background correction job that creates compensating ledger entries and updates wallet balances in transactions.

I would not delete or edit historical ledger rows, because that destroys the audit trail.

## Invariants

Important invariants:

* Every wallet mutation has a ledger entry.
* Wallet balance should match the sum of ledger entries.
* A reward can be claimed once per `(player_id, reward_id)`.
* A purchase debit must have a matching item grant or a pending/compensated state.
* Idempotency key reuse with a different body must be rejected.
* External event IDs should be processed at most once.

## Summary

For a single service, one PostgreSQL transaction protects wallet and inventory correctness.

For an external inventory service, I would use:

* Transactional outbox
* Stable idempotency keys
* Retry on unknown outcomes
* Explicit purchase states
* Reconciliation
* Compensating ledger entries

The goal is effectively-once behavior across services, even when crashes, retries, duplicate processing, and timeouts happen.
