"""Security tests for hopper backend API"""
import os
import pytest
import httpx
import time


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")


class TestAuthenticationRequired:
    """Test that endpoints require authentication"""
    
    def test_destinations_endpoint_requires_auth(self):
        """Test that /api/destinations requires authentication"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
            assert response.status_code == 401
    
    def test_videos_endpoint_requires_auth(self):
        """Test that /api/videos requires authentication"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/videos", timeout=5.0)
            assert response.status_code == 401
    
    def test_settings_endpoint_requires_auth(self):
        """Test that /api/global/settings requires authentication"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/global/settings", timeout=5.0)
            assert response.status_code == 401


class TestPublicEndpoints:
    """Test that public endpoints don't require authentication"""
    
    def test_health_check_public(self):
        """Test that health check endpoint is public"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/", timeout=5.0)
            assert response.status_code == 200
    
    def test_csrf_endpoint_public(self):
        """Test that CSRF token endpoint is public"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
            assert response.status_code == 200
            data = response.json()
            assert "csrf_token" in data


class TestUserRegistrationAndLogin:
    """Test user registration and login flow"""
    
    def test_register_endpoint_accepts_valid_data(self):
        """Test that registration endpoint accepts valid email and password"""
        with httpx.Client() as client:
            test_email = f"test_{int(time.time())}@test.com"
            response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": test_email,
                    "password": "SecurePassword123!"
                },
                timeout=5.0
            )
            # Should succeed (200) or conflict if user exists (400)
            assert response.status_code in [200, 400]
            if response.status_code == 200:
                data = response.json()
                assert "user" in data
                assert data["user"]["email"] == test_email
    
    def test_register_requires_email(self):
        """Test that registration requires email"""
        with httpx.Client() as client:
            response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={"password": "password123"},
                timeout=5.0
            )
            assert response.status_code == 422
    
    def test_register_requires_password(self):
        """Test that registration requires password"""
        with httpx.Client() as client:
            response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={"email": "test@test.com"},
                timeout=5.0
            )
            assert response.status_code == 422
    
    def test_register_password_too_short(self):
        """Test that registration requires password of at least 8 characters"""
        with httpx.Client() as client:
            response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": f"test_{int(time.time())}@test.com",
                    "password": "short"
                },
                timeout=5.0
            )
            assert response.status_code == 400
    
    def test_login_with_invalid_credentials_fails(self):
        """Test that login fails with invalid credentials"""
        with httpx.Client() as client:
            response = client.post(
                f"{BASE_URL}/api/auth/login",
                json={
                    "email": "nonexistent@test.com",
                    "password": "wrong_password"
                },
                timeout=5.0
            )
            assert response.status_code == 401
    
    def test_login_sets_session_cookie(self):
        """Test that successful login sets session cookie"""
        with httpx.Client() as client:
            # First register
            test_email = f"logintest_{int(time.time())}@test.com"
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": test_email,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 200:
                pytest.skip("Could not register test user")
            
            # Then login
            login_response = client.post(
                f"{BASE_URL}/api/auth/login",
                json={
                    "email": test_email,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            assert login_response.status_code == 200
            assert "session_id" in login_response.cookies


class TestCSRFProtection:
    """Test CSRF token protection for authenticated requests"""
    
    def test_get_csrf_token(self):
        """Test that CSRF token endpoint returns a token"""
        with httpx.Client() as client:
            response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
            assert response.status_code == 200
            data = response.json()
            assert "csrf_token" in data
            assert len(data["csrf_token"]) > 0
    
    def test_post_without_csrf_token_fails(self):
        """Test that POST requests without CSRF token are rejected"""
        with httpx.Client() as client:
            # Register and login
            test_email = f"csrftest_{int(time.time())}@test.com"
            
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": test_email,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 200:
                pytest.skip("Could not register test user")
            
            # Get CSRF token (needed for authenticated requests)
            csrf_response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
            csrf_token = csrf_response.json().get("csrf_token")
            
            # Try POST without CSRF token (should fail)
            response = client.post(
                f"{BASE_URL}/api/global/wordbank",
                json={"word": "test"},
                timeout=5.0
            )
            
            # Should be rejected (403)
            assert response.status_code == 403
    
    def test_post_with_valid_csrf_token_succeeds(self):
        """Test that POST requests with valid CSRF token succeed"""
        with httpx.Client() as client:
            # Register
            test_email = f"csrfvalid_{int(time.time())}@test.com"
            
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": test_email,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 200:
                pytest.skip("Could not register test user")
            
            # Get CSRF token
            csrf_response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
            csrf_token = csrf_response.json().get("csrf_token")
            
            if not csrf_token:
                pytest.skip("Could not get CSRF token")
            
            # Try POST with CSRF token (should not be 403)
            response = client.post(
                f"{BASE_URL}/api/global/wordbank",
                json={"word": "test"},
                headers={"X-CSRF-Token": csrf_token},
                timeout=5.0
            )
            
            # Should NOT be 403 (CSRF error)
            assert response.status_code != 403


class TestSessionManagement:
    """Test session management"""
    
    def test_session_persists_across_requests(self):
        """Test that session cookie persists across requests"""
        with httpx.Client() as client:
            # Register
            test_email = f"sessiontest_{int(time.time())}@test.com"
            
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": test_email,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 200:
                pytest.skip("Could not register test user")
            
            # Check session cookie was set
            assert "session_id" in register_response.cookies
            
            # Make another request - should stay authenticated
            me_response = client.get(f"{BASE_URL}/api/auth/me", timeout=5.0)
            assert me_response.status_code == 200
            
            user_data = me_response.json().get("user")
            assert user_data is not None
            assert user_data["email"] == test_email
    
    def test_logout_invalidates_session(self):
        """Test that logout invalidates session"""
        with httpx.Client() as client:
            # Register
            test_email = f"logouttest_{int(time.time())}@test.com"
            
            register_response = client.post(
                f"{BASE_URL}/api/auth/register",
                json={
                    "email": test_email,
                    "password": "TestPassword123!"
                },
                timeout=5.0
            )
            
            if register_response.status_code != 200:
                pytest.skip("Could not register test user")
            
            # Logout (doesn't require CSRF)
            logout_response = client.post(
                f"{BASE_URL}/api/auth/logout",
                timeout=5.0
            )
            
            assert logout_response.status_code == 200
            
            # Session should be invalidated - /api/auth/me should return no user
            me_response = client.get(f"{BASE_URL}/api/auth/me", timeout=5.0)
            assert me_response.status_code == 200
            user_data = me_response.json().get("user")
            assert user_data is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
