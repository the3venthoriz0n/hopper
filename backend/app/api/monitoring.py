"""Monitoring API routes for health checks and metrics"""
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["monitoring"])


@router.get("/metrics")
def metrics_endpoint():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

