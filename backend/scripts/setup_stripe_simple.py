#!/usr/bin/env python3
"""
Simple Stripe setup script for creating products, prices, and webhooks.

Usage:
    # Test/Sandbox mode:
    python setup_stripe_simple.py --mode test --api-key sk_test_... [--webhook-url URL]
    
    # Production/Live mode:
    python setup_stripe_simple.py --mode live --api-key sk_live_... [--webhook-url URL]

Requirements:
    pip install stripe
"""

import argparse
import sys
import stripe
from typing import Dict, Any, List


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


def print_summary(mode: str, products: Dict[str, Dict[str, Any]], webhook: Dict[str, Any] = None):
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
    print("Next Steps:")
    print(f"{'='*60}")
    print("1. Update stripe_config.py with the Product/Price IDs shown above")
    print("2. Add STRIPE_WEBHOOK_SECRET to your .env file (see above)")
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
  # Test mode:
  python %(prog)s --mode test --api-key sk_test_YOUR_KEY
  
  # Test mode with webhook:
  python %(prog)s --mode test --api-key sk_test_YOUR_KEY \\
      --webhook-url https://api-dev.example.com/api/stripe/webhook
  
  # Production mode:
  python %(prog)s --mode live --api-key sk_live_YOUR_KEY \\
      --webhook-url https://api.example.com/api/stripe/webhook
        """
    )
    
    parser.add_argument(
        '--mode',
        required=True,
        choices=['test', 'live'],
        help='Stripe mode: test (sandbox) or live (production)'
    )
    parser.add_argument(
        '--api-key',
        required=True,
        help='Stripe secret API key (sk_test_... or sk_live_...)'
    )
    parser.add_argument(
        '--webhook-url',
        help='Webhook URL (e.g., https://api.example.com/api/stripe/webhook)'
    )
    
    args = parser.parse_args()
    
    # Validate API key matches mode
    if not validate_api_key(args.api_key, args.mode):
        sys.exit(1)
    
    # Set Stripe API key
    stripe.api_key = args.api_key
    stripe.api_version = "2024-11-20.acacia"
    
    print(f"\nStripe Setup Tool")
    print(f"Mode: {args.mode.upper()}")
    print(f"API Key: {args.api_key[:15]}...")
    
    # Create products and prices
    products = create_or_update_products(args.mode)
    
    # Create webhook if URL provided
    webhook = None
    if args.webhook_url:
        webhook = create_or_update_webhook(args.webhook_url, args.mode)
    else:
        print(f"\n⚠️  Skipping webhook creation (no --webhook-url provided)")
        print(f"   Run again with --webhook-url to create webhook endpoint")
    
    # Print summary
    print_summary(args.mode, products, webhook)


if __name__ == '__main__':
    main()

