"""WebSocket API endpoint for real-time updates"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Cookie

from app.core.security import get_session
from app.services.websocket_service import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


def get_user_id_from_session(session_id: str) -> int:
    """Get user_id from session cookie for WebSocket authentication"""
    if not session_id:
        raise ValueError("No session_id provided")
    
    user_id = get_session(session_id)
    if not user_id:
        raise ValueError("Invalid or expired session")
    
    return user_id


@router.websocket("")
async def websocket_endpoint(websocket: WebSocket, session_id: str = Cookie(None)):
    """WebSocket endpoint for real-time updates
    
    Authenticates using session cookie and forwards Redis pub/sub events to client.
    """
    await websocket.accept()
    
    user_id = None
    try:
        # Authenticate using session cookie
        if not session_id:
            await websocket.close(code=1008, reason="Authentication required")
            return
        
        user_id = get_user_id_from_session(session_id)
        
        # Register connection
        await websocket_manager.connect(user_id, websocket)
        
        # Send initial connection confirmation
        await websocket.send_json({
            "event": "connected",
            "payload": {"user_id": user_id}
        })
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message (client can send pings)
                data = await websocket.receive_text()
                
                # Handle ping/pong for keepalive
                if data == "ping":
                    await websocket.send_text("pong")
                    
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"Error in WebSocket connection for user {user_id}: {e}")
                break
                
    except ValueError as e:
        logger.warning(f"WebSocket authentication failed: {e}")
        try:
            await websocket.close(code=1008, reason=str(e))
        except:
            pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except:
            pass
    finally:
        # Clean up connection
        if user_id:
            await websocket_manager.disconnect(user_id, websocket)

