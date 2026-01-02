import { useEffect, useRef, useCallback } from 'react';

/**
 * WebSocket hook for real-time updates
 * 
 * Manages WebSocket connection lifecycle, handles reconnection,
 * and provides event subscription API.
 * 
 * @param {string} url - WebSocket URL
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

  // Keep onMessage ref updated
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    if (!url) return;

    try {
      // Determine WebSocket URL
      const wsUrl = url.startsWith('ws://') || url.startsWith('wss://')
        ? url
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}${url}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        if (onOpen) onOpen();
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (onMessageRef.current) {
            onMessageRef.current(data);
          }
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        if (onError) onError(error);
      };

      ws.onclose = (event) => {
        if (onClose) onClose(event);

        // Attempt reconnection if enabled and not a normal closure
        if (shouldReconnectRef.current && reconnect && event.code !== 1000) {
          if (reconnectAttemptsRef.current < maxReconnectAttempts) {
            reconnectAttemptsRef.current += 1;
            const delay = Math.min(
              reconnectInterval * Math.pow(2, reconnectAttemptsRef.current - 1),
              30000 // Max 30 seconds
            );
            
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
      if (onError) onError(error);
    }
  }, [url, reconnect, reconnectInterval, maxReconnectAttempts, onOpen, onClose, onError]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
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
    connected: wsRef.current?.readyState === WebSocket.OPEN,
    send,
    reconnect: connect,
    disconnect,
  };
}

