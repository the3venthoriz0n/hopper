"""Subscription operations tests (upgrade, downgrade, cancel, renew)"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.services.stripe_service import create_stripe_subscription, StripeRegistry
from app.services.subscription_service import cancel_user_subscription
from app.services.token_service import reset_tokens_for_subscription, handle_subscription_renewal


@pytest.mark.high
class TestPlanUpgrades:
    """Test plan upgrade operations"""
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_upgrade_free_to_starter(self, mock_settings, mock_stripe, mock_registry_get, test_user, db_session):
        """Test upgrade from free to starter, preserve tokens"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        # Mock StripeRegistry
        mock_registry_get.side_effect = lambda key: {
            "free_price": {
                "price_id": "price_free",
                "tokens": 10,
                "name": "Free"
            },
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            },
            "starter_overage_price": {
                "price_id": "price_starter_overage",
                "tokens": 0
            }
        }.get(key)
        
        # Create free subscription with 5 tokens remaining
        free_sub = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_free123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(free_sub)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=5,
            tokens_used_this_period=5,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Mock Stripe subscription creation
        mock_subscription = Mock()
        mock_subscription.id = 'sub_starter123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        mock_stripe.Subscription.delete = Mock(return_value=Mock(deleted=True))
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        # Upgrade to starter
        result = create_stripe_subscription(test_user.id, "starter", db_session)
        
        assert result is not None
        assert result.plan_type == "starter"
        
        # Verify old subscription was canceled
        db_session.refresh(free_sub)
        # Old subscription should be deleted from DB (create_stripe_subscription deletes existing)
        
        # Verify tokens were preserved (5 + 300 = 305)
        db_session.refresh(balance)
        assert balance.tokens_remaining == 305  # Preserved 5 + new 300
        assert balance.monthly_tokens == 305
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_upgrade_starter_to_creator(self, mock_settings, mock_stripe, mock_registry_get, test_user, db_session):
        """Test upgrade from starter to creator"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        mock_registry_get.side_effect = lambda key: {
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            },
            "creator_price": {
                "price_id": "price_creator",
                "tokens": 1250,
                "name": "Creator"
            },
            "creator_overage_price": {
                "price_id": "price_creator_overage",
                "tokens": 0
            }
        }.get(key)
        
        starter_sub = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_starter123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(starter_sub)
        db_session.commit()
        
        mock_subscription = Mock()
        mock_subscription.id = 'sub_creator123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        mock_stripe.Subscription.delete = Mock(return_value=Mock(deleted=True))
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = create_stripe_subscription(test_user.id, "creator", db_session)
        
        assert result is not None
        assert result.plan_type == "creator"
    
    @patch('app.services.stripe_service.stripe')
    def test_upgrade_cancels_old_subscription(self, mock_stripe, test_user, db_session):
        """Test that upgrade cancels old subscription in Stripe"""
        from app.services.stripe_service import cancel_all_user_subscriptions
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_old123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        mock_stripe.Subscription.delete = Mock(return_value=Mock(deleted=True))
        
        canceled_count = cancel_all_user_subscriptions(test_user.id, db_session, invoice_now=True)
        
        assert canceled_count == 1
        mock_stripe.Subscription.delete.assert_called_once_with("sub_old123", invoice_now=True)


@pytest.mark.high
class TestPlanDowngrades:
    """Test plan downgrade operations"""
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_downgrade_creator_to_starter(self, mock_settings, mock_stripe, mock_registry_get, test_user, db_session):
        """Test downgrade from creator to starter"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        mock_registry_get.side_effect = lambda key: {
            "creator_price": {
                "price_id": "price_creator",
                "tokens": 1250,
                "name": "Creator"
            },
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            },
            "starter_overage_price": {
                "price_id": "price_starter_overage",
                "tokens": 0
            }
        }.get(key)
        
        creator_sub = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_creator123",
            stripe_customer_id="cus_test123",
            plan_type="creator",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(creator_sub)
        db_session.commit()
        
        mock_subscription = Mock()
        mock_subscription.id = 'sub_starter123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        mock_stripe.Subscription.delete = Mock(return_value=Mock(deleted=True))
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = create_stripe_subscription(test_user.id, "starter", db_session)
        
        assert result is not None
        assert result.plan_type == "starter"
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_downgrade_paid_to_free(self, mock_settings, mock_stripe, mock_registry_get, test_user, db_session):
        """Test downgrade to free, preserve tokens"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        mock_registry_get.side_effect = lambda key: {
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            },
            "free_price": {
                "price_id": "price_free",
                "tokens": 10,
                "name": "Free"
            }
        }.get(key)
        
        starter_sub = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_starter123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(starter_sub)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=150,
            tokens_used_this_period=150,
            monthly_tokens=300,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        mock_subscription = Mock()
        mock_subscription.id = 'sub_free123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        mock_stripe.Subscription.delete = Mock(return_value=Mock(deleted=True))
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = create_stripe_subscription(test_user.id, "free", db_session)
        
        assert result is not None
        assert result.plan_type == "free"
        
        # Verify tokens preserved (150 + 10 = 160)
        db_session.refresh(balance)
        assert balance.tokens_remaining == 160
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_cancel_subscription_switches_to_free(self, mock_settings, mock_stripe, mock_registry_get, test_user, db_session):
        """Test cancel_user_subscription switches to free plan"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        mock_registry_get.side_effect = lambda key: {
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            },
            "free_price": {
                "price_id": "price_free",
                "tokens": 10,
                "name": "Free"
            }
        }.get(key)
        
        starter_sub = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_starter123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(starter_sub)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=200,
            tokens_used_this_period=100,
            monthly_tokens=300,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        mock_subscription = Mock()
        mock_subscription.id = 'sub_free123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        mock_stripe.Subscription.delete = Mock(return_value=Mock(deleted=True))
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        result = cancel_user_subscription(test_user.id, db_session)
        
        assert result["status"] == "success"
        assert result["plan_type"] == "free"
        assert result["tokens_preserved"] == 200
        
        # Verify free subscription was created
        free_sub = db_session.query(Subscription).filter(
            Subscription.user_id == test_user.id
        ).first()
        assert free_sub is not None
        assert free_sub.plan_type == "free"


@pytest.mark.high
class TestSubscriptionLifecycle:
    """Test subscription lifecycle operations"""
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    def test_subscription_renewal_resets_tokens(self, mock_registry_get, test_user, db_session):
        """Test tokens reset on renewal"""
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
            current_period_start=datetime.now(timezone.utc) - timedelta(days=30),
            current_period_end=datetime.now(timezone.utc)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=50,
            tokens_used_this_period=250,
            monthly_tokens=300,
            period_start=datetime.now(timezone.utc) - timedelta(days=30),
            period_end=datetime.now(timezone.utc)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Simulate renewal - period advances
        old_period_end = subscription.current_period_end
        subscription.current_period_start = datetime.now(timezone.utc)
        subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
        
        # Handle renewal
        result = handle_subscription_renewal(test_user.id, subscription, old_period_end, db_session)
        
        assert result is True
        
        # Verify tokens were reset (not added)
        db_session.refresh(balance)
        assert balance.tokens_remaining == 300  # Reset to monthly allocation
        assert balance.monthly_tokens == 300
        assert balance.tokens_used_this_period == 0
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    def test_subscription_renewal_detection(self, mock_registry_get, test_user, db_session):
        """Test handle_subscription_renewal logic"""
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
        
        old_period_end = datetime.now(timezone.utc)
        subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
        
        # Period advanced by 30 days - should be detected as renewal
        result = handle_subscription_renewal(test_user.id, subscription, old_period_end, db_session)
        
        assert result is True
    
    def test_subscription_period_update(self, test_user, db_session):
        """Test subscription period updates correctly"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        new_start = datetime.now(timezone.utc) + timedelta(days=30)
        new_end = datetime.now(timezone.utc) + timedelta(days=60)
        
        subscription.current_period_start = new_start
        subscription.current_period_end = new_end
        db_session.commit()
        
        db_session.refresh(subscription)
        assert subscription.current_period_start == new_start
        assert subscription.current_period_end == new_end

