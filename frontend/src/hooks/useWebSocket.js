import { useEffect, useRef, useCallback, useState } from 'react';
import { getWebSocketUrl } from '../services/api';

/**
 * WebSocket hook for real-time updates
 * 
 * Manages WebSocket connection lifecycle, handles reconnection,
 * and provides event subscription API.
 * 
 * @param {string} url - WebSocket URL path (e.g., '/ws')
 * @param {function} onMessage - Callback for received messages
 * @param {object} options - Configuration options
 * @returns {object} - { connected, send, reconnect }
 */
export function useWebSocket(url, onMessage, options = {}) {
  const {
    reconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
    onOpen = null,
    onClose = null,
    onError = null,
  } = options;

  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const shouldReconnectRef = useRef(true);
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);
  const pingIntervalRef = useRef(null);
  const [connected, setConnected] = useState(false);

  // Keep callback refs updated
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    onOpenRef.current = onOpen;
  }, [onOpen]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const connect = useCallback(() => {
    if (!url) return;

    try {
      // Use getWebSocketUrl() to construct URL through nginx proxy
      // This ensures WebSocket connects through nginx, not directly to backend port
      const wsUrl = url.startsWith('ws://') || url.startsWith('wss://')
        ? url
        : getWebSocketUrl();

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        setConnected(true);
        console.log('✅ WebSocket connected to:', wsUrl);
        
        // Start ping interval to keep connection alive
        pingIntervalRef.current = setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            try {
              wsRef.current.send('ping');
            } catch (err) {
              console.error('Failed to send ping:', err);
            }
          }
        }, 30000); // Ping every 30 seconds
        
        if (onOpenRef.current) onOpenRef.current();
      };

      ws.onmessage = (event) => {
        try {
          // Handle ping/pong keepalive messages (plain text, not JSON)
          if (event.data === 'pong' || event.data === 'ping') {
            // Ignore ping/pong messages - they're just keepalive
            return;
          }
          
          // Parse JSON messages
          const data = JSON.parse(event.data);
          console.log('📨 WebSocket message received:', data);
          if (onMessageRef.current) {
            onMessageRef.current(data);
          }
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        if (onErrorRef.current) onErrorRef.current(error);
      };

      ws.onclose = (event) => {
        setConnected(false);
        
        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }
        
        if (onCloseRef.current) onCloseRef.current(event);

        // Attempt reconnection if enabled and not a normal closure
        if (shouldReconnectRef.current && reconnect && event.code !== 1000) {
          if (reconnectAttemptsRef.current < maxReconnectAttempts) {
            reconnectAttemptsRef.current += 1;
            // Add jitter to prevent thundering herd
            const baseDelay = reconnectInterval * Math.pow(2, reconnectAttemptsRef.current - 1);
            const jitter = Math.random() * 1000; // 0-1 second jitter
            const delay = Math.min(baseDelay + jitter, 30000); // Max 30 seconds
            
            reconnectTimeoutRef.current = setTimeout(() => {
              console.log(`Reconnecting WebSocket (attempt ${reconnectAttemptsRef.current})...`);
              connect();
            }, delay);
          } else {
            console.error('Max WebSocket reconnection attempts reached');
          }
        }
      };
    } catch (error) {
      console.error('Failed to create WebSocket connection:', error);
      if (onErrorRef.current) onErrorRef.current(error);
    }
  }, [url, reconnect, reconnectInterval, maxReconnectAttempts]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    setConnected(false);
    
    // Clear ping interval
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }
  }, []);

  const send = useCallback((message) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof message === 'string' ? message : JSON.stringify(message));
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    connected,
    send,
    reconnect: connect,
    disconnect,
  };
}

