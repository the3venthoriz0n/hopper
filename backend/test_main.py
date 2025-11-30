"""Simple unit tests for hopper backend"""
import pytest
import sys
from pathlib import Path

# Add backend directory to Python path
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Import the functions we want to test
from main import (
    generate_csrf_token,
    get_csrf_token,
    validate_csrf_token,
    replace_template_placeholders,
    get_default_global_settings
)


class TestCSRFToken:
    """Test CSRF token generation and validation"""
    
    def test_generate_csrf_token_returns_string(self):
        """Test that generate_csrf_token returns a string"""
        token = generate_csrf_token()
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_get_csrf_token_returns_token(self):
        """Test that get_csrf_token returns a token for a session"""
        session_id = "test_session_123"
        token = get_csrf_token(session_id)
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_get_csrf_token_same_session_returns_same_token(self):
        """Test that same session gets same token"""
        session_id = "test_session_456"
        token1 = get_csrf_token(session_id)
        token2 = get_csrf_token(session_id)
        assert token1 == token2
    
    def test_validate_csrf_token_valid(self):
        """Test that valid CSRF token validates correctly"""
        session_id = "test_session_789"
        token = get_csrf_token(session_id)
        assert validate_csrf_token(session_id, token) is True
    
    def test_validate_csrf_token_invalid(self):
        """Test that invalid CSRF token fails validation"""
        session_id = "test_session_999"
        get_csrf_token(session_id)  # Generate token for session
        invalid_token = "invalid_token_123"
        assert validate_csrf_token(session_id, invalid_token) is False


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
        """Test that multiple {random} placeholders are replaced"""
        template = "{random} video {random}"
        filename = "test.mp4"
        wordbank = ["cool", "awesome"]
        result = replace_template_placeholders(template, filename, wordbank)
        assert result.count("{random}") == 0
        assert result.count("video") == 1
    
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


class TestDefaultSettings:
    """Test default settings functions"""
    
    def test_get_default_global_settings_returns_dict(self):
        """Test that get_default_global_settings returns a dictionary"""
        settings = get_default_global_settings()
        assert isinstance(settings, dict)
    
    def test_get_default_global_settings_has_required_keys(self):
        """Test that default settings have required keys"""
        settings = get_default_global_settings()
        required_keys = [
            "title_template",
            "description_template",
            "wordbank",
            "upload_immediately",
            "allow_duplicates"
        ]
        for key in required_keys:
            assert key in settings
