"""Stripe configuration and plan definitions"""
import os
import json
import logging
import stripe
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Stripe API configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_API_VERSION = os.getenv("STRIPE_API_VERSION", "2024-11-20.acacia")

# Initialize Stripe
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    stripe.api_version = STRIPE_API_VERSION
else:
    logger.warning("STRIPE_SECRET_KEY not set - Stripe functionality will be disabled")


def detect_stripe_mode(api_key: str = None) -> str:
    """
    Detect Stripe mode (test or live) from API key.
    
    Args:
        api_key: Stripe API key (defaults to STRIPE_SECRET_KEY)
        
    Returns:
        'test' or 'live' or 'unknown'
    """
    if api_key is None:
        api_key = STRIPE_SECRET_KEY
    
    if not api_key:
        return 'unknown'
    
    if api_key.startswith('sk_test_'):
        return 'test'
    elif api_key.startswith('sk_live_'):
        return 'live'
    else:
        return 'unknown'


def get_stripe_mode() -> str:
    """Get current Stripe mode (test or live)"""
    return detect_stripe_mode(STRIPE_SECRET_KEY)


def load_plans(mode: str = None) -> Dict[str, Dict[str, Any]]:
    """
    Load plan configuration from JSON file.
    
    Args:
        mode: 'test' or 'live' (auto-detected if not provided)
        
    Returns:
        Dict of plans keyed by plan type
    """
    if mode is None:
        mode = get_stripe_mode()
        logger.debug(f"Auto-detected Stripe mode: {mode}")
    
    if mode not in ['test', 'live']:
        logger.warning(f"Unknown Stripe mode '{mode}', defaulting to test")
        mode = 'test'
    
    # Read from backend/ directory (same directory as this file)
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(backend_dir, f'stripe_plans_{mode}.json')
    
    logger.debug(f"Loading plans from: {config_file}")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            plans = json.load(f)
            
            # Validate the loaded plans structure
            if not isinstance(plans, dict):
                logger.error(f"Plans file {config_file} does not contain a JSON object")
                return _get_fallback_plans()
            
            # Validate each plan has required fields
            valid_plans = {}
            for plan_key, plan_data in plans.items():
                if not isinstance(plan_data, dict):
                    logger.warning(f"Skipping invalid plan '{plan_key}': not a dictionary")
                    continue
                
                price_id = plan_data.get('stripe_price_id')
                if not price_id:
                    logger.warning(f"Plan '{plan_key}' has no stripe_price_id - this plan will not work for subscriptions")
                
                valid_plans[plan_key] = plan_data
            
            if len(valid_plans) == 0:
                logger.error(f"No valid plans found in {config_file}")
                return _get_fallback_plans()
            
            logger.info(f"Loaded {len(valid_plans)} plans from {config_file}")
            # Log price IDs at INFO level for verification
            for plan_key, plan_data in valid_plans.items():
                price_id = plan_data.get('stripe_price_id')
                overage_price_id = plan_data.get('stripe_overage_price_id')
                logger.info(f"  {plan_key}: price_id={price_id}, overage_price_id={overage_price_id}")
            
            return valid_plans
    except FileNotFoundError:
        logger.error(f"Plan config file not found: {config_file}")
        logger.error("Run setup_stripe.py to generate configuration")
        logger.warning("Using fallback plans (free plan only)")
        return _get_fallback_plans()
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {config_file}: {e}")
        logger.warning("Using fallback plans (free plan only)")
        return _get_fallback_plans()


def _get_fallback_plans() -> Dict[str, Dict[str, Any]]:
    """Fallback plans if JSON config is missing."""
    return {
        'free': {
            'name': 'Free',
            'monthly_tokens': 10,
            'stripe_price_id': None,
            'stripe_product_id': None,
            'stripe_overage_price_id': None,
        }
    }


# Load plans on module import
_PLANS_CACHE = None

def get_plans() -> Dict[str, Dict[str, Any]]:
    """
    Get the appropriate PLANS dictionary based on current Stripe mode.
    Cached after first load.
    
    Returns:
        PLANS dict for current mode (test or live)
    """
    global _PLANS_CACHE
    if _PLANS_CACHE is None:
        _PLANS_CACHE = load_plans()
    return _PLANS_CACHE


def reload_plans():
    """Force reload of plans from JSON (useful after running setup)."""
    global _PLANS_CACHE
    logger.info("Reloading plans from file (clearing cache)")
    _PLANS_CACHE = load_plans()
    logger.info(f"Plans reloaded: {len(_PLANS_CACHE)} plans")
    return _PLANS_CACHE


# Token calculation: 1 token = 10MB
TOKEN_CALCULATION_MB_PER_TOKEN = 10
BYTES_PER_MB = 1024 * 1024


def calculate_tokens_from_bytes(file_size_bytes: int) -> int:
    """
    Calculate tokens required for a file upload.
    
    Formula: 1 token = 10MB
    Rounds up to nearest integer (so 1MB = 1 token, 11MB = 2 tokens)
    
    Args:
        file_size_bytes: File size in bytes
        
    Returns:
        Number of tokens required
    """
    if file_size_bytes <= 0:
        return 0
    
    size_mb = file_size_bytes / BYTES_PER_MB
    tokens = int(size_mb / TOKEN_CALCULATION_MB_PER_TOKEN)
    
    # Round up: if there's any remainder, add 1 token
    if size_mb % TOKEN_CALCULATION_MB_PER_TOKEN > 0:
        tokens += 1
    
    return max(1, tokens)  # Minimum 1 token for any upload


def get_plan_monthly_tokens(plan_type: str) -> int:
    """Get monthly token allocation for a plan
    
    Returns:
        -1 for unlimited plan, otherwise the monthly token count
    """
    plans = get_plans()
    plan = plans.get(plan_type)
    if plan:
        return plan['monthly_tokens']  # -1 for unlimited, otherwise token count
    return plans.get('free', {}).get('monthly_tokens', 10)  # Default to free


def get_plan_price_id(plan_type: str) -> Optional[str]:
    """Get Stripe price ID for a plan type
    
    Args:
        plan_type: Plan type ('free', 'starter', 'creator', 'unlimited')
        
    Returns:
        Stripe price ID or None if not found/configured
    """
    plans = get_plans()
    plan = plans.get(plan_type)
    if plan:
        return plan.get('stripe_price_id')
    logger.warning(f"Plan type '{plan_type}' not found in plans. Available plans: {list(plans.keys())}")
    return None


def get_plan_overage_price_id(plan_type: str) -> Optional[str]:
    """Get Stripe overage price ID for a plan type (metered usage)
    
    Args:
        plan_type: Plan type ('free', 'starter', 'creator', 'unlimited')
        
    Returns:
        Stripe overage price ID or None if not found/configured
    """
    plans = get_plans()
    plan = plans.get(plan_type)
    if plan:
        return plan.get('stripe_overage_price_id')
    logger.warning(f"Plan type '{plan_type}' not found in plans. Available plans: {list(plans.keys())}")
    return None


def get_price_info(price_id: str) -> Optional[Dict[str, Any]]:
    """
    Get price information from Stripe.
    
    Args:
        price_id: Stripe price ID
        
    Returns:
        Dict with 'amount' (in cents), 'currency', 'formatted' (e.g., '$9.99/month'), or None if not found
    """
    if not STRIPE_SECRET_KEY or not price_id:
        return None
    
    try:
        price = stripe.Price.retrieve(price_id)
        
        amount = price.unit_amount
        currency = price.currency.upper() if hasattr(price, 'currency') else 'USD'
        
        if amount is None:
            return None
        
        # Format price (amount is in cents)
        amount_dollars = amount / 100
        formatted = f"${amount_dollars:.2f}"
        if currency != 'USD':
            formatted = f"{currency} {amount_dollars:.2f}"
        
        # Add /month if it's a recurring price
        if hasattr(price, 'recurring') and price.recurring:
            formatted += "/month"
        
        return {
            'amount': amount,  # In cents
            'amount_dollars': amount_dollars,
            'currency': currency,
            'formatted': formatted
        }
    except stripe.error.StripeError as e:
        logger.warning(f"Error retrieving price {price_id}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error retrieving price {price_id}: {e}")
        return None