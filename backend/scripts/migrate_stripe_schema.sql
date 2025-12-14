-- Migration to update Stripe/Token schema
-- Run this on BOTH dev and prod databases
--
-- Usage:
--   DEV:  docker exec -i dev-hopper-postgres psql -U hopper -d hopper < backend/scripts/migrate_stripe_schema.sql
--   PROD: docker exec -i prod-hopper-postgres psql -U hopper -d hopper < backend/scripts/migrate_stripe_schema.sql

BEGIN;

-- ============================================================================
-- 1. FIX SUBSCRIPTIONS TABLE
-- ============================================================================

-- CLEAN UP: Delete any old/invalid subscription records with NULL required fields
-- These will be recreated automatically when users log in
DELETE FROM subscriptions WHERE stripe_subscription_id IS NULL OR stripe_customer_id IS NULL;

-- Rename plan_id to plan_type
ALTER TABLE subscriptions RENAME COLUMN plan_id TO plan_type;

-- Drop unused column
ALTER TABLE subscriptions DROP COLUMN IF EXISTS canceled_at;

-- Fill in default values for any NULL fields before setting NOT NULL
UPDATE subscriptions SET plan_type = 'free' WHERE plan_type IS NULL;
UPDATE subscriptions SET current_period_start = NOW() WHERE current_period_start IS NULL;
UPDATE subscriptions SET current_period_end = NOW() + INTERVAL '1 month' WHERE current_period_end IS NULL;
UPDATE subscriptions SET cancel_at_period_end = FALSE WHERE cancel_at_period_end IS NULL;
UPDATE subscriptions SET created_at = NOW() WHERE created_at IS NULL;
UPDATE subscriptions SET updated_at = NOW() WHERE updated_at IS NULL;

-- Fix timestamp types (add timezone)
ALTER TABLE subscriptions 
  ALTER COLUMN current_period_start TYPE timestamp with time zone USING current_period_start AT TIME ZONE 'UTC',
  ALTER COLUMN current_period_end TYPE timestamp with time zone USING current_period_end AT TIME ZONE 'UTC',
  ALTER COLUMN created_at TYPE timestamp with time zone USING created_at AT TIME ZONE 'UTC',
  ALTER COLUMN updated_at TYPE timestamp with time zone USING updated_at AT TIME ZONE 'UTC';

-- Set NOT NULL constraints
ALTER TABLE subscriptions 
  ALTER COLUMN stripe_subscription_id SET NOT NULL,
  ALTER COLUMN stripe_customer_id SET NOT NULL,
  ALTER COLUMN plan_type SET NOT NULL,
  ALTER COLUMN current_period_start SET NOT NULL,
  ALTER COLUMN current_period_end SET NOT NULL,
  ALTER COLUMN cancel_at_period_end SET NOT NULL,
  ALTER COLUMN created_at SET NOT NULL,
  ALTER COLUMN updated_at SET NOT NULL;

-- Add missing indexes
CREATE INDEX IF NOT EXISTS ix_subscriptions_id ON subscriptions(id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_stripe_customer_id ON subscriptions(stripe_customer_id);

-- Add unique constraint on user_id (if not already exists)
DO $$ 
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'subscriptions_user_id_key'
  ) THEN
    ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_user_id_key UNIQUE (user_id);
  END IF;
END $$;

-- ============================================================================
-- 2. FIX STRIPE_EVENTS TABLE
-- ============================================================================

-- Rename/add columns to match new schema
ALTER TABLE stripe_events DROP COLUMN IF EXISTS processed_at;
ALTER TABLE stripe_events DROP COLUMN IF EXISTS raw_data;
ALTER TABLE stripe_events ADD COLUMN IF NOT EXISTS payload JSON NOT NULL DEFAULT '{}'::json;
ALTER TABLE stripe_events ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Fix timestamp type
ALTER TABLE stripe_events 
  ALTER COLUMN created_at TYPE timestamp with time zone USING created_at AT TIME ZONE 'UTC';

-- Set NOT NULL and default
ALTER TABLE stripe_events 
  ALTER COLUMN processed SET NOT NULL,
  ALTER COLUMN processed SET DEFAULT FALSE,
  ALTER COLUMN created_at SET NOT NULL;

-- Add missing indexes
CREATE INDEX IF NOT EXISTS ix_stripe_events_id ON stripe_events(id);
CREATE INDEX IF NOT EXISTS ix_stripe_events_event_type ON stripe_events(event_type);

-- ============================================================================
-- 3. REBUILD TOKEN_BALANCES TABLE (completely different schema)
-- ============================================================================

-- Drop and recreate with new schema
DROP TABLE IF EXISTS token_balances CASCADE;

CREATE TABLE token_balances (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    tokens_remaining INTEGER NOT NULL DEFAULT 0,
    tokens_used_this_period INTEGER NOT NULL DEFAULT 0,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    unlimited_tokens BOOLEAN NOT NULL DEFAULT FALSE,
    last_reset_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_token_balances_id ON token_balances(id);
CREATE UNIQUE INDEX ix_token_balances_user_id ON token_balances(user_id);

-- ============================================================================
-- 4. REBUILD TOKEN_TRANSACTIONS TABLE (completely different schema)
-- ============================================================================

-- Drop and recreate with new schema
DROP TABLE IF EXISTS token_transactions CASCADE;

CREATE TABLE token_transactions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    video_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    transaction_type VARCHAR(50) NOT NULL,
    tokens INTEGER NOT NULL,
    balance_before INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    transaction_metadata JSON,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_token_transactions_id ON token_transactions(id);
CREATE INDEX ix_token_transactions_user_id ON token_transactions(user_id);
CREATE INDEX ix_token_transactions_created_at ON token_transactions(created_at);
CREATE INDEX ix_token_transactions_user_created ON token_transactions(user_id, created_at);

COMMIT;

-- ============================================================================
-- DONE!
-- ============================================================================
-- After running this migration:
-- 1. Restart your backend: docker-compose restart backend
-- 2. Test the subscription endpoints
-- 3. Users will get free subscriptions auto-created on first API call

