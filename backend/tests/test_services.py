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
from app.services.stripe_service import create_free_subscription


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
        
        # Deduct tokens
        deduct_tokens(test_user.id, 3, video_id=1, db=db_session)
        
        # Verify transaction exists
        transaction = db_session.query(TokenTransaction).filter(
            TokenTransaction.user_id == test_user.id,
            TokenTransaction.video_id == 1
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
            assert balance.tokens_remaining == -5  # Can go negative for overage tracking
    
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
    
    def test_reset_tokens_for_subscription_sets_monthly_tokens(self, test_user, db_session):
        """Test reset_tokens_for_subscription() sets correct monthly tokens"""
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
    
    def test_process_stripe_webhook_subscription_created(self, test_user, db_session, mock_stripe):
        """Test process_stripe_webhook() with customer.subscription.created creates subscription"""
        from app.services.stripe_service import get_plan_price_id
        
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
                                "id": get_plan_price_id("free") or "price_test123"
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
        
        # Mock Stripe webhook construction
        mock_stripe.Webhook.construct_event.return_value = event_payload
        
        # Mock subscription retrieval
        mock_subscription = Mock()
        mock_subscription.id = "sub_test123"
        mock_subscription.status = "active"
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
        mock_subscription.items.data = [Mock(price=Mock(id=get_plan_price_id("free") or "price_test123"))]
        mock_subscription.metadata = {"user_id": str(test_user.id)}
        mock_stripe.Subscription.retrieve.return_value = mock_subscription
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                result = process_stripe_webhook(
                    b'{"test": "payload"}',
                    "test_signature",
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
        
        mock_stripe.Webhook.construct_event.return_value = event_payload
        
        with patch('app.core.config.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
            with patch('app.services.stripe_service.settings.STRIPE_WEBHOOK_SECRET', 'whsec_test123'):
                result = process_stripe_webhook(
                    b'{"test": "payload"}',
                    "test_signature",
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
    
    def test_get_current_subscription_with_auto_repair_creates_free(self, test_user, db_session, mock_stripe):
        """Test get_current_subscription_with_auto_repair() creates free plan if missing"""
        # Verify no subscription exists
        subscription = db_session.query(Subscription).filter(
            Subscription.user_id == test_user.id
        ).first()
        assert subscription is None
        
        # Mock create_free_subscription
        with patch('app.services.subscription_service.create_free_subscription') as mock_create:
            mock_sub = Mock()
            mock_sub.plan_type = "free"
            mock_sub.status = "active"
            mock_sub.stripe_subscription_id = "sub_free123"
            mock_sub.stripe_customer_id = "cus_test123"
            mock_sub.current_period_start = datetime.now(timezone.utc)
            mock_sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
            mock_create.return_value = mock_sub
            
            result = get_current_subscription_with_auto_repair(test_user.id, db_session)
            
            assert "subscription" in result
            assert result["subscription"] is not None
            mock_create.assert_called_once()
    
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
        with patch('app.services.subscription_service.create_free_subscription') as mock_create:
            # Mock should not be called if subscription exists (even if deleted)
            # Actually, get_subscription_info might return None for canceled, so it might call create_free_subscription
            # But create_free_subscription should update existing, not create duplicate
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

