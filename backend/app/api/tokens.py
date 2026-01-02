"""Token API routes"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.security import require_auth
from app.db.session import get_db
from app.services.token_service import get_token_balance, get_token_transactions

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


@router.get("/balance")
def get_balance(user_id: int = Depends(require_auth), db: Session = Depends(get_db)):
    """Get current token balance"""
    balance = get_token_balance(user_id, db)
    if not balance:
        raise HTTPException(404, "User not found")
    return balance


@router.get("/transactions")
def get_transactions(
    limit: int = 50,
    user_id: int = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get token transaction history"""
    transactions = get_token_transactions(user_id, limit, db)
    return {"transactions": transactions}

