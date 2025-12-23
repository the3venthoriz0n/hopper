"""Admin API routes"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.schemas.auth import CreateUserRequest
from app.schemas.subscriptions import GrantTokensRequest, DeductTokensRequest
from app.core.security import require_auth
from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import create_user
from app.services.token_service import add_tokens, deduct_tokens

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(user_id: int = Depends(require_auth), db: Session = Depends(get_db)) -> User:
    """Dependency: Require admin role"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


@router.post("/users")
def create_user_endpoint(
    request_data: CreateUserRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new user (admin only)"""
    try:
        user = create_user(request_data.email, request_data.password, db=db)
        if request_data.is_admin:
            user.is_admin = True
            db.commit()
        return {"user": {"id": user.id, "email": user.email}}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/users/{user_id}/grant-tokens")
def grant_tokens_endpoint(
    user_id: int,
    request_data: GrantTokensRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Grant tokens to a user (admin only)"""
    if request_data.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    
    if not add_tokens(user_id, request_data.amount, transaction_type='grant', metadata={'reason': request_data.reason}, db=db):
        raise HTTPException(404, "User not found")
    
    return {"message": f"Granted {request_data.amount} tokens to user {user_id}"}


@router.post("/users/{user_id}/deduct-tokens")
def deduct_tokens_endpoint(
    user_id: int,
    request_data: DeductTokensRequest,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deduct tokens from a user (admin only)"""
    if request_data.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    
    if not deduct_tokens(user_id, request_data.amount, transaction_type='grant', metadata={'reason': request_data.reason}, db=db):
        raise HTTPException(404, "User not found or insufficient tokens")
    
    return {"message": f"Deducted {request_data.amount} tokens from user {user_id}"}

