# Stripe Setup Guide

This guide explains how to set up Stripe products, prices, and webhooks for both test (development) and live (production) environments.

## Prerequisites

1. **Stripe Account**: Sign up at [stripe.com](https://stripe.com)
2. **Python Dependencies**: 
   ```bash
   pip install stripe
   ```

## Quick Start

### 1. Get Your Stripe API Keys

Visit the [Stripe API Keys page](https://dashboard.stripe.com/apikeys):

- **Test Mode Keys** (for development):
  - Secret key: `sk_test_...`
  - Publishable key: `pk_test_...`

- **Live Mode Keys** (for production):
  - Secret key: `sk_live_...`
  - Publishable key: `pk_live_...`

### 2. Set Up Test Environment (Development)

```bash
cd backend/scripts

# Create products and prices only
python setup_stripe_simple.py \
    --mode test \
    --api-key sk_test_YOUR_TEST_KEY

# Create products, prices, AND webhook
python setup_stripe_simple.py \
    --mode test \
    --api-key sk_test_YOUR_TEST_KEY \
    --webhook-url https://api-dev.example.com/api/stripe/webhook
```

### 3. Set Up Live Environment (Production)

```bash
# Create products and prices only
python setup_stripe_simple.py \
    --mode live \
    --api-key sk_live_YOUR_LIVE_KEY

# Create products, prices, AND webhook
python setup_stripe_simple.py \
    --mode live \
    --api-key sk_live_YOUR_LIVE_KEY \
    --webhook-url https://api.example.com/api/stripe/webhook
```

## What This Script Creates

### Products & Prices

The script creates three subscription products in Stripe:

| Plan | Price | Tokens/Month |
|------|-------|--------------|
| **Hopper Free** | $0.00 | 10 |
| **Hopper Medium** | $9.99 | 100 |
| **Hopper Pro** | $29.99 | 500 |

### Webhook Events

If you provide a `--webhook-url`, the script configures these events:
- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_succeeded`
- `invoice.payment_failed`

## After Running the Script

### 1. Update Your Configuration

The script will output Product IDs and Price IDs. Update `stripe_config.py`:

```python
PLANS_TEST = {
    'free': {
        'name': 'Hopper Free',
        'monthly_tokens': 10,
        'stripe_price_id': "price_TEST_ID_HERE",
        'stripe_product_id': "prod_TEST_ID_HERE",
    },
    # ... etc
}

PLANS_LIVE = {
    'free': {
        'name': 'Hopper Free',
        'monthly_tokens': 10,
        'stripe_price_id': "price_LIVE_ID_HERE",
        'stripe_product_id': "prod_LIVE_ID_HERE",
    },
    # ... etc
}
```

### 2. Add Webhook Secret to Environment

Add the webhook signing secret to your `.env.dev` or `.env.prod`:

```bash
# For test mode
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# For live mode
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

**Note**: If the webhook already existed, you need to get the signing secret from the Stripe Dashboard:
1. Go to [Stripe Webhooks](https://dashboard.stripe.com/webhooks)
2. Click on your webhook endpoint
3. Click "Reveal" next to "Signing secret"
4. Copy and add to your `.env` file

## Testing Your Webhook Locally

Use Stripe CLI to forward webhook events to your local development server:

```bash
# Install Stripe CLI: https://stripe.com/docs/stripe-cli

# Login
stripe login

# Forward events to your local server
stripe listen --forward-to http://localhost:8000/api/stripe/webhook

# Test a specific event
stripe trigger checkout.session.completed
```

## Idempotency

The script is safe to run multiple times:
- **Existing products**: Found by name, not recreated
- **Existing prices**: Found by amount/currency/interval, not recreated
- **Existing webhooks**: Found by URL, events updated if needed

## Customizing Products

To change product details, edit the `PRODUCTS` dictionary in `setup_stripe_simple.py`:

```python
PRODUCTS = {
    'free': {
        'name': 'Hopper Free',
        'description': '10 tokens per month',
        'monthly_tokens': 10,
        'price_cents': 0,  # $0.00
    },
    'medium': {
        'name': 'Hopper Medium',
        'description': '100 tokens per month',
        'monthly_tokens': 100,
        'price_cents': 999,  # $9.99
    },
    # ... add more plans
}
```

Then run the script again. Existing products won't be affected; only new products will be created.

## Troubleshooting

### "API key does not match mode"

Make sure:
- Test mode uses `sk_test_...` keys
- Live mode uses `sk_live_...` keys

### "Product already exists with different price"

The script finds existing prices by matching:
- Product ID
- Unit amount (price)
- Currency (USD)
- Interval (month)

If you changed the price, you need to either:
1. Create a new price in Stripe Dashboard and update config manually
2. Delete the old product/price and re-run the script

### "Webhook secret not showing"

Webhook secrets are only shown when a webhook is **newly created**. For existing webhooks, get the secret from the Stripe Dashboard (see "After Running the Script" section above).

## Support

For Stripe API documentation, visit: https://stripe.com/docs/api

