"""WebSocket connection manager for real-time updates"""
import asyncio
import json
import logging
from typing import Dict, Set
from collections import defaultdict

from app.db.redis import async_redis_client

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and forwards Redis pub/sub events to clients"""
    
    def __init__(self):
        # Map user_id -> set of WebSocket connections
        self.active_connections: Dict[int, Set] = defaultdict(set)
        
        # Redis pubsub (async)
        self.pubsub = None
    
    async def connect(self, user_id: int, websocket) -> None:
        """Register a WebSocket connection for a user"""
        self.active_connections[user_id].add(websocket)
        logger.info(f"WebSocket connected for user {user_id} (total connections: {len(self.active_connections[user_id])})")
        
        # Subscribe to user's channels if first connection
        if len(self.active_connections[user_id]) == 1:
            await self._subscribe_user_channels(user_id)
    
    async def disconnect(self, user_id: int, websocket) -> None:
        """Unregister a WebSocket connection for a user"""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            
            # If no more connections for this user, unsubscribe from channels
            if len(self.active_connections[user_id]) == 0:
                await self._unsubscribe_user_channels(user_id)
                del self.active_connections[user_id]
        
        logger.info(f"WebSocket disconnected for user {user_id}")
    
    async def _subscribe_user_channels(self, user_id: int) -> None:
        """Subscribe to Redis channels for a user"""
        if not self.pubsub:
            self.pubsub = async_redis_client.pubsub()
        
        channels = [
            f"user:{user_id}:videos",
            f"user:{user_id}:destinations",
            f"user:{user_id}:upload_progress",
            f"user:{user_id}:settings",
            f"user:{user_id}:tokens"
        ]
        
        # Simple async subscribe - no thread pool needed!
        await self.pubsub.subscribe(*channels)
        logger.debug(f"Subscribed to Redis channels for user {user_id}")
    
    async def _unsubscribe_user_channels(self, user_id: int) -> None:
        """Unsubscribe from Redis channels for a user"""
        if not self.pubsub:
            return
        
        channels = [
            f"user:{user_id}:videos",
            f"user:{user_id}:destinations",
            f"user:{user_id}:upload_progress",
            f"user:{user_id}:settings",
            f"user:{user_id}:tokens"
        ]
        
        # Simple async unsubscribe
        await self.pubsub.unsubscribe(*channels)
        logger.debug(f"Unsubscribed from Redis channels for user {user_id}")
    
    async def start_listening(self) -> None:
        """Start listening to Redis pub/sub messages and forward to WebSocket clients"""
        if not self.pubsub:
            self.pubsub = async_redis_client.pubsub()
        
        logger.info("WebSocket manager started listening to Redis pub/sub")
        
        # Elegant async iteration - no blocking, no thread pool!
        async for message in self.pubsub.listen():
            try:
                if message['type'] != 'message':
                    continue
                
                channel = message['channel']
                data = message['data']
                
                # Extract user_id from channel (format: user:{user_id}:{type})
                try:
                    user_id = int(channel.split(':')[1])
                except (IndexError, ValueError):
                    logger.warning(f"Invalid channel format: {channel}")
                    continue
                
                # Parse event data
                try:
                    if isinstance(data, str):
                        event_data = json.loads(data)
                    elif isinstance(data, bytes):
                        event_data = json.loads(data.decode('utf-8'))
                    else:
                        event_data = data
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.warning(f"Failed to parse event data from channel {channel}: {e}")
                    continue
                
                # Forward to all connections for this user
                await self._broadcast_to_user(user_id, event_data)
                    
            except Exception as e:
                logger.error(f"Error in WebSocket manager message loop: {e}", exc_info=True)
                await asyncio.sleep(1)  # Prevent tight loop on errors
    
    async def _broadcast_to_user(self, user_id: int, event_data: Dict) -> None:
        """Broadcast event to all WebSocket connections for a user"""
        if user_id not in self.active_connections:
            return
        
        # Format message for WebSocket
        message = {
            "event": event_data.get("type"),
            "payload": event_data.get("data", {})
        }
        message_json = json.dumps(message)
        
        # Send to all connections (collect dead ones for cleanup)
        dead_connections = set()
        for websocket in self.active_connections[user_id]:
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.debug(f"Failed to send message to WebSocket: {e}")
                dead_connections.add(websocket)
        
        # Clean up dead connections after iteration completes
        if dead_connections:
            for dead_ws in dead_connections:
                self.active_connections[user_id].discard(dead_ws)
            
            # If no more connections for this user, unsubscribe from channels
            if len(self.active_connections[user_id]) == 0:
                await self._unsubscribe_user_channels(user_id)
                del self.active_connections[user_id]
                logger.info(f"All WebSocket connections closed for user {user_id}, unsubscribed from channels")


# Global WebSocket manager instance
websocket_manager = WebSocketManager()
