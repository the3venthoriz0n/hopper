"""Stripe configuration and plan definitions"""
import os
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


# Plan definitions for TEST mode (sandbox)
# Product/Price IDs are auto-updated by setup_stripe.py
PLANS_TEST = {
    'free': {
        'name': 'Hopper Free',
        'monthly_tokens': 10,
        'stripe_price_id': "price_1Se2XZAJugrwwGJAIGrRqT92",
        'stripe_product_id': "prod_TbF1UTDoRuGhOy",
    },
    'medium': {
        'name': 'Hopper Medium',
        'monthly_tokens': 100,
        'stripe_price_id': "price_1Se2XZAJugrwwGJA6zdgFohu",
        'stripe_product_id': "prod_TbF1KSxCYnqVzT",
    },
    'pro': {
        'name': 'Hopper Pro',
        'monthly_tokens': 500,
        'stripe_price_id': "price_1Se2XaAJugrwwGJAzeUZsFiy",
        'stripe_product_id': "prod_TbF1urcgxdTYYv",
    },
    'unlimited': {
        'name': 'Hopper Unlimited',
        'monthly_tokens': -1,  # -1 indicates unlimited
        'stripe_price_id': "price_1Se6W7AJugrwwGJAnlJ3Gqh0",  # Auto-updated by setup_stripe.py
        'stripe_product_id': "prod_TbIU2tjHI5Tx6r",  # Auto-updated by setup_stripe.py
        'hidden': True,  # Hidden from public plans list (dev/admin only)
    }
}

# Plan definitions for LIVE mode (production)
# Product/Price IDs are auto-updated by setup_stripe.py
PLANS_LIVE = {
    'free': {
        'name': 'Hopper Free',
        'monthly_tokens': 10,
        'stripe_price_id': "price_1SdxH7AizedXSXdvzLcftaqi",  # Auto-updated by setup_stripe.py
        'stripe_product_id': "prod_Tb9acbATXP0258",  # Auto-updated by setup_stripe.py
    },
    'medium': {
        'name': 'Hopper Medium',
        'monthly_tokens': 100,
        'stripe_price_id': "price_1SdxH7AizedXSXdvVp0yPXnd",  # Auto-updated by setup_stripe.py
        'stripe_product_id': "prod_Tb9a57n5L7GcuK",  # Auto-updated by setup_stripe.py
    },
    'pro': {
        'name': 'Hopper Pro',
        'monthly_tokens': 500,
        'stripe_price_id': "price_1SdxH7AizedXSXdv1dIUYgby",  # Auto-updated by setup_stripe.py
        'stripe_product_id': "prod_Tb9aHluyY1RIVH",  # Auto-updated by setup_stripe.py
    },
    'unlimited': {
        'name': 'Hopper Unlimited',
        'monthly_tokens': -1,  # -1 indicates unlimited
        'stripe_price_id': "price_1Seh38AizedXSXdv9v8x0nMm",  # Auto-updated by setup_stripe.py
        'stripe_product_id': "prod_Tbusrpl0qNLTq3",  # Auto-updated by setup_stripe.py
        'hidden': True,  # Hidden from public plans list (dev/admin only)
    }
}

# Legacy PLANS dict for backward compatibility - will be set dynamically
PLANS: Dict[str, Dict[str, Any]] = {}


def get_plans() -> Dict[str, Dict[str, Any]]:
    """
    Get the appropriate PLANS dictionary based on current Stripe mode.
    Also updates the global PLANS dict for backward compatibility.
    
    Returns:
        PLANS dict for current mode (test or live)
    """
    mode = get_stripe_mode()
    if mode == 'live':
        plans = PLANS_LIVE
    elif mode == 'test':
        plans = PLANS_TEST
    else:
        # Default to test if unknown
        logger.warning(f"Unknown Stripe mode, defaulting to test. API key: {STRIPE_SECRET_KEY[:10] if STRIPE_SECRET_KEY else 'None'}...")
        plans = PLANS_TEST
    
    # Update global PLANS for backward compatibility
    global PLANS
    PLANS = plans.copy()
    
    return plans


# Initialize PLANS based on current mode
def _init_plans():
    """Initialize PLANS dict based on current Stripe mode"""
    get_plans()  # This will update PLANS


# Initialize on import
_init_plans()

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
    return plans['free']['monthly_tokens']  # Default to free


def get_plan_price_id(plan_type: str) -> Optional[str]:
    """Get Stripe price ID for a plan type
    
    Args:
        plan_type: Plan type ('free', 'medium', 'pro', 'unlimited')
        
    Returns:
        Stripe price ID or None if not found/configured
    """
    plans = get_plans()
    plan = plans.get(plan_type)
    if plan:
        return plan.get('stripe_price_id')
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


def ensure_stripe_products():
    """
    Create Stripe products and prices if they don't exist.
    This is idempotent - it checks for existing products before creating.
    
    Returns:
        dict: Updated PLANS dict with Stripe IDs for current mode
    """
    if not STRIPE_SECRET_KEY:
        logger.error("Cannot create Stripe products: STRIPE_SECRET_KEY not set")
        return get_plans()
    
    mode = get_stripe_mode()
    if mode == 'unknown':
        logger.error("Cannot detect Stripe mode from API key")
        return get_plans()
    
    current_plans = get_plans()
    
    try:
        # Get existing products
        existing_products = stripe.Product.list(limit=100)
        product_map = {p.name: p for p in existing_products.data}
        
        # Get existing prices
        existing_prices = stripe.Price.list(limit=100, active=True)
        price_map = {}  # Map product_id -> price
        
        for price in existing_prices.data:
            if price.product not in price_map:
                price_map[price.product] = price
        
        updated_plans = {}
        
        for plan_key, plan_config in current_plans.items():
            plan_name = plan_config['name']
            
            # Check if product exists
            if plan_name in product_map:
                product = product_map[plan_name]
                logger.info(f"Found existing Stripe product ({mode}): {plan_name} ({product.id})")
            else:
                # Create product
                product = stripe.Product.create(
                    name=plan_name,
                    description=f"{plan_name} plan - {plan_config['monthly_tokens']} tokens per month"
                )
                logger.info(f"Created Stripe product ({mode}): {plan_name} ({product.id})")
            
            # Check if price exists for this product
            if product.id in price_map:
                price = price_map[product.id]
                logger.info(f"Found existing Stripe price ({mode}) for {plan_name}: {price.id}")
            else:
                # Create price (monthly recurring)
                # Note: Set actual price amounts in Stripe dashboard or via API
                # For now, using placeholder amounts - UPDATE THESE with real prices
                price_amounts = {
                    'free': 0,      # Free plan
                    'medium': 999,  # $9.99/month - UPDATE THIS
                    'pro': 2999,    # $29.99/month - UPDATE THIS
                }
                
                price = stripe.Price.create(
                    product=product.id,
                    unit_amount=price_amounts.get(plan_key, 0),  # Amount in cents
                    currency='usd',
                    recurring={'interval': 'month'},
                )
                logger.info(f"Created Stripe price ({mode}) for {plan_name}: {price.id} (${price_amounts.get(plan_key, 0)/100:.2f}/month)")
            
            updated_plans[plan_key] = {
                **plan_config,
                'stripe_product_id': product.id,
                'stripe_price_id': price.id,
            }
        
        # Update the global PLANS dict
        global PLANS
        PLANS = updated_plans
        
        # Also update the mode-specific dict
        if mode == 'test':
            for key in updated_plans:
                PLANS_TEST[key].update(updated_plans[key])
        elif mode == 'live':
            for key in updated_plans:
                PLANS_LIVE[key].update(updated_plans[key])
        
        return updated_plans
        
    except stripe.error.StripeError as e:
        logger.error(f"Error creating Stripe products ({mode}): {e}")
        return current_plans
    except Exception as e:
        logger.error(f"Unexpected error in ensure_stripe_products ({mode}): {e}", exc_info=True)
        return current_plans

