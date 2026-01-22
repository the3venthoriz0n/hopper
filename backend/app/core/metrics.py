"""Prometheus metrics for the application"""
try:
    from prometheus_client import Counter, Gauge, REGISTRY
    
    # Upload metrics
    try:
        successful_uploads_counter = Counter(
            'hopper_successful_uploads_total',
            'Total number of successful video uploads'
        )
    except ValueError:
        successful_uploads_counter = REGISTRY._names_to_collectors.get('hopper_successful_uploads_total')
    
    try:
        failed_uploads_gauge = Gauge(
            'hopper_failed_uploads',
            'Number of failed video uploads'
        )
    except ValueError:
        failed_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_failed_uploads')
    
    try:
        cancelled_uploads_gauge = Gauge(
            'hopper_cancelled_uploads',
            'Number of cancelled video uploads'
        )
    except ValueError:
        cancelled_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_cancelled_uploads')
    
    # Scheduler metrics
    try:
        scheduler_runs_counter = Counter(
            'hopper_scheduler_runs_total',
            'Total number of scheduler job runs',
            ['status']
        )
    except ValueError:
        scheduler_runs_counter = REGISTRY._names_to_collectors.get('hopper_scheduler_runs_total')
    
    try:
        scheduler_videos_processed_counter = Counter(
            'hopper_scheduler_videos_processed_total',
            'Total number of videos processed by scheduler'
        )
    except ValueError:
        scheduler_videos_processed_counter = REGISTRY._names_to_collectors.get('hopper_scheduler_videos_processed_total')
    
    # Cleanup metrics
    try:
        cleanup_runs_counter = Counter(
            'hopper_cleanup_runs_total',
            'Total number of cleanup job runs',
            ['status']
        )
    except ValueError:
        cleanup_runs_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_runs_total')
    
    try:
        cleanup_files_removed_counter = Counter(
            'hopper_cleanup_files_removed_total',
            'Total number of files removed by cleanup job'
        )
    except ValueError:
        cleanup_files_removed_counter = REGISTRY._names_to_collectors.get('hopper_cleanup_files_removed_total')
    
    try:
        orphaned_videos_gauge = Gauge(
            'hopper_orphaned_videos',
            'Number of orphaned video files (files without database records)'
        )
    except ValueError:
        orphaned_videos_gauge = REGISTRY._names_to_collectors.get('hopper_orphaned_videos')
    
    try:
        storage_size_gauge = Gauge(
            'hopper_storage_size_bytes',
            'Storage size in bytes',
            ['type']
        )
    except ValueError:
        storage_size_gauge = REGISTRY._names_to_collectors.get('hopper_storage_size_bytes')
    
    # Auth metrics
    try:
        login_attempts_counter = Counter(
            'hopper_login_attempts_total',
            'Total number of login attempts',
            ['status', 'method']
        )
    except ValueError:
        login_attempts_counter = REGISTRY._names_to_collectors.get('hopper_login_attempts_total')
    
    # User activity metrics
    try:
        active_users_gauge = Gauge(
            'hopper_active_users',
            'Number of active users (made requests within last hour)'
        )
    except ValueError:
        active_users_gauge = REGISTRY._names_to_collectors.get('hopper_active_users')
    
    try:
        active_users_detail_gauge = Gauge(
            'hopper_active_users_detail',
            'Active users with email and last activity time',
            ['user_id', 'user_email', 'last_activity']
        )
    except ValueError:
        active_users_detail_gauge = REGISTRY._names_to_collectors.get('hopper_active_users_detail')
    
    # Upload status metrics
    try:
        current_uploads_gauge = Gauge(
            'hopper_current_uploads',
            'Number of videos currently being uploaded'
        )
    except ValueError:
        current_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_current_uploads')
    
    try:
        queued_uploads_gauge = Gauge(
            'hopper_queued_uploads',
            'Number of videos queued for upload (pending)'
        )
    except ValueError:
        queued_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_queued_uploads')
    
    try:
        scheduled_uploads_gauge = Gauge(
            'hopper_scheduled_uploads',
            'Number of videos scheduled for upload'
        )
    except ValueError:
        scheduled_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_scheduled_uploads')
    
    try:
        scheduled_uploads_detail_gauge = Gauge(
            'hopper_scheduled_uploads_detail',
            'Scheduled uploads with scheduled time and created date',
            ['user_id', 'user_email', 'filename', 'video_title', 'scheduled_time', 'created_at', 'status']
        )
    except ValueError:
        scheduled_uploads_detail_gauge = REGISTRY._names_to_collectors.get('hopper_scheduled_uploads_detail')
    
    try:
        user_uploads_gauge = Gauge(
            'hopper_user_uploads',
            'Number of uploads per user by status',
            ['user_id', 'user_email', 'status']
        )
    except ValueError:
        user_uploads_gauge = REGISTRY._names_to_collectors.get('hopper_user_uploads')
    
    # Subscription metrics
    try:
        active_subscriptions_gauge = Gauge(
            'hopper_active_subscriptions',
            'Number of active subscriptions by plan type',
            ['plan_type']
        )
    except ValueError:
        active_subscriptions_gauge = REGISTRY._names_to_collectors.get('hopper_active_subscriptions')
        
except ImportError:
    # Prometheus not available - create no-op metrics
    class NoOpCounter:
        def labels(self, **kwargs):
            return self
        def inc(self, value=1):
            pass
    
    class NoOpGauge:
        def labels(self, **kwargs):
            return self
        def inc(self, value=1):
            pass
        def set(self, value):
            pass
    
    successful_uploads_counter = NoOpCounter()
    failed_uploads_gauge = NoOpGauge()
    cancelled_uploads_gauge = NoOpGauge()
    scheduler_runs_counter = NoOpCounter()
    scheduler_videos_processed_counter = NoOpCounter()
    cleanup_runs_counter = NoOpCounter()
    cleanup_files_removed_counter = NoOpCounter()
    orphaned_videos_gauge = NoOpGauge()
    storage_size_gauge = NoOpGauge()
    login_attempts_counter = NoOpCounter()
    active_users_gauge = NoOpGauge()
    active_users_detail_gauge = NoOpGauge()
    current_uploads_gauge = NoOpGauge()
    queued_uploads_gauge = NoOpGauge()
    scheduled_uploads_gauge = NoOpGauge()
    scheduled_uploads_detail_gauge = NoOpGauge()
    user_uploads_gauge = NoOpGauge()
    active_subscriptions_gauge = NoOpGauge()


def update_active_users_gauge_from_sessions() -> int:
    """
    Recalculate and update the active users gauge based on recent activity.
    
    Uses activity heartbeat keys (activity:{user_id}) which have a 1-hour TTL.
    This tracks users who have made requests within the last hour, not just
    users with valid sessions (which can last 30 days).
    """
    try:
        from app.db.redis import get_active_user_ids
    except Exception:
        # Fallback if import fails
        return 0
    
    # Get active user IDs from activity keys (simple and extensible)
    active_user_ids = get_active_user_ids()
    active_users = len(active_user_ids)
    
    try:
        active_users_gauge.set(active_users)
    except Exception:
        # Never let metric updates break auth flow
        pass
    
    return active_users


def update_active_users_detail_gauge(active_users_data: dict, db) -> None:
    """
    Update the active_users_detail_gauge with user emails and last activity timestamps.
    
    Args:
        active_users_data: Dict mapping user_id to ISO timestamp string
        db: Database session to query user emails
    """
    try:
        from app.models.user import User
        
        # Clear existing gauge data by clearing all label combinations
        active_users_detail_gauge._metrics.clear()
        
        # Track processed user_ids to prevent duplicates
        processed_user_ids = set()
        
        # Populate gauge with current active users
        for user_id, last_activity in active_users_data.items():
            # Skip if we've already processed this user_id (deduplicate)
            if user_id in processed_user_ids:
                continue
            
            try:
                # Get user email from database
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    # Set gauge with labels - value is always 1 (user is active)
                    active_users_detail_gauge.labels(
                        user_id=str(user_id),
                        user_email=user.email,
                        last_activity=last_activity
                    ).set(1)
                    processed_user_ids.add(user_id)
            except Exception as e:
                # Skip users that cause errors but continue processing others
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to update metrics for user {user_id}: {e}")
                continue
    except Exception as e:
        # Never let metric updates break the metrics endpoint
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to update active_users_detail_gauge: {e}", exc_info=True)


def update_scheduled_uploads_detail_gauge(db) -> None:
    """
    Update the scheduled_uploads_detail_gauge with scheduled videos and their details.
    
    Args:
        db: Database session to query scheduled videos
    """
    try:
        from app.models.video import Video
        from app.models.user import User
        from datetime import datetime, timezone
        
        # Query all scheduled videos with their user information
        scheduled_videos = db.query(Video, User).join(
            User, Video.user_id == User.id
        ).filter(
            Video.status == 'scheduled',
            Video.scheduled_time.isnot(None)
        ).all()
        
        # Clear existing gauge data by clearing all label combinations
        scheduled_uploads_detail_gauge._metrics.clear()
        
        # Populate gauge with current scheduled videos
        for video, user in scheduled_videos:
            try:
                # Format timestamps as ISO strings for Prometheus labels
                scheduled_time_str = video.scheduled_time.isoformat() if video.scheduled_time else ""
                created_at_str = video.created_at.isoformat() if video.created_at else ""
                
                # Get video title (fallback to filename if title is None)
                video_title = video.generated_title if video.generated_title else video.filename
                
                # Set gauge with labels - value is always 1 (video is scheduled)
                scheduled_uploads_detail_gauge.labels(
                    user_id=str(video.user_id),
                    user_email=user.email,
                    filename=video.filename,
                    video_title=video_title,
                    scheduled_time=scheduled_time_str,
                    created_at=created_at_str,
                    status=video.status
                ).set(1)
            except Exception as e:
                # Skip videos that cause errors but continue processing others
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to update metrics for video {video.id}: {e}")
                continue
    except Exception as e:
        # Never let metric updates break the metrics endpoint
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to update scheduled_uploads_detail_gauge: {e}", exc_info=True)


def update_active_subscriptions_gauge(db) -> None:
    """
    Update the active_subscriptions_gauge with counts of active subscriptions by plan type.
    
    Args:
        db: Database session to query subscriptions
    """
    try:
        from app.models.subscription import Subscription
        from sqlalchemy import func
        
        # Query active subscriptions grouped by plan_type
        results = db.query(
            Subscription.plan_type,
            func.count(Subscription.id).label('count')
        ).filter(
            Subscription.status == 'active'
        ).group_by(
            Subscription.plan_type
        ).all()
        
        # Clear existing gauge data by clearing all label combinations
        active_subscriptions_gauge._metrics.clear()
        
        # Populate gauge with current active subscriptions
        for plan_type, count in results:
            try:
                # Set gauge with plan_type label
                active_subscriptions_gauge.labels(plan_type=plan_type).set(count)
            except Exception as e:
                # Skip plan types that cause errors but continue processing others
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to update metrics for plan_type {plan_type}: {e}")
                continue
    except Exception as e:
        # Never let metric updates break the metrics endpoint
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to update active_subscriptions_gauge: {e}", exc_info=True)


def update_upload_status_gauges(db) -> None:
    """
    Update upload status gauges by querying database for video counts by status.
    
    Args:
        db: Database session to query videos
    """
    try:
        from app.models.video import Video
        from sqlalchemy import func
        
        # Query video counts grouped by status
        results = db.query(
            Video.status,
            func.count(Video.id).label('count')
        ).group_by(
            Video.status
        ).all()
        
        # Initialize counts
        queued_count = 0
        scheduled_count = 0
        current_count = 0
        failed_count = 0
        cancelled_count = 0
        
        # Aggregate counts by status
        for status, count in results:
            if status == 'pending':
                queued_count = count
            elif status == 'scheduled':
                scheduled_count = count
            elif status == 'uploading':
                current_count = count
            elif status == 'failed':
                failed_count = count
            elif status == 'cancelled':
                cancelled_count = count
        
        # Update gauges
        try:
            queued_uploads_gauge.set(queued_count)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to update queued_uploads_gauge: {e}")
        
        try:
            scheduled_uploads_gauge.set(scheduled_count)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to update scheduled_uploads_gauge: {e}")
        
        try:
            current_uploads_gauge.set(current_count)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to update current_uploads_gauge: {e}")
        
        try:
            failed_uploads_gauge.set(failed_count)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to update failed_uploads_gauge: {e}")
        
        try:
            cancelled_uploads_gauge.set(cancelled_count)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to update cancelled_uploads_gauge: {e}")
            
    except Exception as e:
        # Never let metric updates break the metrics endpoint
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to update upload_status_gauges: {e}", exc_info=True)