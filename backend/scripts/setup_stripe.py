#!/usr/bin/env python3
"""
Stripe setup script - creates products, prices, and webhooks.

Usage:
    python setup_stripe.py --env-file dev
    python setup_stripe.py --env-file prod
    python setup_stripe.py --mode test --api-key sk_test_KEY [--webhook-url URL]
"""

import argparse
import os
import re
import sys
import stripe
from typing import Dict, Any

# Product definitions
PRODUCTS = {
    'free': {'name': 'Hopper Free', 'description': '10 tokens per month', 'monthly_tokens': 10, 'price_cents': 0},
    'medium': {'name': 'Hopper Medium', 'description': '100 tokens per month', 'monthly_tokens': 100, 'price_cents': 999},
    'pro': {'name': 'Hopper Pro', 'description': '500 tokens per month', 'monthly_tokens': 500, 'price_cents': 2999},
    'unlimited': {'name': 'Hopper Unlimited', 'description': 'Unlimited tokens', 'monthly_tokens': -1, 'price_cents': 0, 'hidden': True}
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
        
        paths = [
            f'/app/.env.{env_file}',
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), f'.env.{env_file}'),
            f'.env.{env_file}',
        ]
        
        for path in paths:
            if os.path.exists(path):
                load_dotenv(path, override=True)
                
                # Manual parsing for ${VAR} substitution
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            value = value.strip().strip('"').strip("'")
                            value = re.sub(r'\$\{(\w+)\}', lambda m: os.getenv(m.group(1), ''), value)
                            if key and value:
                                os.environ[key.strip()] = value
                
                print(f"✓ Loaded {os.path.basename(path)}")
                return True
        
        print(f"⚠️  .env.{env_file} not found, using existing env vars")
        return False
        
    except ImportError:
        print("❌ python-dotenv not installed: pip install python-dotenv")
        return False


def create_or_update_products(mode: str) -> Dict[str, Dict[str, Any]]:
    """Create or update Stripe products and prices."""
    print(f"\n{'='*60}\nProducts and Prices ({mode.upper()})\n{'='*60}\n")
    
    results = {}
    existing_products = {p.name: p for p in stripe.Product.list(limit=100).data}
    existing_prices = stripe.Price.list(limit=100, active=True)
    price_map = {}
    for price in existing_prices.data:
        price_map.setdefault(price.product, []).append(price)
    
    for key, config in PRODUCTS.items():
        print(f"{config['name']} (key: {key})")
        
        # Create or find product
        product = existing_products.get(config['name'])
        if product:
            print(f"  ✓ Found product: {product.id}")
        else:
            product = stripe.Product.create(name=config['name'], description=config['description'])
            print(f"  ✓ Created product: {product.id}")
        
        # Find or create price
        price = None
        for p in price_map.get(product.id, []):
            if p.unit_amount == config['price_cents'] and p.currency == 'usd':
                if config['price_cents'] == 0 and not p.recurring:
                    price = p
                    break
                elif config['price_cents'] > 0 and p.recurring and p.recurring.interval == 'month':
                    price = p
                    break
        
        if price:
            print(f"  ✓ Found price: {price.id}")
        else:
            if config['price_cents'] == 0:
                price = stripe.Price.create(product=product.id, unit_amount=0, currency='usd')
            else:
                price = stripe.Price.create(
                    product=product.id,
                    unit_amount=config['price_cents'],
                    currency='usd',
                    recurring={'interval': 'month'}
                )
            print(f"  ✓ Created price: {price.id}")
        
        results[key] = {
            'name': config['name'],
            'product_id': product.id,
            'price_id': price.id,
            'monthly_tokens': config['monthly_tokens'],
            'price_cents': config['price_cents'],
        }
        print()
    
    return results


def update_config_file(products: Dict[str, Dict[str, Any]], mode: str) -> bool:
    """Update stripe_config.py with product and price IDs."""
    config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'stripe_config.py')
    
    if not os.path.exists(config_file):
        print(f"⚠️  {config_file} not found")
        return False
    
    with open(config_file) as f:
        lines = f.readlines()
    
    plans_dict = 'PLANS_TEST' if mode == 'test' else 'PLANS_LIVE'
    in_target_dict = False
    in_plan = None
    new_lines = []
    updated_plans = set()
    
    for line in lines:
        # Check if entering target dictionary
        if f'{plans_dict} = {{' in line:
            in_target_dict = True
            new_lines.append(line)
            continue
        
        # Check if exiting target dictionary (closing brace at start of line)
        if in_target_dict and line.lstrip().startswith('}'):
            in_target_dict = False
            new_lines.append(line)
            continue
        
        if in_target_dict:
            # Check if entering a plan (e.g., 'unlimited': {)
            plan_match = re.match(r"\s+'(\w+)':\s+\{", line)
            if plan_match:
                in_plan = plan_match.group(1)
                new_lines.append(line)
                continue
            
            # Check if exiting a plan (line starts with }, or } followed by comment)
            if in_plan and line.lstrip().startswith('},'):
                in_plan = None
                new_lines.append(line)
                continue
            
            # Update stripe IDs if we're in a plan that we have data for
            if in_plan and in_plan in products:
                product_info = products[in_plan]
                indent = len(line) - len(line.lstrip())
                
                if "'stripe_price_id':" in line or '"stripe_price_id":' in line:
                    # Preserve comment if present
                    comment = f"  # {line.split('#', 1)[1].strip()}" if '#' in line else ""
                    line = f"{' ' * indent}'stripe_price_id': \"{product_info['price_id']}\",{comment}\n"
                    updated_plans.add(in_plan)
                    print(f"  → Updating {in_plan} price_id: {product_info['price_id']}")
                elif "'stripe_product_id':" in line or '"stripe_product_id":' in line:
                    # Preserve comment if present
                    comment = f"  # {line.split('#', 1)[1].strip()}" if '#' in line else ""
                    line = f"{' ' * indent}'stripe_product_id': \"{product_info['product_id']}\",{comment}\n"
                    updated_plans.add(in_plan)
                    print(f"  → Updating {in_plan} product_id: {product_info['product_id']}")
        
        new_lines.append(line)
    
    if updated_plans:
        with open(config_file, 'w') as f:
            f.writelines(new_lines)
        print(f"\n✓ Updated stripe_config.py: {', '.join(sorted(updated_plans))}")
        
        # Check for missing plans
        missing = set(products.keys()) - updated_plans
        if missing:
            print(f"⚠️  Could not update: {', '.join(sorted(missing))}")
        
        return True
    
    print("⚠️  No plans updated in stripe_config.py")
    print(f"   Expected plans: {', '.join(products.keys())}")
    return False


def create_or_update_webhook(webhook_url: str, mode: str) -> Dict[str, Any]:
    """Create or update Stripe webhook endpoint."""
    print(f"\n{'='*60}\nWebhook ({mode.upper()})\n{'='*60}\n")
    print(f"URL: {webhook_url}\n")
    
    existing = stripe.WebhookEndpoint.list(limit=100)
    matching = next((w for w in existing.data if w.url == webhook_url), None)
    
    if matching:
        print(f"✓ Found webhook: {matching.id}")
        
        current_events = set(matching.enabled_events)
        if current_events != set(WEBHOOK_EVENTS):
            webhook = stripe.WebhookEndpoint.modify(matching.id, enabled_events=WEBHOOK_EVENTS)
            print("✓ Updated events")
        else:
            webhook = matching
            print("✓ Events already correct")
        
        print(f"\n⚠️  Get signing secret from Stripe Dashboard:")
        print(f"   https://dashboard.stripe.com/{'test/' if mode == 'test' else ''}webhooks")
        return {'id': webhook.id, 'url': webhook.url, 'secret': None}
    
    webhook = stripe.WebhookEndpoint.create(
        url=webhook_url,
        enabled_events=WEBHOOK_EVENTS,
        description=f"Hopper webhook ({mode})"
    )
    print(f"✓ Created webhook: {webhook.id}")
    
    secret = getattr(webhook, 'secret', None)
    if secret:
        print(f"\n🔑 Signing Secret: {secret}")
        print(f"   Add to .env: STRIPE_WEBHOOK_SECRET={secret}")
    
    return {'id': webhook.id, 'url': webhook.url, 'secret': secret}


def print_summary(mode: str, products: Dict, webhook: Dict = None, config_updated: bool = False):
    """Print summary."""
    print(f"\n{'='*60}\n✅ Setup Complete ({mode.upper()})\n{'='*60}\n")
    
    print("Products:")
    for key, info in products.items():
        print(f"  {key}: {info['product_id']} / {info['price_id']}")
    
    if webhook:
        print(f"\nWebhook: {webhook['id']}")
    
    print(f"\n{'='*60}")
    if not config_updated:
        print("⚠️  Manually update stripe_config.py with IDs above")
    if webhook and not webhook.get('secret'):
        print("⚠️  Get webhook secret from Stripe Dashboard")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Setup Stripe products, prices, and webhooks')
    parser.add_argument('--env-file', choices=['dev', 'prod'], help='Load from .env.dev or .env.prod')
    parser.add_argument('--mode', choices=['test', 'live'], help='Stripe mode')
    parser.add_argument('--api-key', help='Stripe API key')
    parser.add_argument('--webhook-url', help='Webhook URL')
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
    mode = args.mode
    if not mode:
        mode = 'test' if api_key.startswith('sk_test_') else 'live'
        print(f"✓ Detected {mode.upper()} mode")
    
    # Validate API key
    if mode == 'test' and not api_key.startswith('sk_test_'):
        print("❌ Test mode requires sk_test_ key")
        sys.exit(1)
    if mode == 'live' and not api_key.startswith('sk_live_'):
        print("❌ Live mode requires sk_live_ key")
        sys.exit(1)
    
    # Get webhook URL
    webhook_url = args.webhook_url
    if not webhook_url and args.env_file:
        backend_url = os.getenv('BACKEND_URL')
        if backend_url:
            webhook_url = f"{backend_url.rstrip('/')}/api/stripe/webhook"
            print(f"✓ Using webhook: {webhook_url}")
    
    # Setup Stripe
    stripe.api_key = api_key
    stripe.api_version = "2024-11-20.acacia"
    
    print(f"\nStripe Setup - {mode.upper()}")
    
    # Create products
    products = create_or_update_products(mode)
    
    # Update config
    config_updated = update_config_file(products, mode)
    
    # Create webhook
    webhook = None
    if webhook_url:
        webhook = create_or_update_webhook(webhook_url, mode)
    else:
        print("\n⚠️  No webhook URL provided")
    
    # Summary
    print_summary(mode, products, webhook, config_updated)


if __name__ == '__main__':
    main()