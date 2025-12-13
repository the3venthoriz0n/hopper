#!/usr/bin/env python3

import sys
import os
import argparse
import stripe

# Add parent directory to path to import modules
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
sys.path.insert(0, backend_dir)
sys.path.insert(0, script_dir)  # Also add scripts directory for relative imports

# Import stripe_config from backend directory
from stripe_config import ensure_stripe_products, get_plans, PLANS_TEST, PLANS_LIVE

# Webhook events we need to listen for
REQUIRED_WEBHOOK_EVENTS = [
    'checkout.session.completed',
    'customer.subscription.created',
    'customer.subscription.updated',
    'customer.subscription.deleted',
    'invoice.payment_succeeded',
    'invoice.payment_failed',
]


def update_stripe_config_with_ids(updated_plans: dict, mode: str):
    """
    Update stripe_config.py with Stripe product and price IDs directly.
    
    Args:
        updated_plans: Dictionary of plans with Stripe IDs
        mode: 'test' or 'live'
    """
    import re
    
    # Find stripe_config.py in backend directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(script_dir)
    config_file = os.path.join(backend_dir, 'stripe_config.py')
    
    if not os.path.exists(config_file):
        print(f"WARNING: {config_file} not found, cannot update with Stripe IDs")
        return
    
    # Read existing stripe_config.py file
    try:
        with open(config_file, 'r') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"ERROR: Could not read {config_file}: {e}")
        return
    
    # Determine which plans dict to update
    env_prefix = 'TEST' if mode == 'test' else 'LIVE'
    plans_dict_name = 'PLANS_TEST' if mode == 'test' else 'PLANS_LIVE'
    
    # Find the start of the plans dict and update IDs
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
        
        # Check if we're leaving the plans dict
        if in_target_dict and line.strip() == '}':
            in_target_dict = False
            new_lines.append(line)
            i += 1
            continue
        
        if in_target_dict:
            # Check if we're entering a plan dict
            plan_match = re.match(r"\s+'(\w+)':\s+\{", line)
            if plan_match:
                in_plan = plan_match.group(1)
                new_lines.append(line)
                i += 1
                continue
            
            # Check if we're leaving a plan dict
            if in_plan and line.strip() == '},':
                in_plan = None
                new_lines.append(line)
                i += 1
                continue
            
            # If we're in a plan that needs updating
            if in_plan and in_plan in updated_plans:
                plan_config = updated_plans[in_plan]
                product_id = plan_config.get('stripe_product_id', '')
                price_id = plan_config.get('stripe_price_id', '')
                
                # Replace product_id line - update empty string or existing value
                if f"'stripe_product_id':" in line:
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(f"{' ' * indent}'stripe_product_id': \"{product_id}\",\n")
                    updated_count += 1
                    i += 1
                    continue
                
                # Replace price_id line - update empty string or existing value
                if f"'stripe_price_id':" in line:
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(f"{' ' * indent}'stripe_price_id': \"{price_id}\",\n")
                    updated_count += 1
                    i += 1
                    continue
        
        new_lines.append(line)
        i += 1
    
    # Write back to file
    if updated_count > 0:
        try:
            with open(config_file, 'w') as f:
                f.writelines(new_lines)
            print(f"✓ Updated stripe_config.py with {updated_count} Stripe Product/Price IDs for {mode} mode")
        except Exception as e:
            print(f"ERROR: Could not write to {config_file}: {e}")
    else:
        print(f"WARNING: No Stripe IDs were updated in stripe_config.py")


def detect_stripe_mode(api_key: str) -> str:
    """Detect if Stripe key is test or live mode"""
    if api_key.startswith('sk_test_'):
        return 'test'
    elif api_key.startswith('sk_live_'):
        return 'live'
    else:
        return 'unknown'


def create_or_update_webhook(webhook_url: str, mode: str) -> dict:
    """
    Create or update Stripe webhook endpoint.
    
    Args:
        webhook_url: Full URL to webhook endpoint
        mode: 'test' or 'live'
        
    Returns:
        dict with webhook info including signing secret
    """
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
            # Update existing webhook
            print(f"  Found existing webhook: {matching_webhook.id}")
            
            # Check if events need updating
            current_events = set(matching_webhook.enabled_events)
            required_events = set(REQUIRED_WEBHOOK_EVENTS)
            
            if current_events != required_events:
                print(f"  Updating webhook events...")
                webhook = stripe.WebhookEndpoint.modify(
                    matching_webhook.id,
                    enabled_events=REQUIRED_WEBHOOK_EVENTS,
                )
                print(f"  ✓ Updated webhook events")
            else:
                webhook = matching_webhook
                print(f"  ✓ Webhook events already correct")
        else:
            # Create new webhook
            print(f"  Creating new webhook...")
            webhook = stripe.WebhookEndpoint.create(
                url=webhook_url,
                enabled_events=REQUIRED_WEBHOOK_EVENTS,
                description=f"Hopper webhook ({mode} mode)",
            )
            print(f"  ✓ Created webhook: {webhook.id}")
        
        # Get signing secret
        # Note: Stripe only returns the secret when you CREATE a webhook
        # For existing webhooks, you need to get it from the dashboard
        signing_secret = None
        if matching_webhook is None:  # Newly created webhook
            # Stripe returns the secret in the creation response
            if hasattr(webhook, 'secret') and webhook.secret:
                signing_secret = webhook.secret
                print(f"  ✓ Webhook signing secret: {signing_secret[:20]}...")
        
        if not signing_secret:
            print(f"  ⚠️  Webhook signing secret not available (existing webhook)")
            print(f"     Get it from Stripe Dashboard:")
            print(f"     1. Go to: https://dashboard.stripe.com/webhooks")
            print(f"     2. Click on webhook: {webhook.id}")
            print(f"     3. Click 'Reveal' next to 'Signing secret'")
            print(f"     4. Copy the secret (starts with whsec_)")
            print(f"     5. Add to .env: STRIPE_WEBHOOK_SECRET=whsec_...")
        
        return {
            'id': webhook.id,
            'url': webhook.url,
            'enabled_events': webhook.enabled_events,
            'status': webhook.status,
            'signing_secret': signing_secret,
        }
        
    except stripe.error.StripeError as e:
        print(f"  ✗ Error creating/updating webhook: {e}")
        return None
    except Exception as e:
        print(f"  ✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Main setup function"""
    parser = argparse.ArgumentParser(description='Setup Stripe products, prices, and webhooks')
    parser.add_argument(
        '--mode',
        choices=['test', 'live', 'auto'],
        default='auto',
        help='Stripe mode: test (sandbox), live (production), or auto (detect from API key)'
    )
    parser.add_argument(
        '--webhook-url',
        help='Webhook URL (e.g., https://api-dev.dunkbox.net/api/stripe/webhook)'
    )
    parser.add_argument(
        '--skip-webhook',
        action='store_true',
        help='Skip webhook creation'
    )
    parser.add_argument(
        '--env-file',
        choices=['dev', 'prod', 'auto'],
        default='auto',
        help='Which .env file to load: dev, prod, or auto (try dev first, then prod)'
    )
    args = parser.parse_args()
    
    # Load .env file if python-dotenv is available
    env_loaded = False
    detected_env = None  # 'dev' or 'prod'
    try:
        from dotenv import load_dotenv
        # Determine which .env file to load
        script_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(script_dir)
        project_root = os.path.dirname(backend_dir)
        
        env_file = None
        if args.env_file == 'dev':
            env_file = os.path.join(project_root, '.env.dev')
            detected_env = 'dev'
        elif args.env_file == 'prod':
            env_file = os.path.join(project_root, '.env.prod')
            detected_env = 'prod'
        else:  # auto
            # Try .env.dev first, then .env.prod
            dev_file = os.path.join(project_root, '.env.dev')
            prod_file = os.path.join(project_root, '.env.prod')
            if os.path.exists(dev_file):
                env_file = dev_file
                detected_env = 'dev'
            elif os.path.exists(prod_file):
                env_file = prod_file
                detected_env = 'prod'
        
        if env_file and os.path.exists(env_file):
            # Load .env file
            load_dotenv(env_file, override=True)
            
            # Handle variable substitution (e.g., ${POSTGRES_PASSWORD})
            # Read the file manually to do substitution
            with open(env_file, 'r') as f:
                env_content = f.read()
            
            # Simple variable substitution for common patterns
            import re
            def substitute_vars(match):
                var_name = match.group(1)
                return os.getenv(var_name, match.group(0))
            
            # Replace ${VAR} patterns
            env_content = re.sub(r'\$\{(\w+)\}', substitute_vars, env_content)
            
            # Parse the substituted content
            for line in env_content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Set in environment (override=True means we want to override existing values)
                    if key and value:
                        os.environ[key] = value
            
            env_loaded = True
            print(f"✓ Loaded environment from {os.path.basename(env_file)}")
            
            # Debug: Check if STRIPE_SECRET_KEY was loaded
            if os.getenv("STRIPE_SECRET_KEY"):
                print(f"  ✓ Found STRIPE_SECRET_KEY (starts with {os.getenv('STRIPE_SECRET_KEY')[:10]}...)")
            else:
                print(f"  ⚠️  STRIPE_SECRET_KEY not found in {os.path.basename(env_file)}")
        elif args.env_file != 'auto':
            print(f"WARNING: {env_file} not found, using environment variables")
    except ImportError:
        print("NOTE: python-dotenv not installed, using environment variables only")
        print("      Install with: pip install python-dotenv")
    except Exception as e:
        print(f"WARNING: Error loading .env file: {e}")
        print("         Using environment variables only")
    
    # Get Stripe API key from environment (loaded from .env or already set)
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret_key:
        print("\nERROR: STRIPE_SECRET_KEY not found")
        if not env_loaded:
            print("Please either:")
            print("  1. Set STRIPE_SECRET_KEY environment variable:")
            print("     export STRIPE_SECRET_KEY=sk_test_...")
            print("  2. Or ensure .env.dev or .env.prod exists with STRIPE_SECRET_KEY")
        else:
            print("Please add STRIPE_SECRET_KEY to your .env file")
        sys.exit(1)
    
    # Set Stripe API key (this updates the stripe module that was imported earlier)
    stripe.api_key = stripe_secret_key
    stripe.api_version = os.getenv("STRIPE_API_VERSION", "2024-11-20.acacia")
    
    # Detect or set mode
    if args.mode == 'auto':
        detected_mode = detect_stripe_mode(stripe_secret_key)
        if detected_mode == 'unknown':
            print("ERROR: Could not detect Stripe mode from API key")
            print("Please specify --mode test or --mode live")
            sys.exit(1)
        mode = detected_mode
    else:
        mode = args.mode
    
    # Verify mode matches API key
    if mode == 'test' and not stripe_secret_key.startswith('sk_test_'):
        print(f"WARNING: Mode is 'test' but API key starts with 'sk_live_'")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            sys.exit(1)
    elif mode == 'live' and not stripe_secret_key.startswith('sk_live_'):
        print(f"WARNING: Mode is 'live' but API key starts with 'sk_test_'")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            sys.exit(1)
    
    # Set Stripe API key
    stripe.api_key = stripe_secret_key
    
    print("=" * 60)
    print(f"Stripe Setup - {mode.upper()} Mode")
    print("=" * 60)
    print()
    
    # Step 1: Create products and prices
    print("Step 1: Creating/updating Stripe products and prices...")
    print("-" * 60)
    
    # Get plans for current mode
    current_plans = get_plans()
    print(f"Plans to create ({mode} mode):")
    for plan_key, plan_config in current_plans.items():
        print(f"  - {plan_config['name']}: {plan_config['monthly_tokens']} tokens/month")
    
    print("\nCreating/updating products and prices...")
    updated_plans = ensure_stripe_products()
    
    print("\n✓ Products and prices setup complete!")
    print("\nStripe Product/Price IDs:")
    for plan_key, plan_config in updated_plans.items():
        print(f"  {plan_config['name']}:")
        print(f"    Product ID: {plan_config.get('stripe_product_id', 'Not created')}")
        print(f"    Price ID: {plan_config.get('stripe_price_id', 'Not created')}")
    
    # Update stripe_config.py with the IDs
    print(f"\nUpdating stripe_config.py with Stripe IDs...")
    update_stripe_config_with_ids(updated_plans, mode)
    
    # Step 2: Create webhook
    if not args.skip_webhook:
        print("\n" + "=" * 60)
        print("Step 2: Creating/updating Stripe webhook...")
        print("-" * 60)
        
        if not args.webhook_url:
            # Try to get from environment (loaded from .env file)
            backend_url = os.getenv("BACKEND_URL") or os.getenv("FRONTEND_URL")
            if backend_url:
                webhook_url = f"{backend_url.rstrip('/')}/api/stripe/webhook"
                print(f"Using webhook URL from environment: {webhook_url}")
            elif detected_env:
                # Auto-detect based on .env file name
                if detected_env == 'dev':
                    webhook_url = "https://api-dev.dunkbox.net/api/stripe/webhook"
                    print(f"Using dev webhook URL: {webhook_url}")
                elif detected_env == 'prod':
                    webhook_url = "https://api.dunkbox.net/api/stripe/webhook"
                    print(f"Using prod webhook URL: {webhook_url}")
            else:
                print("ERROR: --webhook-url required")
                print("Example: --webhook-url https://api-dev.dunkbox.net/api/stripe/webhook")
                print("Or use --env-file dev/prod to auto-detect")
                sys.exit(1)
        else:
            webhook_url = args.webhook_url
        
        print(f"Webhook URL: {webhook_url}")
        print(f"Events to enable: {', '.join(REQUIRED_WEBHOOK_EVENTS)}")
        print()
        
        webhook_info = create_or_update_webhook(webhook_url, mode)
        
        if webhook_info:
            print("\n✓ Webhook setup complete!")
            print(f"\nWebhook Details:")
            print(f"  ID: {webhook_info['id']}")
            print(f"  URL: {webhook_info['url']}")
            print(f"  Status: {webhook_info['status']}")
            print(f"  Events: {len(webhook_info['enabled_events'])} events enabled")
            
            if webhook_info.get('signing_secret'):
                print(f"\n⚠️  IMPORTANT: Add this to your .env file:")
                print(f"   STRIPE_WEBHOOK_SECRET={webhook_info['signing_secret']}")
            else:
                print(f"\n⚠️  IMPORTANT: Get webhook signing secret from Stripe Dashboard:")
                print(f"   1. Go to: https://dashboard.stripe.com/webhooks")
                print(f"   2. Click on webhook ID: {webhook_info['id']}")
                print(f"   3. Copy the 'Signing secret' (starts with whsec_)")
                print(f"   4. Add to .env: STRIPE_WEBHOOK_SECRET=whsec_...")
        else:
            print("\n✗ Webhook setup failed - check errors above")
    
    print("\n" + "=" * 60)
    print("✓ Setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. stripe_config.py has been updated with Product/Price IDs")
    print("2. Set STRIPE_WEBHOOK_SECRET in your .env file")
    print("3. Test webhook with: stripe listen --forward-to YOUR_WEBHOOK_URL")
    if mode == 'test':
        print("4. Switch to live mode when ready: --mode live --webhook-url PROD_URL")


if __name__ == "__main__":
    main()

