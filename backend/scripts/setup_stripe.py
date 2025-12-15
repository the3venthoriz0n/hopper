#!/usr/bin/env python3
"""
Stripe setup script - creates products, prices, and webhooks.
Writes configuration to stripe_plans.json for runtime use.

Usage:
    python setup_stripe.py --env-file dev
    python setup_stripe.py --env-file prod
    python setup_stripe.py --mode test --api-key sk_test_KEY
"""

import argparse
import json
import os
import sys
import stripe
from typing import Dict, Any, List, Optional

# Product definitions
PRODUCTS = {
    'free': {
        'name': 'Free',
        'description': '10 tokens per month',
        'monthly_tokens': 10,
        'price_cents': 0,
        'overage_price_cents': None  # Hard limit, no overages
    },
    'starter': {
        'name': 'Starter',
        'description': '100 tokens per month',
        'monthly_tokens': 100,
        'price_cents': 999,  # $9.99/month
        'overage_price_cents': 29  # $0.29 per token
    },
    'creator': {
        'name': 'Creator',
        'description': '500 tokens per month',
        'monthly_tokens': 500,
        'price_cents': 2999,  # $29.99/month
        'overage_price_cents': 20  # $0.20 per token
    },
    'unlimited': {
        'name': 'Unlimited',
        'description': 'Unlimited tokens',
        'monthly_tokens': -1,
        'price_cents': 0,
        'overage_price_cents': None,
        'hidden': True
    }
}

WEBHOOK_EVENTS = [
    'checkout.session.completed',
    'customer.subscription.created',
    'customer.subscription.updated',
    'customer.subscription.deleted',
    'invoice.payment_succeeded',
    'invoice.payment_failed',
]


def load_env_file(env_file: str) -> bool:
    """Load environment variables from .env file."""
    try:
        from dotenv import load_dotenv
        
        # Look for .env file in multiple locations
        # 1. Project root (../../.env.{env_file} from scripts/)
        # 2. Current directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(script_dir)
        project_root = os.path.dirname(backend_dir)
        
        paths = [
            os.path.join(project_root, f'.env.{env_file}'),
            f'.env.{env_file}',
        ]
        
        for path in paths:
            if os.path.exists(path):
                load_dotenv(path, override=True)
                print(f"✓ Loaded {path}")
                return True
        
        print(f"⚠️  .env.{env_file} not found")
        return False
    except ImportError:
        print("❌ python-dotenv not installed: pip install python-dotenv")
        return False


def find_or_create_price(product_id: str, config: Dict[str, Any], 
                         existing_prices: List[Any], is_metered: bool = False) -> Any:
    """Find existing price or create new one."""
    amount = config['overage_price_cents'] if is_metered else config['price_cents']
    
    # Search for existing price
    for price in existing_prices:
        if price.product != product_id or price.unit_amount != amount:
            continue
        
        if is_metered:
            if (price.recurring and 
                hasattr(price.recurring, 'usage_type') and 
                price.recurring.usage_type == 'metered'):
                return price
        else:
            if price.recurring and price.recurring.interval == 'month':
                return price
    
    # Create new price
    price_params = {
        'product': product_id,
        'unit_amount': amount,
        'currency': 'usd',
        'recurring': {'interval': 'month'}
    }
    
    if is_metered:
        price_params['recurring'].update({
            'usage_type': 'metered',
            'aggregate_usage': 'sum'
        })
        price_params['billing_scheme'] = 'per_unit'
    
    return stripe.Price.create(**price_params)


def create_or_update_products() -> Dict[str, Dict[str, Any]]:
    """Create or update Stripe products and prices."""
    print(f"\n{'='*60}\nProducts and Prices\n{'='*60}\n")
    
    results = {}
    existing_products = {p.name: p for p in stripe.Product.list(limit=100).data}
    existing_prices = stripe.Price.list(limit=100, active=True).data
    
    for key, config in PRODUCTS.items():
        print(f"{config['name']} (key: {key})")
        
        # Find or create product
        product = existing_products.get(config['name'])
        if product:
            print(f"  ✓ Product: {product.id}")
        else:
            product = stripe.Product.create(
                name=config['name'],
                description=config['description']
            )
            print(f"  ✓ Created product: {product.id}")
        
        # Find or create base price
        price = find_or_create_price(product.id, config, existing_prices)
        print(f"  ✓ Price: {price.id} (${config['price_cents']/100:.2f}/month)")
        
        # Build plan config
        plan_config = {
            'name': config['name'],
            'monthly_tokens': config['monthly_tokens'],
            'stripe_product_id': product.id,
            'stripe_price_id': price.id,
            'stripe_overage_price_id': None
        }
        
        # Add hidden flag if present
        if config.get('hidden'):
            plan_config['hidden'] = True
        
        # Create metered overage price if configured
        if config.get('overage_price_cents') is not None:
            overage_price = find_or_create_price(product.id, config, existing_prices, is_metered=True)
            plan_config['stripe_overage_price_id'] = overage_price.id
            print(f"  ✓ Overage: {overage_price.id} (${config['overage_price_cents']/100:.2f}/token)")
        
        results[key] = plan_config
        print()
    
    return results


def save_config(plans: Dict[str, Dict[str, Any]], mode: str) -> bool:
    """Save plans configuration to JSON file."""
    # Write to backend/ directory (one level up from scripts/)
    # This will be: /mnt/y/Misc/_DevRemote/hopper_sync/backend/stripe_plans_{mode}.json
    config_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_file = os.path.join(config_dir, f'stripe_plans_{mode}.json')
    
    print(f"\n{'='*60}\nSaving Configuration\n{'='*60}")
    print(f"File: {config_file}\n")
    
    try:
        with open(config_file, 'w') as f:
            json.dump(plans, f, indent=2)
        
        print(f"✓ Saved configuration for {len(plans)} plans")
        print(f"✓ Mode: {mode}")
        
        # Verify
        with open(config_file) as f:
            loaded = json.load(f)
        
        if loaded == plans:
            print(f"✓ Verified file write successful")
            return True
        else:
            print(f"❌ Verification failed")
            return False
            
    except Exception as e:
        print(f"❌ Error saving config: {e}")
        return False


def create_or_update_webhook(webhook_url: str) -> Optional[Dict[str, Any]]:
    """Create or update Stripe webhook endpoint."""
    print(f"\n{'='*60}\nWebhook\n{'='*60}\n")
    print(f"URL: {webhook_url}\n")
    
    existing = stripe.WebhookEndpoint.list(limit=100)
    matching = next((w for w in existing.data if w.url == webhook_url), None)
    
    if matching:
        print(f"✓ Found webhook: {matching.id}")
        if set(matching.enabled_events) != set(WEBHOOK_EVENTS):
            stripe.WebhookEndpoint.modify(matching.id, enabled_events=WEBHOOK_EVENTS)
            print("✓ Updated events")
        return {'id': matching.id, 'secret': None}
    
    webhook = stripe.WebhookEndpoint.create(
        url=webhook_url,
        enabled_events=WEBHOOK_EVENTS
    )
    print(f"✓ Created webhook: {webhook.id}")
    
    if hasattr(webhook, 'secret'):
        print(f"\n🔑 Secret: {webhook.secret}")
        print(f"   Add to .env: STRIPE_WEBHOOK_SECRET={webhook.secret}")
        return {'id': webhook.id, 'secret': webhook.secret}
    
    return {'id': webhook.id, 'secret': None}


def main():
    parser = argparse.ArgumentParser(description='Setup Stripe products, prices, and webhooks')
    parser.add_argument('--env-file', choices=['dev', 'prod'], help='Load from .env file')
    parser.add_argument('--mode', choices=['test', 'live'], help='Stripe mode')
    parser.add_argument('--api-key', help='Stripe API key')
    parser.add_argument('--webhook-url', help='Webhook URL (optional)')
    args = parser.parse_args()
    
    # Load env file
    if args.env_file:
        load_env_file(args.env_file)
    
    # Get API key
    api_key = args.api_key or os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("❌ STRIPE_SECRET_KEY not found")
        sys.exit(1)
    
    # Detect mode
    mode = args.mode or ('test' if api_key.startswith('sk_test_') else 'live')
    
    # Validate API key matches mode
    if (mode == 'test' and not api_key.startswith('sk_test_')) or \
       (mode == 'live' and not api_key.startswith('sk_live_')):
        print(f"❌ API key doesn't match {mode} mode")
        sys.exit(1)
    
    print(f"\nStripe Setup - {mode.upper()}")
    
    # Initialize Stripe
    stripe.api_key = api_key
    stripe.api_version = "2024-11-20.acacia"
    
    # Create products and prices
    plans = create_or_update_products()
    
    # Save config to JSON
    config_saved = save_config(plans, mode)
    
    # Create webhook (optional)
    webhook = None
    webhook_url = args.webhook_url or os.getenv('BACKEND_URL', '').rstrip('/') + '/api/stripe/webhook'
    if webhook_url and not webhook_url.startswith('/api'):
        webhook = create_or_update_webhook(webhook_url)
    
    # Summary
    print(f"\n{'='*60}\n✅ Setup Complete\n{'='*60}\n")
    if not config_saved:
        print("⚠️  Config file not saved")
    if webhook and not webhook.get('secret'):
        print("⚠️  Get webhook secret from Stripe Dashboard")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()