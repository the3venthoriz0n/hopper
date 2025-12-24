"""Auth API routes"""
import secrets
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.schemas.auth import (
    RegisterRequest, LoginRequest, VerifyEmailRequest, ResendVerificationRequest,
    ForgotPasswordRequest, ResetPasswordRequest, SetPasswordRequest, ChangePasswordRequest
)
from app.services.auth_service import (
    register_user, login_user, logout_user, verify_email_with_stripe_setup,
    resend_verification_code, forgot_password_with_email, reset_password_with_validation,
    get_current_user_from_session, set_password_with_validation, change_password_with_validation,
    delete_user_account_complete
)
from app.core.security import require_auth, require_csrf_new, set_auth_cookie
from app.db.session import get_db
from app.db.redis import get_or_create_csrf_token, get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/register")
def register(request_data: RegisterRequest, request: Request, response: Response):
    """Begin registration by sending a verification email"""
    try:
        return register_user(request_data.email, request_data.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(500, "Registration failed")


@router.post("/login")
def login(request_data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Login user"""
    try:
        result = login_user(request_data.email, request_data.password, db)
        set_auth_cookie(response, result["session_id"], request)
        return {"user": result["user"]}
    except ValueError as e:
        error_msg = str(e)
        if "Invalid email or password" in error_msg:
            raise HTTPException(401, error_msg)
        elif "Email address not verified" in error_msg:
            raise HTTPException(403, error_msg)
        else:
            raise HTTPException(401, error_msg)
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(500, "Login failed")


@router.post("/logout")
def logout(request: Request, response: Response):
    """Logout user"""
    session_id = request.cookies.get("session_id")
    result = logout_user(session_id)
    if session_id:
        response.delete_cookie("session_id")
    return result


@router.post("/verify-email")
def verify_email(request_data: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify a user's email address using a one-time code"""
    try:
        return verify_email_with_stripe_setup(request_data.email, request_data.code, db)
    except ValueError as e:
        error_msg = str(e)
        if "Invalid or expired" in error_msg:
            raise HTTPException(400, error_msg)
        elif "User not found" in error_msg:
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(400, error_msg)


@router.post("/resend-verification")
def resend_verification(request_data: ResendVerificationRequest, db: Session = Depends(get_db)):
    """Resend an email verification code"""
    return resend_verification_code(request_data.email, db)


@router.post("/forgot-password")
def forgot_password(request_data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Initiate password reset by sending a reset link"""
    return forgot_password_with_email(request_data.email, db)


@router.post("/reset-password")
def reset_password(request_data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Complete password reset using the token from the emailed link"""
    try:
        return reset_password_with_validation(request_data.token, request_data.new_password, db)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/me")
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Get current logged-in user"""
    try:
        session_id = request.cookies.get("session_id")
        return get_current_user_from_session(session_id, db)
    except Exception:
        # Return None on any error to prevent redirect loops
        return {"user": None}


@router.post("/set-password")
def set_password(
    request_data: SetPasswordRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Set password for OAuth user"""
    try:
        return set_password_with_validation(user_id, request_data.password, db)
    except ValueError as e:
        error_msg = str(e)
        if "Password must be" in error_msg:
            raise HTTPException(400, error_msg)
        elif "User not found" in error_msg:
            raise HTTPException(404, error_msg)
        else:
            raise HTTPException(400, error_msg)


@router.post("/change-password")
def change_password(
    request_data: ChangePasswordRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Change password for authenticated user"""
    try:
        return change_password_with_validation(user_id, request_data.current_password, request_data.new_password, db)
    except ValueError as e:
        error_msg = str(e)
        if "User not found" in error_msg:
            raise HTTPException(404, error_msg)
        elif "Password must be" in error_msg:
            raise HTTPException(400, error_msg)
        elif "Current password is incorrect" in error_msg:
            raise HTTPException(400, error_msg)
        elif "Failed to change password" in error_msg:
            raise HTTPException(500, error_msg)
        else:
            raise HTTPException(400, error_msg)


@router.get("/csrf")
def get_csrf_token_route(request: Request, response: Response):
    """Get or generate CSRF token for the session"""
    session_id = request.cookies.get("session_id")
    
    # Ensure a session_id exists (HTTP concern - cookie management)
    if not session_id:
        session_id = secrets.token_urlsafe(32)
        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=True,  # Always use True if you are on HTTPS (dunkbox.net)
            samesite="lax",
            max_age=3600 * 24  # 24 hours
        )
    
    # Get or create CSRF token (business logic in redis)
    csrf_token = get_or_create_csrf_token(session_id)
    
    return {"csrf_token": csrf_token}


@router.delete("/account")
def delete_account(
    request: Request,
    response: Response,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Delete user account and all associated data (user-initiated)
    
    This endpoint performs a complete data deletion (GDPR compliant):
    - Deletes all videos from database
    - Deletes all video files from disk
    - Deletes all settings
    - Deletes all OAuth tokens
    - Deletes user account
    - Clears all sessions and caches
    
    This action is irreversible.
    """
    try:
        result = delete_user_account_complete(user_id, db)
        # Clear session cookie (HTTP concern)
        response.delete_cookie("session_id")
        return result
    except ValueError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        security_logger = logging.getLogger("security")
        security_logger.error(f"Error deleting account for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to delete account: {str(e)}")

