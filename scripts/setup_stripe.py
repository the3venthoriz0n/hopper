#!/usr/bin/env python3
"""
Stripe setup script - creates products, prices, and meters.
Injects 'tokens' into Metadata for both Products and Prices.
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

# price_total_dollars: The flat fee for the cycle
# overage_unit_cents: The fractional cent cost per token (e.g., 1.5 = $0.015)
PRODUCTS = {
    'free': {
        'name': 'Free',
        'description': '100 tokens included',
        'tokens': 100,
        'price_total_dollars': 0,
        'overage_unit_cents': None
    },
    'starter': {
        'name': 'Starter',
        'description': '300 tokens included',
        'tokens': 300,
        'price_total_dollars': 3.0,
        'overage_unit_cents': 1.5
    },
    'creator': {
        'name': 'Creator',
        'description': '1250 tokens included',
        'tokens': 1250,
        'price_total_dollars': 10.0,
        'overage_unit_cents': 0.8
    },
    'unlimited': {
        'name': 'Unlimited',
        'description': 'Unlimited tokens',
        'tokens': -1,  # Using -1 to represent unlimited in your logic
        'price_total_dollars': 0.0,
        'overage_unit_cents': None,   # No overage for unlimited
        'hidden': True
    }
}

def load_env_file(env_file: str) -> bool:
    """Load environment variables from .env.{env_file}."""
    try:
        from dotenv import load_dotenv
        # Look in current and parent directory (standard FastAPI structure)
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
    """Finds or creates price using stable lookup_keys and ensures metadata sync."""
    
    metadata = {"tokens": str(config['tokens'])}
    if is_metered:
        target_value = str(config['overage_unit_cents'])
        lookup_key = f"{plan_key}_overage_price"
    else:
        target_value = str(int(config['price_total_dollars'] * 100))
        lookup_key = f"{plan_key}_price"

    # Search for existing active price with this lookup_key
    for price in existing_prices:
        if getattr(price, 'lookup_key', None) == lookup_key and price.active:
            # If price value is the same, just update metadata if needed
            if price.unit_amount_decimal == target_value:
                if price.metadata.get("tokens") != metadata["tokens"]:
                    stripe.Price.modify(price.id, metadata=metadata)
                    print(f"    ✓ Updated metadata for price: {price.id} ({lookup_key})")
                else:
                    print(f"    ✓ Price and metadata up to date: {price.id} ({lookup_key})")
                return price
            else:
                # Deactivate old price if the value changed
                print(f"    ⚠️  Price value for {lookup_key} changed. Deactivating {price.id}...")
                stripe.Price.modify(price.id, active=False, lookup_key=None)

    print(f"    ➕ Creating new price for {lookup_key}...")
    params = {
        "product": product_id,
        "currency": "usd",
        "unit_amount_decimal": target_value,
        "recurring": {"interval": "month"},
        "lookup_key": lookup_key,
        "transfer_lookup_key": True,
        "metadata": metadata
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
    # List prices and expand product to check metadata
    existing_prices = stripe.Price.list(limit=100, active=True).data

    for key, config in PRODUCTS.items():
        print(f"Plan: {config['name']}")
        
        # 1. Product Metadata Sync
        product = existing_products.get(config['name'])
        metadata = {"tokens": str(config['tokens'])}
        
        # Add hidden flag to metadata if present
        if config.get('hidden'):
            metadata["hidden"] = "true"
        
        if not product:
            product = stripe.Product.create(
                name=config['name'], 
                description=config['description'],
                metadata=metadata
            )
            print(f"  ✓ Created product: {product.id}")
        else:
            # Update product if description or metadata changed
            current_hidden = "true" if config.get('hidden') else "false"
            if (product.description != config['description'] or 
                product.metadata.get("tokens") != metadata.get("tokens") or
                product.metadata.get("hidden", "false") != current_hidden):
                stripe.Product.modify(
                    product.id, 
                    description=config['description'],
                    metadata=metadata
                )
                print(f"  ✓ Updated product metadata/description: {product.id}")
        
        # 2. Base Price Sync (updates Price metadata too)
        find_or_create_price(product.id, config, existing_prices, is_metered=False, plan_key=key)

        # 3. Overage Price Sync
        if config.get('overage_unit_cents') is not None:
            find_or_create_price(product.id, config, existing_prices, is_metered=True, meter_id=meter_id, plan_key=key)

def main():
    parser = argparse.ArgumentParser(description='Setup Stripe Resources with stable Lookup Keys.')
    parser.add_argument('--env-file', choices=['dev', 'prod'], help='Load from .env file')
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    api_key = os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("❌ STRIPE_SECRET_KEY not found in environment. Check your .env file.")
        sys.exit(1)

    stripe.api_key = api_key
    stripe.api_version = STRIPE_API_VERSION
    mode = 'test' if api_key.startswith('sk_test_') else 'live'

    print(f"Starting Setup in {mode.upper()} mode")
    sync_stripe_resources()
    print(f"\n{'='*60}\n✅ Sync Complete. Code 'tokens' is now the source of truth.\n{'='*60}")

if __name__ == '__main__':
    main()