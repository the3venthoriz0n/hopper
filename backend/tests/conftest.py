"""Shared pytest fixtures for test suite"""
import pytest
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import fakeredis
import secrets

# Add backend directory to Python path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.db.session import get_db
from app.models import Base
from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.services.auth_service import create_user
from app.db import redis as redis_module


# SQLite in-memory database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

# Create test engine with StaticPool for in-memory database
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Create test session factory
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Create a fresh SQLite in-memory database session for each test"""
    # Create all tables
    Base.metadata.create_all(bind=test_engine)
    
    # Create session
    session = TestSessionLocal()
    
    try:
        yield session
    finally:
        session.close()
        # Drop all tables after test
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def mock_redis():
    """Mock Redis client using fakeredis"""
    fake_redis = fakeredis.FakeStrictRedis(decode_responses=True)
    
    # Helper functions that use fake_redis
    def set_session(sid, uid):
        fake_redis.setex(f"session:{sid}", 2592000, str(uid))
    
    def get_session(sid):
        val = fake_redis.get(f"session:{sid}")
        return int(val) if val else None
    
    def delete_session(sid):
        fake_redis.delete(f"session:{sid}")
    
    def set_csrf_token(sid, token):
        fake_redis.setex(f"csrf:{sid}", 2592000, token)
    
    def get_csrf_token(sid):
        return fake_redis.get(f"csrf:{sid}")
    
    def get_or_create_csrf_token(sid):
        token = fake_redis.get(f"csrf:{sid}")
        if not token:
            token = secrets.token_urlsafe(32)
            fake_redis.setex(f"csrf:{sid}", 2592000, token)
        return token
    
    # Patch redis_client and functions in the redis module
    with patch.object(redis_module, 'redis_client', fake_redis):
        with patch.object(redis_module, 'set_session', set_session):
            with patch.object(redis_module, 'get_session', get_session):
                with patch.object(redis_module, 'delete_session', delete_session):
                    with patch.object(redis_module, 'set_csrf_token', set_csrf_token):
                        with patch.object(redis_module, 'get_csrf_token', get_csrf_token):
                            with patch.object(redis_module, 'get_or_create_csrf_token', get_or_create_csrf_token):
                                yield fake_redis


@pytest.fixture(scope="function")
def client(db_session: Session, mock_redis) -> Generator[TestClient, None, None]:
    """FastAPI test client with test database and mocked Redis"""
    
    # Override get_db dependency to use test database
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # Don't close session here, handled by fixture
    
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        # Disable OpenTelemetry instrumentation in tests
        with patch('app.core.otel.initialize_otel', return_value=False):
            with patch('app.core.otel.setup_otel_logging', return_value=False):
                with patch('app.core.otel.instrument_fastapi'):
                    with patch('app.core.otel.instrument_httpx'):
                        with patch('app.core.otel.instrument_sqlalchemy'):
                            with TestClient(app) as test_client:
                                yield test_client
    finally:
        # Cleanup - always clear overrides
        app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def test_user(db_session: Session) -> User:
    """Create a verified test user using Resend test email"""
    # Use RESEND_TEST_DELIVERED for test user (defined below in this file)
    user = create_user(
        email="delivered@resend.dev",
        password="TestPassword123!",
        db=db_session
    )
    # Mark email as verified
    user.is_email_verified = True
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_user_2(db_session: Session) -> User:
    """Create a second verified test user for ownership tests using Resend test email"""
    # Use a variant of RESEND_TEST_DELIVERED with +2 suffix for second user
    user = create_user(
        email="delivered+test2@resend.dev",
        password="TestPassword123!",
        db=db_session
    )
    user.is_email_verified = True
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def authenticated_client(client: TestClient, test_user: User, mock_redis) -> TestClient:
    """Client with authenticated user session and CSRF token"""
    # First, get CSRF token to establish session
    csrf_response = client.get("/api/auth/csrf")
    assert csrf_response.status_code == 200
    session_id = csrf_response.cookies.get("session_id")
    
    # Set session in Redis mock
    if session_id:
        mock_redis.setex(f"session:{session_id}", 2592000, str(test_user.id))
        # Get CSRF token from response
        csrf_token = csrf_response.headers.get("X-CSRF-Token") or csrf_response.json().get("csrf_token")
        if csrf_token:
            mock_redis.setex(f"csrf:{session_id}", 2592000, csrf_token)
    
    # Login to authenticate
    login_response = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "TestPassword123!"}
    )
    
    assert login_response.status_code == 200
    
    # Get CSRF token from login response
    csrf_token = login_response.headers.get("X-CSRF-Token") or login_response.cookies.get("csrf_token_client")
    if not csrf_token:
        # Fallback: get from CSRF endpoint
        csrf_response = client.get("/api/auth/csrf")
        csrf_token = csrf_response.headers.get("X-CSRF-Token") or csrf_response.json().get("csrf_token")
    
    # Store CSRF token for use in tests
    if csrf_token:
        client.headers.update({"X-CSRF-Token": csrf_token})
    
    return client


@pytest.fixture(scope="function")
def csrf_token(authenticated_client: TestClient, mock_redis) -> str:
    """Get CSRF token from authenticated session"""
    # Get token from header
    token = authenticated_client.headers.get("X-CSRF-Token")
    if not token:
        # Try to get from cookie
        token = authenticated_client.cookies.get("csrf_token_client")
    if not token:
        # Request CSRF endpoint
        response = authenticated_client.get("/api/auth/csrf")
        token = response.headers.get("X-CSRF-Token") or response.json().get("csrf_token")
    
    # If still no token, get from Redis mock using session_id
    if not token:
        session_id = authenticated_client.cookies.get("session_id")
        if session_id:
            token = mock_redis.get(f"csrf:{session_id}")
    
    assert token is not None, "CSRF token should be available"
    return token


@pytest.fixture(scope="function")
def two_users(db_session: Session) -> tuple[User, User]:
    """Create two users for ownership tests using Resend test emails"""
    user1 = create_user(
        email="delivered+user1@resend.dev",
        password="TestPassword123!",
        db=db_session
    )
    user1.is_email_verified = True
    
    user2 = create_user(
        email="delivered+user2@resend.dev",
        password="TestPassword123!",
        db=db_session
    )
    user2.is_email_verified = True
    
    db_session.commit()
    db_session.refresh(user1)
    db_session.refresh(user2)
    
    return user1, user2


@pytest.fixture(scope="function", autouse=True)
def auto_mock_stripe():
    """Automatically mock Stripe for all tests to prevent creating real customers"""
    with patch('app.services.stripe_service.stripe') as mock_stripe_module:
        # Mock Customer operations
        mock_customer = Mock(id="cus_test123", email="delivered@resend.dev")
        mock_stripe_module.Customer.create = Mock(return_value=mock_customer)
        mock_stripe_module.Customer.retrieve = Mock(return_value=mock_customer)
        mock_stripe_module.Customer.delete = Mock(return_value=Mock(deleted=True))
        
        # Mock Subscription operations
        mock_subscription = Mock(
            id="sub_test123",
            status="active",
            current_period_start=1234567890,
            current_period_end=1237159890,
            customer="cus_test123",
            cancel_at_period_end=False
        )
        mock_stripe_module.Subscription.create = Mock(return_value=mock_subscription)
        mock_stripe_module.Subscription.retrieve = Mock(return_value=mock_subscription)
        mock_stripe_module.Subscription.list = Mock(return_value=Mock(data=[]))
        
        # Mock SubscriptionItem operations
        mock_subscription_item = Mock(
            id="si_test123",
            price=Mock(id="price_test123", product="prod_test123")
        )
        mock_stripe_module.SubscriptionItem.list = Mock(return_value=Mock(data=[mock_subscription_item]))
        mock_stripe_module.SubscriptionItem.create = Mock(return_value=mock_subscription_item)
        
        # Mock Checkout operations
        mock_stripe_module.Checkout.Session.create = Mock(return_value=Mock(
            id="cs_test123",
            url="https://checkout.stripe.com/test"
        ))
        mock_stripe_module.Checkout.Session.retrieve = Mock(return_value=Mock(
            id="cs_test123",
            customer="cus_test123",
            subscription="sub_test123"
        ))
        mock_stripe_module.Checkout.Session.list = Mock(return_value=Mock(data=[]))
        
        # Mock Billing Portal operations
        mock_stripe_module.billing_portal.Session.create = Mock(return_value=Mock(
            url="https://billing.stripe.com/test"
        ))
        
        # Mock Webhook operations
        mock_stripe_module.Webhook.construct_event = Mock(return_value={
            "id": "evt_test123",
            "type": "customer.subscription.created",
            "data": {"object": {}}
        })
        
        # Mock Price operations
        mock_price = Mock(
            id="price_test123",
            product="prod_test123",
            unit_amount=0,
            currency="usd",
            recurring=Mock(interval="month")
        )
        mock_stripe_module.Price.retrieve = Mock(return_value=mock_price)
        
        # Mock Product operations
        mock_stripe_module.Product.retrieve = Mock(return_value=Mock(
            id="prod_test123",
            name="Test Product"
        ))
        
        # Mock error classes
        mock_stripe_module.error.SignatureVerificationError = Exception
        mock_stripe_module.error.InvalidRequestError = Exception
        
        yield mock_stripe_module


@pytest.fixture(scope="function")
def mock_stripe():
    """Mock Stripe API calls (explicit fixture for tests that need direct access)"""
    with patch('app.services.stripe_service.stripe') as mock_stripe_module:
        # Mock common Stripe objects
        mock_stripe_module.Customer.create = Mock(return_value=Mock(id="cus_test123"))
        mock_stripe_module.Customer.retrieve = Mock(return_value=Mock(id="cus_test123"))
        mock_stripe_module.Subscription.create = Mock(return_value=Mock(
            id="sub_test123",
            status="active",
            current_period_start=1234567890,
            current_period_end=1237159890
        ))
        mock_stripe_module.Subscription.retrieve = Mock(return_value=Mock(
            id="sub_test123",
            status="active",
            current_period_start=1234567890,
            current_period_end=1237159890,
            items=Mock(data=[Mock(price=Mock(id="price_test123"))])
        ))
        mock_stripe_module.Webhook.construct_event = Mock(return_value={
            "id": "evt_test123",
            "type": "customer.subscription.created",
            "data": {"object": {}}
        })
        mock_stripe_module.Checkout.Session.create = Mock(return_value=Mock(
            id="cs_test123",
            url="https://checkout.stripe.com/test"
        ))
        mock_stripe_module.error.SignatureVerificationError = Exception
        
        yield mock_stripe_module


@pytest.fixture(scope="function")
def mock_email_service():
    """Mock email service (Resend) to avoid sending actual emails"""
    with patch('app.services.email_service.resend') as mock_resend:
        mock_resend.Emails.send = Mock(return_value=Mock(id="email_test123"))
        yield mock_resend


# Resend test email addresses - use these in ALL tests to avoid fake addresses
# See: https://resend.com/docs/dashboard/emails/send-test-emails
# 
# RESEND_TEST_DELIVERED: Email will be successfully delivered (use for normal flows)
# RESEND_TEST_BOUNCED: Email will hard bounce with SMTP 550 error (use for bounce testing)
# RESEND_TEST_COMPLAINED: Email will be marked as spam (use for complaint testing)
RESEND_TEST_DELIVERED = "delivered@resend.dev"
RESEND_TEST_BOUNCED = "bounced@resend.dev"
RESEND_TEST_COMPLAINED = "complained@resend.dev"
