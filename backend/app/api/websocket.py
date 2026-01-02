"""WebSocket API endpoint for real-time updates"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Cookie

from app.db.redis import async_get_session, async_set_user_activity
from app.services.websocket_service import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


async def get_user_id_from_session(session_id: str) -> int:
    """Get user_id from session cookie for WebSocket authentication (async)"""
    if not session_id:
        raise ValueError("No session_id provided")
    
    user_id = await async_get_session(session_id)
    if not user_id:
        raise ValueError("Invalid or expired session")
    
    return user_id


@router.websocket("")
async def websocket_endpoint(websocket: WebSocket, session_id: str = Cookie(None)):
    """WebSocket endpoint for real-time updates
    
    Authenticates using session cookie and forwards Redis pub/sub events to client.
    """
    logger.info(f"WebSocket connection attempt, session_id present: {session_id is not None}")
    await websocket.accept()
    logger.info("WebSocket accepted")
    
    user_id = None
    try:
        # Authenticate using session cookie
        if not session_id:
            logger.warning("WebSocket connection rejected: no session_id")
            await websocket.close(code=1008, reason="Authentication required")
            return
        
        logger.info(f"Authenticating websocket with session_id: {session_id[:16]}...")
        user_id = await get_user_id_from_session(session_id)
        logger.info(f"✓ WebSocket authenticated for user_id: {user_id}")
        
        # Track user activity
        try:
            await async_set_user_activity(user_id)
            logger.debug(f"✓ User activity tracked for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to track activity for user {user_id}: {e}")
        
        # Register connection
        logger.info(f"Registering websocket connection for user {user_id}...")
        await websocket_manager.connect(user_id, websocket)
        logger.info(f"✓ WebSocket manager registered connection for user {user_id}")
        
        # Send initial connection confirmation
        logger.info(f"Sending 'connected' event to user {user_id}...")
        await websocket.send_json({
            "event": "connected",
            "payload": {"user_id": user_id}
        })
        logger.info(f"✓ Sent 'connected' event to user {user_id}")
        
        # Keep connection alive and handle incoming messages
        logger.info(f"Entering WebSocket message loop for user {user_id}")
        while True:
            try:
                # Wait for any message (client can send pings)
                data = await websocket.receive_text()
                logger.debug(f"WebSocket received message from user {user_id}: {data[:50]}")
                
                # Handle ping/pong for keepalive
                if data == "ping":
                    await websocket.send_text("pong")
                    logger.debug(f"Sent pong to user {user_id}")
                    
            except WebSocketDisconnect as e:
                logger.info(f"WebSocket disconnect for user {user_id}: code={e.code if hasattr(e, 'code') else 'unknown'}")
                break
            except Exception as e:
                logger.error(f"Error in WebSocket connection for user {user_id}: {e}", exc_info=True)
                break
                
    except ValueError as e:
        logger.warning(f"WebSocket authentication failed: {e}")
        try:
            await websocket.close(code=1008, reason=str(e))
        except Exception as close_err:
            logger.error(f"Failed to close websocket after auth failure: {close_err}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception as close_err:
            logger.error(f"Failed to close websocket after error: {close_err}")
    finally:
        # Clean up connection
        if user_id:
            logger.info(f"Cleaning up WebSocket connection for user {user_id}")
            await websocket_manager.disconnect(user_id, websocket)
        else:
            logger.info("WebSocket cleanup: no user_id found (connection may have failed early)")

