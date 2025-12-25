"""Database integrity tests"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.models.subscription import Subscription
from app.models.token_balance import TokenBalance
from app.models.token_transaction import TokenTransaction
from app.models.video import Video
from app.models.setting import Setting
from app.models.oauth_token import OAuthToken
from app.services.auth_service import create_user


@pytest.mark.medium
class TestModelRelationships:
    """Test model relationships"""
    
    def test_user_videos_relationship(self, test_user, db_session):
        """Test User.videos relationship"""
        # Create video for user
        video = Video(
            user_id=test_user.id,
            filename="test.mp4",
            path="/tmp/test.mp4",
            status="pending"
        )
        db_session.add(video)
        db_session.commit()
        
        # Verify relationship
        assert len(test_user.videos) == 1
        assert test_user.videos[0].id == video.id
        assert test_user.videos[0].user_id == test_user.id
    
    def test_user_settings_relationship(self, test_user, db_session):
        """Test User.settings relationship"""
        # Create setting for user
        setting = Setting(
            user_id=test_user.id,
            category="global",
            key="test_key",
            value="test_value"
        )
        db_session.add(setting)
        db_session.commit()
        
        # Verify relationship
        assert len(test_user.settings) == 1
        assert test_user.settings[0].key == "test_key"
    
    def test_user_subscription_relationship(self, test_user, db_session):
        """Test User.subscription relationship (one-to-one)"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        db_session.refresh(test_user)
        
        # Verify relationship
        assert test_user.subscription is not None
        assert test_user.subscription.id == subscription.id
    
    def test_user_token_balance_relationship(self, test_user, db_session):
        """Test User.token_balance relationship (one-to-one)"""
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        db_session.refresh(test_user)
        
        # Verify relationship
        assert test_user.token_balance is not None
        assert test_user.token_balance.id == balance.id
    
    def test_video_token_transactions_relationship(self, test_user, db_session):
        """Test Video.token_transactions relationship"""
        # Create video
        video = Video(
            user_id=test_user.id,
            filename="test.mp4",
            path="/tmp/test.mp4",
            status="pending"
        )
        db_session.add(video)
        db_session.commit()
        
        # Create token transaction for video
        transaction = TokenTransaction(
            user_id=test_user.id,
            video_id=video.id,
            transaction_type="upload",
            tokens=-5,
            balance_before=10,
            balance_after=5
        )
        db_session.add(transaction)
        db_session.commit()
        db_session.refresh(video)
        
        # Verify relationship
        assert len(video.token_transactions) == 1
        assert video.token_transactions[0].id == transaction.id


@pytest.mark.medium
class TestCascadeDeletes:
    """Test cascade delete behavior"""
    
    def test_delete_user_deletes_videos(self, test_user, db_session):
        """Test deleting user deletes all videos"""
        # Create videos for user
        video1 = Video(
            user_id=test_user.id,
            filename="test1.mp4",
            path="/tmp/test1.mp4",
            status="pending"
        )
        video2 = Video(
            user_id=test_user.id,
            filename="test2.mp4",
            path="/tmp/test2.mp4",
            status="pending"
        )
        db_session.add_all([video1, video2])
        db_session.commit()
        
        video_ids = [video1.id, video2.id]
        
        # Delete user
        db_session.delete(test_user)
        db_session.commit()
        
        # Verify videos were deleted
        videos = db_session.query(Video).filter(Video.id.in_(video_ids)).all()
        assert len(videos) == 0
    
    def test_delete_user_deletes_settings(self, test_user, db_session):
        """Test deleting user deletes all settings"""
        # Create settings for user
        setting1 = Setting(
            user_id=test_user.id,
            category="global",
            key="key1",
            value="value1"
        )
        setting2 = Setting(
            user_id=test_user.id,
            category="youtube",
            key="key2",
            value="value2"
        )
        db_session.add_all([setting1, setting2])
        db_session.commit()
        
        setting_ids = [setting1.id, setting2.id]
        
        # Delete user
        db_session.delete(test_user)
        db_session.commit()
        
        # Verify settings were deleted
        settings = db_session.query(Setting).filter(Setting.id.in_(setting_ids)).all()
        assert len(settings) == 0
    
    def test_delete_user_deletes_subscription(self, test_user, db_session):
        """Test deleting user deletes subscription"""
        subscription = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription)
        db_session.commit()
        
        subscription_id = subscription.id
        
        # Delete user
        db_session.delete(test_user)
        db_session.commit()
        
        # Verify subscription was deleted
        subscription = db_session.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        assert subscription is None
    
    def test_delete_user_deletes_token_balance(self, test_user, db_session):
        """Test deleting user deletes token balance"""
        balance = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance)
        db_session.commit()
        
        balance_id = balance.id
        
        # Delete user
        db_session.delete(test_user)
        db_session.commit()
        
        # Verify token balance was deleted
        balance = db_session.query(TokenBalance).filter(
            TokenBalance.id == balance_id
        ).first()
        assert balance is None
    
    def test_delete_user_deletes_token_transactions(self, test_user, db_session):
        """Test deleting user deletes token transactions"""
        transaction1 = TokenTransaction(
            user_id=test_user.id,
            transaction_type="upload",
            tokens=-5,
            balance_before=10,
            balance_after=5
        )
        transaction2 = TokenTransaction(
            user_id=test_user.id,
            transaction_type="grant",
            tokens=10,
            balance_before=0,
            balance_after=10
        )
        db_session.add_all([transaction1, transaction2])
        db_session.commit()
        
        transaction_ids = [transaction1.id, transaction2.id]
        
        # Delete user
        db_session.delete(test_user)
        db_session.commit()
        
        # Verify transactions were deleted
        transactions = db_session.query(TokenTransaction).filter(
            TokenTransaction.id.in_(transaction_ids)
        ).all()
        assert len(transactions) == 0


@pytest.mark.medium
class TestConstraints:
    """Test database constraints"""
    
    def test_unique_email_constraint(self, db_session):
        """Test unique email constraint (duplicate email -> IntegrityError)"""
        # Create first user directly in DB to test constraint
        user1 = User(
            email="duplicate@example.com",
            password_hash="hashed_password"
        )
        db_session.add(user1)
        db_session.commit()
        
        # Try to create second user with same email directly in DB
        with pytest.raises(IntegrityError):
            user2 = User(
                email="duplicate@example.com",
                password_hash="hashed_password2"
            )
            db_session.add(user2)
            db_session.commit()
    
    def test_unique_user_id_in_subscription(self, test_user, db_session):
        """Test unique user_id in Subscription (one subscription per user)"""
        # Create first subscription
        subscription1 = Subscription(
            user_id=test_user.id,
            stripe_subscription_id="sub_test123",
            stripe_customer_id="cus_test123",
            plan_type="free",
            status="active",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(subscription1)
        db_session.commit()
        
        # Try to create second subscription for same user
        with pytest.raises(IntegrityError):
            subscription2 = Subscription(
                user_id=test_user.id,
                stripe_subscription_id="sub_test456",
                stripe_customer_id="cus_test123",
                plan_type="starter",
                status="active",
                current_period_start=datetime.now(timezone.utc),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
            )
            db_session.add(subscription2)
            db_session.commit()
    
    def test_unique_user_id_in_token_balance(self, test_user, db_session):
        """Test unique user_id in TokenBalance (one balance per user)"""
        # Create first balance
        balance1 = TokenBalance(
            user_id=test_user.id,
            tokens_remaining=10,
            tokens_used_this_period=0,
            monthly_tokens=10,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )
        db_session.add(balance1)
        db_session.commit()
        
        # Try to create second balance for same user
        with pytest.raises(IntegrityError):
            balance2 = TokenBalance(
                user_id=test_user.id,
                tokens_remaining=20,
                tokens_used_this_period=0,
                monthly_tokens=20,
                period_start=datetime.now(timezone.utc),
                period_end=datetime.now(timezone.utc) + timedelta(days=30)
            )
            db_session.add(balance2)
            db_session.commit()
    
    def test_foreign_key_constraint_invalid_user_id(self, db_session):
        """Test foreign key constraints (invalid user_id -> IntegrityError)"""
        from sqlalchemy import text
        
        # Enable foreign key constraints in SQLite
        db_session.execute(text("PRAGMA foreign_keys = ON"))
        db_session.commit()
        
        # Try to create subscription with non-existent user_id
        with pytest.raises(IntegrityError):
            subscription = Subscription(
                user_id=99999,  # Non-existent user
                stripe_subscription_id="sub_test123",
                stripe_customer_id="cus_test123",
                plan_type="free",
                status="active",
                current_period_start=datetime.now(timezone.utc),
                current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
            )
            db_session.add(subscription)
            db_session.commit()


@pytest.mark.medium
class TestJSONColumnCompatibility:
    """Test JSON column compatibility with SQLite"""
    
    def test_video_custom_settings_json(self, test_user, db_session):
        """Test Video.custom_settings JSON column stores/retrieves complex structures"""
        complex_settings = {
            "title": "Test Video",
            "tags": ["tag1", "tag2"],
            "metadata": {
                "duration": 120,
                "resolution": {"width": 1920, "height": 1080}
            }
        }
        
        video = Video(
            user_id=test_user.id,
            filename="test.mp4",
            path="/tmp/test.mp4",
            status="pending",
            custom_settings=complex_settings
        )
        db_session.add(video)
        db_session.commit()
        db_session.refresh(video)
        
        # Verify JSON was stored and retrieved correctly
        assert video.custom_settings == complex_settings
        assert video.custom_settings["title"] == "Test Video"
        assert video.custom_settings["tags"] == ["tag1", "tag2"]
        assert video.custom_settings["metadata"]["duration"] == 120
    
    def test_setting_value_json(self, test_user, db_session):
        """Test Setting.value JSON column stores/retrieves data"""
        import json
        
        json_value = {
            "wordbank": ["Test", "Awesome"],
            "template": "{filename} - {random}"
        }
        
        setting = Setting(
            user_id=test_user.id,
            category="global",
            key="wordbank",
            value=json.dumps(json_value)  # Serialize to JSON string
        )
        db_session.add(setting)
        db_session.commit()
        db_session.refresh(setting)
        
        # Verify JSON was stored and retrieved correctly (parse on retrieval)
        parsed_value = json.loads(setting.value)
        assert parsed_value == json_value
        assert parsed_value["wordbank"] == ["Test", "Awesome"]
        assert parsed_value["template"] == "{filename} - {random}"

