#!/usr/bin/env python3
"""
Stripe setup script - creates products, prices, and webhooks.
Uses unit_amount_decimal for fractional cent support (e.g., 0.8 cents).
"""

import argparse
import json
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
        'overage_unit_cents': 0.8  # 0.8 cents per token ($0.008)
    },
    'unlimited': {
        'name': 'Unlimited',
        'description': 'Unlimited tokens',
        'monthly_tokens': -1,
        'price_total_dollars': 0,
        'overage_unit_cents': None,
        'hidden': True
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
                         meter_id: Optional[str] = None, plan_key: Optional[str] = None) -> Any:
    """Finds or creates price using unit_amount_decimal for idempotency."""
    if is_metered:
        target_value = str(config['overage_unit_cents'])
        lookup_key = f"{plan_key}_overage_price" if plan_key else None
    else:
        target_value = str(int(config['price_total_dollars'] * 100))
        lookup_key = f"{plan_key}_price" if plan_key else None

    # First try to find by lookup_key if provided
    if lookup_key:
        for price in existing_prices:
            if price.product == product_id and price.active and getattr(price, 'lookup_key', None) == lookup_key:
                current_val = getattr(price, 'unit_amount_decimal', None)
                is_usage_metered = getattr(price.recurring, 'usage_type', None) == 'metered'
                if current_val == target_value and is_usage_metered == is_metered:
                    if is_metered and getattr(price.recurring, 'meter', None) != meter_id:
                        continue
                    print(f"    ✓ Found price by lookup_key: {price.id} ({lookup_key})")
                    return price

    # Fallback: find by amount and type
    for price in existing_prices:
        if price.product != product_id or not price.active:
            continue
        
        current_val = getattr(price, 'unit_amount_decimal', None)
        is_usage_metered = getattr(price.recurring, 'usage_type', None) == 'metered'
        
        if current_val == target_value and is_usage_metered == is_metered:
            if is_metered and getattr(price.recurring, 'meter', None) != meter_id:
                continue
            # Update existing price with lookup_key if it doesn't have one
            if lookup_key and not getattr(price, 'lookup_key', None):
                try:
                    stripe.Price.modify(price.id, lookup_key=lookup_key)
                    print(f"    ✓ Added lookup_key to existing price: {price.id} ({lookup_key})")
                except Exception as e:
                    print(f"    ⚠️  Could not add lookup_key to {price.id}: {e}")
            print(f"    ✓ Reusing price: {price.id} ({target_value} cents)")
            return price

    print(f"    ➕ Creating price: {target_value} cents (Metered: {is_metered}, lookup_key: {lookup_key})")
    params = {
        "product": product_id,
        "currency": "usd",
        "unit_amount_decimal": target_value,
        "recurring": {"interval": "month"}
    }
    if lookup_key:
        params["lookup_key"] = lookup_key
    if is_metered:
        params["recurring"]["usage_type"] = "metered"
        params["recurring"]["meter"] = meter_id
    
    return stripe.Price.create(**params)

def create_or_update_products() -> Dict[str, Dict[str, Any]]:
    print(f"\n{'='*60}\nSyncing Stripe Products\n{'='*60}\n")
    meter = get_or_create_meter()
    meter_id = meter.id if meter else None
    
    results = {}
    all_products = stripe.Product.list(limit=100).data
    existing_products = {p.name: p for p in all_products if p.active}
    existing_prices = stripe.Price.list(limit=100, active=True).data

    for key, config in PRODUCTS.items():
        print(f"Plan: {config['name']}")
        
        product = existing_products.get(config['name'])
        if not product:
            product = stripe.Product.create(name=config['name'], description=config['description'])
            print(f"  ✓ Created product: {product.id}")
        
        base_price = find_or_create_price(product.id, config, existing_prices, is_metered=False, plan_key=key)
        
        plan_config = {
            'name': config['name'],
            'monthly_tokens': config['monthly_tokens'],
            'stripe_product_id': product.id,
            'stripe_price_id': base_price.id,
            'stripe_overage_price_id': None
        }

        if config.get('overage_unit_cents') is not None:
            ov_price = find_or_create_price(product.id, config, existing_prices, is_metered=True, meter_id=meter_id, plan_key=key)
            plan_config['stripe_overage_price_id'] = ov_price.id

        # Preserve hidden flag if present
        if config.get('hidden'):
            plan_config['hidden'] = True

        results[key] = plan_config
    return results

def save_config(plans: Dict[str, Dict[str, Any]], mode: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    target_dir = os.path.join(project_root, 'backend', 'app', 'core', 'assets')
    
    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, f'stripe_plans_{mode}.json')
    
    with open(file_path, 'w') as f:
        json.dump(plans, f, indent=2)
    print(f"\n✓ Configuration saved to: {file_path}")

def main():
    parser = argparse.ArgumentParser(description='Setup Stripe fractional pricing.')
    parser.add_argument('--env-file', choices=['dev', 'prod'], help='Load from .env file')
    parser.add_argument('--mode', choices=['test', 'live'], help='Stripe mode')
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    api_key = os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("❌ STRIPE_SECRET_KEY not found in environment.")
        sys.exit(1)

    mode = args.mode or ('test' if api_key.startswith('sk_test_') else 'live')
    stripe.api_key = api_key
    stripe.api_version = STRIPE_API_VERSION

    print(f"Starting Setup: {mode.upper()}")
    
    plans = create_or_update_products()
    save_config(plans, mode)
    print(f"\n{'='*60}\n✅ Idempotent Sync Complete\n{'='*60}")

if __name__ == '__main__':
    main()