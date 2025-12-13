#!/usr/bin/env python3
"""
Script to grant admin access to a user.

Usage:
    python setup_admin.py <user_email>
    
Example:
    python setup_admin.py admin@example.com
"""
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import SessionLocal, User


def grant_admin(email: str):
    """Grant admin access to a user by email"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"ERROR: User with email '{email}' not found")
            sys.exit(1)
        
        if user.is_admin:
            print(f"User '{email}' already has admin access")
            return
        
        user.is_admin = True
        db.commit()
        
        print(f"✓ Admin access granted to user: {email} (ID: {user.id})")
        
    except Exception as e:
        print(f"ERROR: Failed to grant admin access: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python setup_admin.py <user_email>")
        sys.exit(1)
    
    email = sys.argv[1]
    grant_admin(email)

