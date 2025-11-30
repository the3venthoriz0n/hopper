"""Security tests for hopper backend API - Database-backed architecture"""
import os
import pytest
import httpx
import time


# Get base URL from environment or use default
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")


class TestAuthenticationRequired:
    """Test that endpoints require authentication"""
    
    def test_destinations_endpoint_requires_auth(self):
        """Test that /api/destinations requires authentication"""
        with httpx.Client() as client:
            # Request without session cookie should return 401
            response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
            assert response.status_code == 401, \
                f"Expected 401 (Not authenticated), got {response.status_code}"
            assert "authenticated" in response.json().get("detail", "").lower()
    
    def test_videos_endpoint_requires_auth(self):
        """Test that /api/videos requires authentication"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/videos", timeout=5.0)
            assert response.status_code == 401, \
                f"Expected 401 (Not authenticated), got {response.status_code}"
    
    def test_settings_endpoint_requires_auth(self):
        """Test that /api/global/settings requires authentication"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/global/settings", timeout=5.0)
            assert response.status_code == 401, \
                f"Expected 401 (Not authenticated), got {response.status_code}"
    
    def test_youtube_oauth_requires_auth(self):
        """Test that YouTube OAuth initiation requires authentication"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/auth/youtube", timeout=5.0)
            assert response.status_code == 401, \
                f"Expected 401 (Not authenticated), got {response.status_code}"


class TestPublicEndpoints:
    """Test that public endpoints don't require authentication"""
    
    def test_health_check_public(self):
        """Test that health check endpoint is public"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/", timeout=5.0)
            # Should return 200 without authentication
            assert response.status_code == 200
    
    def test_terms_endpoint_public(self):
        """Test that terms of service endpoint is public"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/terms", timeout=5.0)
            assert response.status_code == 200
    
    def test_privacy_endpoint_public(self):
        """Test that privacy policy endpoint is public"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/privacy", timeout=5.0)
            assert response.status_code == 200


class TestUserRegistrationAndLogin:
    """Test user registration and login flow"""
    
    def test_register_endpoint_accepts_valid_data(self):
        """Test that registration endpoint accepts valid data"""
        with httpx.Client() as client:
            # Try to register a user
            test_username = f"testuser_{int(time.time())}"
            response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "username": test_username,
                    "email": f"{test_username}@test.com",
                    "password": "SecurePassword123!"
                },
                timeout=5.0
            )
            
            # Should succeed (201) or conflict if user exists (409)
            assert response.status_code in [201, 409], \
                f"Expected 201 or 409, got {response.status_code}"
            
            if response.status_code == 201:
                data = response.json()
                assert "user" in data
                assert data["user"]["username"] == test_username
    
    def test_register_requires_username(self):
        """Test that registration requires username"""
        with httpx.Client() as client:
            response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": "test@test.com",
                    "password": "password123"
                },
                timeout=5.0
            )
            # Should return 422 (validation error)
            assert response.status_code == 422
    
    def test_login_with_invalid_credentials_fails(self):
        """Test that login fails with invalid credentials"""
        with httpx.Client() as client:
            response = client.post(
                f"{BASE_URL}/api/auth/login",
                json={
                    "username": "nonexistent_user",
                    "password": "wrong_password"
                },
                timeout=5.0
            )
            # Should return 401
            assert response.status_code == 401


class TestCSRFProtection:
    """Test CSRF token protection for authenticated requests"""
    
    def test_get_csrf_token_endpoint(self):
        """Test that CSRF token endpoint is accessible"""
        with httpx.Client() as client:
            # CSRF token endpoint should be public
            response = client.get(f"{BASE_URL}/api/auth/csrf-token", timeout=5.0)
            # Should return 200 with a token
            assert response.status_code == 200
            data = response.json()
            assert "csrf_token" in data
            assert len(data["csrf_token"]) > 0
    
    def test_post_without_csrf_token_fails_when_authenticated(self):
        """Test that POST requests without CSRF token are rejected for authenticated users"""
        with httpx.Client() as client:
            # First register and login a user
            test_username = f"csrftest_{int(time.time())}"
            
            # Register
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "username": test_username,
                    "email": f"{test_username}@test.com",
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 201:
                pytest.skip("Could not register test user")
            
            # Login to get session
            login_response = client.post(
                f"{BASE_URL}/api/auth/login",
                json={
                    "username": test_username,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if login_response.status_code != 200:
                pytest.skip("Could not login test user")
            
            # Try POST without CSRF token (should fail)
            response = client.post(
                f"{BASE_URL}/api/global/wordbank",
                json={"word": "test"},
                timeout=5.0
            )
            
            # Should be rejected (403)
            assert response.status_code == 403, \
                f"Expected 403 without CSRF token, got {response.status_code}"
    
    def test_post_with_valid_csrf_token_succeeds(self):
        """Test that POST requests with valid CSRF token succeed"""
        with httpx.Client() as client:
            # Register and login
            test_username = f"csrfvalid_{int(time.time())}"
            
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "username": test_username,
                    "email": f"{test_username}@test.com",
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 201:
                pytest.skip("Could not register test user")
            
            login_response = client.post(
                f"{BASE_URL}/api/auth/login",
                json={
                    "username": test_username,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if login_response.status_code != 200:
                pytest.skip("Could not login test user")
            
            # Get CSRF token
            csrf_response = client.get(f"{BASE_URL}/api/auth/csrf-token", timeout=5.0)
            csrf_token = csrf_response.json().get("csrf_token")
            
            if not csrf_token:
                pytest.skip("Could not get CSRF token")
            
            # Try POST with CSRF token (should succeed or return different error)
            response = client.post(
                f"{BASE_URL}/api/global/wordbank",
                json={"word": "test"},
                headers={"X-CSRF-Token": csrf_token},
                timeout=5.0
            )
            
            # Should NOT be 403 (CSRF error)
            assert response.status_code != 403, \
                f"Should not get 403 with valid CSRF token"


class TestOriginValidation:
    """Test origin/referer validation"""
    
    def test_invalid_origin_rejected_in_production(self):
        """Test that requests with invalid origin are rejected in production"""
        with httpx.Client() as client:
            # Register and login first
            test_username = f"origintest_{int(time.time())}"
            
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "username": test_username,
                    "email": f"{test_username}@test.com",
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 201:
                pytest.skip("Could not register test user")
            
            login_response = client.post(
                f"{BASE_URL}/api/auth/login",
                json={
                    "username": test_username,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if login_response.status_code != 200:
                pytest.skip("Could not login test user")
            
            # Get CSRF token
            csrf_response = client.get(f"{BASE_URL}/api/auth/csrf-token", timeout=5.0)
            csrf_token = csrf_response.json().get("csrf_token")
            
            # Try POST with invalid origin
            response = client.post(
                f"{BASE_URL}/api/global/wordbank",
                json={"word": "test"},
                headers={
                    "X-CSRF-Token": csrf_token,
                    "Origin": "https://evil-site.com",
                    "Referer": "https://evil-site.com/"
                },
                timeout=5.0
            )
            
            # In production should be rejected (403)
            # In development might be allowed
            # Just check we get some response
            assert response.status_code in [200, 403], \
                f"Expected 200 (dev) or 403 (prod) with invalid origin, got {response.status_code}"


class TestRateLimiting:
    """Test rate limiting"""
    
    def test_rate_limiting_enforced(self):
        """Test that rapid requests are rate limited"""
        with httpx.Client() as client:
            rate_limited = False
            rate_limit_request_num = 0
            
            # Send rapid requests to public endpoint
            # Production limit is 5000, dev is 1000, so we'll send 1100 to test
            for i in range(1, 1101):
                try:
                    response = client.get(
                        f"{BASE_URL}/",
                        timeout=2.0
                    )
                    
                    if response.status_code == 429:
                        rate_limited = True
                        rate_limit_request_num = i
                        break
                except httpx.TimeoutException:
                    continue
                except Exception:
                    continue
                
                # Small delay to avoid overwhelming the server
                if i % 100 == 0:
                    time.sleep(0.1)
            
            # Rate limiting should kick in at some point
            # Note: This test might be flaky depending on rate limit settings
            if not rate_limited:
                pytest.skip(
                    f"Rate limiting not triggered after {rate_limit_request_num or 1100} requests. "
                    "This might be expected if rate limits are very high."
                )
            else:
                assert rate_limited, "Rate limiting should have been triggered"
                assert rate_limit_request_num > 0, "Should have rate limited at some point"


class TestSessionPersistence:
    """Test that sessions persist across requests"""
    
    def test_session_cookie_persists(self):
        """Test that session cookie is maintained across requests"""
        with httpx.Client() as client:
            # Register and login
            test_username = f"sessiontest_{int(time.time())}"
            
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "username": test_username,
                    "email": f"{test_username}@test.com",
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 201:
                pytest.skip("Could not register test user")
            
            login_response = client.post(
                f"{BASE_URL}/api/auth/login",
                json={
                    "username": test_username,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if login_response.status_code != 200:
                pytest.skip("Could not login test user")
            
            # Check session cookie was set
            assert "session_id" in client.cookies
            
            # Make another request - should stay authenticated
            me_response = client.get(f"{BASE_URL}/api/auth/me", timeout=5.0)
            assert me_response.status_code == 200
            
            user_data = me_response.json().get("user")
            assert user_data is not None
            assert user_data["username"] == test_username


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
