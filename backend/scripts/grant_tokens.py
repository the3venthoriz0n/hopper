#!/usr/bin/env python3
"""
Grant tokens or reset subscriptions for users.

Usage:
    # Grant additional tokens
    python grant_tokens.py --email user@example.com --tokens 100
    
    # Reset free subscription period (monthly reset)
    python grant_tokens.py --email user@example.com --reset-subscription
    
    # Grant unlimited tokens
    python grant_tokens.py --email user@example.com --unlimited
    
    # Remove unlimited
    python grant_tokens.py --email user@example.com --no-unlimited
"""

import argparse
import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path to import backend modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import SessionLocal, User, Subscription, TokenBalance, TokenTransaction


def grant_tokens(email: str, tokens: int):
    """Grant additional tokens to a user"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ User not found: {email}")
            return False
        
        balance = db.query(TokenBalance).filter(TokenBalance.user_id == user.id).first()
        if not balance:
            print(f"❌ No token balance found for user {email}")
            return False
        
        old_balance = balance.tokens_remaining
        balance.tokens_remaining += tokens
        balance.updated_at = datetime.now(timezone.utc)
        
        # Create transaction record
        transaction = TokenTransaction(
            user_id=user.id,
            transaction_type='grant',
            tokens=tokens,
            balance_before=old_balance,
            balance_after=balance.tokens_remaining,
            transaction_metadata={'reason': 'admin_grant', 'admin_script': True},
            created_at=datetime.now(timezone.utc)
        )
        db.add(transaction)
        db.commit()
        
        print(f"✅ Granted {tokens} tokens to {email}")
        print(f"   Balance: {old_balance} → {balance.tokens_remaining}")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def reset_subscription(email: str):
    """Reset user's subscription period and tokens"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ User not found: {email}")
            return False
        
        subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not subscription:
            print(f"❌ No subscription found for user {email}")
            return False
        
        balance = db.query(TokenBalance).filter(TokenBalance.user_id == user.id).first()
        if not balance:
            print(f"❌ No token balance found for user {email}")
            return False
        
        # Get monthly tokens for plan
        from stripe_config import get_plan_monthly_tokens
        monthly_tokens = get_plan_monthly_tokens(subscription.plan_type)
        
        # Reset subscription period
        now = datetime.now(timezone.utc)
        period_end = now + timedelta(days=30)
        
        subscription.current_period_start = now
        subscription.current_period_end = period_end
        subscription.updated_at = now
        
        # Handle unlimited plan (don't reset token balance, just update period)
        if subscription.plan_type == 'unlimited':
            balance.period_start = now
            balance.period_end = period_end
            balance.last_reset_at = now
            balance.updated_at = now
            db.commit()
            print(f"✅ Reset subscription period for {email}")
            print(f"   Plan: {subscription.plan_type} (unlimited)")
            print(f"   Period: {now.date()} → {period_end.date()}")
        else:
            # Reset token balance for regular plans
            old_balance = balance.tokens_remaining
            balance.tokens_remaining = monthly_tokens
            balance.tokens_used_this_period = 0
            balance.period_start = now
            balance.period_end = period_end
            balance.last_reset_at = now
            balance.updated_at = now
            
            # Create transaction record
            transaction = TokenTransaction(
                user_id=user.id,
                transaction_type='reset',
                tokens=monthly_tokens,
                balance_before=old_balance,
                balance_after=balance.tokens_remaining,
                transaction_metadata={'reason': 'admin_reset', 'admin_script': True, 'plan_type': subscription.plan_type},
                created_at=now
            )
            db.add(transaction)
            db.commit()
            print(f"✅ Reset subscription for {email}")
            print(f"   Plan: {subscription.plan_type}")
            print(f"   Period: {now.date()} → {period_end.date()}")
            print(f"   Tokens: {old_balance} → {monthly_tokens}")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()


def set_unlimited(email: str, unlimited: bool):
    """Set or remove unlimited plan for a user (DEPRECATED: Use assign_unlimited_plan instead)"""
    print("⚠️  WARNING: set_unlimited is deprecated. Use --unlimited-plan flag instead.")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ User not found: {email}")
            return False
        
        # If enabling unlimited, update subscription to unlimited plan
        if unlimited:
            subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
            if not subscription:
                # Create subscription if it doesn't exist
                from stripe_helpers import create_free_subscription
                subscription = create_free_subscription(user.id, db)
            if subscription:
                subscription.plan_type = 'unlimited'
                subscription.status = 'active'
                subscription.updated_at = datetime.now(timezone.utc)
        # If disabling, revert to free plan
        else:
            subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
            if subscription and subscription.plan_type == 'unlimited':
                subscription.plan_type = 'free'
                subscription.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        status = "enabled" if unlimited else "disabled"
        print(f"✅ Unlimited tokens {status} for {email}")
        if unlimited:
            print(f"   Subscription updated to 'unlimited' plan")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()


def assign_unlimited_plan(email: str):
    """Assign unlimited plan subscription to a user (dev/admin only)"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"❌ User not found: {email}")
            return False
        
        from stripe_helpers import create_free_subscription
        from stripe_config import get_plans
        
        # Verify unlimited plan exists
        plans = get_plans()
        if 'unlimited' not in plans:
            print(f"❌ Unlimited plan not found in configuration")
            return False
        
        # Get or create subscription
        subscription = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not subscription:
            subscription = create_free_subscription(user.id, db)
        if not subscription:
            print(f"❌ Failed to get or create subscription")
            return False
        
        # Update to unlimited plan
        old_plan = subscription.plan_type
        subscription.plan_type = 'unlimited'
        subscription.status = 'active'
        subscription.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        print(f"✅ Assigned unlimited plan to {email}")
        print(f"   Previous plan: {old_plan}")
        print(f"   New plan: unlimited")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description='Grant tokens or reset subscriptions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Grant 100 additional tokens
  python %(prog)s --email user@example.com --tokens 100
  
  # Reset subscription period (gives new monthly allocation)
  python %(prog)s --email user@example.com --reset-subscription
  
  # Enable unlimited tokens
  python %(prog)s --email user@example.com --unlimited
  
  # Disable unlimited tokens
  python %(prog)s --email user@example.com --no-unlimited
  
  # Assign unlimited plan (dev/admin only, hidden from users)
  python %(prog)s --email user@example.com --unlimited-plan
        """
    )
    
    parser.add_argument('--email', required=True, help='User email address')
    parser.add_argument('--tokens', type=int, help='Number of tokens to grant')
    parser.add_argument('--reset-subscription', action='store_true', help='Reset subscription period and token balance')
    parser.add_argument('--unlimited', action='store_true', help='Enable unlimited tokens (sets unlimited_tokens flag)')
    parser.add_argument('--no-unlimited', action='store_true', help='Disable unlimited tokens')
    parser.add_argument('--unlimited-plan', action='store_true', help='Assign unlimited plan subscription (dev/admin only)')
    
    args = parser.parse_args()
    
    # Validate arguments
    actions = sum([
        bool(args.tokens),
        args.reset_subscription,
        args.unlimited,
        args.no_unlimited,
        args.unlimited_plan
    ])
    
    if actions == 0:
        print("❌ Error: Must specify one action (--tokens, --reset-subscription, --unlimited, --no-unlimited, or --unlimited-plan)")
        parser.print_help()
        sys.exit(1)
    
    if actions > 1:
        print("❌ Error: Can only specify one action at a time")
        sys.exit(1)
    
    # Execute action
    if args.tokens:
        success = grant_tokens(args.email, args.tokens)
    elif args.reset_subscription:
        success = reset_subscription(args.email)
    elif args.unlimited:
        success = set_unlimited(args.email, True)
    elif args.no_unlimited:
        success = set_unlimited(args.email, False)
    elif args.unlimited_plan:
        success = assign_unlimited_plan(args.email)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

