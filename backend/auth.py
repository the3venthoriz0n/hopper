"""Authentication helpers"""
import bcrypt
from models import User, SessionLocal
from typing import Optional


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def create_user(email: str, password: str = None) -> User:
    """Create a new user (password optional for OAuth users)"""
    db = SessionLocal()
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise ValueError("Email already registered")
        
        # Create user
        password_hash = hash_password(password) if password else None
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def authenticate_user(email: str, password: str) -> Optional[User]:
    """Authenticate a user by email and password"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user
    finally:
        db.close()


def get_user_by_id(user_id: int) -> Optional[User]:
    """Get user by ID"""
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def get_user_by_email(email: str) -> Optional[User]:
    """Get user by email"""
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).first()
    finally:
        db.close()


def get_or_create_oauth_user(email: str) -> tuple[User, bool]:
    """Get existing user by email or create new OAuth user
    
    Returns:
        tuple: (User object, is_new_user boolean)
    """
    db = SessionLocal()
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
            from stripe_helpers import create_stripe_customer, create_free_subscription
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
        db.close()


def set_user_password(user_id: int, password: str) -> bool:
    """Set password for OAuth user
    
    Returns:
        bool: True if successful, False if user not found
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        user.password_hash = hash_password(password)
        db.commit()
        return True
    finally:
        db.close()

