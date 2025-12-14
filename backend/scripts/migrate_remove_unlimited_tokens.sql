-- Migration script to remove unlimited_tokens field and migrate to subscription-based unlimited plan
-- Run this manually on your database

-- Step 1: Migrate existing users with unlimited_tokens=true to unlimited plan subscriptions
-- This creates a fake Stripe subscription ID for users who had unlimited_tokens but no unlimited subscription
UPDATE subscriptions
SET plan_type = 'unlimited',
    status = 'active',
    updated_at = NOW()
WHERE user_id IN (
    SELECT id FROM users WHERE unlimited_tokens = true
)
AND plan_type != 'unlimited';

-- For users with unlimited_tokens but no subscription, create one
-- (This assumes they have a stripe_customer_id - if not, you'll need to create customers first)
INSERT INTO subscriptions (user_id, stripe_subscription_id, stripe_customer_id, plan_type, status, current_period_start, current_period_end, cancel_at_period_end, created_at, updated_at)
SELECT 
    u.id,
    'unlimited_' || u.id || '_' || EXTRACT(EPOCH FROM NOW())::bigint,
    COALESCE(u.stripe_customer_id, 'customer_' || u.id),
    'unlimited',
    'active',
    NOW(),
    NOW() + INTERVAL '1 month',
    false,
    NOW(),
    NOW()
FROM users u
WHERE u.unlimited_tokens = true
AND NOT EXISTS (
    SELECT 1 FROM subscriptions s WHERE s.user_id = u.id
);

-- Step 2: Remove unlimited_tokens column from token_balances table
ALTER TABLE token_balances DROP COLUMN IF EXISTS unlimited_tokens;

-- Step 3: Remove unlimited_tokens column from users table
ALTER TABLE users DROP COLUMN IF EXISTS unlimited_tokens;

-- Verify migration
SELECT 
    u.id,
    u.email,
    s.plan_type,
    s.status
FROM users u
LEFT JOIN subscriptions s ON s.user_id = u.id
WHERE s.plan_type = 'unlimited'
ORDER BY u.id;

