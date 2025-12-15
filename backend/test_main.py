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

from main import replace_template_placeholders, cleanup_video_file, get_client_identifier


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
    
    @patch('main.redis_client')
    def test_require_auth_valid_session(self, mock_redis):
        """Test authentication with valid session"""
        from main import require_auth
        
        mock_request = Mock()
        mock_request.cookies.get.return_value = "valid_session"
        mock_redis.get_session.return_value = 123
        
        result = require_auth(mock_request)
        assert result == 123
    
    @patch('main.redis_client')
    def test_require_auth_no_session(self, mock_redis):
        """Test authentication fails without session"""
        from main import require_auth
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
        from models import Video
        
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
        from models import Video
        
        mock_video = Mock(spec=Video)
        mock_video.path = "/tmp/nonexistent.mp4"
        mock_video.filename = "nonexistent.mp4"
        
        result = cleanup_video_file(mock_video)
        assert result is True
    
    def test_cleanup_permission_error(self):
        """Test cleanup handles permission errors"""
        from models import Video
        
        mock_video = Mock(spec=Video)
        mock_video.path = "/protected/file.mp4"
        mock_video.filename = "file.mp4"
        
        with patch('main.Path') as mock_path:
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
        from models import User
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
        
        result = create_stripe_customer("test@example.com", 1, mock_db)
        
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
        result = create_stripe_customer("test@example.com", 1, mock_db)
        
        assert result is None
        mock_stripe.Customer.create.assert_not_called()
    
    @patch('stripe_helpers.stripe')
    @patch('stripe_helpers.STRIPE_SECRET_KEY', 'sk_test_123')
    def test_create_stripe_customer_existing(self, mock_stripe):
        """Test creating customer returns existing customer ID"""
        from stripe_helpers import create_stripe_customer
        from models import User
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
        
        result = create_stripe_customer("test@example.com", 1, mock_db)
        
        assert result == 'cus_existing123'
        mock_stripe.Customer.create.assert_not_called()
        mock_stripe.Customer.retrieve.assert_called_once_with('cus_existing123')
    
    @patch('token_helpers.reset_tokens_for_subscription')
    @patch('stripe_helpers.ensure_stripe_customer_exists')
    @patch('stripe_helpers.update_subscription_from_stripe')
    @patch('stripe_helpers.stripe')
    @patch('stripe_helpers.STRIPE_SECRET_KEY', 'sk_test_123')
    @patch('stripe_config.get_plan_price_id')
    def test_create_free_subscription(self, mock_get_price, mock_stripe, mock_update_sub, mock_ensure_customer, mock_reset_tokens):
        """Test creating a free subscription"""
        from stripe_helpers import create_free_subscription
        from models import User, Subscription
        from sqlalchemy.orm import Session
        from datetime import datetime, timezone
        
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
        from models import TokenTransaction
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
    
    def test_get_plan_monthly_tokens(self):
        """Test getting monthly tokens for a plan"""
        from stripe_config import get_plan_monthly_tokens
        
        # Test that function exists and returns a value
        result = get_plan_monthly_tokens('free')
        assert isinstance(result, int)
        assert result >= 0
        
        # Test with different plan types
        for plan in ['free', 'medium', 'pro', 'unlimited']:
            tokens = get_plan_monthly_tokens(plan)
            assert isinstance(tokens, int)
            if plan == 'unlimited':
                assert tokens == -1  # Unlimited plan
            else:
                assert tokens > 0  # Regular plans have positive tokens


if __name__ == "__main__":
    pytest.main([__file__, "-v"])