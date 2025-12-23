"""Auth API routes"""
import secrets
import logging
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.schemas.auth import (
    RegisterRequest, LoginRequest, VerifyEmailRequest, ResendVerificationRequest,
    ForgotPasswordRequest, ResetPasswordRequest, SetPasswordRequest, ChangePasswordRequest
)
from app.services.auth_service import (
    initiate_registration, complete_email_verification, authenticate_user,
    create_session, delete_user_session, initiate_password_reset, complete_password_reset,
    set_user_password, get_user_by_email, get_user_by_id
)
from app.services.email_service import send_verification_email, send_password_reset_email
from app.core.security import require_auth, require_csrf_new, set_auth_cookie
from app.db.session import get_db
from app.db import helpers as db_helpers
from app.db.redis import (
    set_pending_registration, get_pending_registration, delete_pending_registration,
    set_email_verification_code, get_email_verification_code, delete_email_verification_code,
    set_password_reset_token, get_password_reset_email, delete_password_reset_token,
    delete_session, get_session, redis_client
)
from app.services.stripe_service import create_stripe_customer, create_free_subscription

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post("/register")
def register(request_data: RegisterRequest, request: Request, response: Response):
    """Begin registration by sending a verification email"""
    try:
        if len(request_data.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters long")

        existing_user = get_user_by_email(request_data.email)
        if existing_user:
            raise HTTPException(
                400,
                "Email already registered. Please log in, reset your password, or resend the verification email.",
            )

        verification_code, password_hash = initiate_registration(request_data.email, request_data.password)
        
        try:
            send_verification_email(request_data.email, verification_code)
        except Exception:
            logger.warning(f"Failed to send verification email to {request_data.email}", exc_info=True)

        logger.info(f"Registration initiated (verification required) for: {request_data.email}")

        return {
            "user": {
                "id": None,
                "email": request_data.email,
                "created_at": None,
                "is_admin": False,
                "is_email_verified": False,
            },
            "requires_email_verification": True,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}", exc_info=True)
        raise HTTPException(500, "Registration failed")


@router.post("/login")
def login(request_data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Login user"""
    try:
        user = authenticate_user(request_data.email, request_data.password, db=db)
        if not user:
            raise HTTPException(401, "Invalid email or password")

        if not getattr(user, "is_email_verified", False):
            raise HTTPException(403, "Email address not verified")

        session_id = create_session(user.id)
        set_auth_cookie(response, session_id, request)
        
        logger.info(f"User logged in: {user.email} (ID: {user.id})")
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat(),
                "is_admin": user.is_admin
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(500, "Login failed")


@router.post("/logout")
def logout(request: Request, response: Response):
    """Logout user"""
    session_id = request.cookies.get("session_id")
    if session_id:
        delete_session(session_id)
        response.delete_cookie("session_id")
        logger.info(f"User logged out (session: {session_id[:16]}...)")
    
    return {"message": "Logged out successfully"}


@router.post("/verify-email")
def verify_email(request_data: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify a user's email address using a one-time code"""
    from app.services.auth_service import verify_email_code
    
    if not verify_email_code(request_data.email, request_data.code):
        raise HTTPException(400, "Invalid or expired verification code")

    user = complete_email_verification(request_data.email, db)
    if not user:
        raise HTTPException(404, "User not found")

    # Ensure Stripe customer and free subscription exist
    try:
        create_stripe_customer(user.email, user.id, db)
        create_free_subscription(user.id, db)
    except Exception as e:
        logger.warning(f"Failed to create Stripe customer/subscription for user {user.id}: {e}")

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
            "is_admin": user.is_admin,
            "is_email_verified": True,
        }
    }


@router.post("/resend-verification")
def resend_verification(request_data: ResendVerificationRequest, db: Session = Depends(get_db)):
    """Resend an email verification code"""
    user = get_user_by_email(request_data.email, db=db)
    if user and getattr(user, "is_email_verified", False):
        return {"message": "If this email is registered, a verification email has been sent."}

    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    verification_code = "".join(secrets.choice(alphabet) for _ in range(6))
    set_email_verification_code(request_data.email, verification_code)

    try:
        send_verification_email(request_data.email, verification_code)
    except Exception:
        logger.warning(f"Failed to send verification email (resend) to {request_data.email}", exc_info=True)

    return {"message": "If this email is registered, a verification email has been sent."}


@router.post("/forgot-password")
def forgot_password(request_data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Initiate password reset by sending a reset link"""
    reset_token = initiate_password_reset(request_data.email, db=db)
    
    if reset_token:
        try:
            send_password_reset_email(request_data.email, reset_token)
        except Exception:
            logger.warning(f"Failed to send password reset email to {request_data.email}", exc_info=True)

    return {"message": "If this email is registered, a password reset email has been sent."}


@router.post("/reset-password")
def reset_password(request_data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Complete password reset using the token from the emailed link"""
    if len(request_data.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters long")

    if not complete_password_reset(request_data.token, request_data.new_password, db):
        raise HTTPException(400, "Invalid or expired reset link")

    return {"message": "Password has been reset successfully."}


@router.get("/me")
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Get current logged-in user"""
    try:
        session_id = request.cookies.get("session_id")
        if not session_id:
            return {"user": None}
        
        user_id = get_session(session_id)
        if not user_id:
            return {"user": None}
        
        user = get_user_by_id(user_id, db=db)
        if not user:
            return {"user": None}
        
        return {
            "user": {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat(),
                "is_admin": user.is_admin,
                "is_email_verified": user.is_email_verified,
            }
        }
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
    if len(request_data.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters long")

    if not set_user_password(user_id, request_data.password, db=db):
        raise HTTPException(404, "User not found")

    return {"message": "Password set successfully"}


@router.post("/change-password")
def change_password(
    request_data: ChangePasswordRequest,
    user_id: int = Depends(require_csrf_new),
    db: Session = Depends(get_db)
):
    """Change password for authenticated user"""
    user = get_user_by_id(user_id, db=db)
    if not user:
        raise HTTPException(404, "User not found")

    if len(request_data.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters long")

    from app.services.auth_service import verify_password
    if not verify_password(request_data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")

    if not set_user_password(user_id, request_data.new_password, db=db):
        raise HTTPException(500, "Failed to change password")

    return {"message": "Password changed successfully"}


@router.get("/csrf")
def get_csrf_token(request: Request):
    """Get CSRF token for authenticated session"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(401, "Not authenticated")
    
    from app.db.redis import get_csrf_token, set_csrf_token
    
    csrf_token = get_csrf_token(session_id)
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        set_csrf_token(session_id, csrf_token)
    
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
    security_logger = logging.getLogger("security")
    upload_logger = logging.getLogger("upload")
    
    security_logger.info(f"User {user_id} requested account deletion")
    
    try:
        # Delete user account and get cleanup info
        result = db_helpers.delete_user_account(user_id, db=db)
        
        if not result["success"]:
            security_logger.error(f"Failed to delete user {user_id}: {result.get('error')}")
            raise HTTPException(500, f"Failed to delete account: {result.get('error')}")
        
        # Clean up video files from disk
        video_paths = result.get("video_file_paths", [])
        files_deleted = 0
        files_failed = 0
        
        for video_path in video_paths:
            try:
                # ROOT CAUSE FIX: Resolve path to absolute to ensure proper file access
                path = Path(video_path).resolve()
                if path.exists():
                    path.unlink()
                    files_deleted += 1
                    upload_logger.debug(f"Deleted video file: {video_path}")
            except Exception as e:
                files_failed += 1
                upload_logger.warning(f"Failed to delete video file {video_path}: {e}")
        
        # Log current session to delete it
        session_id = request.cookies.get("session_id")
        if session_id:
            delete_session(session_id)
            redis_client.redis_client.delete(f"csrf:{session_id}")
        
        # Clear session cookie
        response.delete_cookie("session_id")
        
        # Log deletion
        stats = result.get("stats", {})
        security_logger.info(
            f"Account deleted: user_id={user_id}, "
            f"email={stats.get('user_email')}, "
            f"videos={stats.get('videos_deleted', 0)}, "
            f"settings={stats.get('settings_deleted', 0)}, "
            f"oauth_tokens={stats.get('oauth_tokens_deleted', 0)}, "
            f"files_deleted={files_deleted}, "
            f"files_failed={files_failed}"
        )
        
        return {
            "message": "Account deleted successfully",
            "stats": {
                **stats,
                "files_deleted": files_deleted,
                "files_failed": files_failed
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        security_logger.error(f"Error deleting account for user {user_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to delete account: {str(e)}")

