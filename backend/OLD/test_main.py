"""Unit tests for hopper backend"""
import pytest
import sys
import os
import tempfile
from pathlib import Path
from datetime import timedelta
from unittest.mock import Mock, patch, MagicMock

# Add backend directory to Python path
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.utils.templates import replace_template_placeholders
from app.services.video_service import cleanup_video_file
from app.core.security import get_client_identifier


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
    
    @patch('app.db.redis.get_session')
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
    """Test video file cleanup"""
    
    def test_cleanup_existing_file(self):
        """Test cleanup removes existing file"""
        from app.models.video import Video
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.mp4') as tmp:
            tmp.write("test")
            temp_path = tmp.name
        
        try:
            mock_video = Mock(spec=Video)
            mock_video.path = temp_path
            mock_video.filename = "test.mp4"
            
            assert os.path.exists(temp_path)
            result = cleanup_video_file(mock_video)
            
            assert result is True
            assert not os.path.exists(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_cleanup_nonexistent_file(self):
        """Test cleanup succeeds when file already deleted"""
        from app.models.video import Video
        
        mock_video = Mock(spec=Video)
        mock_video.path = "/tmp/nonexistent.mp4"
        mock_video.filename = "nonexistent.mp4"
        
        result = cleanup_video_file(mock_video)
        assert result is True
    
    def test_cleanup_permission_error(self):
        """Test cleanup handles permission errors"""
        from app.models.video import Video
        
        mock_video = Mock(spec=Video)
        mock_video.path = "/protected/file.mp4"
        mock_video.filename = "file.mp4"
        
        with patch('app.services.video_service.Path') as mock_path:
            mock_path_instance = MagicMock()
            # ROOT CAUSE FIX: Ensure resolve() returns the same mock instance
            mock_path_instance.resolve.return_value = mock_path_instance
            mock_path.return_value = mock_path_instance
            mock_path_instance.exists.return_value = True
            mock_path_instance.unlink.side_effect = PermissionError()
            
            result = cleanup_video_file(mock_video)
            assert result is False


class TestStripeFunctionality:
    """Test basic Stripe functionality"""
    
    @patch('stripe_helpers.stripe')
    @patch('stripe_helpers.STRIPE_SECRET_KEY', 'sk_test_123')
    def test_create_stripe_customer_success(self, mock_stripe):
        """Test creating a Stripe customer successfully"""
        from stripe_helpers import create_stripe_customer
        from app.models.user import User
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
        
        result = create_stripe_customer("test@hopper-unit-test.com", 1, mock_db)
        
        assert result == 'cus_test123'
        assert mock_user.stripe_customer_id == 'cus_test123'
        mock_db.commit.assert_called_once()
        mock_stripe.Customer.create.assert_called_once()
    
    @patch('stripe_helpers.stripe')
    @patch('stripe_helpers.STRIPE_SECRET_KEY', None)
    def test_create_stripe_customer_no_key(self, mock_stripe):
        """Test creating customer fails when Stripe key is not set"""
        from stripe_helpers import create_stripe_customer
        from sqlalchemy.orm import Session
        
        mock_db = Mock(spec=Session)
        result = create_stripe_customer("test@hopper-unit-test.com", 1, mock_db)
        
        assert result is None
        mock_stripe.Customer.create.assert_not_called()
    
    @patch('stripe_helpers.stripe')
    @patch('stripe_helpers.STRIPE_SECRET_KEY', 'sk_test_123')
    def test_create_stripe_customer_existing(self, mock_stripe):
        """Test creating customer returns existing customer ID"""
        from stripe_helpers import create_stripe_customer
        from app.models.user import User
        from sqlalchemy.orm import Session
        
        # Mock existing customer
        mock_customer = Mock()
        mock_stripe.Customer.retrieve.return_value = mock_customer
        
        # Mock database session with existing customer
        mock_db = Mock(spec=Session)
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.stripe_customer_id = 'cus_existing123'
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        
        result = create_stripe_customer("test@hopper-unit-test.com", 1, mock_db)
        
        assert result == 'cus_existing123'
        mock_stripe.Customer.create.assert_not_called()
        mock_stripe.Customer.retrieve.assert_called_once_with('cus_existing123')
    
    @patch('token_helpers.reset_tokens_for_subscription')
    @patch('stripe_helpers.ensure_stripe_customer_exists')
    @patch('stripe_helpers.update_subscription_from_stripe')
    @patch('stripe_helpers.stripe')
    @patch('stripe_helpers.STRIPE_SECRET_KEY', 'sk_test_123')
    @patch('stripe_config.get_plan_price_id')
    @patch('stripe_config.get_plans')
    def test_create_free_subscription(self, mock_get_plans, mock_get_price, mock_stripe, mock_update_sub, mock_ensure_customer, mock_reset_tokens):
        """Test creating a free subscription"""
        from stripe_helpers import create_free_subscription
        from app.models.user import User
        from app.models.subscription import Subscription
        from sqlalchemy.orm import Session
        from datetime import datetime, timezone
        
        # Mock plans data
        mock_plans = {
            'free': {
                'name': 'Free',
                'monthly_tokens': 10,
                'stripe_price_id': 'price_free',
                'stripe_product_id': 'prod_free',
                'stripe_overage_price_id': None,
            }
        }
        mock_get_plans.return_value = mock_plans
        
        # Mock price ID lookup
        mock_get_price.return_value = 'price_free'
        
        # Mock Stripe subscription
        mock_subscription = Mock()
        mock_subscription.id = 'sub_test123'
        mock_subscription.customer = 'cus_test123'
        mock_subscription.status = 'active'
        mock_subscription.current_period_start = int(datetime.now(timezone.utc).timestamp())
        mock_subscription.current_period_end = int((datetime.now(timezone.utc).timestamp() + 2592000))
        mock_subscription.items.data = [Mock()]
        mock_subscription.items.data[0].price.id = 'price_free'
        mock_stripe.Subscription.create.return_value = mock_subscription
        
        # Mock customer creation
        mock_ensure_customer.return_value = 'cus_test123'
        
        # Mock database
        mock_db = Mock(spec=Session)
        mock_user = Mock(spec=User)
        mock_user.id = 1
        mock_user.stripe_customer_id = 'cus_test123'
        
        # Mock subscription creation in DB
        mock_new_sub = Mock(spec=Subscription)
        mock_new_sub.plan_type = 'free'
        mock_new_sub.current_period_start = datetime.fromtimestamp(mock_subscription.current_period_start, tz=timezone.utc)
        mock_new_sub.current_period_end = datetime.fromtimestamp(mock_subscription.current_period_end, tz=timezone.utc)
        mock_update_sub.return_value = mock_new_sub
        
        # Mock query chain: first call returns None (no existing subscription), second returns user
        mock_db.query.return_value.filter.return_value.first.side_effect = [None, mock_user]
        
        mock_reset_tokens.return_value = True
        result = create_free_subscription(1, mock_db)
        
        assert result is not None
        mock_stripe.Subscription.create.assert_called_once()
        mock_reset_tokens.assert_called_once()
        mock_ensure_customer.assert_called_once_with(1, mock_db)
    
    def test_check_if_tokens_already_added_for_period(self):
        """Test duplicate token detection for subscription period"""
        from token_helpers import _check_if_tokens_already_added_for_period
        from app.models.token_transaction import TokenTransaction
        from sqlalchemy.orm import Session
        from datetime import datetime, timezone, timedelta
        
        # Mock database with existing transaction
        mock_db = Mock(spec=Session)
        mock_transaction = Mock(spec=TokenTransaction)
        mock_transaction.user_id = 1
        mock_transaction.transaction_type = 'reset'
        period_start = datetime.now(timezone.utc)
        period_end = datetime.now(timezone.utc).replace(day=1) + timedelta(days=32)
        mock_transaction.transaction_metadata = {
            'subscription_id': 'sub_test123',
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'is_renewal': False
        }
        
        # Mock query to return existing transaction
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = [mock_transaction]
        mock_db.query.return_value = mock_query
        
        result = _check_if_tokens_already_added_for_period(
            1, 'sub_test123', period_start, period_end, mock_db
        )
        
        # Should detect duplicate (periods match within tolerance)
        assert result is True
    
    def test_check_if_tokens_not_added_for_period(self):
        """Test duplicate detection returns False when no tokens added"""
        from token_helpers import _check_if_tokens_already_added_for_period
        from sqlalchemy.orm import Session
        from datetime import datetime, timezone, timedelta
        
        # Mock database with no matching transaction
        mock_db = Mock(spec=Session)
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        period_start = datetime.now(timezone.utc)
        period_end = datetime.now(timezone.utc).replace(day=1) + timedelta(days=32)
        
        result = _check_if_tokens_already_added_for_period(
            1, 'sub_test123', period_start, period_end, mock_db
        )
        
        assert result is False
    
    @patch('stripe_config.get_plans')
    def test_get_plan_monthly_tokens(self, mock_get_plans):
        """Test getting monthly tokens for a plan"""
        from stripe_config import get_plan_monthly_tokens
        
        # Mock plans data matching JSON structure
        mock_plans = {
            'free': {
                'name': 'Free',
                'monthly_tokens': 10,
                'stripe_price_id': None,
                'stripe_product_id': None,
                'stripe_overage_price_id': None,
            },
            'starter': {
                'name': 'Starter',
                'monthly_tokens': 100,
                'stripe_price_id': 'price_test_starter',
                'stripe_product_id': 'prod_test_starter',
                'stripe_overage_price_id': 'price_test_starter_overage',
            },
            'creator': {
                'name': 'Creator',
                'monthly_tokens': 500,
                'stripe_price_id': 'price_test_creator',
                'stripe_product_id': 'prod_test_creator',
                'stripe_overage_price_id': 'price_test_creator_overage',
            },
            'unlimited': {
                'name': 'Unlimited',
                'monthly_tokens': -1,
                'stripe_price_id': 'price_test_unlimited',
                'stripe_product_id': 'prod_test_unlimited',
                'stripe_overage_price_id': None,
                'hidden': True,
            }
        }
        mock_get_plans.return_value = mock_plans
        
        # Test that function exists and returns a value
        result = get_plan_monthly_tokens('free')
        assert isinstance(result, int)
        assert result == 10
        
        # Test with different plan types
        test_cases = [
            ('free', 10),
            ('starter', 100),
            ('creator', 500),
            ('unlimited', -1),  # Unlimited plan
        ]
        
        for plan, expected_tokens in test_cases:
            tokens = get_plan_monthly_tokens(plan)
            assert isinstance(tokens, int)
            assert tokens == expected_tokens, f"Plan {plan} should have {expected_tokens} tokens, got {tokens}"
    
    @patch('builtins.open', create=True)
    def test_load_plans_from_json(self, mock_open):
        """Test loading plans from JSON file"""
        from stripe_config import load_plans
        
        # Mock JSON file content
        mock_json_data = {
            'free': {
                'name': 'Free',
                'monthly_tokens': 10,
                'stripe_price_id': 'price_test_free',
                'stripe_product_id': 'prod_test_free',
                'stripe_overage_price_id': None,
            },
            'starter': {
                'name': 'Starter',
                'monthly_tokens': 100,
                'stripe_price_id': 'price_test_starter',
                'stripe_product_id': 'prod_test_starter',
                'stripe_overage_price_id': 'price_test_starter_overage',
            }
        }
        
        # Mock file opening
        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.__exit__.return_value = None
        mock_open.return_value = mock_file
        
        # Mock json.load
        with patch('stripe_config.json.load', return_value=mock_json_data):
            # Clear cache
            import stripe_config
            stripe_config._PLANS_CACHE = None
            
            result = load_plans('test')
            
            assert result == mock_json_data
            assert 'free' in result
            assert 'starter' in result
            assert result['free']['monthly_tokens'] == 10
            assert result['starter']['monthly_tokens'] == 100
    
    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_load_plans_fallback_when_file_missing(self, mock_open):
        """Test that fallback plans are used when JSON file is missing"""
        from stripe_config import load_plans
        
        # Clear cache
        import stripe_config
        stripe_config._PLANS_CACHE = None
        
        result = load_plans('test')
        
        # Should return fallback plans (only free plan)
        assert 'free' in result
        assert result['free']['monthly_tokens'] == 10
        # Fallback should not have other plans
        assert 'starter' not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])