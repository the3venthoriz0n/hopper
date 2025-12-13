#!/usr/bin/env python3
"""
Setup script to create Stripe products and prices.
Run this script once to initialize Stripe products/prices, or whenever you need to update them.

Usage:
source venv/bin/activate
python backend/setup_stripe.py

This script is idempotent - it will create products/prices if they don't exist,
or use existing ones if they do.
"""
import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stripe_config import ensure_stripe_products, PLANS, STRIPE_SECRET_KEY


def main():
    """Main setup function"""
    if not STRIPE_SECRET_KEY:
        print("ERROR: STRIPE_SECRET_KEY environment variable not set")
        print("Please set it before running this script:")
        print("  export STRIPE_SECRET_KEY=sk_...")
        sys.exit(1)
    
    print("Setting up Stripe products and prices...")
    print(f"Plans to create:")
    for plan_key, plan_config in PLANS.items():
        print(f"  - {plan_config['name']}: {plan_config['monthly_tokens']} tokens/month")
    
    print("\nCreating/updating Stripe products and prices...")
    
    updated_plans = asyncio.run(ensure_stripe_products())
    
    print("\n✓ Setup complete!")
    print("\nStripe Product/Price IDs:")
    for plan_key, plan_config in updated_plans.items():
        print(f"  {plan_config['name']}:")
        print(f"    Product ID: {plan_config.get('stripe_product_id', 'Not created')}")
        print(f"    Price ID: {plan_config.get('stripe_price_id', 'Not created')}")
    
    print("\n⚠️  IMPORTANT: Update the PRICE AMOUNTS in stripe_config.py!")
    print("   The script creates prices with placeholder amounts.")
    print("   You need to either:")
    print("   1. Update prices in Stripe dashboard, or")
    print("   2. Update the price_amounts dict in stripe_config.py and re-run this script")
    
    print("\n⚠️  Also update stripe_config.py with the actual Price IDs above")
    print("   so they're used in the application.")


if __name__ == "__main__":
    main()

