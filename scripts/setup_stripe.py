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

# Meter configuration for usage-based billing (Stripe Meters API)
# This meter is used to track overage tokens across paid plans.
METER_EVENT_NAME = "hopper_tokens"
METER_DISPLAY_NAME = "hopper tokens"

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
        'price_cents': 10,  # $0.10 per token (100 tokens × $0.10 = $10.00/month)
        'overage_price_cents': 10  # $0.10 per token (matches base price)
    },
    'creator': {
        'name': 'Creator',
        'description': '500 tokens per month',
        'monthly_tokens': 500,
        'price_cents': 6,  # $0.06 per token (500 tokens × $0.06 = $30.00/month)
        'overage_price_cents': 6  # $0.06 per token (matches base price)
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
        # 1. Project root (../.env.{env_file} from backend/)
        # 2. Current directory
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
    """
    Get or create the Stripe billing meter used for token overage.

    Uses the new Stripe Meters API:
    https://docs.stripe.com/billing/subscriptions/usage-based/meters/configure

    NOTE: Attaching the meter to a price is configured in the Stripe Dashboard.
    This helper only ensures the meter exists; it does not modify prices, since
    Stripe rejects those parameters on existing prices.
    """
    try:
        meters = stripe.billing.Meter.list(limit=100)
        for meter in meters.data:
            if getattr(meter, "event_name", None) == METER_EVENT_NAME:
                print(f"  ✓ Using existing meter: {meter.id} (event_name={METER_EVENT_NAME})")
                return meter
    except Exception as e:
        print(f"⚠️  Error listing meters: {e}")

    print(f"  ➕ Creating meter for event_name={METER_EVENT_NAME}")
    # Note: event_ingestion parameter was removed in newer Stripe API versions
    # The default behavior (raw event ingestion) is used automatically
    meter = stripe.billing.Meter.create(
        display_name=METER_DISPLAY_NAME,
        event_name=METER_EVENT_NAME,
        default_aggregation={"formula": "sum"},  # Sum all usage values for billing period
        customer_mapping={
            "event_payload_key": "stripe_customer_id",  # Key in payload for customer ID
            "type": "by_id",  # Map by Stripe customer ID
        },
        value_settings={"event_payload_key": "value"},  # Key in payload for usage value
    )
    print(f"  ✓ Created meter: {meter.id}")
    return meter


def archive_old_prices(product_id: str, config: Dict[str, Any], 
                       existing_prices: List[Any], is_metered: bool = False, meter_id: Optional[str] = None) -> int:
    """Archive old prices that should be replaced.
    
    For metered prices: archives any metered prices without the correct meter attached.
    This ensures new prices with meters are created instead of reusing old ones.
    
    Returns:
        Number of prices archived
    """
    amount = config['overage_price_cents'] if is_metered else config['price_cents']
    archived_count = 0
    
    if not is_metered:
        # Don't archive regular prices - they're fine to reuse
        return 0
    
    # Only archive metered prices that don't have the correct meter
    for price in existing_prices:
        # Only consider prices for this product with matching amount
        if price.product != product_id or price.unit_amount != amount:
            continue
        
        # Only archive metered prices
        if (
            price.recurring
            and hasattr(price.recurring, "usage_type")
            and price.recurring.usage_type == "metered"
        ):
            # Check if this price has the correct meter attached
            has_correct_meter = (
                hasattr(price.recurring, 'meter') and 
                price.recurring.meter is not None and
                price.recurring.meter == meter_id
            )
            
            if not has_correct_meter:
                try:
                    stripe.Price.modify(price.id, active=False)
                    print(f"    🗑️  Archived old metered price (no meter): {price.id}")
                    archived_count += 1
                except stripe.error.StripeError as e:
                    print(f"    ⚠️  Failed to archive price {price.id}: {e}")
    
    return archived_count


def find_or_create_price(product_id: str, config: Dict[str, Any], 
                         existing_prices: List[Any], is_metered: bool = False, meter_id: Optional[str] = None) -> Any:
    """Find existing price or create new one.
    
    Args:
        product_id: Stripe product ID
        config: Product configuration dict
        existing_prices: List of existing Stripe prices
        is_metered: Whether this is a metered price for overage
        meter_id: Meter ID to attach (only used when creating new metered prices)
    """
    amount = config['overage_price_cents'] if is_metered else config['price_cents']
    
    # Archive old prices first (cleanup)
    archived = archive_old_prices(product_id, config, existing_prices, is_metered, meter_id)
    if archived > 0:
        # Refresh the prices list after archiving
        existing_prices = [p for p in stripe.Price.list(limit=100, active=True).data]
    
    # Search for existing price (only active prices are in the list)
    for price in existing_prices:
        if price.product != product_id or price.unit_amount != amount:
            continue
        
        # Must have recurring configuration
        if not price.recurring or price.recurring.interval != 'month':
            continue
        
        if is_metered:
            # For metered prices: must be metered and have meter attached
            if (
                hasattr(price.recurring, "usage_type")
                and price.recurring.usage_type == "metered"
            ):
                # Check if this price already has the meter attached
                has_meter = (
                    hasattr(price.recurring, 'meter') and 
                    price.recurring.meter is not None and
                    price.recurring.meter == meter_id
                )
                if has_meter:
                    print(f"    ✓ Found existing metered price with meter attached: {price.id}")
                    return price
        else:
            # For base prices: must NOT be metered (regular recurring price)
            is_price_metered = (
                hasattr(price.recurring, "usage_type")
                and price.recurring.usage_type == "metered"
            )
            if not is_price_metered:
                # This is a non-metered recurring price - perfect for base price
                print(f"    ✓ Found existing non-metered base price: {price.id}")
                return price
    
    # No matching price found - create new one
    if is_metered:
        print(f"    ➕ Creating new metered price with meter attached...")
    else:
        print(f"    ➕ Creating new price...")
    price_params = {
        'product': product_id,
        'unit_amount': amount,
        'currency': 'usd',
        'recurring': {'interval': 'month'}
    }
    
    if is_metered:
        # Create metered price with meter attached (new Meters API)
        price_params['recurring']['usage_type'] = 'metered'
        price_params['billing_scheme'] = 'per_unit'
        
        # Attach meter if provided (for new Meters API)
        # Note: When using meter, do NOT include aggregate_usage (meter handles aggregation)
        if meter_id:
            price_params['recurring']['meter'] = meter_id
        else:
            # Only include aggregate_usage if NOT using meter (for backward compatibility)
            price_params['recurring']['aggregate_usage'] = 'sum'
    
    return stripe.Price.create(**price_params)


def create_or_update_products() -> Dict[str, Dict[str, Any]]:
    """Create or update Stripe products and prices."""
    print(f"\n{'='*60}\nProducts and Prices\n{'='*60}\n")
    
    # Get or create meter first (needed for attaching to new metered prices)
    meter = get_or_create_meter()
    meter_id = meter.id if meter else None
    
    results = {}
    # Get all products (active and inactive)
    all_products = stripe.Product.list(limit=100).data
    existing_products = {p.name: p for p in all_products}
    # Only get ACTIVE prices - deleted prices won't be in this list, so new ones will be created
    existing_prices = stripe.Price.list(limit=100, active=True).data
    print(f"Found {len(existing_products)} existing products, {len(existing_prices)} active prices\n")
    
    for key, config in PRODUCTS.items():
        print(f"{config['name']} (key: {key})")
        
        # Find or create product
        product = existing_products.get(config['name'])
        if product:
            print(f"  ✓ Found existing product: {product.id}")
        else:
            print(f"  ➕ Creating new product: {config['name']}")
            product = stripe.Product.create(
                name=config['name'],
                description=config['description']
            )
            print(f"  ✓ Created product: {product.id}")
        
        # Find or create base price
        price = find_or_create_price(product.id, config, existing_prices)
        if any(p.id == price.id for p in existing_prices):
            print(f"  ✓ Found existing price: {price.id} (${config['price_cents']/100:.2f}/month)")
        else:
            print(f"  ✓ Created new price: {price.id} (${config['price_cents']/100:.2f}/month)")
        
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
            # Pass meter_id so new prices get the meter attached automatically
            overage_price = find_or_create_price(product.id, config, existing_prices, is_metered=True, meter_id=meter_id)
            plan_config['stripe_overage_price_id'] = overage_price.id
            if meter_id and not any(
                p.id == overage_price.id and 
                p.recurring and 
                hasattr(p.recurring, 'meter') and 
                p.recurring.meter == meter_id
                for p in existing_prices
            ):
                print(f"  ✓ Overage: {overage_price.id} (${config['overage_price_cents']/100:.2f}/token) with meter attached")
            else:
                print(f"  ✓ Overage: {overage_price.id} (${config['overage_price_cents']/100:.2f}/token)")
        
        results[key] = plan_config
        print()
    
    return results


def save_config(plans: Dict[str, Dict[str, Any]], mode: str) -> bool:
    """Save plans configuration to JSON file."""
    # Write to backend/app/core/assets/ directory (new directory structure)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # script_dir is hopper/scripts/, so go up one level to hopper/, then to backend/app/core/assets/
    project_root = os.path.dirname(script_dir)  # hopper/
    config_dir = os.path.join(project_root, 'backend', 'app', 'core', 'assets')
    
    # Create directory if it doesn't exist
    os.makedirs(config_dir, exist_ok=True)
    
    config_file = os.path.join(config_dir, f'stripe_plans_{mode}.json')
    
    print(f"\n{'='*60}\nSaving Configuration\n{'='*60}")
    print(f"Directory: {config_dir}")
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


def create_or_update_pricing_table(plans: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """
    Detect and validate existing Stripe pricing table.
    
    Note: Stripe pricing tables must be created via Dashboard.
    This function detects the pricing table ID from environment variables.
    
    Returns:
        Pricing table ID if found in environment, None otherwise
    """
    print(f"\n{'='*60}\nPricing Table\n{'='*60}\n")
    
    # Check if pricing table ID is already in environment
    existing_table_id = os.getenv('STRIPE_PRICING_TABLE_ID')
    if existing_table_id:
        print(f"✓ Found pricing table ID in environment: {existing_table_id}")
        print(f"  View in Dashboard: https://dashboard.stripe.com/pricing-tables/{existing_table_id}")
        
        # Validate the pricing table exists (optional check)
        try:
            # Try to retrieve it to verify it exists
            # Note: This API endpoint may not exist, so we'll catch the error
            try:
                table = stripe.billing.PricingTable.retrieve(existing_table_id)
                print(f"  ✓ Verified pricing table exists")
                if hasattr(table, 'display_name'):
                    print(f"  Display name: {table.display_name}")
            except (AttributeError, stripe.error.InvalidRequestError):
                # API doesn't support retrieval, but that's okay
                print(f"  ✓ Pricing table ID configured (cannot verify via API)")
            except Exception as e:
                print(f"  ⚠️  Could not verify pricing table: {e}")
        except Exception:
            pass
        
        return existing_table_id
    
    # No pricing table ID found - provide instructions
    print("⚠️  No pricing table ID found in environment")
    print("\n📋 To set up pricing table:\n")
    print("  1. Create pricing table in Dashboard: https://dashboard.stripe.com/pricing-tables")
    print("  2. Add your products to the pricing table")
    print("  3. Copy the Pricing Table ID (starts with 'prctbl_')")
    print("  4. Add to your .env file:")
    print("     STRIPE_PRICING_TABLE_ID=prctbl_xxxxx")
    print()
    print("  Available products for your pricing table:\n")
    
    visible_plans = {k: v for k, v in plans.items() if not v.get('hidden', False)}
    for key, plan in visible_plans.items():
        tokens = plan['monthly_tokens']
        if tokens > 0:
            token_text = f"{tokens} tokens/month"
        elif tokens == -1:
            token_text = "Unlimited tokens"
        else:
            token_text = f"{tokens} tokens/month"
        
        print(f"     - {plan['name']}: {plan['stripe_product_id']} / {plan['stripe_price_id']} ({token_text})")
    
    print()
    
    return None


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
    
    # Create pricing table
    pricing_table_id = create_or_update_pricing_table(plans)
    
    # Create webhook (optional)
    webhook = None
    webhook_url = args.webhook_url or os.getenv('BACKEND_URL', '').rstrip('/') + '/api/stripe/webhook'
    if webhook_url and not webhook_url.startswith('/api'):
        webhook = create_or_update_webhook(webhook_url)
    
    # Summary
    print(f"\n{'='*60}\n✅ Setup Complete\n{'='*60}\n")
    if not config_saved:
        print("⚠️  Config file not saved")
    if pricing_table_id:
        print(f"✓ Pricing table ID: {pricing_table_id}")
        print(f"  Add to .env: STRIPE_PRICING_TABLE_ID={pricing_table_id}")
    else:
        print("⚠️  Pricing table not created - see instructions above")
    if webhook and not webhook.get('secret'):
        print("⚠️  Get webhook secret from Stripe Dashboard")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()

