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
        'description': '100 tokens per month',
        'tokens': 100,
        'price_total_dollars': 0,
        'overage_unit_cents': None,
        'internal_status': 'archived_legacy'
    },
    'free_daily': {
        'name': 'Free',
        'description': '3 tokens per day, max 10 tokens',
        'tokens': 3,
        'price_total_dollars': 0,
        'overage_unit_cents': None,
        'recurring_interval': 'day',
        'max_accrual': 10
    },
    'starter': {
        'name': 'Starter',
        'description': '300 tokens per month',
        'tokens': 300,
        'price_total_dollars': 3.0,
        'overage_unit_cents': 1.5
    },
    'creator': {
        'name': 'Creator',
        'description': '1250 tokens per month',
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

    recurring_interval = config.get('recurring_interval', 'month')

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
        "recurring": {"interval": recurring_interval},
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
    # Build lookup by name AND by plan_key in metadata
    existing_products_by_name = {p.name: p for p in all_products}
    existing_products_by_plan_key = {}
    for p in all_products:
        plan_key = p.metadata.get('plan_key')
        if plan_key:
            existing_products_by_plan_key[plan_key] = p
    
    # List prices and expand product to check metadata
    existing_prices = stripe.Price.list(limit=100, active=True).data

    for key, config in PRODUCTS.items():
        print(f"Plan: {config['name']} (key: {key})")
        
        # 1. Product Metadata Sync
        metadata = {"tokens": str(config['tokens']), "plan_key": key}
        
        # Add hidden flag to metadata if present
        if config.get('hidden'):
            metadata["hidden"] = "true"
        
        # Add max_accrual to metadata if present
        if config.get('max_accrual'):
            metadata["max_accrual"] = str(config['max_accrual'])
        
        # Add internal_status to metadata if present
        if config.get('internal_status'):
            metadata["internal_status"] = config['internal_status']
        
        # Look up product by plan_key first, then by name as fallback
        product = existing_products_by_plan_key.get(key)
        if not product:
            product = existing_products_by_name.get(config['name'])
        
        # Special handling: if processing 'free_daily' and found an archived 'free' product, convert it
        if key == 'free_daily' and product:
            product_plan_key = product.metadata.get('plan_key', '')
            product_internal_status = product.metadata.get('internal_status', '')
            # If this is the old 'free' product (no plan_key or has archived_legacy), convert it
            if product_plan_key != 'free_daily' and (not product_plan_key or product_internal_status == 'archived_legacy'):
                print(f"  🔄 Converting archived 'free' product to 'free_daily'...")
                stripe.Product.modify(
                    product.id,
                    description=config['description'],
                    metadata=metadata,
                    active=True  # Reactivate it
                )
                print(f"  ✓ Converted product to free_daily: {product.id}")
                product = stripe.Product.retrieve(product.id)  # Refresh to get updated metadata
            elif product_plan_key == 'free_daily':
                # Already the correct product, just update if needed
                if (product.description != config['description'] or 
                    product.metadata.get("tokens") != metadata.get("tokens") or
                    product.metadata.get("max_accrual") != metadata.get("max_accrual")):
                    stripe.Product.modify(
                        product.id, 
                        description=config['description'],
                        metadata=metadata
                    )
                    print(f"  ✓ Updated product metadata/description: {product.id}")
        elif not product:
            # Create new product
            product = stripe.Product.create(
                name=config['name'], 
                description=config['description'],
                metadata=metadata
            )
            print(f"  ✓ Created product: {product.id}")
        else:
            # Update existing product if description or metadata changed
            current_hidden = "true" if config.get('hidden') else "false"
            current_internal_status = config.get('internal_status', '')
            product_internal_status = product.metadata.get('internal_status', '')
            product_plan_key = product.metadata.get('plan_key', '')
            
            # Update plan_key if missing
            if product_plan_key != key:
                metadata["plan_key"] = key
            
            if (product.description != config['description'] or 
                product.metadata.get("tokens") != metadata.get("tokens") or
                product.metadata.get("hidden", "false") != current_hidden or
                product_internal_status != current_internal_status or
                product.metadata.get("max_accrual") != metadata.get("max_accrual") or
                product_plan_key != key):
                stripe.Product.modify(
                    product.id, 
                    description=config['description'],
                    metadata=metadata
                )
                print(f"  ✓ Updated product metadata/description: {product.id}")
        
        # Deactivate product if it has archived_legacy status (but skip if we just converted it to free_daily)
        if config.get('internal_status') == 'archived_legacy' and product.active and key != 'free_daily':
            stripe.Product.modify(product.id, active=False)
            print(f"  ✓ Deactivated archived product: {product.id}")
        
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