"""Pydantic schemas for subscriptions"""
from pydantic import BaseModel
from typing import Optional


class CheckoutRequest(BaseModel):
    plan_key: str


class SwitchPlanRequest(BaseModel):
    plan_key: str  # 'free', 'starter', 'creator', 'unlimited'


class GrantTokensRequest(BaseModel):
    amount: int
    reason: Optional[str] = None


class DeductTokensRequest(BaseModel):
    amount: int
    reason: Optional[str] = None

