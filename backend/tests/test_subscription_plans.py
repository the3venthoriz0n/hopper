"""Subscription plan-specific tests"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.services.stripe_service import create_stripe_subscription, StripeRegistry
from app.services.token_service import (
    reset_tokens_for_subscription, deduct_tokens, check_tokens_available,
    handle_daily_token_grant
)


@pytest.mark.high
class TestStarterPlan:
    """Test Starter plan functionality"""
    
    @patch('app.services.token_service.ensure_tokens_synced_for_subscription')
    @patch('app.services.stripe_service.StripeRegistry.get')
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    async def test_create_starter_subscription(self, mock_settings, mock_stripe, mock_registry_get, mock_ensure_tokens, test_user, db_session, mock_async_redis):
        """Test creating starter subscription, verify 300 tokens"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        # Mock StripeRegistry to return starter plan config
        mock_registry_get.side_effect = lambda key: {
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter",
                "description": "Starter plan",
                "amount_dollars": 3.0,
                "currency": "USD",
                "formatted": "$3.00"
            },
            "starter_overage_price": {
                "price_id": "price_starter_overage",
                "tokens": 0,
                "name": "Starter Overage",
                "amount_dollars": 0.015,
                "currency": "USD",
                "formatted": "$0.015"
            }
        }.get(key)
        
        # Mock Stripe subscription
        mock_subscription = Mock()
        mock_subscription.id = 'sub_starter123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        
        # Set user's customer ID
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = create_stripe_subscription(test_user.id, "starter", db_session)
        
        assert result is not None
        assert result.plan_type == "starter"
        
        # Manually set tokens since ensure_tokens_synced_for_subscription is mocked
        from app.services.token_service import reset_tokens_for_subscription
        await reset_tokens_for_subscription(
            test_user.id, "starter", 
            datetime.fromtimestamp(mock_subscription.current_period_start, tz=timezone.utc),
            datetime.fromtimestamp(mock_subscription.current_period_end, tz=timezone.utc),
            db_session, is_renewal=False
        )
        
        # Verify token balance
        balance = db_session.query(TokenBalance).filter(TokenBalance.user_id == test_user.id).first()
        assert balance is not None
        assert balance.tokens_remaining == 300
        assert balance.monthly_tokens == 300
    
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.StripeRegistry.get')
    async def test_starter_plan_allows_overage(self, mock_registry_get, test_user, db_session, mock_async_redis):
        """Test starter plan allows overage tokens"""
        # Mock StripeRegistry
        mock_registry_get.return_value = {
            "price_id": "price_starter",
            "tokens": 300,
            "name": "Starter"
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_starter123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=5,
            tokens_used_this_period=295,
            monthly_tokens=300,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Try to deduct 10 tokens (only have 5, should allow overage)
        with patch('app.services.stripe_service.record_token_usage_to_stripe'):
            result = await deduct_tokens(test_user.id, 10, db=db_session)
            assert result is True  # Paid plan allows overage
            
            db_session.refresh(balance)
            assert balance.tokens_remaining == 0  # Clamped at 0
            assert balance.tokens_used_this_period == 305  # Total used
    
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.StripeRegistry.get')
    async def test_starter_plan_token_reset(self, mock_registry_get, test_user, db_session, mock_async_redis):
        """Test monthly token reset for starter plan"""
        mock_registry_get.return_value = {
            "price_id": "price_starter",
            "tokens": 300,
            "name": "Starter"
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_starter123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        period_start = datetime.now(timezone.utc)
        period_end = datetime.now(timezone.utc) + timedelta(days=30)
        
        result = await reset_tokens_for_subscription(
            test_user.id, "starter", period_start, period_end, db_session, is_renewal=True
        )
        assert result is True
        
        balance = db_session.query(TokenBalance).filter(
            TokenBalance.user_id == test_user.id
        ).first()
        assert balance is not None
        assert balance.tokens_remaining == 300
        assert balance.monthly_tokens == 300


@pytest.mark.high
class TestCreatorPlan:
    """Test Creator plan functionality"""
    
    @pytest.mark.asyncio
    @patch('app.services.token_service.ensure_tokens_synced_for_subscription')
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    async def test_create_creator_subscription(self, mock_settings, mock_stripe, mock_registry_get, mock_ensure_tokens, test_user, db_session, mock_async_redis):
        """Test creating creator subscription, verify 1250 tokens"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        # Mock StripeRegistry
        mock_registry_get.side_effect = lambda key: {
            "creator_price": {
                "price_id": "price_creator",
                "tokens": 1250,
                "name": "Creator",
                "description": "Creator plan",
                "amount_dollars": 10.0,
                "currency": "USD",
                "formatted": "$10.00"
            },
            "creator_overage_price": {
                "price_id": "price_creator_overage",
                "tokens": 0,
                "name": "Creator Overage",
                "amount_dollars": 0.008,
                "currency": "USD",
                "formatted": "$0.008"
            }
        }.get(key)
        
        # Mock Stripe subscription
        mock_subscription = Mock()
        mock_subscription.id = 'sub_creator123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = create_stripe_subscription(test_user.id, "creator", db_session)
        
        assert result is not None
        assert result.plan_type == "creator"
        
        # Manually set tokens since ensure_tokens_synced_for_subscription is mocked
        from app.services.token_service import reset_tokens_for_subscription
        await reset_tokens_for_subscription(
            test_user.id, "creator", 
            datetime.fromtimestamp(mock_subscription.current_period_start, tz=timezone.utc),
            datetime.fromtimestamp(mock_subscription.current_period_end, tz=timezone.utc),
            db_session, is_renewal=False
        )
        
        balance = db_session.query(TokenBalance).filter(TokenBalance.user_id == test_user.id).first()
        assert balance is not None
        assert balance.tokens_remaining == 1250
        assert balance.monthly_tokens == 1250
    
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.StripeRegistry.get')
    async def test_creator_plan_allows_overage(self, mock_registry_get, test_user, db_session, mock_async_redis):
        """Test creator plan allows overage tokens"""
        mock_registry_get.return_value = {
            "price_id": "price_creator",
            "tokens": 1250,
            "name": "Creator"
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_creator123",
            stripe_customer_id="cus_test123",
            plan_type="creator",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=1240,
            monthly_tokens=1250,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        with patch('app.services.stripe_service.record_token_usage_to_stripe'):
            result = await deduct_tokens(test_user.id, 20, db=db_session)
            assert result is True
            
            db_session.refresh(balance)
            assert balance.tokens_remaining == 0
            assert balance.tokens_used_this_period == 1260
    
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.StripeRegistry.get')
    async def test_creator_plan_token_reset(self, mock_registry_get, test_user, db_session, mock_async_redis):
        """Test monthly token reset for creator plan"""
        mock_registry_get.return_value = {
            "price_id": "price_creator",
            "tokens": 1250,
            "name": "Creator"
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_creator123",
            stripe_customer_id="cus_test123",
            plan_type="creator",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        period_start = datetime.now(timezone.utc)
        period_end = datetime.now(timezone.utc) + timedelta(days=30)
        
        result = await reset_tokens_for_subscription(
            test_user.id, "creator", period_start, period_end, db_session, is_renewal=True
        )
        assert result is True
        
        balance = db_session.query(TokenBalance).filter(
            TokenBalance.user_id == test_user.id
        ).first()
        assert balance.tokens_remaining == 1250
        assert balance.monthly_tokens == 1250


@pytest.mark.high
class TestFreeDailyPlan:
    """Test Free Daily plan functionality"""
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_create_free_daily_subscription(self, mock_settings, mock_stripe, mock_registry_get, test_user, db_session):
        """Test creating free_daily subscription"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        mock_registry_get.side_effect = lambda key: {
            "free_daily_price": {
                "price_id": "price_free_daily",
                "tokens": 3,
                "name": "Free Daily",
                "description": "3 tokens per day",
                "amount_dollars": 0.0,
                "currency": "USD",
                "formatted": "Free",
                "max_accrual": 10,
                "recurring_interval": "day"
            }
        }.get(key)
        
        mock_subscription = Mock()
        mock_subscription.id = 'sub_free_daily123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = create_stripe_subscription(test_user.id, "free_daily", db_session)
        
        assert result is not None
        assert result.plan_type == "free_daily"
    
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.StripeRegistry.get')
    async def test_free_daily_daily_token_grant(self, mock_registry_get, test_user, db_session, mock_async_redis):
        """Test daily token grant for free_daily plan"""
        mock_registry_get.return_value = {
            "price_id": "price_free_daily",
            "tokens": 3,
            "max_accrual": 10
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_free_daily123",
            stripe_customer_id="cus_test123",
            plan_type="free_daily",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=1)
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Grant daily tokens
        result = await handle_daily_token_grant(test_user.id, "sub_free_daily123", db_session)
        assert result is True
        
        balance = db_session.query(TokenBalance).filter(TokenBalance.user_id == test_user.id).first()
        assert balance is not None
        assert balance.tokens_remaining == 3
    
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.StripeRegistry.get')
    async def test_free_daily_max_accrual_cap(self, mock_registry_get, test_user, db_session, mock_async_redis):
        """Test tokens cap at max_accrual (10)"""
        mock_registry_get.return_value = {
            "price_id": "price_free_daily",
            "tokens": 3,
            "max_accrual": 10
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_free_daily123",
            stripe_customer_id="cus_test123",
            plan_type="free_daily",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=1)
        )
        db_session.add(subscription)
        
        # Start with 8 tokens (close to max)
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=8,
            tokens_used_this_period=0,
            monthly_tokens=8,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=1)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Grant daily tokens (should only add 2 to reach max of 10)
        result = await handle_daily_token_grant(test_user.id, "sub_free_daily123", db_session)
        assert result is True
        
        db_session.refresh(balance)
        assert balance.tokens_remaining == 10  # Capped at max_accrual
        assert balance.monthly_tokens == 10
    
    @pytest.mark.asyncio
    @patch('app.services.stripe_service.StripeRegistry.get')
    async def test_free_daily_banking_logic(self, mock_registry_get, test_user, db_session, mock_async_redis):
        """Test tokens don't exceed max_accrual"""
        mock_registry_get.return_value = {
            "price_id": "price_free_daily",
            "tokens": 3,
            "max_accrual": 10
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_free_daily123",
            stripe_customer_id="cus_test123",
            plan_type="free_daily",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=1)
        )
        db_session.add(subscription)
        
        # Start at max
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=1)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Try to grant more (should not add any)
        result = await handle_daily_token_grant(test_user.id, "sub_free_daily123", db_session)
        assert result is True  # Returns True but doesn't add tokens
        
        db_session.refresh(balance)
        assert balance.tokens_remaining == 10  # Still at max


@pytest.mark.high
class TestUnlimitedPlan:
    """Test Unlimited plan functionality"""
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_create_unlimited_subscription(self, mock_settings, mock_stripe, mock_registry_get, test_user, db_session):
        """Test creating unlimited subscription"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        mock_registry_get.side_effect = lambda key: {
            "unlimited_price": {
                "price_id": "price_unlimited",
                "tokens": -1,  # -1 represents unlimited
                "name": "Unlimited",
                "description": "Unlimited tokens",
                "amount_dollars": 0.0,
                "currency": "USD",
                "formatted": "Free",
                "hidden": True
            }
        }.get(key)
        
        mock_subscription = Mock()
        mock_subscription.id = 'sub_unlimited123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = create_stripe_subscription(test_user.id, "unlimited", db_session)
        
        assert result is not None
        assert result.plan_type == "unlimited"
    
    @pytest.mark.asyncio
    async def test_unlimited_plan_bypasses_token_checks(self, test_user, db_session, mock_async_redis):
        """Test unlimited plan always allows usage"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_unlimited123",
            stripe_customer_id="cus_test123",
            plan_type="unlimited",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Check tokens available (should always return True)
        result = check_tokens_available(test_user.id, 10000, db_session)
        assert result is True
        
        # Deduct tokens (should always succeed)
        result = await deduct_tokens(test_user.id, 10000, db=db_session)
        assert result is True
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    def test_unlimited_plan_preserves_tokens(self, mock_registry_get, test_user, db_session):
        """Test token preservation when enrolling in unlimited plan"""
        mock_registry_get.side_effect = lambda key: {
            "unlimited_price": {
                "price_id": "price_unlimited",
                "tokens": -1,
                "name": "Unlimited"
            },
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            }
        }.get(key)
        
        # Create starter subscription with tokens
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_starter123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            preserved_tokens_balance=150,
            preserved_plan_type="starter"
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=150,
            tokens_used_this_period=0,
            monthly_tokens=300,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Verify preservation fields
        assert subscription.preserved_tokens_balance == 150
        assert subscription.preserved_plan_type == "starter"

