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


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    """Force reset Redis singleton before each test to prevent loop mismatches"""
    # Force the singleton to None before every test starts
    redis_module._async_client = None
    redis_module._client = None
    yield
    # Cleanup after test
    redis_module._async_client = None
    redis_module._client = None


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


@pytest.fixture(scope="function", autouse=True)
def mock_redis():
    """Mock Redis client using fakeredis (automatically applied to all tests)"""
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
    
    # ROOT CAUSE FIX: Patch redis.from_url to prevent any real connections
    # This ensures that even if get_redis_client() tries to create a real client,
    # it will get the fake one instead
    import redis
    
    def mock_from_url(*args, **kwargs):
        """Mock redis.from_url to return fake client instead of creating real connection"""
        return fake_redis
    
    # Patch both the getter function AND the underlying connection creation
    with patch.object(redis_module, 'get_redis_client', return_value=fake_redis):
        with patch.object(redis_module, 'redis_client', fake_redis):
            with patch.object(redis, 'from_url', side_effect=mock_from_url):
                with patch.object(redis_module, 'set_session', set_session):
                    with patch.object(redis_module, 'get_session', get_session):
                        with patch.object(redis_module, 'delete_session', delete_session):
                            with patch.object(redis_module, 'set_csrf_token', set_csrf_token):
                                with patch.object(redis_module, 'get_csrf_token', get_csrf_token):
                                    with patch.object(redis_module, 'get_or_create_csrf_token', get_or_create_csrf_token):
                                        yield fake_redis


@pytest.fixture(scope="function", autouse=True)
def mock_async_redis():
    """Mock async Redis client using fakeredis.aioredis (automatically applied to all tests)"""
    try:
        import fakeredis.aioredis
        # Use fakeredis.aioredis for proper async Redis simulation
        fake_async_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    except (ImportError, AttributeError):
        # Fallback to MagicMock if fakeredis.aioredis not available
        from unittest.mock import AsyncMock, MagicMock
        fake_async_redis = MagicMock()
        fake_async_redis.publish = AsyncMock(return_value=1)
        fake_async_redis.get = AsyncMock(return_value=None)
        fake_async_redis.set = AsyncMock(return_value=True)
        fake_async_redis.setex = AsyncMock(return_value=True)
        fake_async_redis.delete = AsyncMock(return_value=1)
        
        # Create pubsub mock
        fake_pubsub = MagicMock()
        fake_pubsub.psubscribe = AsyncMock()
        
        async def mock_listen():
            return
            yield
        
        fake_pubsub.listen = mock_listen
        fake_async_redis.pubsub = MagicMock(return_value=fake_pubsub)
    
    # ROOT CAUSE FIX: Patch aioredis.from_url to prevent any real connections
    # This ensures that even if get_async_redis_client() tries to create a real client,
    # it will get the fake one instead
    import redis.asyncio as aioredis
    
    def mock_from_url(*args, **kwargs):
        """Mock aioredis.from_url to return fake client instead of creating real connection"""
        return fake_async_redis
    
    # Patch both the getter function AND the underlying connection creation
    # This covers ALL services that import from app.db.redis
    with patch.object(redis_module, 'get_async_redis_client', return_value=fake_async_redis):
        with patch.object(redis_module, 'async_redis_client', fake_async_redis):
            with patch.object(aioredis, 'from_url', side_effect=mock_from_url):
                try:
                    yield fake_async_redis
                finally:
                    # CRITICAL: Close async connections before event loop closes
                    try:
                        if hasattr(fake_async_redis, 'aclose'):
                            import asyncio
                            try:
                                loop = asyncio.get_event_loop()
                                if not loop.is_closed():
                                    if loop.is_running():
                                        # Can't await in running loop - fakeredis doesn't need cleanup
                                        pass
                                    else:
                                        loop.run_until_complete(fake_async_redis.aclose())
                            except (RuntimeError, AttributeError, ValueError):
                                # Event loop issues - fakeredis is in-memory, doesn't need cleanup
                                pass
                    except Exception:
                        # Ignore any cleanup errors - fakeredis is in-memory
                        pass


@pytest.fixture(scope="function")
def client(db_session: Session, mock_redis, mock_async_redis) -> Generator[TestClient, None, None]:
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
def authenticated_client(client: TestClient, test_user: User, mock_redis, mock_async_redis) -> TestClient:
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
    # First, set up Price.list mock that will work even when tests patch stripe
    def create_mock_price(price_id, lookup_key, unit_amount, tokens, name, description="", 
                         hidden=False, max_accrual=None, interval="month"):
        """Helper to create a mock price with product"""
        mock_product = Mock()
        mock_product.id = f"prod_{lookup_key.replace('_price', '')}"
        mock_product.name = name
        mock_product.description = description
        mock_product.active = True
        metadata = {'tokens': str(tokens)}
        if hidden:
            metadata['hidden'] = 'true'
        if max_accrual is not None:
            metadata['max_accrual'] = str(max_accrual)
        mock_product.metadata = metadata
        
        mock_price_obj = Mock()
        mock_price_obj.id = price_id
        mock_price_obj.lookup_key = lookup_key
        mock_price_obj.unit_amount = unit_amount
        mock_price_obj.currency = 'usd'
        mock_price_obj.recurring = {'interval': interval}
        mock_price_obj.created = 1234567890
        mock_price_obj.product = mock_product
        return mock_price_obj
    
    # Create all required mock prices
    mock_prices = [
        # free_price: legacy plan type, same as free_daily (10 tokens, monthly)
        create_mock_price("price_free", "free_price", 0, 10, "Free", 
                        "Free plan", hidden=False, max_accrual=None, interval="month"),
        create_mock_price("price_free_daily", "free_daily_price", 0, 3, "Free Daily", 
                        "3 tokens per day", hidden=False, max_accrual=10, interval="day"),
        create_mock_price("price_starter", "starter_price", 300, 300, "Starter", 
                        "Starter plan", hidden=False, max_accrual=None, interval="month"),
        create_mock_price("price_starter_overage", "starter_overage_price", 15, 0, "Starter Overage", 
                        "Starter overage", hidden=False, max_accrual=None, interval="month"),
        create_mock_price("price_creator", "creator_price", 1000, 1250, "Creator", 
                        "Creator plan", hidden=False, max_accrual=None, interval="month"),
        create_mock_price("price_creator_overage", "creator_overage_price", 8, 0, "Creator Overage", 
                        "Creator overage", hidden=False, max_accrual=None, interval="month"),
        create_mock_price("price_unlimited", "unlimited_price", 0, -1, "Unlimited", 
                        "Unlimited tokens", hidden=True, max_accrual=None, interval="month"),
    ]
    
    mock_list_result = Mock()
    mock_list_result.auto_paging_iter.return_value = mock_prices
    
    # Patch stripe module and Price.list directly to ensure it works even when tests patch stripe
    # Use patch.object to patch Price.list directly on the stripe module
    import stripe as stripe_module
    from app.services import stripe_service
    from app.core.config import settings
    from datetime import datetime, timezone
    
    # ROOT CAUSE FIX: Pre-populate StripeRegistry._cache with mock plan configurations
    # This ensures tests work even if sync() returns early due to missing STRIPE_SECRET_KEY
    def populate_stripe_registry_cache():
        """Pre-populate StripeRegistry cache with mock plan configurations"""
        from app.services.stripe_service import StripeRegistry
        
        # Build cache entries matching the structure created by sync()
        cache_entries = {
            "free_price": {
                "price_id": "price_free",
                "product_id": "prod_free",
                "name": "Free",
                "description": "Free plan",
                "tokens": 10,
                "hidden": False,
                "max_accrual": None,
                "recurring_interval": "month",
                "amount_dollars": 0.0,
                "currency": "USD",
                "formatted": "Free"
            },
            "free_daily_price": {
                "price_id": "price_free_daily",
                "product_id": "prod_free_daily",
                "name": "Free Daily",
                "description": "3 tokens per day",
                "tokens": 3,
                "hidden": False,
                "max_accrual": 10,
                "recurring_interval": "day",
                "amount_dollars": 0.0,
                "currency": "USD",
                "formatted": "Free"
            },
            "starter_price": {
                "price_id": "price_starter",
                "product_id": "prod_starter",
                "name": "Starter",
                "description": "Starter plan",
                "tokens": 300,
                "hidden": False,
                "max_accrual": None,
                "recurring_interval": "month",
                "amount_dollars": 3.0,
                "currency": "USD",
                "formatted": "$3.00"
            },
            "starter_overage_price": {
                "price_id": "price_starter_overage",
                "product_id": "prod_starter_overage",
                "name": "Starter Overage",
                "description": "Starter overage",
                "tokens": 0,
                "hidden": False,
                "max_accrual": None,
                "recurring_interval": "month",
                "amount_dollars": 0.015,
                "currency": "USD",
                "formatted": "$0.02"
            },
            "creator_price": {
                "price_id": "price_creator",
                "product_id": "prod_creator",
                "name": "Creator",
                "description": "Creator plan",
                "tokens": 1250,
                "hidden": False,
                "max_accrual": None,
                "recurring_interval": "month",
                "amount_dollars": 10.0,
                "currency": "USD",
                "formatted": "$10.00"
            },
            "creator_overage_price": {
                "price_id": "price_creator_overage",
                "product_id": "prod_creator_overage",
                "name": "Creator Overage",
                "description": "Creator overage",
                "tokens": 0,
                "hidden": False,
                "max_accrual": None,
                "recurring_interval": "month",
                "amount_dollars": 0.008,
                "currency": "USD",
                "formatted": "$0.01"
            },
            "unlimited_price": {
                "price_id": "price_unlimited",
                "product_id": "prod_unlimited",
                "name": "Unlimited",
                "description": "Unlimited tokens",
                "tokens": -1,
                "hidden": True,
                "max_accrual": None,
                "recurring_interval": "month",
                "amount_dollars": 0.0,
                "currency": "USD",
                "formatted": "Free"
            }
        }
        
        # Populate cache and set last_sync to prevent sync() from running
        StripeRegistry._cache = cache_entries
        StripeRegistry._last_sync = datetime.now(timezone.utc)
        StripeRegistry._sync_attempts = 0
    
    # Store original Price.list if it exists
    original_price_list = getattr(stripe_module.Price, 'list', None)
    
    # Patch stripe module and ensure Price.list is always available
    # The key issue: when tests patch stripe, they create a new Mock without Price.list
    # Solution: patch Price.list on the actual module AND ensure mocks have it
    def setup_price_list(mock_obj):
        """Helper to ensure Price.list is set up on a mock object"""
        if not hasattr(mock_obj, 'Price'):
            mock_obj.Price = Mock()
        mock_obj.Price.list = Mock(return_value=mock_list_result)
        return mock_obj
    
    # ROOT CAUSE FIX: The code does `stripe.Price.list()` where `stripe` is imported in stripe_service.py
    # When tests patch `app.services.stripe_service.stripe`, they replace that reference with a new Mock
    # That new Mock doesn't have Price.list, so sync fails.
    #
    # Solution: Use patch.object to patch Price.list on stripe_service.stripe.Price so it persists
    # even when tests patch stripe. We also need to ensure that when tests patch stripe and create
    # a new Mock, that Mock automatically gets Price.list set up. We do this by patching it on
    # the module reference and using a PropertyMock or ensuring it's always available.
    
    # Create a helper function that ensures Price.list is always available
    def ensure_price_list(mock_obj):
        """Ensure Price.list is available on a mock object"""
        if not hasattr(mock_obj, 'Price'):
            mock_obj.Price = Mock()
        if not hasattr(mock_obj.Price, 'list'):
            mock_obj.Price.list = Mock(return_value=mock_list_result)
        return mock_obj
    
    # ROOT CAUSE FIX: Patch settings.STRIPE_SECRET_KEY to prevent sync() from returning early
    # and pre-populate StripeRegistry cache before any tests run
    with patch.object(settings, 'STRIPE_SECRET_KEY', 'sk_test_mock_key'), \
         patch.object(stripe_module.Price, 'list', return_value=mock_list_result, create=True), \
         patch('app.services.stripe_service.stripe') as mock_stripe_module:
        # Pre-populate StripeRegistry cache immediately
        populate_stripe_registry_cache()
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
        
        # Set up Price.list on the mock_stripe_module for StripeRegistry.sync()
        setup_price_list(mock_stripe_module)
        ensure_price_list(mock_stripe_module)
        
        # CRITICAL FIX: Ensure Price.list is always available on stripe_service.stripe.Price
        # When tests patch stripe, they replace the reference with a new Mock. That new Mock
        # doesn't have Price.list, so when sync() calls stripe.Price.list(), it fails.
        #
        # Solution: Use patch.object to patch Price.list on stripe_service.stripe.Price.
        # This patches the attribute on the Price object at that reference. When tests patch
        # stripe, they replace the reference, but if they don't replace Price, our patch will
        # still be active. However, if they create a completely new Mock without Price, we
        # need to ensure it's set up.
        #
        # We ensure Price exists on stripe_service.stripe first, then patch Price.list.
        ensure_price_list(stripe_service.stripe)
        
        # Patch Price.list on stripe_service.stripe.Price using patch.object
        # This ensures it's available even when tests patch stripe (unless they replace Price)
        # We use create=True to create the attribute if it doesn't exist
        if hasattr(stripe_service.stripe, 'Price'):
            price_list_patcher = patch.object(
                stripe_service.stripe.Price, 
                'list', 
                return_value=mock_list_result,
                create=True
            )
            price_list_patcher.start()
        else:
            # If Price doesn't exist, create it and set up list
            stripe_service.stripe.Price = Mock()
            stripe_service.stripe.Price.list = Mock(return_value=mock_list_result)
            price_list_patcher = None
        
        # Mock error classes
        mock_stripe_module.error.SignatureVerificationError = Exception
        mock_stripe_module.error.InvalidRequestError = Exception
        
        try:
            yield mock_stripe_module
        finally:
            # Clean up the price_list_patcher if it was created
            if 'price_list_patcher' in locals() and price_list_patcher is not None:
                price_list_patcher.stop()


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


def create_test_video(user_id: int, filename: str, path: str, status: str = "pending", **kwargs):
    """Helper function to create a Video object with platform_statuses initialized
    
    Args:
        user_id: User ID
        filename: Video filename
        path: Video file path (R2 object key)
        status: Video status (default: "pending")
        **kwargs: Additional Video attributes (e.g., custom_settings, file_size_bytes)
    
    Returns:
        Video object with platform_statuses initialized
    """
    from app.models.video import Video
    from datetime import datetime, timezone
    
    # Initialize custom_settings with platform_statuses if not provided
    custom_settings = kwargs.pop('custom_settings', {})
    if not isinstance(custom_settings, dict):
        custom_settings = {}
    
    # Ensure platform_statuses exists (merge with existing if provided)
    if "platform_statuses" not in custom_settings:
        custom_settings["platform_statuses"] = {
            "youtube": {"status": "pending", "error": None, "updated_at": datetime.now(timezone.utc).isoformat()},
            "tiktok": {"status": "pending", "error": None, "updated_at": datetime.now(timezone.utc).isoformat()},
            "instagram": {"status": "pending", "error": None, "updated_at": datetime.now(timezone.utc).isoformat()}
        }
    else:
        # Merge platform_statuses - ensure all platforms are present
        platform_statuses = custom_settings["platform_statuses"]
        default_platforms = {
            "youtube": {"status": "pending", "error": None, "updated_at": datetime.now(timezone.utc).isoformat()},
            "tiktok": {"status": "pending", "error": None, "updated_at": datetime.now(timezone.utc).isoformat()},
            "instagram": {"status": "pending", "error": None, "updated_at": datetime.now(timezone.utc).isoformat()}
        }
        for platform, default_status in default_platforms.items():
            if platform not in platform_statuses:
                platform_statuses[platform] = default_status
    
    return Video(
        user_id=user_id,
        filename=filename,
        path=path,
        status=status,
        custom_settings=custom_settings,
        **kwargs
    )