"""Unit tests for hopper backend - Database-backed architecture"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

# Add backend directory to Python path
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Import the functions we want to test
from main import (
    replace_template_placeholders,
)


class TestTemplatePlaceholders:
    """Test template placeholder replacement"""
    
    def test_replace_filename_placeholder(self):
        """Test that {filename} placeholder is replaced"""
        template = "Video: {filename}"
        filename = "test_video.mp4"
        result = replace_template_placeholders(template, filename, [])
        assert result == "Video: test_video.mp4"
    
    def test_replace_random_placeholder(self):
        """Test that {random} placeholder is replaced with word from wordbank"""
        template = "Title with {random} word"
        filename = "test.mp4"
        wordbank = ["awesome", "cool", "great"]
        result = replace_template_placeholders(template, filename, wordbank)
        assert "{random}" not in result
        assert result.startswith("Title with ")
        assert result.endswith(" word")
        # Check that one of the words from wordbank was used
        assert any(word in result for word in wordbank)
    
    def test_replace_multiple_random_placeholders(self):
        """Test that multiple {random} placeholders are replaced independently"""
        template = "{random} video {random}"
        filename = "test.mp4"
        wordbank = ["cool", "awesome"]
        result = replace_template_placeholders(template, filename, wordbank)
        assert result.count("{random}") == 0
        assert result.count("video") == 1
        # Each {random} should be replaced
        words_used = [word for word in wordbank if word in result]
        assert len(words_used) >= 1  # At least one word from wordbank used
    
    def test_replace_random_with_empty_wordbank(self):
        """Test that {random} is removed when wordbank is empty"""
        template = "Title with {random} word"
        filename = "test.mp4"
        result = replace_template_placeholders(template, filename, [])
        assert result == "Title with  word"
    
    def test_replace_both_placeholders(self):
        """Test replacing both {filename} and {random}"""
        template = "{filename} - {random} video"
        filename = "my_video.mp4"
        wordbank = ["awesome"]
        result = replace_template_placeholders(template, filename, wordbank)
        assert "my_video.mp4" in result
        assert "awesome" in result
        assert "{filename}" not in result
        assert "{random}" not in result
    
    def test_filename_without_extension(self):
        """Test filename placeholder works correctly"""
        template = "Upload: {filename}"
        filename = "video_file"
        result = replace_template_placeholders(template, filename, [])
        assert result == "Upload: video_file"
    
    def test_complex_template(self):
        """Test complex template with multiple placeholders"""
        template = "{filename} | {random} content | {random} style"
        filename = "my_video.mp4"
        wordbank = ["epic", "amazing", "cool"]
        result = replace_template_placeholders(template, filename, wordbank)
        assert "my_video.mp4" in result
        assert "{filename}" not in result
        assert "{random}" not in result


class TestAuthenticationDependencies:
    """Test authentication dependency functions"""
    
    @patch('main.redis_client')
    def test_require_auth_with_valid_session(self, mock_redis):
        """Test require_auth with valid session returns user_id"""
        from main import require_auth
        from fastapi import Request
        
        # Mock request with session cookie
        mock_request = Mock(spec=Request)
        mock_request.cookies.get.return_value = "valid_session_id"
        
        # Mock redis returning user_id
        mock_redis.get_session.return_value = 123
        
        result = require_auth(mock_request)
        assert result == 123
        mock_redis.get_session.assert_called_once_with("valid_session_id")
    
    @patch('main.redis_client')
    def test_require_auth_without_session_cookie_raises_401(self, mock_redis):
        """Test require_auth without session cookie raises 401"""
        from main import require_auth
        from fastapi import Request, HTTPException
        
        # Mock request without session cookie
        mock_request = Mock(spec=Request)
        mock_request.cookies.get.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            require_auth(mock_request)
        
        assert exc_info.value.status_code == 401
        assert "Not authenticated" in str(exc_info.value.detail)
    
    @patch('main.redis_client')
    def test_require_auth_with_expired_session_raises_401(self, mock_redis):
        """Test require_auth with expired session raises 401"""
        from main import require_auth
        from fastapi import Request, HTTPException
        
        # Mock request with session cookie
        mock_request = Mock(spec=Request)
        mock_request.cookies.get.return_value = "expired_session_id"
        
        # Mock redis returning None (expired session)
        mock_redis.get_session.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            require_auth(mock_request)
        
        assert exc_info.value.status_code == 401
        assert "Session expired" in str(exc_info.value.detail)


class TestRateLimiting:
    """Test rate limiting functions"""
    
    def test_get_client_identifier_with_session_id(self):
        """Test client identifier generation with session_id"""
        from main import get_client_identifier
        from fastapi import Request
        
        mock_request = Mock(spec=Request)
        result = get_client_identifier(mock_request, "test_session_123")
        assert result == "session:test_session_123"
    
    def test_get_client_identifier_with_ip_fallback(self):
        """Test client identifier generation with IP fallback"""
        from main import get_client_identifier
        from fastapi import Request
        
        mock_request = Mock(spec=Request)
        mock_request.headers.get.return_value = ""
        mock_request.client.host = "192.168.1.1"
        
        result = get_client_identifier(mock_request, None)
        assert result == "ip:192.168.1.1"


class TestHelperFunctions:
    """Test various helper functions"""
    
    def test_validate_origin_referer_basic(self):
        """Test origin/referer validation (basic test)"""
        from main import validate_origin_referer
        from fastapi import Request
        
        mock_request = Mock(spec=Request)
        mock_request.headers.get.side_effect = lambda key: {
            "Origin": "http://localhost:3000"
        }.get(key)
        
        # This will depend on ALLOWED_ORIGINS in main.py
        # Just test that function runs without error
        result = validate_origin_referer(mock_request)
        assert isinstance(result, bool)


# Integration test helpers (these would need actual DB setup)
class TestDatabaseIntegration:
    """Integration tests requiring database setup"""
    
    @pytest.mark.skip(reason="Requires database setup")
    def test_user_registration_flow(self):
        """Test complete user registration flow"""
        # This would test:
        # 1. POST /api/auth/register
        # 2. User created in database
        # 3. Password hashed correctly
        pass
    
    @pytest.mark.skip(reason="Requires database setup")
    def test_user_login_flow(self):
        """Test complete user login flow"""
        # This would test:
        # 1. POST /api/auth/login
        # 2. Session created in Redis
        # 3. Cookie set correctly
        pass
    
    @pytest.mark.skip(reason="Requires database setup")
    def test_oauth_token_encryption(self):
        """Test OAuth token encryption/decryption"""
        # This would test:
        # 1. Token saved to database encrypted
        # 2. Token retrieved and decrypted correctly
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
