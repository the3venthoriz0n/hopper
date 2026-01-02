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
        
        # Redis pubsub (async) - created once and reused
        self.pubsub = None
        
        # Track which channels we're subscribed to (to avoid duplicate subscriptions)
        self.subscribed_channels: Set[str] = set()
        
        # Flag to track if listen loop is running
        self.listening = False
        self.listen_task = None
    
    async def connect(self, user_id: int, websocket) -> None:
        """Register a WebSocket connection for a user"""
        self.active_connections[user_id].add(websocket)
        logger.info(f"WebSocket connected for user {user_id} (total connections: {len(self.active_connections[user_id])})")
        
        # Subscribe to user's channels if first connection
        if len(self.active_connections[user_id]) == 1:
            await self._subscribe_user_channels(user_id)
            
            # Start listening if not already started
            if not self.listening:
                self.listen_task = asyncio.create_task(self._listen_loop())
                self.listening = True
                logger.info("Started Redis pub/sub listen loop")
    
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
        # Create pubsub if it doesn't exist
        if not self.pubsub:
            self.pubsub = async_redis_client.pubsub()
            logger.info("Created pubsub instance")
        
        channels = [
            f"user:{user_id}:videos",
            f"user:{user_id}:destinations",
            f"user:{user_id}:upload_progress",
            f"user:{user_id}:settings",
            f"user:{user_id}:tokens"
        ]
        
        # Only subscribe to channels we're not already subscribed to
        channels_to_subscribe = [ch for ch in channels if ch not in self.subscribed_channels]
        
        if channels_to_subscribe:
            # Subscribe to channels
            await self.pubsub.subscribe(*channels_to_subscribe)
            self.subscribed_channels.update(channels_to_subscribe)
            logger.info(f"✓ Subscribed to Redis channels for user {user_id}: {channels_to_subscribe}")
            logger.info(f"✓ Total subscribed channels: {len(self.subscribed_channels)}")
        else:
            logger.debug(f"Already subscribed to all channels for user {user_id}")
    
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
        
        # Only unsubscribe from channels we're actually subscribed to
        channels_to_unsubscribe = [ch for ch in channels if ch in self.subscribed_channels]
        
        if channels_to_unsubscribe:
            await self.pubsub.unsubscribe(*channels_to_unsubscribe)
            self.subscribed_channels.difference_update(channels_to_unsubscribe)
            logger.info(f"✓ Unsubscribed from Redis channels for user {user_id}: {channels_to_unsubscribe}")
        else:
            logger.debug(f"Not subscribed to channels for user {user_id}")
    
    async def _listen_loop(self) -> None:
        """Internal listen loop - started when first user connects"""
        logger.info("🎧 Starting Redis pub/sub listen loop")
        
        try:
            async for message in self.pubsub.listen():
                try:
                    # Handle message types - with decode_responses=True, keys are strings
                    if not isinstance(message, dict):
                        logger.warning(f"Unexpected message format: {type(message)}")
                        continue
                    
                    message_type = message.get('type')
                    if not message_type:
                        logger.warning(f"Message missing 'type' field: {message}")
                        continue
                    
                    # Skip control messages (subscribe/unsubscribe confirmations)
                    if message_type in ('subscribe', 'unsubscribe', 'psubscribe', 'punsubscribe'):
                        channel = message.get('channel', '')
                        logger.debug(f"Pubsub control message: {message_type} for channel {channel}")
                        continue
                    
                    # Process actual messages
                    if message_type != 'message':
                        continue
                    
                    channel = message.get('channel')
                    if not channel:
                        logger.warning(f"Message missing 'channel' field: {message}")
                        continue
                    
                    data = message.get('data')
                    if not data:
                        logger.warning(f"Message missing 'data' field: {message}")
                        continue
                    
                    # Extract user_id from channel (format: user:{user_id}:{type})
                    try:
                        user_id = int(channel.split(':')[1])
                    except (IndexError, ValueError):
                        logger.warning(f"Invalid channel format: {channel}")
                        continue
                    
                    # Parse event data (data is already a string due to decode_responses=True)
                    try:
                        event_data = json.loads(data)
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse event data from channel {channel}: {e}")
                        continue
                    
                    # Validate event data structure
                    if not isinstance(event_data, dict):
                        logger.warning(f"Invalid event data format from channel {channel}: expected dict, got {type(event_data)}")
                        continue
                    
                    event_type = event_data.get("type")
                    if not event_type:
                        logger.warning(f"Event data missing 'type' field from channel {channel}")
                        continue
                    
                    # Log received events for debugging
                    if event_type == "destination_toggled":
                        event_payload = event_data.get("data", {})
                        video_count = len(event_payload.get("videos", []))
                        logger.info(f"📨 Received destination_toggled from Redis for user {user_id}: "
                                   f"platform={event_payload.get('platform')}, enabled={event_payload.get('enabled')}, video_count={video_count}")
                    
                    # Forward to all connections for this user
                    await self._broadcast_to_user(user_id, event_data)
                        
                except Exception as e:
                    logger.error(f"Error processing pub/sub message: {e}", exc_info=True)
                    
        except Exception as e:
            logger.error(f"Error in Redis pub/sub listen loop: {e}", exc_info=True)
            self.listening = False
    
    async def _broadcast_to_user(self, user_id: int, event_data: Dict) -> None:
        """Broadcast event to all WebSocket connections for a user"""
        if user_id not in self.active_connections:
            logger.debug(f"No active WebSocket connections for user {user_id}, skipping broadcast")
            return
        
        event_type = event_data.get("type")
        payload = event_data.get("data", {})
        
        # Format message for WebSocket (must match frontend expectations)
        message = {
            "event": event_type,
            "payload": payload
        }
        message_json = json.dumps(message)
        
        # Log the event being sent
        connection_count = len(self.active_connections[user_id])
        if event_type == "destination_toggled":
            video_count = len(payload.get("videos", []))
            logger.info(f"📤 Broadcasting destination_toggled to {connection_count} WebSocket(s) for user {user_id}: "
                       f"platform={payload.get('platform')}, enabled={payload.get('enabled')}, video_count={video_count}")
        else:
            logger.debug(f"Broadcasting {event_type} to {connection_count} WebSocket(s) for user {user_id}")
        
        # Send to all connections
        dead_connections = set()
        sent_count = 0
        for websocket in self.active_connections[user_id]:
            try:
                await websocket.send_text(message_json)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send {event_type} to WebSocket for user {user_id}: {e}")
                dead_connections.add(websocket)
        
        if sent_count > 0:
            logger.info(f"✓ Successfully sent {event_type} to {sent_count} WebSocket connection(s) for user {user_id}")
        else:
            logger.warning(f"⚠ Failed to send {event_type} to any WebSocket connections for user {user_id}")
        
        # Clean up dead connections
        if dead_connections:
            for dead_ws in dead_connections:
                self.active_connections[user_id].discard(dead_ws)
            
            if len(self.active_connections[user_id]) == 0:
                await self._unsubscribe_user_channels(user_id)
                del self.active_connections[user_id]
                logger.info(f"All WebSocket connections closed for user {user_id}, unsubscribed from channels")
    
    async def start_listening(self) -> None:
        """Initialize pubsub instance (actual listening starts when first user connects)"""
        if not self.pubsub:
            self.pubsub = async_redis_client.pubsub()
            logger.info("✓ Initialized pubsub instance (listen loop will start when first user connects)")
        else:
            logger.warning("⚠ Pubsub already initialized")


# Global WebSocket manager instance
websocket_manager = WebSocketManager()
