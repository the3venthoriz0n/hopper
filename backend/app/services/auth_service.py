"""Authentication service - business logic for user authentication"""
import bcrypt
import secrets
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.models.user import User
from app.db.redis import (
    set_session, delete_session, set_email_verification_code,
    get_email_verification_code, delete_email_verification_code,
    set_pending_registration, get_pending_registration, delete_pending_registration,
    set_password_reset_token, get_password_reset_email, delete_password_reset_token,
    delete_all_user_sessions, invalidate_all_user_caches
)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash"""
    # If the user has no password hash (e.g. OAuth-only account), immediately fail
    if not password_hash or not password:
        return False
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def create_user(email: str, password: str = None, password_hash: str = None, db: Session = None) -> User:
    """Create a new user.

    Args:
        email: User email (must be unique).
        password: Raw password for the user (optional for OAuth users).
        password_hash: Pre-hashed password (if provided, `password` must be None).
        db: Database session (if None, creates its own).
    """
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise ValueError("Email already registered")

        # Create user
        if password_hash and password:
            raise ValueError("Provide either password or password_hash, not both")
        if not password_hash and password:
            password_hash = hash_password(password)
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        if should_close:
            db.close()


def authenticate_user(email: str, password: str, db: Session = None) -> Optional[User]:
    """Authenticate a user by email and password"""
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user
    finally:
        if should_close:
            db.close()


def get_user_by_id(user_id: int, db: Session = None) -> Optional[User]:
    """Get user by ID"""
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        if should_close:
            db.close()


def get_user_by_email(email: str, db: Session = None) -> Optional[User]:
    """Get user by email"""
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        user = db.query(User).filter(User.email == email).first()
        return user
    finally:
        if should_close:
            db.close()


def get_or_create_oauth_user(email: str, db: Session = None) -> Tuple[User, bool]:
    """Get existing user by email or create new OAuth user
    
    Args:
        email: User email
        db: Database session (if None, creates its own)
    
    Returns:
        tuple: (User object, is_new_user boolean)
    """
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            return existing_user, False
        
        # Create new OAuth user (no password)
        user = User(email=email, password_hash=None)
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create Stripe customer and free subscription for new user
        try:
            from app.services.stripe_service import create_stripe_customer, create_free_subscription
            import logging
            logger = logging.getLogger(__name__)
            
            create_stripe_customer(user.email, user.id, db)
            create_free_subscription(user.id, db)
            logger.info(f"Created Stripe customer and free subscription for OAuth user {user.id}")
        except Exception as e:
            # Log error but don't fail user creation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to create Stripe customer/subscription for OAuth user {user.id}: {e}")
        
        return user, True
    finally:
        if should_close:
            db.close()


def set_user_password(user_id: int, password: str, db: Session = None) -> bool:
    """Set password for OAuth user
    
    Args:
        user_id: User ID
        password: New password
        db: Database session (if None, creates its own)
    
    Returns:
        bool: True if successful, False if user not found
    """
    from app.db.session import SessionLocal
    
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        user.password_hash = hash_password(password)
        db.commit()
        return True
    finally:
        if should_close:
            db.close()


def create_session(user_id: int) -> str:
    """Create a new session for a user
    
    Args:
        user_id: User ID
        
    Returns:
        str: Session ID
    """
    session_id = secrets.token_urlsafe(32)
    set_session(session_id, user_id)
    return session_id


def delete_user_session(session_id: str) -> None:
    """Delete a user session"""
    delete_session(session_id)


def delete_all_sessions_for_user(user_id: int) -> int:
    """Delete all sessions for a user
    
    Args:
        user_id: User ID
        
    Returns:
        int: Number of sessions deleted
    """
    return delete_all_user_sessions(user_id)


def initiate_registration(email: str, password: str) -> Tuple[str, str]:
    """Initiate registration by storing pending registration and generating verification code
    
    Args:
        email: User email
        password: User password
        
    Returns:
        tuple: (verification_code, password_hash)
    """
    # Hash password and store in pending registration
    password_hash = hash_password(password)
    set_pending_registration(email, password_hash)
    
    # Generate and store email verification code (6-character, uppercase A-Z/0-9)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    verification_code = "".join(secrets.choice(alphabet) for _ in range(6))
    set_email_verification_code(email, verification_code)
    
    return verification_code, password_hash


def verify_email_code(email: str, code: str) -> bool:
    """Verify email verification code
    
    Args:
        email: User email
        code: Verification code
        
    Returns:
        bool: True if code is valid
    """
    expected_code = get_email_verification_code(email)
    if not expected_code:
        return False
    
    # Normalize both codes for case-insensitive comparison
    normalized_expected = expected_code.upper() if expected_code else None
    normalized_provided = code.strip().upper()
    
    return normalized_expected == normalized_provided


def complete_email_verification(email: str, db: Session) -> Optional[User]:
    """Complete email verification and create user if needed
    
    Args:
        email: User email
        db: Database session
        
    Returns:
        User: Created or existing user, None if error
    """
    # Check for pending registration
    pending = get_pending_registration(email)
    
    if pending and pending.get("password_hash"):
        # Create the user using the stored password hash
        try:
            user = create_user(email, password=None, password_hash=pending["password_hash"], db=db)
        except ValueError:
            # If user somehow exists now, get existing user
            user = get_user_by_email(email, db=db)
            if not user:
                return None
    else:
        # No pending registration; get existing user
        user = get_user_by_email(email, db=db)
        if not user:
            return None
    
    # Mark email as verified
    db_user = db.query(User).filter(User.email == email).first()
    if not db_user:
        return None
    
    db_user.is_email_verified = True
    db.commit()
    
    # Remove used code and pending registration data
    delete_email_verification_code(email)
    delete_pending_registration(email)
    
    return db_user


def initiate_password_reset(email: str, db: Session = None) -> Optional[str]:
    """Initiate password reset by generating a reset token
    
    Args:
        email: User email
        db: Database session (optional)
        
    Returns:
        str: Reset token if user exists and is verified, None otherwise
    """
    user = get_user_by_email(email, db=db)
    if not user or not getattr(user, "is_email_verified", False):
        return None
    
    # Generate a secure token (32 bytes, URL-safe)
    reset_token = secrets.token_urlsafe(32)
    set_password_reset_token(reset_token, email)
    
    return reset_token


def complete_password_reset(token: str, new_password: str, db: Session) -> bool:
    """Complete password reset using token
    
    Args:
        token: Password reset token
        new_password: New password
        db: Database session
        
    Returns:
        bool: True if successful, False if token invalid or user not found
    """
    # Basic password policy
    if len(new_password) < 8:
        return False
    
    # Look up email associated with token
    email = get_password_reset_email(token)
    if not email:
        return False
    
    user = get_user_by_email(email, db=db)
    if not user:
        return False
    
    # Update password
    if not set_user_password(user.id, new_password, db=db):
        return False
    
    # Clear used reset token
    delete_password_reset_token(token)
    
    return True


def delete_user_account(user_id: int, db: Session) -> bool:
    """Delete a user account and all associated data
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        bool: True if successful, False if user not found
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    
    # Delete all Redis data (sessions, caches, etc.)
    invalidate_all_user_caches(user_id)
    
    # Delete user (cascade will handle related records)
    db.delete(user)
    db.commit()
    
    return True


def register_user(email: str, password: str) -> dict:
    """Complete registration flow: validate password, check existing user, initiate registration, send verification email
    
    Args:
        email: User email
        password: User password
        
    Returns:
        dict: Registration response with user info
        
    Raises:
        ValueError: If password too short or email already registered
    """
    import logging
    from app.services.email_service import send_verification_email
    
    logger = logging.getLogger(__name__)
    
    # Validate password
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    
    # Check existing user
    existing_user = get_user_by_email(email)
    if existing_user:
        raise ValueError("Email already registered. Please log in, reset your password, or resend the verification email.")
    
    # Initiate registration
    verification_code, password_hash = initiate_registration(email, password)
    
    # Send verification email
    try:
        send_verification_email(email, verification_code)
    except Exception:
        logger.warning(f"Failed to send verification email to {email}", exc_info=True)
    
    logger.info(f"Registration initiated (verification required) for: {email}")
    
    return {
        "user": {
            "id": None,
            "email": email,
            "created_at": None,
            "is_admin": False,
            "is_email_verified": False,
        },
        "requires_email_verification": True,
    }


def login_user(email: str, password: str, db: Session) -> dict:
    """Complete login flow: authenticate, verify email, create session, return user info
    
    Args:
        email: User email
        password: User password
        db: Database session
        
    Returns:
        dict: Login response with user info and session_id
        
    Raises:
        ValueError: If invalid credentials or email not verified
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Authenticate user
    user = authenticate_user(email, password, db=db)
    if not user:
        raise ValueError("Invalid email or password")
    
    # Check email verification
    if not getattr(user, "is_email_verified", False):
        raise ValueError("Email address not verified")
    
    # Create session
    session_id = create_session(user.id)
    
    logger.info(f"User logged in: {user.email} (ID: {user.id})")
    
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
            "is_admin": user.is_admin
        },
        "session_id": session_id
    }


def logout_user(session_id: Optional[str]) -> dict:
    """Logout flow: delete session
    
    Args:
        session_id: Session ID (optional)
        
    Returns:
        dict: Logout response message
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    if session_id:
        delete_user_session(session_id)
        logger.info(f"User logged out (session: {session_id[:16]}...)")
    
    return {"message": "Logged out successfully"}


def verify_email_with_stripe_setup(email: str, code: str, db: Session) -> dict:
    """Verify email and ensure Stripe customer/subscription exist
    
    Args:
        email: User email
        code: Verification code
        db: Database session
        
    Returns:
        dict: User info with verification status
        
    Raises:
        ValueError: If invalid code or user not found
    """
    import logging
    from app.services.stripe_service import create_stripe_customer, create_free_subscription
    
    logger = logging.getLogger(__name__)
    
    # Verify code
    if not verify_email_code(email, code):
        raise ValueError("Invalid or expired verification code")
    
    # Complete email verification
    user = complete_email_verification(email, db)
    if not user:
        raise ValueError("User not found")
    
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


def resend_verification_code(email: str, db: Session) -> dict:
    """Generate new verification code and send email
    
    Args:
        email: User email
        db: Database session
        
    Returns:
        dict: Response message
    """
    import logging
    import secrets
    from app.services.email_service import send_verification_email
    
    logger = logging.getLogger(__name__)
    
    # Check if user already verified
    user = get_user_by_email(email, db=db)
    if user and getattr(user, "is_email_verified", False):
        return {"message": "If this email is registered, a verification email has been sent."}
    
    # Generate new verification code
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    verification_code = "".join(secrets.choice(alphabet) for _ in range(6))
    set_email_verification_code(email, verification_code)
    
    # Send email
    try:
        send_verification_email(email, verification_code)
    except Exception:
        logger.warning(f"Failed to send verification email (resend) to {email}", exc_info=True)
    
    return {"message": "If this email is registered, a verification email has been sent."}


def forgot_password_with_email(email: str, db: Session) -> dict:
    """Initiate password reset and send email
    
    Args:
        email: User email
        db: Database session
        
    Returns:
        dict: Response message
    """
    import logging
    from app.services.email_service import send_password_reset_email
    
    logger = logging.getLogger(__name__)
    
    # Initiate password reset
    reset_token = initiate_password_reset(email, db=db)
    
    # Send email if token was generated
    if reset_token:
        try:
            send_password_reset_email(email, reset_token)
        except Exception:
            logger.warning(f"Failed to send password reset email to {email}", exc_info=True)
    
    return {"message": "If this email is registered, a password reset email has been sent."}


def reset_password_with_validation(token: str, new_password: str, db: Session) -> dict:
    """Validate password and complete reset
    
    Args:
        token: Password reset token
        new_password: New password
        db: Database session
        
    Returns:
        dict: Success message
        
    Raises:
        ValueError: If password too short or token invalid
    """
    # Validate password
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    
    # Complete password reset
    if not complete_password_reset(token, new_password, db):
        raise ValueError("Invalid or expired reset link")
    
    return {"message": "Password has been reset successfully."}


def get_current_user_from_session(session_id: Optional[str], db: Session) -> dict:
    """Get user from session
    
    Args:
        session_id: Session ID
        db: Database session
        
    Returns:
        dict: User info or None
    """
    from app.db.redis import get_session
    
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


def set_password_with_validation(user_id: int, password: str, db: Session) -> dict:
    """Validate and set password
    
    Args:
        user_id: User ID
        password: New password
        db: Database session
        
    Returns:
        dict: Success message
        
    Raises:
        ValueError: If password too short or user not found
    """
    # Validate password
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    
    # Set password
    if not set_user_password(user_id, password, db=db):
        raise ValueError("User not found")
    
    return {"message": "Password set successfully"}


def change_password_with_validation(user_id: int, current_password: str, new_password: str, db: Session) -> dict:
    """Validate current password, validate new password, change password
    
    Args:
        user_id: User ID
        current_password: Current password
        new_password: New password
        db: Database session
        
    Returns:
        dict: Success message
        
    Raises:
        ValueError: If user not found, password too short, or current password incorrect
    """
    # Get user
    user = get_user_by_id(user_id, db=db)
    if not user:
        raise ValueError("User not found")
    
    # Validate new password
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    
    # Verify current password
    if not verify_password(current_password, user.password_hash):
        raise ValueError("Current password is incorrect")
    
    # Change password
    if not set_user_password(user_id, new_password, db=db):
        raise ValueError("Failed to change password")
    
    return {"message": "Password changed successfully"}


def delete_user_account_complete(user_id: int, db: Session) -> dict:
    """Complete account deletion: delete account via db_helpers, clean up video files, delete sessions
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        dict: Deletion result with stats
        
    Raises:
        ValueError: If deletion fails
    """
    import logging
    from pathlib import Path
    from app.db import helpers as db_helpers
    from app.db.redis import delete_session, redis_client
    
    security_logger = logging.getLogger("security")
    upload_logger = logging.getLogger("upload")
    
    security_logger.info(f"User {user_id} requested account deletion")
    
    # Delete user account and get cleanup info
    result = db_helpers.delete_user_account(user_id, db=db)
    
    if not result["success"]:
        security_logger.error(f"Failed to delete user {user_id}: {result.get('error')}")
        raise ValueError(f"Failed to delete account: {result.get('error')}")
    
    # Clean up video files from disk
    video_paths = result.get("video_file_paths", [])
    files_deleted = 0
    files_failed = 0
    
    for video_path in video_paths:
        try:
            # Resolve path to absolute to ensure proper file access
            path = Path(video_path).resolve()
            if path.exists():
                path.unlink()
                files_deleted += 1
                upload_logger.debug(f"Deleted video file: {video_path}")
        except Exception as e:
            files_failed += 1
            upload_logger.warning(f"Failed to delete video file {video_path}: {e}")
    
    # Delete all sessions and CSRF tokens for user
    delete_all_sessions_for_user(user_id)
    
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
