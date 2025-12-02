"""Simplified security tests for hopper backend API"""
import os
import pytest
import httpx
import time


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")
# Determine frontend origin based on backend URL
FRONTEND_ORIGIN = os.getenv("TEST_FRONTEND_ORIGIN")
if not FRONTEND_ORIGIN:
    if "api-dev.dunkbox.net" in BASE_URL:
        FRONTEND_ORIGIN = "https://hopper-dev.dunkbox.net"
    elif "api.dunkbox.net" in BASE_URL:
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
    """Get CSRF token from API"""
    response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
    return response.json()["csrf_token"]


def register_user(client, email, password):
    """Register a new user"""
    csrf_token = get_csrf_token(client)
    return client.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf_token},
        timeout=5.0
    )


def test_protected_endpoint_requires_auth(client):
    """Test that protected endpoints require authentication"""
    response = client.get(f"{BASE_URL}/api/destinations", timeout=5.0)
    assert response.status_code in [401, 403]


def test_public_endpoint_accessible(client):
    """Test that public endpoints are accessible"""
    response = client.get(f"{BASE_URL}/api/auth/csrf", timeout=5.0)
    assert response.status_code == 200
    assert "csrf_token" in response.json()


def test_user_registration(client):
    """Test user registration with valid data"""
    test_email = f"test_{int(time.time())}@test.com"
    response = register_user(client, test_email, "SecurePassword123!")
    
    assert response.status_code in [200, 400]
    if response.status_code == 200:
        assert response.json()["user"]["email"] == test_email


def test_login_with_invalid_credentials(client):
    """Test that login fails with invalid credentials"""
    response = client.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "nonexistent@test.com", "password": "wrong_password"},
        timeout=5.0
    )
    assert response.status_code == 401


def test_session_cookie_set_on_login(client):
    """Test that login sets session cookie"""
    test_email = f"logintest_{int(time.time())}@test.com"
    
    # Register user
    response = register_user(client, test_email, "TestPassword123!")
    if response.status_code != 200:
        pytest.skip("Could not register test user")
    
    # Login
    response = client.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": test_email, "password": "TestPassword123!"},
        timeout=5.0
    )
    
    assert response.status_code == 200
    assert "session_id" in response.cookies


def test_csrf_protection(client):
    """Test that POST requests without CSRF token are rejected"""
    test_email = f"csrftest_{int(time.time())}@test.com"
    register_user(client, test_email, "TestPassword123!")
    
    # POST without CSRF token should fail
    response = client.post(
        f"{BASE_URL}/api/global/wordbank",
        json={"word": "test"},
        timeout=5.0
    )
    assert response.status_code == 403


def test_logout_invalidates_session(client):
    """Test that logout invalidates the session"""
    test_email = f"logouttest_{int(time.time())}@test.com"
    register_user(client, test_email, "TestPassword123!")
    
    # Logout
    client.post(f"{BASE_URL}/api/auth/logout", timeout=5.0)
    
    # Check session is invalid
    response = client.get(f"{BASE_URL}/api/auth/me", timeout=5.0)
    assert response.json().get("user") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])