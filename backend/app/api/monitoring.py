"""Monitoring API routes for health checks and metrics"""
from fastapi import APIRouter, Response, Depends
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["monitoring"])


@router.get("/metrics")
def metrics_endpoint(db: Session = Depends(get_db)):
    """Prometheus metrics endpoint - updates gauges before export"""
    from app.core.metrics import (
        update_active_users_gauge_from_sessions,
        update_active_users_detail_gauge,
        update_active_subscriptions_gauge,
        update_scheduled_uploads_detail_gauge,
        update_upload_status_gauges
    )
    from app.db.redis import get_active_users_with_timestamps
    from app.models.user import User
    
    # Update simple active users gauge (count only)
    update_active_users_gauge_from_sessions()
    
    # Update detailed active users gauge with current data
    active_users_data = get_active_users_with_timestamps()
    update_active_users_detail_gauge(active_users_data, db)
    
    # Update active subscriptions gauge with current data
    update_active_subscriptions_gauge(db)
    
    # Update scheduled uploads detail gauge with current data
    update_scheduled_uploads_detail_gauge(db)
    
    # Update upload status gauges (queued, scheduled, current, failed)
    update_upload_status_gauges(db)
    
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

