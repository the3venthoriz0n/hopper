"""WebSocket connection manager for real-time updates"""
import asyncio
import json
import logging
from typing import Dict, Set
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.db.redis import redis_client

logger = logging.getLogger(__name__)

# Thread pool for running synchronous Redis operations
_executor = ThreadPoolExecutor(max_workers=2)


class WebSocketManager:
    """Manages WebSocket connections and forwards Redis pub/sub events to clients"""
    
    def __init__(self):
        # Map user_id -> set of WebSocket connections
        self.active_connections: Dict[int, Set] = defaultdict(set)
        
        # Redis pubsub subscriber
        self.pubsub = None
        self.subscribed_channels: Set[str] = set()
        
        # Background task for Redis subscription
        self.subscription_task = None
    
    async def connect(self, user_id: int, websocket) -> None:
        """Register a WebSocket connection for a user"""
        self.active_connections[user_id].add(websocket)
        logger.info(f"WebSocket connected for user {user_id} (total connections: {len(self.active_connections[user_id])})")
        
        # Send a test message to confirm connection works
        try:
            await websocket.send_text(json.dumps({
                "event": "connected",
                "payload": {"user_id": user_id, "timestamp": datetime.now(timezone.utc).isoformat()}
            }))
        except Exception as e:
            logger.error(f"Failed to send connected event: {e}")
        
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
            self.pubsub = redis_client.pubsub()
        
        channels = [
            f"user:{user_id}:videos",
            f"user:{user_id}:destinations",
            f"user:{user_id}:upload_progress",
            f"user:{user_id}:settings",
            f"user:{user_id}:tokens"
        ]
        
        # Run synchronous Redis operations in thread pool
        def subscribe():
            for channel in channels:
                if channel not in self.subscribed_channels:
                    self.pubsub.subscribe(channel)
                    self.subscribed_channels.add(channel)
                    logger.debug(f"Subscribed to Redis channel: {channel}")
        
        await asyncio.get_event_loop().run_in_executor(_executor, subscribe)
    
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
        
        # Run synchronous Redis operations in thread pool
        def unsubscribe():
            for channel in channels:
                if channel in self.subscribed_channels:
                    self.pubsub.unsubscribe(channel)
                    self.subscribed_channels.discard(channel)
                    logger.debug(f"Unsubscribed from Redis channel: {channel}")
        
        await asyncio.get_event_loop().run_in_executor(_executor, unsubscribe)
    
    async def start_listening(self) -> None:
        """Start listening to Redis pub/sub messages and forward to WebSocket clients"""
        if not self.pubsub:
            self.pubsub = redis_client.pubsub()
        
        logger.info("WebSocket manager started listening to Redis pub/sub")
        
        while True:
            try:
                # Run synchronous get_message in thread pool
                message = await asyncio.get_event_loop().run_in_executor(
                    _executor,
                    lambda: self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                )
                
                if message and message['type'] == 'message':
                    channel = message['channel'].decode('utf-8') if isinstance(message['channel'], bytes) else message['channel']
                    data = message['data']
                    
                    # Extract user_id from channel (format: user:{user_id}:{type})
                    try:
                        user_id = int(channel.split(':')[1])
                    except (IndexError, ValueError):
                        logger.warning(f"Invalid channel format: {channel}")
                        continue
                    
                    # Parse event data
                    try:
                        event_data = json.loads(data) if isinstance(data, bytes) else json.loads(data)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse event data from channel {channel}")
                        continue
                    
                    # Forward to all connections for this user
                    await self._broadcast_to_user(user_id, event_data)
                else:
                    # No message, small sleep to prevent tight loop
                    await asyncio.sleep(0.1)
                    
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
        
        # Send to all connections (remove dead ones)
        dead_connections = set()
        for websocket in self.active_connections[user_id]:
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.debug(f"Failed to send message to WebSocket: {e}")
                dead_connections.add(websocket)
        
        # Clean up dead connections
        for dead_ws in dead_connections:
            await self.disconnect(user_id, dead_ws)


# Global WebSocket manager instance
websocket_manager = WebSocketManager()

