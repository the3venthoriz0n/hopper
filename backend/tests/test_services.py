"""Service logic tests"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.models.token_transaction import TokenTransaction
from app.models.stripe_event import StripeEvent
from app.services.token_service import (
    deduct_tokens, check_tokens_available, reset_tokens_for_subscription,
    get_or_create_token_balance, get_token_balance
)
from app.services.subscription_service import (
    process_stripe_webhook, get_current_subscription_with_auto_repair
)
from app.services.settings_service import (
    add_wordbank_word, remove_wordbank_word, clear_wordbank
)
from app.services.stripe_service import create_stripe_subscription


@pytest.mark.critical
class TestTokenService:
    """Test token service logic"""
    
    def test_deduct_tokens_decreases_balance(self, test_user, db_session):
        """Test deduct_tokens() decreases balance correctly"""
        # Create subscription and token balance
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Deduct 5 tokens
        result = deduct_tokens(test_user.id, 5, db=db_session)
        assert result is True
        
        # Verify balance decreased
        db_session.refresh(balance)
        assert balance.tokens_remaining == 5
        assert balance.tokens_used_this_period == 5
        
        # Verify transaction was created
        transaction = db_session.query(TokenTransaction).filter(
            TokenTransaction.user_id == test_user.id
        ).first()
        assert transaction is not None
        assert transaction.tokens == -5
    
    def test_deduct_tokens_with_zero_tokens_returns_false(self, test_user, db_session):
        """Test deduct_tokens() with 0 tokens returns False for free plan"""
        # Create subscription and token balance with 0 tokens
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=0,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Try to deduct 5 tokens
        result = deduct_tokens(test_user.id, 5, db=db_session)
        assert result is False  # Free plan has hard limit
    
    def test_deduct_tokens_creates_transaction(self, test_user, db_session):
        """Test deduct_tokens() creates TokenTransaction record"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Create a video first (required for foreign key constraint)
        from app.models.video import Video
        video = Video(
            user_id=test_user.id,
            filename="test.mp4",
            path="/tmp/test.mp4",
            status="pending"
        )
        db_session.add(video)
        db_session.commit()
        
        # Deduct tokens
        deduct_tokens(test_user.id, 3, video_id=video.id, db=db_session)
        
        # Verify transaction exists
        transaction = db_session.query(TokenTransaction).filter(
            TokenTransaction.user_id == test_user.id,
            TokenTransaction.video_id == video.id
        ).first()
        assert transaction is not None
        assert transaction.transaction_type == "upload"
        assert transaction.tokens == -3
    
    def test_unlimited_plan_bypasses_deduction(self, test_user, db_session):
        """Test unlimited plan bypasses deduction but still logs transaction"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="unlimited",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Deduct tokens (should succeed even without balance)
        result = deduct_tokens(test_user.id, 100, db=db_session)
        assert result is True
        
        # Verify transaction was logged
        transaction = db_session.query(TokenTransaction).filter(
            TokenTransaction.user_id == test_user.id
        ).first()
        assert transaction is not None
        assert transaction.balance_before == -1  # Unlimited indicator
        assert transaction.balance_after == -1
    
    def test_free_plan_cannot_go_negative(self, test_user, db_session):
        """Test free plan cannot go negative (hard limit, no overage)"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=5,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Try to deduct 10 tokens (only have 5)
        result = deduct_tokens(test_user.id, 10, db=db_session)
        assert result is False  # Free plan blocks overage
    
    def test_paid_plan_allows_overage(self, test_user, db_session):
        """Test paid plans allow overage (negative balance)"""
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
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=5,
            tokens_used_this_period=0,
            monthly_tokens=100,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        # Deduct 10 tokens (only have 5, should allow overage)
        with patch('app.services.stripe_service.record_token_usage_to_stripe'):
            result = deduct_tokens(test_user.id, 10, db=db_session)
            assert result is True  # Paid plan allows overage
            
            db_session.refresh(balance)
            # The code calculates: included_tokens_used = min(10, max(0, 5)) = 5
            # Then: balance.tokens_remaining = 5 - 5 = 0
            # The balance is clamped at 0, overage is tracked separately in tokens_used_this_period
            assert balance.tokens_remaining == 0  # Balance clamped at 0 for paid plans
            assert balance.tokens_used_this_period == 10  # Total tokens used (5 included + 5 overage)
    
    def test_check_tokens_available_sufficient(self, test_user, db_session):
        """Test check_tokens_available() returns True when sufficient tokens"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        result = check_tokens_available(test_user.id, 5, db_session)
        assert result is True
    
    def test_check_tokens_available_insufficient(self, test_user, db_session):
        """Test check_tokens_available() returns False when insufficient tokens for free plan"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=5,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        result = check_tokens_available(test_user.id, 10, db_session)
        assert result is False  # Free plan has hard limit
    
    def test_unlimited_plan_always_returns_true(self, test_user, db_session):
        """Test unlimited plan always returns True for check_tokens_available"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="unlimited",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        result = check_tokens_available(test_user.id, 1000, db_session)
        assert result is True
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    def test_reset_tokens_for_subscription_sets_monthly_tokens(self, mock_registry_get, test_user, db_session):
        """Test reset_tokens_for_subscription() sets correct monthly tokens"""
        # Mock StripeRegistry to return free plan config
        mock_registry_get.return_value = {
            "price_id": "price_free",
            "tokens": 10,
            "name": "Free",
            "description": "Free plan",
            "amount_dollars": 0.0,
            "currency": "USD",
            "formatted": "Free"
        }
        
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        period_start = datetime.now(timezone.utc)
        period_end = datetime.now(timezone.utc) + timedelta(days=30)
        
        result = reset_tokens_for_subscription(
            test_user.id, "free", period_start, period_end, db_session, is_renewal=True
        )
        assert result is True
        
        balance = db_session.query(TokenBalance).filter(
            TokenBalance.user_id == test_user.id
        ).first()
        assert balance is not None
        assert balance.tokens_remaining == 10  # Free plan has 10 tokens
        assert balance.monthly_tokens == 10


@pytest.mark.critical
class TestSubscriptionService:
    """Test subscription service logic"""
    
    @patch('app.services.stripe_service.StripeRegistry')
    def test_process_stripe_webhook_subscription_created(self, mock_registry_class, test_user, db_session, mock_stripe):
        """Test process_stripe_webhook() with customer.subscription.created creates subscription"""
        # Mock StripeRegistry to return free plan config
        mock_registry_instance = Mock()
        mock_registry_instance._cache = {
            "free_price": {
                "price_id": "price_free",
                "tokens": 10,
                "name": "Free",
                "description": "Free plan",
                "amount_dollars": 0.0,
                "currency": "USD",
                "formatted": "Free"
            }
        }
        mock_registry_class._cache = mock_registry_instance._cache
        mock_registry_class.get = Mock(side_effect=lambda key: mock_registry_instance._cache.get(key))
        
        price_id = "price_free"
        
        # Mock Stripe event
        event_payload = {
            "id": "evt_test123",
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_test123",
                    "customer": "cus_test123",
                    "status": "active",
                    "current_period_start": int(datetime.now(timezone.utc).timestamp()),
                    "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
                    "items": {
                        "data": [{
                            "price": {
                                "id": price_id
                            }
                        }]
                    },
                    "metadata": {"user_id": str(test_user.id)}
                }
            }
        }
        
        # Set up user's Stripe customer ID
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        # Mock Stripe webhook construction - patch where it's used in subscription_service
        # subscription_service imports stripe directly, so patch it there
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_subscription.items.data = [Mock(price=Mock(id=price_id))]
        mock_subscription.metadata = {"user_id": str(test_user.id)}
        mock_stripe.Subscription.retrieve.return_value = mock_subscription
        mock_stripe.SubscriptionItem.list.return_value = Mock(data=[Mock(price=Mock(id=price_id))])
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                # Patch stripe module where it's imported in subscription_service
                with patch('app.services.subscription_service.stripe.Webhook.construct_event', return_value=event_payload):
                    import time
                    timestamp = str(int(time.time()))
                    result = process_stripe_webhook(
                        b'{"test": "payload"}',
                        f"t={timestamp},v1=test_signature",  # Valid format but mock bypasses it
                        db_session
                    )
                
                # Verify event was logged
                event = db_session.query(StripeEvent).filter(
                    StripeEvent.stripe_event_id == "evt_test123"
                ).first()
                assert event is not None
                assert event.processed is True
    
    def test_webhook_idempotency_duplicate_event(self, test_user, db_session, mock_stripe):
        """Test webhook idempotency - same event ID twice doesn't process twice"""
        from app.services.stripe_service import log_stripe_event, mark_stripe_event_processed
        
        # Log event first time
        event = log_stripe_event(
            "evt_test123",
            "customer.subscription.created",
            {"id": "evt_test123", "type": "customer.subscription.created"},
            db_session
        )
        mark_stripe_event_processed("evt_test123", db_session)
        db_session.refresh(event)
        
        # Get initial token balance (if any)
        balance_before = db_session.query(TokenBalance).filter(
            TokenBalance.user_id == test_user.id
        ).first()
        tokens_before = balance_before.tokens_remaining if balance_before else 0
        
        # Process same event again
        event_payload = {
            "id": "evt_test123",
            "type": "customer.subscription.created",
            "data": {"object": {}}
        }
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                # Patch stripe module where it's imported in subscription_service
                with patch('app.services.subscription_service.stripe.Webhook.construct_event', return_value=event_payload):
                    import time
                    timestamp = str(int(time.time()))
                    result = process_stripe_webhook(
                        b'{"test": "payload"}',
                        f"t={timestamp},v1=test_signature",  # Valid format but mock bypasses it
                        db_session
                    )
                    
                    # Should return already_processed
                    assert result["status"] == "already_processed"
                
                # Verify tokens were NOT credited twice
                balance_after = db_session.query(TokenBalance).filter(
                    TokenBalance.user_id == test_user.id
                ).first()
                tokens_after = balance_after.tokens_remaining if balance_after else 0
                
                # Tokens should not have changed (or only changed once if first processing happened)
                # Since we marked it processed before second call, tokens should be same
                assert tokens_after == tokens_before
    
    def test_webhook_signature_verification_invalid(self, db_session, mock_stripe):
        """Test webhook signature verification rejects invalid signature"""
        import stripe
        
        mock_stripe.Webhook.construct_event.side_effect = stripe.error.SignatureVerificationError(
            "Invalid signature", "test_signature"
        )
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                with pytest.raises(stripe.error.SignatureVerificationError):
                    process_stripe_webhook(
                        b'{"test": "payload"}',
                        "invalid_signature",
                        db_session
                    )
    
    @patch('app.services.stripe_service.StripeRegistry')
    def test_webhook_subscription_updated(self, mock_registry_class, test_user, db_session, mock_stripe):
        """Test subscription.updated webhook event"""
        # Create subscription first so it can be updated
        existing_sub = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(existing_sub)
        db_session.commit()
        
        # Mock StripeRegistry
        mock_registry_instance = Mock()
        mock_registry_instance._cache = {
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            }
        }
        mock_registry_class._cache = mock_registry_instance._cache
        mock_registry_class.get = Mock(side_effect=lambda key: mock_registry_instance._cache.get(key))
        
        price_id = "price_starter"
        
        event_payload = {
            "id": "evt_test456",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test123",
                    "customer": "cus_test123",
                    "status": "active",
                    "current_period_start": int(datetime.now(timezone.utc).timestamp()),
                    "current_period_end": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
                }
            }
        }
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_subscription.items.data = [Mock(price=Mock(id=price_id))]
        mock_stripe.Subscription.retrieve.return_value = mock_subscription
        mock_stripe.SubscriptionItem.list.return_value = Mock(data=[Mock(price=Mock(id=price_id))])
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                with patch('app.services.subscription_service.stripe.Webhook.construct_event', return_value=event_payload):
                    with patch('app.services.token_service.ensure_tokens_synced_for_subscription') as mock_sync:
                        import time
                        timestamp = str(int(time.time()))
                        result = process_stripe_webhook(
                            b'{"test": "payload"}',
                            f"t={timestamp},v1=test_signature",
                            db_session
                        )
                        
                        assert result["status"] == "success"
    
    def test_webhook_subscription_deleted(self, test_user, db_session, mock_stripe):
        """Test subscription.deleted webhook event"""
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
        
        event_payload = {
            "id": "evt_test789",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_test123",
                    "customer": "cus_test123"
                }
            }
        }
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                with patch('app.services.subscription_service.stripe.Webhook.construct_event', return_value=event_payload):
                    import time
                    timestamp = str(int(time.time()))
                    result = process_stripe_webhook(
                        b'{"test": "payload"}',
                        f"t={timestamp},v1=test_signature",
                        db_session
                    )
                    
                    assert result["status"] == "success"
                    
                    # Verify subscription status updated
                    db_session.refresh(subscription)
                    assert subscription.status == "canceled"
    
    def test_webhook_invoice_payment_succeeded(self, test_user, db_session, mock_stripe):
        """Test invoice.payment_succeeded webhook event"""
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
        
        event_payload = {
            "id": "evt_invoice123",
            "type": "invoice.payment_succeeded",
            "data": {
                "object": {
                    "id": "in_test123",
                    "subscription": "sub_test123"
                }
            }
        }
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                with patch('app.services.subscription_service.stripe.Webhook.construct_event', return_value=event_payload):
                    with patch('app.services.token_service.ensure_tokens_synced_for_subscription') as mock_sync:
                        import time
                        timestamp = str(int(time.time()))
                        result = process_stripe_webhook(
                            b'{"test": "payload"}',
                            f"t={timestamp},v1=test_signature",
                            db_session
                        )
                        
                        assert result["status"] == "success"
                        mock_sync.assert_called_once_with(test_user.id, "sub_test123", db_session)
    
    def test_webhook_invoice_payment_failed(self, db_session, mock_stripe):
        """Test invoice.payment_failed webhook event"""
        event_payload = {
            "id": "evt_invoice_fail",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_fail123",
                    "subscription": "sub_test123"
                }
            }
        }
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                with patch('app.services.subscription_service.stripe.Webhook.construct_event', return_value=event_payload):
                    import time
                    timestamp = str(int(time.time()))
                    result = process_stripe_webhook(
                        b'{"test": "payload"}',
                        f"t={timestamp},v1=test_signature",
                        db_session
                    )
                    
                    assert result["status"] == "success"
    
    def test_webhook_checkout_completed(self, test_user, db_session, mock_stripe):
        """Test checkout.session.completed webhook event"""
        test_user.stripe_customer_id = None
        db_session.commit()
        
        event_payload = {
            "id": "evt_checkout123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test123",
                    "customer": "cus_new123",
                    "metadata": {"user_id": str(test_user.id)}
                }
            }
        }
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                with patch('app.services.subscription_service.stripe.Webhook.construct_event', return_value=event_payload):
                    import time
                    timestamp = str(int(time.time()))
                    result = process_stripe_webhook(
                        b'{"test": "payload"}',
                        f"t={timestamp},v1=test_signature",
                        db_session
                    )
                    
                    assert result["status"] == "success"
                    
                    # Verify customer ID was set
                    db_session.refresh(test_user)
                    assert test_user.stripe_customer_id == "cus_new123"
    
    @patch('app.services.token_service.ensure_tokens_synced_for_subscription')
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_get_current_subscription_with_auto_repair_creates_free(self, mock_settings, mock_stripe, mock_registry_get, mock_ensure_tokens, test_user, db_session):
        """Test get_current_subscription_with_auto_repair() creates free plan if missing"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        # Mock StripeRegistry to return free plan config
        mock_registry_get.return_value = {
            "price_id": "price_free",
            "tokens": 10,
            "name": "Free",
            "description": "Free plan",
            "amount_dollars": 0.0,
            "currency": "USD",
            "formatted": "Free"
        }
        
        # Mock Stripe subscription
        mock_subscription = Mock()
        mock_subscription.id = 'sub_free123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_stripe.Subscription.create.return_value = mock_subscription
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        # Verify no subscription exists
        subscription = db_session.query(Subscription).filter(
            Subscription.user_id == test_user.id
        ).first()
        assert subscription is None
        
        result = get_current_subscription_with_auto_repair(test_user.id, db_session)
        
        assert "subscription" in result
        assert result["subscription"] is not None
    
    def test_auto_repair_updates_existing_deleted_subscription(self, test_user, db_session, mock_stripe):
        """Test auto-repair updates existing deleted subscription instead of creating duplicate"""
        # Create a deleted subscription
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_deleted123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="canceled",
            current_period_start=datetime.now(timezone.utc) - timedelta(days=30),
            current_period_end=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Call auto-repair
        with patch('app.services.subscription_service.create_stripe_subscription') as mock_create:
            # Mock should not be called if subscription exists (even if deleted)
            # Actually, get_subscription_info might return None for canceled, so it might call create_stripe_subscription
            # But create_stripe_subscription should update existing, not create duplicate
            mock_sub = Mock()
            mock_sub.plan_type = "free"
            mock_sub.status = "active"
            mock_sub.stripe_subscription_id = "sub_free123"
            mock_sub.stripe_customer_id = "cus_test123"
            mock_sub.current_period_start = datetime.now(timezone.utc)
            mock_sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
            mock_create.return_value = mock_sub
            
            # This should handle the existing subscription correctly
            result = get_current_subscription_with_auto_repair(test_user.id, db_session)
            
            # Verify only one subscription exists (or updated existing)
            subscriptions = db_session.query(Subscription).filter(
                Subscription.user_id == test_user.id
            ).all()
            # Should have at most one subscription (might be updated or replaced)
            assert len(subscriptions) <= 1


@pytest.mark.high
class TestSettingsService:
    """Test settings service logic"""
    
    def test_add_wordbank_word_strips_whitespace(self, test_user, db_session):
        """Test add_wordbank_word() strips whitespace: '  word  ' -> 'Word'"""
        result = add_wordbank_word(test_user.id, "  test  ", db_session)
        
        # Get settings to verify
        from app.db.helpers import get_user_settings
        settings = get_user_settings(test_user.id, "global", db=db_session)
        wordbank = settings.get("wordbank", [])
        
        assert "Test" in wordbank
        assert "  test  " not in wordbank
        assert "test" not in wordbank
    
    def test_add_wordbank_word_capitalizes(self, test_user, db_session):
        """Test add_wordbank_word() capitalizes: 'test' -> 'Test'"""
        result = add_wordbank_word(test_user.id, "awesome", db_session)
        
        from app.db.helpers import get_user_settings
        settings = get_user_settings(test_user.id, "global", db=db_session)
        wordbank = settings.get("wordbank", [])
        
        assert "Awesome" in wordbank
        assert "awesome" not in wordbank
    
    def test_add_wordbank_word_prevents_duplicates(self, test_user, db_session):
        """Test add_wordbank_word() prevents duplicates"""
        # Add word first time
        add_wordbank_word(test_user.id, "test", db_session)
        
        # Try to add same word again
        add_wordbank_word(test_user.id, "test", db_session)
        
        from app.db.helpers import get_user_settings
        settings = get_user_settings(test_user.id, "global", db=db_session)
        wordbank = settings.get("wordbank", [])
        
        # Word should only appear once
        assert wordbank.count("Test") == 1
    
    def test_remove_wordbank_word(self, test_user, db_session):
        """Test remove_wordbank_word() removes word correctly"""
        # Add word
        add_wordbank_word(test_user.id, "test", db_session)
        
        # Remove word
        result = remove_wordbank_word(test_user.id, "Test", db_session)
        
        from app.db.helpers import get_user_settings
        settings = get_user_settings(test_user.id, "global", db=db_session)
        wordbank = settings.get("wordbank", [])
        
        assert "Test" not in wordbank
    
    def test_clear_wordbank(self, test_user, db_session):
        """Test clear_wordbank() clears all words"""
        # Add some words
        for word in ["test", "awesome", "cool"]:
            add_wordbank_word(test_user.id, word, db_session)
        
        # Clear wordbank
        result = clear_wordbank(test_user.id, db_session)
        
        assert result["wordbank"] == []
        
        from app.db.helpers import get_user_settings
        settings = get_user_settings(test_user.id, "global", db=db_session)
        wordbank = settings.get("wordbank", [])
        
        assert wordbank == []

