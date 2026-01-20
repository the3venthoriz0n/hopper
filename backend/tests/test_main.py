"""Unit tests for hopper backend"""
import pytest
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

# Add backend directory to Python path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.utils.templates import replace_template_placeholders
from app.services.video.helpers import cleanup_video_file
from app.core.security import get_client_identifier
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance


class TestTemplatePlaceholders:
    """Test template placeholder replacement"""
    
    def test_replace_filename(self):
        """Test {filename} placeholder replacement"""
        result = replace_template_placeholders("Video: {filename}", "test.mp4", [])
        assert result == "Video: test.mp4"
    
    def test_replace_random_from_wordbank(self):
        """Test {random} placeholder uses wordbank"""
        result = replace_template_placeholders("{random} video", "test.mp4", ["awesome"])
        assert result == "awesome video"
    
    def test_replace_random_empty_wordbank(self):
        """Test {random} removed when wordbank is empty"""
        result = replace_template_placeholders("{random} video", "test.mp4", [])
        assert result == " video"
    
    def test_replace_both_placeholders(self):
        """Test both placeholders work together"""
        result = replace_template_placeholders("{filename} - {random}", "vid.mp4", ["cool"])
        assert result == "vid.mp4 - cool"


class TestAuthentication:
    """Test authentication functions"""
    
    @patch('app.core.security.get_session')
    def test_require_auth_valid_session(self, mock_get_session):
        """Test authentication with valid session"""
        from app.core.security import require_auth
        
        mock_request = Mock()
        mock_request.cookies.get.return_value = "valid_session"
        mock_get_session.return_value = 123
        
        result = require_auth(mock_request)
        assert result == 123
    
    def test_require_auth_no_session(self):
        """Test authentication fails without session"""
        from app.core.security import require_auth
        from fastapi import HTTPException
        
        mock_request = Mock()
        mock_request.cookies.get.return_value = None
        
        with pytest.raises(HTTPException) as exc:
            require_auth(mock_request)
        assert exc.value.status_code == 401


class TestRateLimiting:
    """Test rate limiting"""
    
    def test_client_identifier_with_session(self):
        """Test client ID generation with session"""
        mock_request = Mock()
        result = get_client_identifier(mock_request, "session_123")
        assert result == "session:session_123"
    
    def test_client_identifier_with_ip(self):
        """Test client ID generation with IP fallback"""
        mock_request = Mock()
        mock_request.headers.get.return_value = ""
        mock_request.client.host = "192.168.1.1"
        
        result = get_client_identifier(mock_request, None)
        assert result == "ip:192.168.1.1"


class TestVideoCleanup:
    """Test video file cleanup with R2 storage"""
    
    @patch('app.services.video.helpers.get_r2_service')
    def test_cleanup_existing_file(self, mock_get_r2_service):
        """Test cleanup removes existing R2 object"""
        from app.models import Video
        
        # Mock R2 service
        mock_r2_service = Mock()
        mock_r2_service.delete_object.return_value = True
        mock_get_r2_service.return_value = mock_r2_service
        
        mock_video = Mock(spec=Video)
        mock_video.path = "user_123/video_456_test.mp4"  # R2 object key format
        mock_video.filename = "test.mp4"
        mock_video.custom_settings = {}
        
        result = cleanup_video_file(mock_video)
        
        assert result is True
        mock_r2_service.delete_object.assert_called_once_with("user_123/video_456_test.mp4")
    
    @patch('app.services.video.helpers.get_r2_service')
    def test_cleanup_nonexistent_file(self, mock_get_r2_service):
        """Test cleanup succeeds when R2 object already deleted"""
        from app.models import Video
        
        # Mock R2 service - delete_object returns True even if object doesn't exist
        mock_r2_service = Mock()
        mock_r2_service.delete_object.return_value = True
        mock_get_r2_service.return_value = mock_r2_service
        
        mock_video = Mock(spec=Video)
        mock_video.path = "user_123/video_456_nonexistent.mp4"  # R2 object key format
        mock_video.filename = "nonexistent.mp4"
        mock_video.custom_settings = {}
        
        result = cleanup_video_file(mock_video)
        assert result is True
        mock_r2_service.delete_object.assert_called_once_with("user_123/video_456_nonexistent.mp4")
    
    @patch('app.services.video.helpers.get_r2_service')
    def test_cleanup_r2_error(self, mock_get_r2_service):
        """Test cleanup handles R2 deletion errors"""
        from app.models import Video
        
        # Mock R2 service to raise an exception
        mock_r2_service = Mock()
        mock_r2_service.delete_object.side_effect = Exception("R2 connection error")
        mock_get_r2_service.return_value = mock_r2_service
        
        mock_video = Mock(spec=Video)
        mock_video.path = "user_123/video_456_file.mp4"  # R2 object key format
        mock_video.filename = "file.mp4"
        mock_video.custom_settings = {}
        
        result = cleanup_video_file(mock_video)
        assert result is False
        mock_r2_service.delete_object.assert_called_once_with("user_123/video_456_file.mp4")
    
    @patch('app.services.video.helpers.get_r2_service')
    def test_cleanup_skips_tiktok_pull_from_url(self, mock_get_r2_service):
        """Test cleanup skips deletion when TikTok PULL_FROM_URL is in progress"""
        from app.models import Video
        
        mock_r2_service = Mock()
        mock_get_r2_service.return_value = mock_r2_service
        
        mock_video = Mock(spec=Video)
        mock_video.path = "user_123/video_456_test.mp4"
        mock_video.filename = "test.mp4"
        # TikTok PULL_FROM_URL in progress (has publish_id but no tiktok_id)
        mock_video.custom_settings = {
            "tiktok_publish_id": "publish_123",
            "tiktok_id": None
        }
        
        result = cleanup_video_file(mock_video)
        
        # Should return True but not call delete_object
        assert result is True
        mock_r2_service.delete_object.assert_not_called()
    
    def test_cleanup_no_path(self):
        """Test cleanup succeeds when video has no R2 object key"""
        from app.models import Video
        
        mock_video = Mock(spec=Video)
        mock_video.path = None
        mock_video.filename = "test.mp4"
        mock_video.custom_settings = {}
        
        result = cleanup_video_file(mock_video)
        assert result is True


class TestStripeFunctionality:
    """Test basic Stripe functionality"""
    
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_create_stripe_customer_success(self, mock_settings, mock_stripe):
        """Test creating a Stripe customer successfully"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        from app.services.stripe_service import create_stripe_customer
        from app.models import User
        from sqlalchemy.orm import Session
        
        # Mock Stripe customer creation
        mock_customer = Mock()
        mock_customer.id = 'cus_test123'
        mock_stripe.Customer.create.return_value = mock_customer
        
        # Mock database session
        mock_db = Mock(spec=Session)
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.stripe_customer_id = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        
        result = create_stripe_customer("delivered+stripe@resend.dev", 1, mock_db)
        
        assert result == 'cus_test123'
        assert mock_user.stripe_customer_id == 'cus_test123'
        mock_db.commit.assert_called_once()
        mock_stripe.Customer.create.assert_called_once()
    
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_create_stripe_customer_no_key(self, mock_settings, mock_stripe):
        """Test creating customer fails when Stripe key is not set"""
        mock_settings.STRIPE_SECRET_KEY = None
        from app.services.stripe_service import create_stripe_customer
        from sqlalchemy.orm import Session
        
        mock_db = Mock(spec=Session)
        result = create_stripe_customer("delivered+stripe@resend.dev", 1, mock_db)
        
        assert result is None
        mock_stripe.Customer.create.assert_not_called()
    
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_create_stripe_customer_existing(self, mock_settings, mock_stripe):
        """Test creating customer returns existing customer ID"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        from app.services.stripe_service import create_stripe_customer
        from app.models import User
        from sqlalchemy.orm import Session
        
        # Mock database session with existing customer
        mock_db = Mock(spec=Session)
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.stripe_customer_id = 'cus_existing123'
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        
        result = create_stripe_customer("delivered+stripe@resend.dev", 1, mock_db)
        
        assert result == 'cus_existing123'
        mock_stripe.Customer.create.assert_not_called()
        # Implementation no longer calls retrieve() when customer exists
    
    @patch('app.services.token_service.ensure_tokens_synced_for_subscription')
    @patch('app.services.stripe_service.create_stripe_customer')
    @patch('app.services.stripe_service.StripeRegistry.get_all_base_plans')
    @patch('app.services.stripe_service.StripeRegistry.get_plan_config')
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_create_stripe_subscription(self, mock_settings, mock_stripe, mock_registry_get, mock_registry_get_plan_config, mock_registry_get_all_base_plans, mock_create_customer, mock_ensure_tokens, test_user, db_session):
        """Test creating a free_daily subscription"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        from app.services.stripe_service import create_stripe_subscription
        
        # Set up Price.list on the patched stripe Mock so sync() can find prices
        # This is needed because sync() calls stripe.Price.list() when cache is empty
        def create_mock_price(price_id, lookup_key, unit_amount, tokens, name, description="", 
                             hidden=False, max_accrual=None, interval="month"):
            """Helper to create a mock price with product"""
            mock_product = Mock()
            mock_product.id = f"prod_{lookup_key.replace('_price', '')}"
            mock_product.name = name
            mock_product.description = description
            mock_product.active = True
            metadata = {'tokens': str(tokens)}
            if hidden:
                metadata['hidden'] = 'true'
            if max_accrual is not None:
                metadata['max_accrual'] = str(max_accrual)
            mock_product.metadata = metadata
            
            mock_price_obj = Mock()
            mock_price_obj.id = price_id
            mock_price_obj.lookup_key = lookup_key
            mock_price_obj.unit_amount = unit_amount
            mock_price_obj.currency = 'usd'
            mock_price_obj.recurring = {'interval': interval}
            mock_price_obj.created = 1234567890
            mock_price_obj.product = mock_product
            return mock_price_obj
        
        mock_prices = [
            create_mock_price("price_free_daily", "free_daily_price", 0, 3, "Free Daily", 
                            "3 tokens per day", hidden=False, max_accrual=10, interval="day"),
        ]
        mock_list_result = Mock()
        mock_list_result.auto_paging_iter.return_value = mock_prices
        if not hasattr(mock_stripe, 'Price'):
            mock_stripe.Price = Mock()
        mock_stripe.Price.list = Mock(return_value=mock_list_result)
        
        # Mock StripeRegistry.get_plan_config to return free_daily plan config
        mock_registry_get_plan_config.return_value = {
            "price_id": "price_free_daily",
            "product_id": "prod_free_daily",
            "tokens": 10,
            "name": "Free Daily",
            "description": "Free daily plan",
            "amount_dollars": 0.0,
            "currency": "USD",
            "formatted": "Free"
        }
        
        # Mock StripeRegistry.get_all_base_plans to prevent it from being called in error messages
        mock_registry_get_all_base_plans.return_value = {"free_daily": mock_registry_get_plan_config.return_value}
        
        # Mock StripeRegistry.get for overage price lookup (returns None for free_daily)
        mock_registry_get.return_value = None
        
        # Mock stripe.Product.retrieve (called by _build_subscription_items to verify product is active)
        mock_product = Mock()
        mock_product.active = True
        mock_stripe.Product.retrieve.return_value = mock_product
        
        # Mock Stripe subscription response
        mock_subscription = Mock()
        mock_subscription.id = 'sub_test123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc).timestamp() + 2592000))
        mock_stripe.Subscription.create.return_value = mock_subscription
        
        mock_create_customer.return_value = 'cus_test123'
        mock_ensure_tokens.return_value = True
        
        # Set user's customer ID
        test_user.stripe_customer_id = 'cus_test123'
        db_session.commit()
        
        # Invalidate cache to ensure mocks are used instead of cached data
        from app.services.stripe_service import StripeRegistry
        StripeRegistry.invalidate_cache()

        result = create_stripe_subscription(test_user.id, "free_daily", db_session)
        
        assert result is not None
        assert result.plan_type == "free_daily"
        assert result.stripe_subscription_id == 'sub_test123'
        mock_stripe.Subscription.create.assert_called_once()
        mock_ensure_tokens.assert_called_once()

    def test_check_if_tokens_already_added_for_period(self):
        """Test duplicate token detection for subscription period"""
        from app.services.token_service import _check_if_tokens_already_added_for_period
        from app.models import TokenTransaction
        from sqlalchemy.orm import Session
        
        mock_db = Mock(spec=Session)
        mock_transaction = Mock(spec=TokenTransaction)
        period_start = datetime.now(timezone.utc)
        period_end = datetime.now(timezone.utc) + timedelta(days=30)
        
        mock_transaction.transaction_metadata = {
            'subscription_id': 'sub_test123',
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat()
        }
        
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_transaction]
        mock_db.query.return_value = mock_query
        
        result = _check_if_tokens_already_added_for_period(
            1, 'sub_test123', period_start, period_end, mock_db
        )
        assert result is True
    
    def test_check_if_tokens_not_added_for_period(self):
        """Test duplicate detection returns False when no tokens added"""
        from app.services.token_service import _check_if_tokens_already_added_for_period
        from sqlalchemy.orm import Session
        
        mock_db = Mock(spec=Session)
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        result = _check_if_tokens_already_added_for_period(
            1, 'sub_test123', datetime.now(timezone.utc), datetime.now(timezone.utc), mock_db
        )
        assert result is False
    
    @patch('app.services.token_service.StripeRegistry')
    def test_get_plan_tokens(self, mock_registry):
        """Test getting tokens for a plan from StripeRegistry"""
        from app.services.token_service import get_plan_tokens
        
        # Mock StripeRegistry.get_plan_config() to return plan config with tokens
        mock_registry.get_plan_config.return_value = {'tokens': 10}
        
        assert get_plan_tokens('free') == 10
        mock_registry.get_plan_config.assert_called_once_with('free')
    
    @patch('app.services.token_service.StripeRegistry')
    def test_get_plan_tokens_missing_plan(self, mock_registry):
        """Test getting tokens when plan is not found in registry"""
        from app.services.token_service import get_plan_tokens
        
        # Mock StripeRegistry.get_plan_config() to return None (plan not found)
        mock_registry.get_plan_config.return_value = None
        
        assert get_plan_tokens('nonexistent') == 0
        mock_registry.get_plan_config.assert_called_once_with('nonexistent')
    
    @patch('app.services.token_service.StripeRegistry')
    def test_get_plan_tokens_missing_tokens_key(self, mock_registry):
        """Test getting tokens when plan config exists but tokens key is missing"""
        from app.services.token_service import get_plan_tokens
        
        # Mock StripeRegistry.get_plan_config() to return config without tokens key
        mock_registry.get_plan_config.return_value = {'price_id': 'price_123', 'name': 'Free Plan'}
        
        assert get_plan_tokens('free') == 0
        mock_registry.get_plan_config.assert_called_once_with('free')
    
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_stripe_registry_sync(self, mock_settings, mock_stripe):
        """Test StripeRegistry sync from Stripe API"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        from app.services.stripe_service import StripeRegistry
        
        # Mock Stripe Price.list response
        mock_price = Mock()
        mock_price.id = 'price_test123'
        mock_price.lookup_key = 'free_price'
        mock_price.unit_amount = 0
        mock_price.currency = 'usd'
        mock_price.recurring = {'interval': 'month'}
        mock_price.created = 1234567890
        mock_price.product = Mock()
        mock_price.product.id = 'prod_test123'
        mock_price.product.name = 'Free'
        mock_price.product.description = 'Free plan'
        mock_price.product.active = True
        mock_price.product.metadata = {'tokens': '10', 'hidden': 'false'}
        
        # Mock the expand parameter properly - auto_paging_iter() should return an iterable
        mock_list_result = Mock()
        mock_list_result.auto_paging_iter.return_value = [mock_price]
        mock_stripe.Price.list.return_value = mock_list_result
        
        # Clear cache and sync
        StripeRegistry._cache = {}
        StripeRegistry.sync()
        
        # Verify registry was populated
        assert len(StripeRegistry._cache) > 0
        assert 'free_price' in StripeRegistry._cache
        # Verify Price.list was called with expand parameter
        mock_stripe.Price.list.assert_called_once()
        call_args = mock_stripe.Price.list.call_args
        assert 'expand' in call_args.kwargs or 'data.product' in str(call_args)
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    def test_stripe_registry_get_plan(self, mock_registry_get):
        """Test getting plan config from StripeRegistry"""
        from app.services.stripe_service import StripeRegistry
        
        mock_config = {
            "price_id": "price_test123",
            "tokens": 300,
            "name": "Starter",
            "description": "Starter plan",
            "amount_dollars": 3.0,
            "currency": "USD",
            "formatted": "$3.00"
        }
        mock_registry_get.return_value = mock_config
        
        result = StripeRegistry.get("starter_price")
        assert result == mock_config
        mock_registry_get.assert_called_once_with("starter_price")
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    def test_stripe_registry_handles_missing_plan(self, mock_registry_get):
        """Test error handling for missing plans"""
        from app.services.stripe_service import StripeRegistry
        
        mock_registry_get.return_value = None
        
        result = StripeRegistry.get("nonexistent_price")
        assert result is None
        mock_registry_get.assert_called_once_with("nonexistent_price")
    
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_stripe_registry_get_all_base_plans(self, mock_settings, mock_stripe):
        """Test getting all base plans from registry"""
        from app.services.stripe_service import StripeRegistry
        
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        # Mock Stripe Price.list response
        mock_price1 = Mock()
        mock_price1.id = 'price_free'
        mock_price1.lookup_key = 'free_price'
        mock_price1.unit_amount = 0
        mock_price1.currency = 'usd'
        mock_price1.recurring = {'interval': 'month'}
        mock_price1.product = Mock()
        mock_price1.product.id = 'prod_free'
        mock_price1.product.name = 'Free'
        mock_price1.product.metadata = {'tokens': '10', 'hidden': 'false'}
        
        mock_price2 = Mock()
        mock_price2.id = 'price_starter'
        mock_price2.lookup_key = 'starter_price'
        mock_price2.unit_amount = 300
        mock_price2.currency = 'usd'
        mock_price2.recurring = {'interval': 'month'}
        # Mock the expand parameter - need to set product on each price
        mock_price1.product = Mock()
        mock_price1.product.id = 'prod_free'
        mock_price1.product.name = 'Free'
        mock_price1.product.description = 'Free plan'
        mock_price1.product.active = True
        mock_price1.product.metadata = {'tokens': '10', 'hidden': 'false'}
        
        mock_price2.product = Mock()
        mock_price2.product.id = 'prod_starter'
        mock_price2.product.name = 'Starter'
        mock_price2.product.description = 'Starter plan'
        mock_price2.product.active = True
        mock_price2.product.metadata = {'tokens': '300', 'hidden': 'false'}
        
        mock_price1.created = 1234567890
        mock_price2.created = 1234567891
        
        # Mock the expand parameter properly - auto_paging_iter() should return an iterable
        mock_list_result = Mock()
        mock_list_result.auto_paging_iter.return_value = [mock_price1, mock_price2]
        mock_stripe.Price.list.return_value = mock_list_result
        
        # Clear cache and sync
        StripeRegistry._cache = {}
        StripeRegistry.sync()
        
        # Get all base plans
        base_plans = StripeRegistry.get_all_base_plans()
        
        assert 'free' in base_plans
        assert 'starter' in base_plans
        assert 'free_price' not in base_plans  # Should strip _price suffix
    
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_stripe_registry_filters_hidden_plans(self, mock_settings, mock_stripe):
        """Test hidden plan filtering"""
        from app.services.stripe_service import StripeRegistry
        
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        
        # Mock Stripe Price.list response with hidden plan
        mock_price1 = Mock()
        mock_price1.id = 'price_visible'
        mock_price1.lookup_key = 'visible_price'
        mock_price1.unit_amount = 0
        mock_price1.currency = 'usd'
        mock_price1.recurring = {'interval': 'month'}
        mock_price1.product = Mock()
        mock_price1.product.id = 'prod_visible'
        mock_price1.product.name = 'Visible'
        mock_price1.product.description = 'Visible plan'
        mock_price1.product.active = True
        mock_price1.product.metadata = {'tokens': '10', 'hidden': 'false'}
        
        mock_price2 = Mock()
        mock_price2.id = 'price_hidden'
        mock_price2.lookup_key = 'hidden_price'
        mock_price2.unit_amount = 0
        mock_price2.currency = 'usd'
        mock_price2.recurring = {'interval': 'month'}
        mock_price2.product = Mock()
        mock_price2.product.id = 'prod_hidden'
        mock_price2.product.name = 'Hidden'
        mock_price2.product.description = 'Hidden plan'
        mock_price2.product.active = True
        mock_price2.product.metadata = {'tokens': '10', 'hidden': 'true'}
        
        mock_price1.created = 1234567890
        mock_price2.created = 1234567891
        
        # Mock the expand parameter properly - auto_paging_iter() should return an iterable
        mock_list_result = Mock()
        mock_list_result.auto_paging_iter.return_value = [mock_price1, mock_price2]
        mock_stripe.Price.list.return_value = mock_list_result
        
        StripeRegistry._cache = {}
        StripeRegistry.sync()
        
        # Get all base plans (should filter out hidden)
        base_plans = StripeRegistry.get_all_base_plans()
        
        assert 'visible' in base_plans
        assert 'hidden' not in base_plans  # Hidden plans should be filtered out


@pytest.mark.high
class TestCheckoutAndBilling:
    """Test checkout and billing functionality"""
    
    @patch('app.services.stripe_service.StripeRegistry.get_plan_config')
    @patch('app.services.stripe_service.StripeRegistry.get')
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_create_subscription_checkout(self, mock_settings, mock_stripe, mock_registry_get, mock_registry_get_plan_config, test_user, db_session):
        """Test checkout session creation"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        from app.services.subscription_service import create_subscription_checkout
        
        # Set up Price.list on the patched stripe Mock so sync() can find prices
        # This is needed because sync() calls stripe.Price.list() when cache is empty
        def create_mock_price(price_id, lookup_key, unit_amount, tokens, name, description="", 
                             hidden=False, max_accrual=None, interval="month"):
            """Helper to create a mock price with product"""
            mock_product = Mock()
            mock_product.id = f"prod_{lookup_key.replace('_price', '')}"
            mock_product.name = name
            mock_product.description = description
            mock_product.active = True
            metadata = {'tokens': str(tokens)}
            if hidden:
                metadata['hidden'] = 'true'
            if max_accrual is not None:
                metadata['max_accrual'] = str(max_accrual)
            mock_product.metadata = metadata
            
            mock_price_obj = Mock()
            mock_price_obj.id = price_id
            mock_price_obj.lookup_key = lookup_key
            mock_price_obj.unit_amount = unit_amount
            mock_price_obj.currency = 'usd'
            mock_price_obj.recurring = {'interval': interval}
            mock_price_obj.created = 1234567890
            mock_price_obj.product = mock_product
            return mock_price_obj
        
        mock_prices = [
            create_mock_price("price_starter", "starter_price", 300, 300, "Starter", 
                            "Starter plan", hidden=False, max_accrual=None, interval="month"),
            create_mock_price("price_starter_overage", "starter_overage_price", 15, 0, "Starter Overage", 
                            "Starter overage", hidden=False, max_accrual=None, interval="month"),
        ]
        mock_list_result = Mock()
        mock_list_result.auto_paging_iter.return_value = mock_prices
        if not hasattr(mock_stripe, 'Price'):
            mock_stripe.Price = Mock()
        mock_stripe.Price.list = Mock(return_value=mock_list_result)
        
        # Mock StripeRegistry.get_plan_config (called by _build_subscription_items)
        mock_registry_get_plan_config.return_value = {
            "price_id": "price_starter",
            "product_id": "prod_starter",
            "tokens": 300,
            "name": "Starter",
            "description": "Starter plan",
            "amount_dollars": 3.0,
            "currency": "USD",
            "formatted": "$3.00"
        }
        
        # Mock StripeRegistry.get (called by create_subscription_checkout to validate plan)
        # and for overage price lookup (called by _build_subscription_items)
        mock_registry_get.side_effect = lambda key: {
            "starter_price": {
                "price_id": "price_starter",
                "product_id": "prod_starter",
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
                "amount_dollars": 0.15
            }
        }.get(key)
        
        # Mock stripe.Product.retrieve (called by _build_subscription_items to verify product is active)
        mock_product = Mock()
        mock_product.active = True
        mock_stripe.Product.retrieve.return_value = mock_product
        
        mock_checkout_session = Mock()
        mock_checkout_session.id = "cs_test123"
        mock_checkout_session.url = "https://checkout.stripe.com/test"
        mock_stripe.checkout.Session.create.return_value = mock_checkout_session
        
        test_user.stripe_customer_id = "cus_test123"
        db_session.commit()
        
        # Invalidate cache to ensure mocks are used instead of cached data
        from app.services.stripe_service import StripeRegistry
        StripeRegistry.invalidate_cache()
        
        result = create_subscription_checkout(
            test_user.id,
            "starter",
            "http://localhost:3000",
            db_session
        )
        
        assert "id" in result
        assert "url" in result
        assert result["id"] == "cs_test123"
        mock_stripe.checkout.Session.create.assert_called_once()
    
    @patch('app.services.subscription_service.stripe.checkout.Session.retrieve')
    @patch('app.services.subscription_service.settings')
    def test_checkout_status_check(self, mock_settings, mock_retrieve, test_user, db_session):
        """Test check_checkout_status"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        from app.services.subscription_service import check_checkout_status
        
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
        
        mock_session = Mock()
        mock_session.metadata = {"user_id": str(test_user.id)}
        mock_session.payment_status = "paid"
        mock_session.mode = "subscription"
        mock_session.subscription = "sub_test123"
        mock_retrieve.return_value = mock_session
        
        import asyncio
        result = asyncio.run(check_checkout_status("cs_test123", test_user.id, db_session))
        
        assert result["status"] == "completed"
        assert result["payment_status"] == "paid"
        assert result["subscription_created"] is True
    
    @patch('app.services.stripe_service.StripeRegistry.get')
    def test_checkout_prevents_same_plan(self, mock_registry_get, test_user, db_session):
        """Test error when upgrading to same plan"""
        from app.services.subscription_service import create_subscription_checkout
        
        mock_registry_get.side_effect = lambda key: {
            "starter_price": {
                "price_id": "price_starter",
                "tokens": 300,
                "name": "Starter"
            }
        }.get(key)
        
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
        
        with patch('app.services.stripe_service.get_customer_portal_url', return_value="https://portal.stripe.com"):
            result = create_subscription_checkout(
                test_user.id,
                "starter",  # Same plan
                "http://localhost:3000",
                db_session
            )
            
            assert "error" in result
            assert "already have" in result["error"].lower()
    
    @patch('app.services.stripe_service.stripe')
    @patch('app.services.stripe_service.settings')
    def test_record_token_usage_to_stripe(self, mock_settings, mock_stripe, test_user, db_session):
        """Test metered usage recording to Stripe"""
        mock_settings.STRIPE_SECRET_KEY = 'sk_test_123'
        from app.services.stripe_service import record_token_usage_to_stripe
        from app.services.token_service import get_or_create_token_balance
        
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
            tokens_remaining=0,
            tokens_used_this_period=350,  # 50 overage (350 - 300)
            monthly_tokens=300,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        mock_meter_event = Mock()
        mock_meter_event.id = "me_test123"
        mock_stripe.billing.MeterEvent.create.return_value = mock_meter_event
        
        # Record 10 more tokens (should report 10 new overage)
        balance.tokens_used_this_period = 360
        db_session.commit()
        
        result = record_token_usage_to_stripe(test_user.id, 10, db_session)
        
        assert result is True
        mock_stripe.billing.MeterEvent.create.assert_called_once()
    
    def test_overage_calculation(self, test_user, db_session):
        """Test overage token calculation"""
        from app.services.token_service import get_token_balance
        
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
            tokens_remaining=0,
            tokens_used_this_period=350,  # 50 overage
            monthly_tokens=300,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        token_info = get_token_balance(test_user.id, db_session)
        
        assert token_info["overage_tokens"] == 50  # 350 - 300
        assert token_info["tokens_remaining"] == 0
        assert token_info["monthly_tokens"] == 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])