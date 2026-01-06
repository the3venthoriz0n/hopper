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
# Note: 'free_daily' is processed before 'free' to ensure conversion happens before archiving
PRODUCTS = {
    'free_daily': {
        'name': 'Free Daily',
        'description': '3 tokens per day, max 10 tokens',
        'tokens': 3,
        'price_total_dollars': 0,
        'overage_unit_cents': None,
        'recurring_interval': 'day',
        'max_accrual': 10
    },
    'free': {
        'name': 'Free',
        'description': '100 tokens per month',
        'tokens': 100,
        'price_total_dollars': 0,
        'overage_unit_cents': None,
        'internal_status': 'archived_legacy'
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

def find_product_by_plan_key(all_products: List[Any], plan_key: str) -> Optional[Any]:
    """Find product by plan_key in metadata. Returns None if not found."""
    for product in all_products:
        if product.metadata.get('plan_key') == plan_key:
            return product
    return None

def find_product_for_conversion(all_products: List[Any]) -> Optional[Any]:
    """Find 'free' product that can be converted to 'free_daily'.
    Looks for products with plan_key='free' or internal_status='archived_legacy'."""
    for product in all_products:
        plan_key = product.metadata.get('plan_key', '')
        internal_status = product.metadata.get('internal_status', '')
        # Find products that are the old 'free' product (plan_key='free' or archived_legacy)
        if plan_key == 'free' or internal_status == 'archived_legacy':
            # Make sure it's not already free_daily
            if plan_key != 'free_daily':
                return product
    return None

def should_convert_free_to_free_daily(product: Any) -> bool:
    """Check if a product should be converted from 'free' to 'free_daily'."""
    if not product:
        return False
    plan_key = product.metadata.get('plan_key', '')
    internal_status = product.metadata.get('internal_status', '')
    # Convert if it's the old 'free' product (plan_key='free' or archived_legacy) but not already free_daily
    return (plan_key == 'free' or internal_status == 'archived_legacy') and plan_key != 'free_daily'

def update_product_metadata(product: Any, config: Dict[str, Any], metadata: Dict[str, str], plan_key: str) -> bool:
    """Update product metadata if needed. Returns True if update was made."""
    if not product:
        return False
    
    current_hidden = "true" if config.get('hidden') else "false"
    current_internal_status = config.get('internal_status', '')
    product_internal_status = product.metadata.get('internal_status', '')
    product_plan_key = product.metadata.get('plan_key', '')
    
    # Check if update is needed
    needs_update = (
        product.description != config['description'] or
        product.metadata.get("tokens") != metadata.get("tokens") or
        product.metadata.get("hidden", "false") != current_hidden or
        product_internal_status != current_internal_status or
        product.metadata.get("max_accrual") != metadata.get("max_accrual") or
        product_plan_key != plan_key
    )
    
    if needs_update:
        # Ensure plan_key is in metadata
        if product_plan_key != plan_key:
            metadata["plan_key"] = plan_key
        stripe.Product.modify(
            product.id,
            description=config['description'],
            metadata=metadata
        )
        return True
    return False

def deactivate_product_prices(product_id: str, all_prices: List[Any]) -> int:
    """Deactivate all active prices for a product. Returns count of deactivated prices."""
    deactivated = 0
    for price in all_prices:
        price_product_id = getattr(price, 'product', None)
        if isinstance(price_product_id, str):
            product_match = price_product_id == product_id
        else:
            product_match = getattr(price_product_id, 'id', None) == product_id
        
        if product_match and price.active:
            stripe.Price.modify(price.id, active=False, lookup_key=None)
            price.active = False
            deactivated += 1
    return deactivated

def find_or_create_price(product_id: str, config: Dict[str, Any], 
                         existing_prices: List[Any], all_prices: List[Any],
                         is_metered: bool = False, 
                         meter_id: Optional[str] = None, plan_key: str = "") -> Any:
    """Finds or creates price using stable lookup_keys and ensures metadata sync.
    
    Checks both lookup_key and product association to ensure prices are correctly matched.
    """
    
    metadata = {"tokens": str(config['tokens'])}
    if is_metered:
        target_value = str(config['overage_unit_cents'])
        lookup_key = f"{plan_key}_overage_price"
    else:
        target_value = str(int(config['price_total_dollars'] * 100))
        lookup_key = f"{plan_key}_price"

    recurring_interval = config.get('recurring_interval', 'month')

    # Search for existing active price with this lookup_key AND product_id
    for price in existing_prices:
        price_product_id = getattr(price, 'product', None)
        if isinstance(price_product_id, str):
            product_match = price_product_id == product_id
        else:
            product_match = getattr(price_product_id, 'id', None) == product_id
        
        if (getattr(price, 'lookup_key', None) == lookup_key and 
            price.active and 
            product_match):
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
                price.active = False
                existing_prices.remove(price)

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
    
    new_price = stripe.Price.create(**params)
    print(f"    ✓ Created price: {new_price.id} ({lookup_key})")
    existing_prices.append(new_price)
    all_prices.append(new_price)
    return new_price

def sync_stripe_resources():
    print(f"\n{'='*60}\nSyncing Stripe Products & Metadata\n{'='*60}\n")
    meter = get_or_create_meter()
    meter_id = meter.id if meter else None
    
    # Get all products (including archived) for proper lookup
    all_products = stripe.Product.list(limit=100).data
    
    # Get ALL prices (active and inactive) to properly handle duplicates and cleanup
    all_prices = stripe.Price.list(limit=100).data
    existing_prices = [p for p in all_prices if p.active]
    
    # Track if free_daily conversion happened to prevent archiving 'free'
    free_daily_converted = False

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
        
        # Look up product by plan_key (primary identifier)
        product = find_product_by_plan_key(all_products, key)
        
        # Special handling for 'free_daily': convert 'free' product if it exists
        if key == 'free_daily' and not product:
            # Look for 'free' product to convert
            free_product = find_product_for_conversion(all_products)
            if free_product and should_convert_free_to_free_daily(free_product):
                print(f"  🔄 Converting 'free' product to 'free_daily'...")
                
                # Deactivate old prices for the product being converted
                deactivated_count = deactivate_product_prices(free_product.id, all_prices)
                if deactivated_count > 0:
                    print(f"    ⚠️  Deactivated {deactivated_count} old price(s) for converted product")
                    # Refresh existing_prices list
                    existing_prices = [p for p in all_prices if p.active]
                
                stripe.Product.modify(
                    free_product.id,
                    description=config['description'],
                    metadata=metadata,
                    active=True  # Reactivate it
                )
                print(f"  ✓ Converted product to free_daily: {free_product.id}")
                # Query API to verify the conversion and get fresh status
                product = stripe.Product.retrieve(free_product.id)
                if not product.active:
                    # Ensure it's active
                    stripe.Product.modify(free_product.id, active=True)
                    product = stripe.Product.retrieve(free_product.id)
                    print(f"  ✓ Verified product is active: {product.id}")
                free_daily_converted = True
                # Update all_products list to reflect the change
                for p in all_products:
                    if p.id == free_product.id:
                        p.metadata = metadata
                        p.active = product.active
                        break
        
        # If product found by plan_key, update if needed
        if product:
            if key == 'free_daily':
                # For free_daily, check if update is needed
                if (product.description != config['description'] or 
                    product.metadata.get("tokens") != metadata.get("tokens") or
                    product.metadata.get("max_accrual") != metadata.get("max_accrual")):
                    stripe.Product.modify(
                        product.id, 
                        description=config['description'],
                        metadata=metadata
                    )
                    print(f"  ✓ Updated product metadata/description: {product.id}")
                else:
                    print(f"  ✓ Product up to date: {product.id}")
            else:
                # For other products, use unified update function
                if update_product_metadata(product, config, metadata, key):
                    print(f"  ✓ Updated product metadata/description: {product.id}")
                else:
                    print(f"  ✓ Product up to date: {product.id}")
        else:
            # Create new product if not found
            # Set active=True unless it's an archived product
            should_be_active = config.get('internal_status') != 'archived_legacy'
            product = stripe.Product.create(
                name=config['name'], 
                description=config['description'],
                metadata=metadata,
                active=should_be_active
            )
            print(f"  ✓ Created product: {product.id}")
            # Add to all_products for subsequent lookups
            all_products.append(product)
        
        # Query API to get current product status and ensure it's active (unless archived)
        should_be_active = config.get('internal_status') != 'archived_legacy'
        if should_be_active:
            # Query fresh from API to get actual status
            current_product = stripe.Product.retrieve(product.id)
            if not current_product.active:
                # Product should be active but API shows inactive - reactivate it
                stripe.Product.modify(product.id, active=True)
                print(f"  ✓ Reactivated product: {product.id}")
                # Update local reference
                product.active = True
                for p in all_products:
                    if p.id == product.id:
                        p.active = True
                        break
        
        # Deactivate product if it has archived_legacy status
        # But skip if we just converted it to free_daily, or if free_daily already exists
        if config.get('internal_status') == 'archived_legacy' and product.active and key == 'free':
            # Only archive 'free' if free_daily conversion didn't happen
            if not free_daily_converted:
                # Double-check that free_daily product exists
                free_daily_product = find_product_by_plan_key(all_products, 'free_daily')
                if not free_daily_product:
                    # Deactivate all prices before archiving product
                    deactivated_count = deactivate_product_prices(product.id, all_prices)
                    if deactivated_count > 0:
                        print(f"    ⚠️  Deactivated {deactivated_count} price(s) before archiving product")
                        existing_prices = [p for p in all_prices if p.active]
                    
                    stripe.Product.modify(product.id, active=False)
                    print(f"  ✓ Deactivated archived product: {product.id}")
                else:
                    print(f"  ⚠️  Skipping archive of 'free' - free_daily product exists")
            else:
                print(f"  ⚠️  Skipping archive of 'free' - was converted to free_daily")
        
        # 2. Base Price Sync (updates Price metadata too)
        find_or_create_price(product.id, config, existing_prices, all_prices, is_metered=False, plan_key=key)

        # 3. Overage Price Sync
        if config.get('overage_unit_cents') is not None:
            find_or_create_price(product.id, config, existing_prices, all_prices, is_metered=True, meter_id=meter_id, plan_key=key)

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
    
    # Determine Stripe mode and environment
    if api_key.startswith('sk_test_'):
        mode = 'test'
        environment = 'dev'
        api_key_prefix = 'sk_test_'
    elif api_key.startswith('sk_live_'):
        mode = 'live'
        environment = 'prod'
        api_key_prefix = 'sk_live_'
    else:
        mode = 'unknown'
        environment = 'unknown'
        api_key_prefix = 'unknown'

    print(f"\n{'='*60}")
    print(f"Stripe Setup Script")
    print(f"{'='*60}")
    print(f"Mode: {mode.upper()} (Stripe {mode} mode)")
    print(f"Environment: {environment.upper()}")
    print(f"API Key: {api_key_prefix}...{api_key[-4:] if len(api_key) > 4 else '****'}")
    print(f"{'='*60}\n")
    
    sync_stripe_resources()
    print(f"\n{'='*60}\n✅ Sync Complete ({mode.upper()} mode). Code 'tokens' is now the source of truth.\n{'='*60}")

if __name__ == '__main__':
    main()