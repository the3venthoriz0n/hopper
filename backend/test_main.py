"""Unit tests for hopper backend"""
import pytest
import sys
import os
import tempfile
from pathlib import Path
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
            mock_path.return_value = mock_path_instance
            mock_path_instance.exists.return_value = True
            mock_path_instance.unlink.side_effect = PermissionError()
            
            result = cleanup_video_file(mock_video)
            assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])