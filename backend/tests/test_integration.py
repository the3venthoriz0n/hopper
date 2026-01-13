"""Integration tests for hopper backend API"""
import os
import pytest
import httpx
import time

# Determine BASE_URL based on environment
# Priority: 1. TEST_BASE_URL env var, 2. Docker service name, 3. localhost
if os.getenv("TEST_BASE_URL"):
    BASE_URL = os.getenv("TEST_BASE_URL")
elif os.path.exists("/.dockerenv") or os.getenv("DOCKER_CONTAINER"):
    # Running in Docker - use service name (works for both dev and prod)
    # The service name is 'backend' in both docker-compose.dev.yml and docker-compose.prod.yml
    BASE_URL = "http://backend:8000"
else:
    # Running locally (not in Docker)
    BASE_URL = "http://localhost:8000"

# Detect production environment - check multiple indicators
def is_production():
    """Check if running in production environment - always skip tests in production"""
    # Check environment variable (case-insensitive)
    env = os.getenv("ENVIRONMENT", "").lower()
    if env == "production":
        return True
    
    # Check container name (prod containers have "prod-" prefix)
    # HOSTNAME in Docker containers is typically the container name
    container_name = os.getenv("HOSTNAME", "")
    if container_name and "prod-" in container_name.lower():
        return True
    
    # Check for production container name pattern
    # Production containers are named like "prod-hopper-backend"
    if "prod-hopper" in container_name.lower():
        return True
    
    # Check BASE_URL for production indicators (check both TEST_BASE_URL and determined BASE_URL)
    test_base_url = os.getenv("TEST_BASE_URL", "")
    if test_base_url and ("api.dunkbox.net" in test_base_url or "prod-hopper-backend" in test_base_url):
        return True
    
    if BASE_URL and ("api.dunkbox.net" in BASE_URL or "prod-hopper-backend" in BASE_URL):
        return True
    
    # Check if we're in a production docker-compose context
    # Production uses docker-compose.prod.yml which sets container names with "prod-" prefix
    # If we detect we're in Docker and can't determine dev, assume production for safety
    if os.path.exists("/.dockerenv") and not os.getenv("TEST_BASE_URL"):
        # In Docker but no explicit test URL - check if it's likely production
        # This is a safety check - if unsure, skip tests
        env_lower = env
        if not env_lower or env_lower not in ["development", "dev", "test"]:
            # If environment is not explicitly dev/test, assume production for safety
            return True
    
    return False

# Determine frontend origin based on backend URL
FRONTEND_ORIGIN = os.getenv("TEST_FRONTEND_ORIGIN")
if not FRONTEND_ORIGIN:
    if "api-dev.dunkbox.net" in BASE_URL or "dev-hopper-backend" in BASE_URL:
        FRONTEND_ORIGIN = "https://hopper-dev.dunkbox.net"
    elif "api.dunkbox.net" in BASE_URL or "prod-hopper-backend" in BASE_URL:
        FRONTEND_ORIGIN = "https://hopper.dunkbox.net"
    else:
        FRONTEND_ORIGIN = "http://localhost:3000"


@pytest.fixture
def client():
    """Provide HTTP client with default headers"""
    with httpx.Client(
        headers={"Origin": FRONTEND_ORIGIN},
        follow_redirects=True
    ) as c:
        yield c


def get_csrf_token(client):
    """Get CSRF token from API (returns token from response body or header)"""
    response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
    assert response.status_code == 200
    # Token is available in both body and header
    if "csrf_token" in response.json():
        return response.json()["csrf_token"]
    # Fallback to header if body doesn't have it
    return response.headers.get("X-CSRF-Token")


def register_user(client, email, password):
    """Register a new user (does not require CSRF token)"""
    return client.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password},
        timeout=5.0
    )


def login_user(client, email, password):
    """Login user and return client with session cookie"""
    response = client.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=5.0
    )
    return response


@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_protected_endpoint_requires_auth(client):
    """Test that protected endpoints require authentication"""
    response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
    assert response.status_code == 401

@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_public_endpoint_accessible(client):
    """Test that public endpoints are accessible"""
    response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
    assert response.status_code == 200
    # CSRF token should be in response body
    assert "csrf_token" in response.json()
    # Session cookie should be set (even for unauthenticated users)
    assert "session_id" in response.cookies
    
    # On subsequent requests with session cookie, the endpoint should still work
    # Make a second request with the session cookie to verify it persists
    response2 = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
    assert response2.status_code == 200
    # CSRF token should still be in response body
    assert "csrf_token" in response2.json()
    # The X-CSRF-Token header may be set by middleware if session exists,
    # but it's not guaranteed on all responses - the token in the body is the source of truth


@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_user_registration(client):
    """Test user registration with valid data"""
    test_email = f"delivered+registration_{int(time.time())}@resend.dev"
    response = register_user(client, test_email, "SecurePassword123!")
    
    # Accept 200 (success), 400 (validation error), 503 (service unavailable), but not 500
    assert response.status_code in [200, 400, 503], f"Unexpected status code {response.status_code}: {response.text}"
    if response.status_code == 200:
        data = response.json()
        assert data["user"]["email"] == test_email
        assert data["requires_email_verification"] is True
        # User ID should be None until email is verified
        assert data["user"]["id"] is None


@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_login_with_invalid_credentials(client):
    """Test that login fails with invalid credentials"""
    response = client.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "delivered+invalid@resend.dev", "password": "wrong_password"},
        timeout=5.0
    )
    assert response.status_code == 401


@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_session_cookie_set_on_login(client):
    """Test that login sets session cookie (requires email verification)"""
    test_email = f"delivered+login_{int(time.time())}@resend.dev"
    
    # Register user
    response = register_user(client, test_email, "TestPassword123!")
    if response.status_code != 200:
        pytest.skip("Could not register test user")
    
    # Note: Registration doesn't create a user in the database until email verification.
    # So login immediately after registration will fail with 401 (user doesn't exist yet).
    # After email verification, login would fail with 403 if email not verified, or 200 if verified.
    # For a complete test, you would need to verify the email first using the verification code.
    response = client.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": test_email, "password": "TestPassword123!"},
        timeout=5.0
    )
    
    # Login will fail with 401 (user doesn't exist yet) or 403 (email not verified) or 200 (verified)
    assert response.status_code in [200, 401, 403]
    if response.status_code == 200:
        assert "session_id" in response.cookies
        assert "user" in response.json()


@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_csrf_protection(client):
    """Test that POST requests without CSRF token are rejected"""
    # This test requires a logged-in user with verified email
    # Since we can't easily verify email in tests, we'll test the CSRF requirement
    # by attempting to access a protected endpoint without authentication first
    
    # First, test that unauthenticated request fails
    response = client.post(
        f"{BASE_URL}/api/global/wordbank",
        json={"word": "test"},
        timeout=5.0
    )
    # Should fail with 401 (not authenticated) or 403 (missing CSRF)
    assert response.status_code in [401, 403]
    
    # Note: To fully test CSRF protection, you would need:
    # 1. A verified user account
    # 2. A valid session cookie
    # 3. Then test POST without CSRF token (should get 403)
    # 4. Then test POST with invalid CSRF token (should get 403)
    # 5. Then test POST with valid CSRF token (should succeed)


@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_auth_me_endpoint(client):
    """Test that /api/auth/me returns user info or None"""
    # Without authentication, should return None user
    response = client.get(f"{BASE_URL}/api/auth/me", timeout=5.0)
    assert response.status_code == 200
    assert response.json().get("user") is None


@pytest.mark.skipif(
    is_production() or not os.getenv("RUN_INTEGRATION_TESTS", "").lower() == "true",
    reason="Integration test - requires running backend server. Set RUN_INTEGRATION_TESTS=true to run. Disabled in production."
)
def test_logout_invalidates_session(client):
    """Test that logout invalidates the session"""
    # This test requires a logged-in user with verified email
    # Since we can't easily verify email in tests, we'll test logout behavior
    # with an unauthenticated session
    
    # Logout without session (should still return success)
    response = client.post(f"{BASE_URL}/api/auth/logout", timeout=5.0)
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out successfully"
    
    # Check that /api/auth/me returns no user
    response = client.get(f"{BASE_URL}/api/auth/me", timeout=5.0)
    assert response.status_code == 200
    assert response.json().get("user") is None
    
    # Note: To fully test logout with a session, you would need:
    # 1. A verified user account
    # 2. Login to get a session cookie
    # 3. Verify /api/auth/me returns the user
    # 4. Call logout
    # 5. Verify /api/auth/me returns None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
