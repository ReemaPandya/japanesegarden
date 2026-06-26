from __future__ import annotations

from pydantic import BaseModel, Field


MAX_CURRENCY_AMOUNT = 1_000_000_000
MAX_TEXT_LENGTH = 128


class CreditRequest(BaseModel):
    amount: int = Field(..., gt=0, le=MAX_CURRENCY_AMOUNT)
    reason: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)


class PurchaseRequest(BaseModel):
    itemId: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    price: int = Field(..., gt=0, le=MAX_CURRENCY_AMOUNT)


class ClaimRewardRequest(BaseModel):
    playerId: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)


class WalletStateResponse(BaseModel):
    balance: int
    inventory: list[str]
    claimedRewards: list[str]