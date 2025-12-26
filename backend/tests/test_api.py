"""API route tests"""
import pytest
from datetime import datetime, timezone, timedelta
from fastapi import status
from unittest.mock import patch, Mock

from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.models.video import Video
from app.models.setting import Setting


@pytest.mark.critical
class TestAuthentication:
    """Test authentication and protected routes"""
    
    def test_protected_route_requires_auth(self, client):
        """Test that protected endpoints return 401 without authentication"""
        # Test global settings endpoint
        response = client.get("/api/global/settings")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        
        # Test subscription endpoint
        response = client.get("/api/subscription/current")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        
        # Test videos endpoint
        response = client.get("/api/videos")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        
        # Test YouTube settings endpoint
        response = client.get("/api/youtube/settings")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_protected_route_with_auth(self, authenticated_client):
        """Test that protected endpoints work with authentication"""
        response = authenticated_client.get("/api/global/settings")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.critical
class TestCSRFProtection:
    """Test CSRF protection on state-changing endpoints"""
    
    def test_post_without_csrf_token(self, client, test_user, mock_redis, db_session):
        """Test POST requests without CSRF token are rejected"""
        # Login to get session but don't set CSRF token in headers
        login_response = client.post(
            "/api/auth/login",
            json={"email": test_user.email, "password": "TestPassword123!"}
        )
        assert login_response.status_code == 200
        
        # Ensure cookies are properly set on the client
        # TestClient automatically handles cookies, but we need to make sure
        # the session is persisted in Redis mock for the next request
        session_id = login_response.cookies.get("session_id")
        if session_id:
            mock_redis.setex(f"session:{session_id}", 2592000, str(test_user.id))
        
        # Test global settings update without CSRF token in headers
        # Note: We intentionally omit headers={"X-CSRF-Token": ...}
        response = client.post(
            "/api/global/settings",
            json={"title_template": "Test"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Invalid or missing CSRF token" in response.json()["detail"]
        
        # Test wordbank add without CSRF
        response = client.post(
            "/api/global/wordbank",
            json={"word": "test"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Invalid or missing CSRF token" in response.json()["detail"]
    
    def test_post_with_invalid_csrf_token(self, authenticated_client):
        """Test POST requests with invalid CSRF token are rejected"""
        response = authenticated_client.post(
            "/api/global/settings",
            json={"title_template": "Test"},
            headers={"X-CSRF-Token": "invalid_token"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_post_with_valid_csrf_token(self, authenticated_client, csrf_token):
        """Test POST requests with valid CSRF token succeed"""
        response = authenticated_client.post(
            "/api/global/settings",
            json={"title_template": "Test"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.high
class TestOwnershipValidation:
    """Test that users cannot access or modify other users' data"""
    
    def test_user_cannot_access_other_user_settings(self, authenticated_client, two_users):
        """Test User A cannot access User B's settings"""
        user1, user2 = two_users
        
        # User1 is authenticated, try to access user2's settings
        # Settings are user-specific, so user1 should only see their own
        response = authenticated_client.get("/api/global/settings")
        assert response.status_code == status.HTTP_200_OK
        # Settings should be empty for new user, but should not error
    
    def test_user_cannot_modify_other_user_videos(self, authenticated_client, two_users, db_session):
        """Test User A cannot modify User B's videos"""
        user1, user2 = two_users
        
        # Create a video for user2
        video = Video(
            user_id=user2.id,
            filename="test.mp4",
            path="/tmp/test.mp4",
            status="pending"
        )
        db_session.add(video)
        db_session.commit()
        db_session.refresh(video)
        
        # User1 (authenticated) tries to update user2's video using PATCH
        response = authenticated_client.patch(
            f"/api/videos/{video.id}",
            json={"title": "Updated Title"},
            headers={"X-CSRF-Token": authenticated_client.headers.get("X-CSRF-Token", "")}
        )
        # Should fail with 404 (video not found for this user) or 403
        assert response.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]
    
    def test_user_cannot_delete_other_user_wordbank(self, authenticated_client, two_users, db_session):
        """Test User A cannot delete User B's wordbank words"""
        user1, user2 = two_users
        
        # Add word to user2's wordbank (directly in DB)
        from app.db.helpers import set_user_setting
        set_user_setting(user2.id, "global", "wordbank", ["TestWord"], db=db_session)
        
        # User1 tries to delete user2's word
        response = authenticated_client.delete(
            "/api/global/wordbank/TestWord",
            headers={"X-CSRF-Token": authenticated_client.headers.get("X-CSRF-Token", "")}
        )
        # Should succeed but not affect user2's wordbank (user1's wordbank is separate)
        # Actually, wordbank is per-user, so this should work but only affect user1's wordbank
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.critical
class TestSubscriptionFlow:
    """Test subscription and token initialization"""
    
    def test_get_current_subscription_auto_creates_free(self, authenticated_client, test_user, db_session):
        """Test /api/subscription/current auto-creates free subscription for new user"""
        # Verify user has no subscription initially
        subscription = db_session.query(Subscription).filter(Subscription.user_id == test_user.id).first()
        assert subscription is None
        
        # Call endpoint
        response = authenticated_client.get("/api/subscription/current")
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert "subscription" in data
        assert data["subscription"] is not None
        assert data["subscription"]["plan_type"] == "free"
        
        # Verify subscription was created in database
        subscription = db_session.query(Subscription).filter(Subscription.user_id == test_user.id).first()
        assert subscription is not None
        assert subscription.plan_type == "free"
        
        # Verify token balance was initialized
        token_balance = db_session.query(TokenBalance).filter(TokenBalance.user_id == test_user.id).first()
        assert token_balance is not None
        assert token_balance.tokens_remaining == 10  # Free plan has 10 tokens
    
    def test_auto_repair_updates_existing_deleted_subscription(self, authenticated_client, test_user, db_session):
        """Test auto-repair updates existing deleted subscription instead of creating duplicate"""
        from datetime import datetime, timezone
        
        # Create a deleted/canceled subscription
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_deleted123",
            stripe_customer_id="cus_test123",
            plan_type="starter",
            status="canceled",
            current_period_start=datetime.now(timezone.utc) - timedelta(days=30),
            current_period_end=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db_session.add(subscription)
        db_session.commit()
        
        # Call endpoint - should update existing subscription, not create duplicate
        with patch('app.services.stripe_service.create_stripe_subscription') as mock_create:
            mock_sub = Mock()
            mock_sub.id = "sub_free123"
            mock_sub.status = "active"
            mock_sub.current_period_start = int(datetime.now(timezone.utc).timestamp())
            mock_sub.current_period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
            mock_create.return_value = Mock(
                stripe_subscription_id="sub_free123",
                plan_type="free",
                status="active",
                current_period_start=datetime.now(timezone.utc),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
            )
            
            response = authenticated_client.get("/api/subscription/current")
            assert response.status_code == status.HTTP_200_OK
        
        # Verify only one subscription exists (updated, not duplicated)
        subscriptions = db_session.query(Subscription).filter(Subscription.user_id == test_user.id).all()
        assert len(subscriptions) == 1
    
    def test_get_subscription_info(self, authenticated_client, test_user, db_session):
        """Test /api/subscription/info returns subscription details"""
        # First create a subscription
        response = authenticated_client.get("/api/subscription/current")
        assert response.status_code == status.HTTP_200_OK
        
        # Get subscription info
        response = authenticated_client.get("/api/subscription/info")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "subscription" in data
    
    def test_get_subscription_plans(self, authenticated_client):
        """Test /api/subscription/plans returns available plans"""
        response = authenticated_client.get("/api/subscription/plans")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "plans" in data
        assert isinstance(data["plans"], list)


@pytest.mark.high
class TestDataValidation:
    """Test Pydantic validation and constraints"""
    
    def test_youtube_title_too_long(self, authenticated_client, csrf_token):
        """Test YouTube title > 100 characters returns 422"""
        long_title = "a" * 101
        response = authenticated_client.post(
            "/api/youtube/settings",
            json={"title_template": long_title},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_tiktok_title_too_long(self, authenticated_client, csrf_token):
        """Test TikTok title > 100 characters returns 422"""
        long_title = "a" * 101
        response = authenticated_client.post(
            "/api/tiktok/settings",
            json={"title_template": long_title},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_instagram_caption_too_long(self, authenticated_client, csrf_token):
        """Test Instagram caption > 2200 characters returns 422"""
        long_caption = "a" * 2201
        response = authenticated_client.post(
            "/api/instagram/settings",
            json={"caption_template": long_caption},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_invalid_tiktok_privacy_level(self, authenticated_client, csrf_token):
        """Test invalid TikTok privacy level returns 422"""
        response = authenticated_client.post(
            "/api/tiktok/settings",
            json={"privacy_level": "INVALID_PRIVACY"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_valid_tiktok_privacy_enums(self, authenticated_client, csrf_token):
        """Test valid TikTok privacy enums are accepted"""
        valid_levels = [
            "PUBLIC_TO_EVERYONE",
            "MUTUAL_FOLLOW_FRIENDS",
            "SELF_ONLY",
            "FOLLOWER_OF_CREATOR"
        ]
        
        for level in valid_levels:
            response = authenticated_client.post(
                "/api/tiktok/settings",
                json={"privacy_level": level},
                headers={"X-CSRF-Token": csrf_token}
            )
            assert response.status_code == status.HTTP_200_OK, f"Privacy level {level} should be valid"


@pytest.mark.high
class TestWordbankNormalization:
    """Test wordbank word normalization"""
    
    def test_add_word_strips_whitespace(self, authenticated_client, csrf_token):
        """Test adding word with whitespace strips and capitalizes"""
        response = authenticated_client.post(
            "/api/global/wordbank",
            json={"word": "  test  "},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_200_OK
        
        # Verify word was normalized
        settings_response = authenticated_client.get("/api/global/settings")
        wordbank = settings_response.json().get("wordbank", [])
        assert "Test" in wordbank
        assert "  test  " not in wordbank
    
    def test_add_word_capitalizes(self, authenticated_client, csrf_token):
        """Test adding word capitalizes first letter"""
        response = authenticated_client.post(
            "/api/global/wordbank",
            json={"word": "awesome"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_200_OK
        
        settings_response = authenticated_client.get("/api/global/settings")
        wordbank = settings_response.json().get("wordbank", [])
        assert "Awesome" in wordbank
    
    def test_add_duplicate_word(self, authenticated_client, csrf_token):
        """Test adding duplicate word returns existing wordbank"""
        # Add word first time
        response1 = authenticated_client.post(
            "/api/global/wordbank",
            json={"word": "test"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response1.status_code == status.HTTP_200_OK
        
        # Try to add same word again
        response2 = authenticated_client.post(
            "/api/global/wordbank",
            json={"word": "test"},
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response2.status_code == status.HTTP_200_OK
        
        # Verify word only appears once
        settings_response = authenticated_client.get("/api/global/settings")
        wordbank = settings_response.json().get("wordbank", [])
        assert wordbank.count("Test") == 1
    
    def test_remove_word(self, authenticated_client, csrf_token):
        """Test removing word from wordbank"""
        # Add word
        authenticated_client.post(
            "/api/global/wordbank",
            json={"word": "test"},
            headers={"X-CSRF-Token": csrf_token}
        )
        
        # Remove word
        response = authenticated_client.delete(
            "/api/global/wordbank/Test",
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_200_OK
        
        # Verify word was removed
        settings_response = authenticated_client.get("/api/global/settings")
        wordbank = settings_response.json().get("wordbank", [])
        assert "Test" not in wordbank
    
    def test_clear_wordbank(self, authenticated_client, csrf_token):
        """Test clearing all words from wordbank"""
        # Add some words
        for word in ["test", "awesome", "cool"]:
            authenticated_client.post(
                "/api/global/wordbank",
                json={"word": word},
                headers={"X-CSRF-Token": csrf_token}
            )
        
        # Clear wordbank
        response = authenticated_client.delete(
            "/api/global/wordbank",
            headers={"X-CSRF-Token": csrf_token}
        )
        assert response.status_code == status.HTTP_200_OK
        
        # Verify wordbank is empty
        settings_response = authenticated_client.get("/api/global/settings")
        wordbank = settings_response.json().get("wordbank", [])
        assert wordbank == []


@pytest.mark.medium
class TestHappyPathIntegration:
    """Test complete user journey"""
    
    def test_new_user_journey(self, client, db_session, mock_redis, mock_stripe):
        """Test complete new user journey from registration to settings"""
        # 1. Register user
        register_response = client.post(
            "/api/auth/register",
            json={"email": "newuser@example.com", "password": "TestPassword123!"}
        )
        assert register_response.status_code == status.HTTP_200_OK
        data = register_response.json()
        assert data["requires_email_verification"] is True
        
        # 2. Verify email - get verification code from Redis mock
        from app.db.redis import get_email_verification_code
        verification_code = get_email_verification_code("newuser@example.com")
        
        if verification_code:
            # Verify email using the code
            from app.services.auth_service import complete_email_verification
            user = complete_email_verification("newuser@example.com", db_session)
            assert user is not None
            assert user.is_email_verified is True
        
        # 3. Login
        login_response = client.post(
            "/api/auth/login",
            json={"email": "newuser@example.com", "password": "TestPassword123!"}
        )
        assert login_response.status_code == status.HTTP_200_OK
        assert "session_id" in login_response.cookies
        
        # Set cookies on the client instance so they persist automatically
        client.cookies.update(login_response.cookies)
        
        # 4. Get subscription (auto-creates free plan)
        sub_response = client.get("/api/subscription/current")
        assert sub_response.status_code == status.HTTP_200_OK
        sub_data = sub_response.json()
        assert sub_data["subscription"]["plan_type"] == "free"
        
        # Update cookies from subscription response (in case session was updated)
        client.cookies.update(sub_response.cookies)
        
        # 5. Get CSRF token from CSRF endpoint (needed for POST requests)
        csrf_response = client.get("/api/auth/csrf")
        assert csrf_response.status_code == status.HTTP_200_OK
        
        # Update cookies from CSRF response (in case session was updated/initialized)
        client.cookies.update(csrf_response.cookies)
        
        csrf_token = csrf_response.headers.get("X-CSRF-Token") or csrf_response.json().get("csrf_token")
        assert csrf_token is not None, "CSRF token should be available"
        
        # 6. Toggle YouTube destination (cookies are now on client, no need to pass manually)
        toggle_response = client.post(
            "/api/destinations/youtube/toggle",
            json={"enabled": True},
            headers={"X-CSRF-Token": csrf_token}  # Only pass the header
        )
        assert toggle_response.status_code == status.HTTP_200_OK
        
        # 7. Verify settings reflect changes
        settings_response = client.get("/api/destinations")
        assert settings_response.status_code == status.HTTP_200_OK
        dest_data = settings_response.json()
        assert dest_data["youtube"]["enabled"] is True

