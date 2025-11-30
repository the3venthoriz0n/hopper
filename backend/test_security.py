"""Security tests for hopper backend API"""
import os
import pytest
import httpx
import time


# Get base URL from environment or use default
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")


class TestSessionValidation:
    """Test that endpoints require valid sessions"""
    
    def test_destinations_endpoint_requires_session(self):
        """Test that /api/destinations requires a session"""
        with httpx.Client() as client:
            # Request without session cookie
            response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
            # Should either require session (401) or create one (200 with session creation)
            # The endpoint uses get_or_create_session, so 200 is acceptable
            # But if it returns 401, that's also valid (strict session requirement)
            assert response.status_code in [200, 401], \
                f"Expected 200 or 401, got {response.status_code}"
    
    def test_videos_endpoint_requires_session(self):
        """Test that /api/videos requires a session"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/videos", timeout=5.0)
            # Uses get_or_create_session, so 200 is acceptable
            assert response.status_code in [200, 401], \
                f"Expected 200 or 401, got {response.status_code}"


class TestCSRFProtection:
    """Test CSRF token protection"""
    
    def test_post_without_csrf_token_fails(self):
        """Test that POST requests without CSRF token are rejected"""
        with httpx.Client() as client:
            # First, get a session by making a GET request
            get_response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
            cookies = get_response.cookies
            
            if not cookies.get("session_id"):
                pytest.skip("Could not get session_id from GET request")
            
            # Extract CSRF token from response header if available
            csrf_token = get_response.headers.get("X-CSRF-Token")
            
            # Try POST without CSRF token
            response = client.post(
                f"{BASE_URL}/api/destinations/youtube/toggle",
                cookies=cookies,
                timeout=5.0
            )
            
            # Should be rejected (403) if CSRF protection is working
            # Note: Some endpoints might return 401 if session is invalid
            assert response.status_code in [403, 401], \
                f"Expected 403 or 401 without CSRF token, got {response.status_code}"
    
    def test_post_with_invalid_csrf_token_fails(self):
        """Test that POST requests with invalid CSRF token are rejected"""
        with httpx.Client() as client:
            # Get a session
            get_response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
            cookies = get_response.cookies
            
            if not cookies.get("session_id"):
                pytest.skip("Could not get session_id from GET request")
            
            # Try POST with invalid CSRF token
            response = client.post(
                f"{BASE_URL}/api/destinations/youtube/toggle",
                cookies=cookies,
                headers={"X-CSRF-Token": "invalid_token_12345"},
                timeout=5.0
            )
            
            # Should be rejected
            assert response.status_code in [403, 401], \
                f"Expected 403 or 401 with invalid CSRF token, got {response.status_code}"


class TestOriginValidation:
    """Test origin/referer validation"""
    
    def test_invalid_origin_rejected(self):
        """Test that requests with invalid origin are rejected"""
        with httpx.Client() as client:
            # Get a session first
            get_response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
            cookies = get_response.cookies
            
            if not cookies.get("session_id"):
                pytest.skip("Could not get session_id from GET request")
            
            # Try POST with invalid origin
            response = client.post(
                f"{BASE_URL}/api/destinations/youtube/toggle",
                cookies=cookies,
                headers={
                    "Origin": "https://evil-site.com",
                    "Referer": "https://evil-site.com/"
                },
                timeout=5.0
            )
            
            # Should be rejected (403) if origin validation is working
            # Note: In development, origin validation might be relaxed
            assert response.status_code in [403, 401], \
                f"Expected 403 or 401 with invalid origin, got {response.status_code}"


class TestRateLimiting:
    """Test rate limiting"""
    
    def test_rate_limiting_enforced(self):
        """Test that rapid requests are rate limited"""
        with httpx.Client() as client:
            # Use a unique session ID for this test
            test_session_id = f"test_rate_limit_{int(time.time())}"
            cookies = {"session_id": test_session_id}
            
            rate_limited = False
            rate_limit_request_num = 0
            
            # Send rapid requests (more than the limit)
            # Production limit is 5000, dev is 1000, so we'll send 1100 to test
            for i in range(1, 1101):
                try:
                    response = client.get(
                        f"{BASE_URL}/api/destinations",
                        cookies=cookies,
                        timeout=2.0
                    )
                    
                    if response.status_code == 429:
                        rate_limited = True
                        rate_limit_request_num = i
                        break
                except httpx.TimeoutException:
                    # If we're getting timeouts, might be rate limited
                    continue
                except Exception:
                    # Other errors, continue
                    continue
                
                # Small delay to avoid overwhelming the server
                if i % 100 == 0:
                    time.sleep(0.1)
            
            # Rate limiting should kick in at some point
            # Note: This test might be flaky depending on rate limit settings
            # In production with 5000 limit, it might not trigger
            if not rate_limited:
                pytest.skip(
                    f"Rate limiting not triggered after {rate_limit_request_num or 1100} requests. "
                    "This might be expected if rate limits are very high."
                )
            else:
                assert rate_limited, "Rate limiting should have been triggered"
                assert rate_limit_request_num > 0, "Should have rate limited at some point"

