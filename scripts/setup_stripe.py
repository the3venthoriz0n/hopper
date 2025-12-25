#!/usr/bin/env python3
"""
Stripe setup script - creates products, prices, and meters.
Injects monthly_tokens into Product metadata for the StripeRegistry.
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

# price_total_dollars: The flat monthly fee
# overage_unit_cents: The fractional cent cost per token (e.g., 0.8 = $0.008)
PRODUCTS = {
    'free': {
        'name': 'Free',
        'description': '100 tokens per month',
        'monthly_tokens': 100,
        'price_total_dollars': 0,
        'overage_unit_cents': None
    },
    'starter': {
        'name': 'Starter',
        'description': '300 tokens per month',
        'monthly_tokens': 300,
        'price_total_dollars': 3.0,
        'overage_unit_cents': 1.5  # 1.5 cents per token ($0.015)
    },
    'creator': {
        'name': 'Creator',
        'description': '1250 tokens per month',
        'monthly_tokens': 1250,
        'price_total_dollars': 10.0,
        'overage_unit_cents': 0.8  # ($0.008)
    }
}

def load_env_file(env_file: str) -> bool:
    """Load environment variables from .env.{env_file}."""
    try:
        from dotenv import load_dotenv
        backend_dir = os.path.dirname(os.path.abspath(__file__))
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

def get_or_create_meter() -> Any:
    """Find or create the billing meter for token usage."""
    try:
        meters = stripe.billing.Meter.list(limit=100)
        for meter in meters.data:
            if getattr(meter, "event_name", None) == METER_EVENT_NAME:
                print(f"  ✓ Using existing meter: {meter.id}")
                return meter
    except Exception as e:
        print(f"⚠️ Error listing meters: {e}")

    print(f"  ➕ Creating meter for {METER_EVENT_NAME}")
    return stripe.billing.Meter.create(
        display_name=METER_DISPLAY_NAME,
        event_name=METER_EVENT_NAME,
        default_aggregation={"formula": "sum"},
        customer_mapping={"event_payload_key": "stripe_customer_id", "type": "by_id"},
        value_settings={"event_payload_key": "value"},
    )

def find_or_create_price(product_id: str, config: Dict[str, Any], 
                         existing_prices: List[Any], is_metered: bool = False, 
                         meter_id: Optional[str] = None, plan_key: str = "") -> Any:
    """Finds or creates price using stable lookup_keys for the Registry."""
    
    if is_metered:
        target_value = str(config['overage_unit_cents'])
        lookup_key = f"{plan_key}_overage_price"
    else:
        target_value = str(int(config['price_total_dollars'] * 100))
        lookup_key = f"{plan_key}_price"

    # Search for existing active price with this lookup_key
    for price in existing_prices:
        if getattr(price, 'lookup_key', None) == lookup_key and price.active:
            # Check if values match. If not, we'd deactivate and create new, 
            # but for this script we assume lookup_key is the master ID.
            if price.unit_amount_decimal == target_value:
                print(f"    ✓ Found active price by lookup_key: {price.id} ({lookup_key})")
                return price
            else:
                print(f"    ⚠️  Price for {lookup_key} has changed. Deactivating old price...")
                stripe.Price.modify(price.id, active=False)

    print(f"    ➕ Creating new price for {lookup_key}...")
    params = {
        "product": product_id,
        "currency": "usd",
        "unit_amount_decimal": target_value,
        "recurring": {"interval": "month"},
        "lookup_key": lookup_key,
        "transfer_lookup_key": True # Ensures lookup key moves if product is updated
    }
    if is_metered:
        params["recurring"]["usage_type"] = "metered"
        params["recurring"]["meter"] = meter_id
    
    return stripe.Price.create(**params)

def sync_stripe_resources():
    print(f"\n{'='*60}\nSyncing Stripe Products & Metadata\n{'='*60}\n")
    meter = get_or_create_meter()
    meter_id = meter.id if meter else None
    
    all_products = stripe.Product.list(limit=100).data
    existing_products = {p.name: p for p in all_products if p.active}
    existing_prices = stripe.Price.list(limit=100, active=True).data

    for key, config in PRODUCTS.items():
        print(f"Plan: {config['name']}")
        
        # 1. Handle Product & Metadata (The source of truth for monthly_tokens)
        product = existing_products.get(config['name'])
        metadata = {"monthly_tokens": str(config['monthly_tokens'])}
        
        if not product:
            product = stripe.Product.create(
                name=config['name'], 
                description=config['description'],
                metadata=metadata
            )
            print(f"  ✓ Created product: {product.id}")
        else:
            # Update product if description or metadata changed
            if (product.description != config['description'] or 
                product.metadata.get("monthly_tokens") != metadata["monthly_tokens"]):
                stripe.Product.modify(
                    product.id, 
                    description=config['description'],
                    metadata=metadata
                )
                print(f"  ✓ Updated product metadata/description: {product.id}")
        
        # 2. Handle Base Price
        find_or_create_price(product.id, config, existing_prices, is_metered=False, plan_key=key)

        # 3. Handle Overage Price
        if config.get('overage_unit_cents') is not None:
            find_or_create_price(product.id, config, existing_prices, is_metered=True, meter_id=meter_id, plan_key=key)

def main():
    parser = argparse.ArgumentParser(description='Setup Stripe Products with Metadata.')
    parser.add_argument('--env-file', choices=['dev', 'prod'], help='Load from .env file')
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    api_key = os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("❌ STRIPE_SECRET_KEY not found in environment.")
        sys.exit(1)

    stripe.api_key = api_key
    stripe.api_version = STRIPE_API_VERSION
    mode = 'test' if api_key.startswith('sk_test_') else 'live'

    print(f"Starting Setup in {mode.upper()} mode")
    sync_stripe_resources()
    print(f"\n{'='*60}\n✅ Sync Complete. Registry will now fetch these details dynamically.\n{'='*60}")

if __name__ == '__main__':
    main()