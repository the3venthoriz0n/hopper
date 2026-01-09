#!/usr/bin/env python3
"""
Stripe setup script - creates products, prices, and meters.
Idempotent: running multiple times produces the same result.
"""

import argparse
import os
import sys
import stripe
from typing import Dict, Any, List, Optional

# Constants
METER_EVENT_NAME = "hopper_tokens"
METER_DISPLAY_NAME = "hopper tokens"
STRIPE_API_VERSION = "2024-11-20.acacia"

# Plan configurations
PLANS = {
    'free_daily': {
        'name': 'Free Daily',
        'display_name': 'Free',  # What users see
        'description': '3 tokens per day, max 10 tokens',
        'tokens': 3,
        'price_dollars': 0,
        'overage_cents': None,
        'interval': 'day',
        'max_accrual': 10
    },
    'starter': {
        'name': 'Starter',
        'description': '300 tokens per month',
        'tokens': 300,
        'price_dollars': 3.0,
        'overage_cents': 1.5,
        'interval': 'month'
    },
    'creator': {
        'name': 'Creator',
        'description': '1250 tokens per month',
        'tokens': 1250,
        'price_dollars': 10.0,
        'overage_cents': 0.8,
        'interval': 'month'
    },
    'unlimited': {
        'name': 'Unlimited',
        'description': 'Unlimited tokens',
        'tokens': -1,
        'price_dollars': 0.0,
        'overage_cents': None,
        'interval': 'month',
        'hidden': True
    }
}


def load_env_file(env_file: str) -> bool:
    """Load environment variables from .env file."""
    try:
        from dotenv import load_dotenv
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(backend_dir)
        
        paths = [
            os.path.join(project_root, f'.env.{env_file}'),
            os.path.join(backend_dir, f'.env.{env_file}'),
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


def get_or_create_meter() -> stripe.billing.Meter:
    """Find or create the billing meter for token usage."""
    meters = stripe.billing.Meter.list(limit=100)
    for meter in meters.data:
        if getattr(meter, "event_name", None) == METER_EVENT_NAME:
            print(f"  ✓ Using existing meter: {meter.id}")
            return meter

    print(f"  ➕ Creating meter for {METER_EVENT_NAME}")
    return stripe.billing.Meter.create(
        display_name=METER_DISPLAY_NAME,
        event_name=METER_EVENT_NAME,
        default_aggregation={"formula": "sum"},
        customer_mapping={"event_payload_key": "stripe_customer_id", "type": "by_id"},
        value_settings={"event_payload_key": "value"},
    )


def build_product_metadata(plan_key: str, config: Dict[str, Any]) -> Dict[str, str]:
    """Build metadata for a product."""
    metadata = {
        "plan_key": plan_key,
        "tokens": str(config['tokens'])
    }
    
    if config.get('hidden'):
        metadata["hidden"] = "true"
    if config.get('max_accrual'):
        metadata["max_accrual"] = str(config['max_accrual'])
    if config.get('display_name'):
        metadata["display_name"] = config['display_name']
    
    return metadata


def sync_product(plan_key: str, config: Dict[str, Any], all_products: List) -> stripe.Product:
    """Create or update a product to match the config. Idempotent."""
    metadata = build_product_metadata(plan_key, config)
    
    # Find existing product by plan_key
    product = None
    for p in all_products:
        if p.metadata.get('plan_key') == plan_key:
            product = p
            break
    
    if product:
        # Update if needed
        needs_update = (
            product.description != config['description'] or
            product.metadata != metadata or
            not product.active
        )
        
        if needs_update:
            stripe.Product.modify(
                product.id,
                description=config['description'],
                metadata=metadata,
                active=True
            )
            print(f"  ✓ Updated product: {product.id}")
        else:
            print(f"  ✓ Product up to date: {product.id}")
    else:
        # Create new product
        product = stripe.Product.create(
            name=config['name'],
            description=config['description'],
            metadata=metadata,
            active=True
        )
        print(f"  ✓ Created product: {product.id}")
        all_products.append(product)
    
    return product


def sync_price(
    product_id: str,
    plan_key: str,
    config: Dict[str, Any],
    is_overage: bool,
    meter_id: Optional[str],
    all_prices: List
) -> stripe.Price:
    """Create or update a price to match the config. Idempotent."""
    
    # Build price parameters
    lookup_key = f"{plan_key}_overage_price" if is_overage else f"{plan_key}_price"
    interval = config.get('interval', 'month')
    
    if is_overage:
        amount = str(config['overage_cents'])
        usage_type = "metered"
    else:
        amount = str(int(config['price_dollars'] * 100))
        usage_type = "licensed"
    
    metadata = {"tokens": str(config['tokens'])}
    
    # Find existing active price
    existing_price = None
    for price in all_prices:
        if not price.active:
            continue
        
        # Match by lookup_key and product
        price_product_id = price.product if isinstance(price.product, str) else price.product.id
        if price.lookup_key == lookup_key and price_product_id == product_id:
            existing_price = price
            break
    
    # Check if price matches config
    if existing_price:
        price_matches = (
            existing_price.unit_amount_decimal == amount and
            existing_price.metadata == metadata and
            existing_price.recurring.interval == interval
        )
        
        if price_matches:
            print(f"    ✓ Price up to date: {lookup_key}")
            return existing_price
        else:
            # Deactivate old price if value changed
            print(f"    ⚠️  Price changed, deactivating old: {existing_price.id}")
            stripe.Price.modify(existing_price.id, active=False, lookup_key=None)
    
    # Create new price
    print(f"    ➕ Creating price: {lookup_key}")
    params = {
        "product": product_id,
        "currency": "usd",
        "unit_amount_decimal": amount,
        "recurring": {"interval": interval, "usage_type": usage_type},
        "lookup_key": lookup_key,
        "transfer_lookup_key": True,
        "metadata": metadata
    }
    
    if is_overage:
        params["recurring"]["meter"] = meter_id
    
    new_price = stripe.Price.create(**params)
    all_prices.append(new_price)
    return new_price


def sync_stripe_resources():
    """Sync all Stripe products and prices to match PLANS config."""
    print(f"\n{'='*60}\nSyncing Stripe Products & Prices\n{'='*60}\n")
    
    # Get meter
    meter = get_or_create_meter()
    
    # Load all products and prices
    all_products = stripe.Product.list(limit=100).data
    all_prices = stripe.Price.list(limit=100).data
    
    # Sync each plan
    for plan_key, config in PLANS.items():
        print(f"\nPlan: {config['name']} (key: {plan_key})")
        
        # Sync product
        product = sync_product(plan_key, config, all_products)
        
        # Sync base price
        sync_price(product.id, plan_key, config, is_overage=False, meter_id=None, all_prices=all_prices)
        
        # Sync overage price if applicable
        if config.get('overage_cents') is not None:
            sync_price(product.id, plan_key, config, is_overage=True, meter_id=meter.id, all_prices=all_prices)


def main():
    parser = argparse.ArgumentParser(description='Setup Stripe resources (idempotent)')
    parser.add_argument('--env-file', choices=['dev', 'prod'], help='Load from .env file')
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    api_key = os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("❌ STRIPE_SECRET_KEY not found in environment")
        sys.exit(1)

    stripe.api_key = api_key
    stripe.api_version = STRIPE_API_VERSION
    
    # Determine mode
    if api_key.startswith('sk_test_'):
        mode, env = 'TEST', 'dev'
    elif api_key.startswith('sk_live_'):
        mode, env = 'LIVE', 'prod'
    else:
        mode, env = 'UNKNOWN', 'unknown'

    print(f"\n{'='*60}")
    print(f"Stripe Setup Script")
    print(f"Mode: {mode} | Environment: {env}")
    print(f"API Key: ...{api_key[-4:]}")
    print(f"{'='*60}")
    
    sync_stripe_resources()
    
    print(f"\n{'='*60}")
    print(f"✅ Sync Complete ({mode} mode)")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()