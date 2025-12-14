#!/usr/bin/env python3
"""
Stripe setup script - creates products, prices, and webhooks for test and live environments.

Usage:
    # Using .env file (recommended):
    python setup_stripe.py --env-file dev
    python setup_stripe.py --env-file prod
    
    # Or with explicit API key:
    python setup_stripe.py --mode test --api-key sk_test_YOUR_KEY
    
    # With webhook:
    python setup_stripe.py --env-file dev --webhook-url https://api-dev.example.com/api/stripe/webhook

Requirements:
    pip install stripe python-dotenv
"""

import argparse
import sys
import os
import re
import stripe
from typing import Dict, Any


# Product definitions
PRODUCTS = {
    'free': {
        'name': 'Hopper Free',
        'description': '10 tokens per month',
        'monthly_tokens': 10,
        'price_cents': 0,  # Free
    },
    'medium': {
        'name': 'Hopper Medium',
        'description': '100 tokens per month',
        'monthly_tokens': 100,
        'price_cents': 999,  # $9.99/month
    },
    'pro': {
        'name': 'Hopper Pro',
        'description': '500 tokens per month',
        'monthly_tokens': 500,
        'price_cents': 2999,  # $29.99/month
    },
    'unlimited': {
        'name': 'Hopper Unlimited',
        'description': 'Unlimited tokens (dev/admin only)',
        'monthly_tokens': -1,  # -1 indicates unlimited
        'price_cents': 0,  # Free (dev/admin only, not purchasable)
        'hidden': True,  # Hidden from public plans
    }
}


# Webhook events required
WEBHOOK_EVENTS = [
    'checkout.session.completed',
    'customer.subscription.created',
    'customer.subscription.updated',
    'customer.subscription.deleted',
    'invoice.payment_succeeded',
    'invoice.payment_failed',
]


def validate_api_key(api_key: str, mode: str) -> bool:
    """Validate that API key matches the specified mode."""
    if mode == 'test' and not api_key.startswith('sk_test_'):
        print(f"❌ Error: Test mode requires test API key (starts with sk_test_)")
        print(f"   Your key starts with: {api_key[:10]}...")
        return False
    elif mode == 'live' and not api_key.startswith('sk_live_'):
        print(f"❌ Error: Live mode requires live API key (starts with sk_live_)")
        print(f"   Your key starts with: {api_key[:10]}...")
        return False
    return True


def load_env_file(env_file_path: str) -> bool:
    """
    Load environment variables from .env file.
    
    Returns:
        True if file was loaded successfully, False otherwise
    """
    try:
        from dotenv import load_dotenv
        
        if not os.path.exists(env_file_path):
            print(f"❌ Error: File not found: {env_file_path}")
            return False
        
        # Load with dotenv
        load_dotenv(env_file_path, override=True)
        
        # Also do manual parsing for variable substitution like ${VAR}
        with open(env_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Simple variable substitution for ${VAR}
                    value = re.sub(r'\$\{(\w+)\}', lambda m: os.getenv(m.group(1), ''), value)
                    if key and value:
                        os.environ[key] = value
        
        print(f"✓ Loaded environment from {os.path.basename(env_file_path)}")
        return True
        
    except ImportError:
        print("❌ Error: python-dotenv not installed")
        print("   Install with: pip install python-dotenv")
        return False
    except Exception as e:
        print(f"❌ Error loading .env file: {e}")
        return False


def update_stripe_config_file(products: Dict[str, Dict[str, Any]], mode: str) -> bool:
    """
    Update stripe_config.py with product and price IDs.
    
    Args:
        products: Dict mapping product keys to their info (including product_id and price_id)
        mode: 'test' or 'live'
        
    Returns:
        True if update was successful, False otherwise
    """
    try:
        # Find stripe_config.py in backend directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(script_dir)
        config_file = os.path.join(backend_dir, 'stripe_config.py')
        
        if not os.path.exists(config_file):
            print(f"❌ Warning: {config_file} not found, cannot update IDs")
            return False
        
        # Read the file
        with open(config_file, 'r') as f:
            lines = f.readlines()
        
        # Determine which plans dict to update
        plans_dict_name = 'PLANS_TEST' if mode == 'test' else 'PLANS_LIVE'
        
        # Track state while parsing
        in_target_dict = False
        in_plan = None
        new_lines = []
        updated_count = 0
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if we're entering the target plans dict
            if f'{plans_dict_name} = {{' in line:
                in_target_dict = True
                new_lines.append(line)
                i += 1
                continue
            
            # Check if we're leaving the plans dict (closing brace at start of line)
            if in_target_dict and line.strip() == '}':
                in_target_dict = False
                new_lines.append(line)
                i += 1
                continue
            
            if in_target_dict:
                # Check if we're entering a plan dict (e.g., 'free': {)
                plan_match = re.match(r"\s+'(\w+)':\s+\{", line)
                if plan_match:
                    in_plan = plan_match.group(1)
                    new_lines.append(line)
                    i += 1
                    continue
                
                # Check if we're leaving a plan dict (},)
                if in_plan and line.strip() == '},':
                    in_plan = None
                    new_lines.append(line)
                    i += 1
                    continue
                
                # If we're in a plan that we have data for, update its IDs
                if in_plan and in_plan in products:
                    product_info = products[in_plan]
                    
                    # Update stripe_price_id line
                    if "'stripe_price_id':" in line:
                        indent = len(line) - len(line.lstrip())
                        new_lines.append(f"{' ' * indent}'stripe_price_id': \"{product_info['price_id']}\",\n")
                        updated_count += 1
                        i += 1
                        continue
                    
                    # Update stripe_product_id line
                    if "'stripe_product_id':" in line:
                        indent = len(line) - len(line.lstrip())
                        new_lines.append(f"{' ' * indent}'stripe_product_id': \"{product_info['product_id']}\",\n")
                        updated_count += 1
                        i += 1
                        continue
            
            new_lines.append(line)
            i += 1
        
        # Write back to file
        if updated_count > 0:
            with open(config_file, 'w') as f:
                f.writelines(new_lines)
            print(f"\n✓ Updated stripe_config.py with {updated_count} IDs ({mode.upper()} mode)")
            return True
        else:
            print(f"\n❌ Warning: No IDs were updated in stripe_config.py")
            return False
            
    except Exception as e:
        print(f"\n❌ Error updating stripe_config.py: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_or_update_products(mode: str) -> Dict[str, Dict[str, Any]]:
    """
    Create or update Stripe products and prices.
    
    Returns:
        Dict mapping product keys to their Stripe IDs
    """
    print(f"\n{'='*60}")
    print(f"Creating/Updating Products and Prices ({mode.upper()} mode)")
    print(f"{'='*60}\n")
    
    results = {}
    
    try:
        # Get existing products
        existing_products = stripe.Product.list(limit=100)
        product_map = {p.name: p for p in existing_products.data}
        
        # Get existing prices
        existing_prices = stripe.Price.list(limit=100, active=True)
        price_map = {}  # Map: product_id -> [prices]
        for price in existing_prices.data:
            if price.product not in price_map:
                price_map[price.product] = []
            price_map[price.product].append(price)
        
        for key, config in PRODUCTS.items():
            print(f"Processing: {config['name']}")
            
            # Create or find product
            if config['name'] in product_map:
                product = product_map[config['name']]
                print(f"  ✓ Found existing product: {product.id}")
            else:
                product = stripe.Product.create(
                    name=config['name'],
                    description=config['description']
                )
                print(f"  ✓ Created product: {product.id}")
            
            # Find or create price
            price = None
            if product.id in price_map:
                # Find price matching our amount and currency
                for p in price_map[product.id]:
                    if (p.unit_amount == config['price_cents'] and 
                        p.currency == 'usd' and 
                        p.recurring and 
                        p.recurring.interval == 'month'):
                        price = p
                        break
            
            if price:
                print(f"  ✓ Found existing price: {price.id} (${config['price_cents']/100:.2f}/month)")
            else:
                price = stripe.Price.create(
                    product=product.id,
                    unit_amount=config['price_cents'],
                    currency='usd',
                    recurring={'interval': 'month'},
                )
                print(f"  ✓ Created price: {price.id} (${config['price_cents']/100:.2f}/month)")
            
            results[key] = {
                'name': config['name'],
                'product_id': product.id,
                'price_id': price.id,
                'monthly_tokens': config['monthly_tokens'],
                'price_cents': config['price_cents'],
            }
            print()
        
        return results
        
    except stripe.error.StripeError as e:
        print(f"❌ Stripe API error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def create_or_update_webhook(webhook_url: str, mode: str) -> Dict[str, Any]:
    """
    Create or update Stripe webhook endpoint.
    
    Returns:
        Dict with webhook info including ID and signing secret (if newly created)
    """
    print(f"\n{'='*60}")
    print(f"Creating/Updating Webhook ({mode.upper()} mode)")
    print(f"{'='*60}\n")
    print(f"Webhook URL: {webhook_url}")
    print(f"Events: {', '.join(WEBHOOK_EVENTS)}\n")
    
    try:
        # List existing webhooks
        existing_webhooks = stripe.WebhookEndpoint.list(limit=100)
        
        # Find webhook with matching URL
        matching_webhook = None
        for webhook in existing_webhooks.data:
            if webhook.url == webhook_url:
                matching_webhook = webhook
                break
        
        if matching_webhook:
            print(f"✓ Found existing webhook: {matching_webhook.id}")
            
            # Check if events need updating
            current_events = set(matching_webhook.enabled_events)
            required_events = set(WEBHOOK_EVENTS)
            
            if current_events != required_events:
                webhook = stripe.WebhookEndpoint.modify(
                    matching_webhook.id,
                    enabled_events=WEBHOOK_EVENTS,
                )
                print(f"✓ Updated webhook events")
            else:
                webhook = matching_webhook
                print(f"✓ Webhook events already correct")
            
            print(f"\n⚠️  Get signing secret from Stripe Dashboard:")
            print(f"   1. Visit: https://dashboard.stripe.com/{'test/' if mode == 'test' else ''}webhooks")
            print(f"   2. Click webhook: {webhook.id}")
            print(f"   3. Reveal and copy 'Signing secret' (starts with whsec_)")
            
            return {
                'id': webhook.id,
                'url': webhook.url,
                'secret': None,  # Not available for existing webhooks
            }
        else:
            # Create new webhook
            print(f"Creating new webhook...")
            webhook = stripe.WebhookEndpoint.create(
                url=webhook_url,
                enabled_events=WEBHOOK_EVENTS,
                description=f"Hopper webhook ({mode} mode)",
            )
            print(f"✓ Created webhook: {webhook.id}")
            
            # Get signing secret (only available on creation)
            signing_secret = webhook.secret if hasattr(webhook, 'secret') else None
            
            if signing_secret:
                print(f"\n🔑 Webhook Signing Secret:")
                print(f"   {signing_secret}")
                print(f"\n   Save this to your .env file:")
                print(f"   STRIPE_WEBHOOK_SECRET={signing_secret}")
            
            return {
                'id': webhook.id,
                'url': webhook.url,
                'secret': signing_secret,
            }
        
    except stripe.error.StripeError as e:
        print(f"❌ Stripe API error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def print_summary(mode: str, products: Dict[str, Dict[str, Any]], webhook: Dict[str, Any] = None, config_updated: bool = False):
    """Print summary of created/updated resources."""
    print(f"\n{'='*60}")
    print(f"✅ Setup Complete ({mode.upper()} mode)")
    print(f"{'='*60}\n")
    
    print("Products and Prices:")
    print("-" * 60)
    for key, info in products.items():
        print(f"\n{key.upper()}:")
        print(f"  Name:         {info['name']}")
        print(f"  Product ID:   {info['product_id']}")
        print(f"  Price ID:     {info['price_id']}")
        print(f"  Price:        ${info['price_cents']/100:.2f}/month")
        print(f"  Tokens:       {info['monthly_tokens']}/month")
    
    if webhook:
        print(f"\nWebhook:")
        print("-" * 60)
        print(f"  ID:  {webhook['id']}")
        print(f"  URL: {webhook['url']}")
        if webhook.get('secret'):
            print(f"  Secret: {webhook['secret']}")
    
    print(f"\n{'='*60}")
    print("Configuration:")
    print(f"{'='*60}")
    if config_updated:
        print("✓ stripe_config.py has been updated with Product/Price IDs")
    else:
        print("⚠️  stripe_config.py was not updated (see errors above)")
    
    print(f"\n{'='*60}")
    print("Next Steps:")
    print(f"{'='*60}")
    if config_updated:
        print("1. ✓ stripe_config.py is already updated!")
    else:
        print("1. Manually update stripe_config.py with the Product/Price IDs shown above")
    if webhook and webhook.get('secret'):
        print("2. Add STRIPE_WEBHOOK_SECRET to your .env file:")
        print(f"   STRIPE_WEBHOOK_SECRET={webhook['secret']}")
    else:
        print("2. Get webhook signing secret from Stripe Dashboard and add to .env file")
    print(f"3. View resources in Stripe Dashboard: https://dashboard.stripe.com/{'test/' if mode == 'test' else ''}")
    if mode == 'test':
        print("4. When ready for production, run again with --mode live --api-key sk_live_...")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Setup Stripe products, prices, and webhooks',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using .env file (recommended):
  python %(prog)s --env-file dev
  python %(prog)s --env-file prod
  
  # With explicit API key:
  python %(prog)s --mode test --api-key sk_test_YOUR_KEY
  
  # With webhook:
  python %(prog)s --env-file dev --webhook-url https://api-dev.example.com/api/stripe/webhook
        """
    )
    
    parser.add_argument(
        '--env-file',
        choices=['dev', 'prod'],
        help='Load API key from .env.dev or .env.prod file'
    )
    parser.add_argument(
        '--mode',
        choices=['test', 'live'],
        help='Stripe mode: test (sandbox) or live (production) - auto-detected from API key if using --env-file'
    )
    parser.add_argument(
        '--api-key',
        help='Stripe secret API key (sk_test_... or sk_live_...)'
    )
    parser.add_argument(
        '--webhook-url',
        help='Webhook URL (e.g., https://api.example.com/api/stripe/webhook) - auto-detected from BACKEND_URL if using --env-file'
    )
    
    args = parser.parse_args()
    
    # Load .env file if specified (optional - will use existing env vars if file not found)
    if args.env_file:
        # Try multiple possible locations for .env file
        possible_paths = [
            # Inside Docker container (project mounted at /app)
            f'/app/.env.{args.env_file}',
            # From script location (if running locally)
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), f'.env.{args.env_file}'),
            # Current directory
            f'.env.{args.env_file}',
            # Home directory
            os.path.join(os.path.expanduser('~'), f'.env.{args.env_file}'),
        ]
        
        env_file_found = False
        for env_file in possible_paths:
            if os.path.exists(env_file):
                if load_env_file(env_file):
                    env_file_found = True
                    break
        
        if not env_file_found:
            print(f"⚠️  Warning: .env.{args.env_file} not found in any of these locations:")
            for path in possible_paths:
                print(f"   - {path}")
            print("   Continuing with existing environment variables...")
    
    # Get API key from args or environment
    api_key = args.api_key or os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("\n❌ Error: STRIPE_SECRET_KEY not found")
        print("Please either:")
        print("  1. Use --env-file dev or --env-file prod (if .env file exists)")
        print("  2. Use --api-key sk_test_... or --api-key sk_live_...")
        print("  3. Set STRIPE_SECRET_KEY environment variable")
        print("\nNote: If running in Docker, environment variables should already be set via docker-compose.")
        sys.exit(1)
    
    # Detect or validate mode
    if args.mode:
        mode = args.mode
    else:
        # Auto-detect from API key
        if api_key.startswith('sk_test_'):
            mode = 'test'
            print("✓ Detected TEST mode from API key")
        elif api_key.startswith('sk_live_'):
            mode = 'live'
            print("✓ Detected LIVE mode from API key")
        else:
            print("❌ Error: Could not detect mode from API key")
            print("   Please specify --mode test or --mode live")
            sys.exit(1)
    
    # Validate API key matches mode
    if not validate_api_key(api_key, mode):
        sys.exit(1)
    
    # Get webhook URL from args or environment
    webhook_url = args.webhook_url
    if not webhook_url and args.env_file:
        # Try to auto-construct from BACKEND_URL
        backend_url = os.getenv('BACKEND_URL')
        if backend_url:
            webhook_url = f"{backend_url.rstrip('/')}/api/stripe/webhook"
            print(f"✓ Using webhook URL from BACKEND_URL: {webhook_url}")
    
    # Set Stripe API key
    stripe.api_key = api_key
    stripe.api_version = "2024-11-20.acacia"
    
    print(f"\nStripe Setup Tool")
    print(f"Mode: {mode.upper()}")
    print(f"API Key: {api_key[:15]}...")
    
    # Create products and prices
    products = create_or_update_products(mode)
    
    # Update stripe_config.py with the IDs
    config_updated = update_stripe_config_file(products, mode)
    
    # Create webhook if URL provided
    webhook = None
    if webhook_url:
        webhook = create_or_update_webhook(webhook_url, mode)
    else:
        print(f"\n⚠️  Skipping webhook creation (no webhook URL provided)")
        print(f"   Run again with --webhook-url or set BACKEND_URL in .env file")
    
    # Print summary
    print_summary(mode, products, webhook, config_updated)


if __name__ == '__main__':
    main()
