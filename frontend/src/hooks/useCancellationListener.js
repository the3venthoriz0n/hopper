import { useState, useCallback, useRef, useEffect } from 'react';

/**
 * Hook for tracking cancelled video uploads via WebSocket events
 * 
 * Maintains a Set of cancelled video IDs and provides an isCancelled() function
 * that upload functions can check. Automatically cleans up cancelled IDs when
 * upload completes or component unmounts.
 * 
 * @returns {object} { isCancelled, clearCancellation }
 */
export function useCancellationListener() {
  // Use Set for O(1) lookup performance
  const cancelledIdsRef = useRef(new Set());
  const [, forceUpdate] = useState(0);
  
  /**
   * Check if a video ID is cancelled
   * @param {number} videoId - Video ID to check
   * @returns {boolean} True if video is cancelled
   */
  const isCancelled = useCallback((videoId) => {
    return cancelledIdsRef.current.has(videoId);
  }, []);
  
  /**
   * Mark a video as cancelled
   * @param {number} videoId - Video ID to mark as cancelled
   */
  const markCancelled = useCallback((videoId) => {
    if (!cancelledIdsRef.current.has(videoId)) {
      cancelledIdsRef.current.add(videoId);
      // Force re-render to update any components using this hook
      forceUpdate(prev => prev + 1);
      console.log(`Video ${videoId} marked as cancelled`);
    }
  }, []);
  
  /**
   * Clear cancellation status for a video (called when upload completes)
   * @param {number} videoId - Video ID to clear
   */
  const clearCancellation = useCallback((videoId) => {
    if (cancelledIdsRef.current.has(videoId)) {
      cancelledIdsRef.current.delete(videoId);
      forceUpdate(prev => prev + 1);
      console.log(`Video ${videoId} cancellation cleared`);
    }
  }, []);
  
  /**
   * Clear all cancellations (cleanup on unmount)
   */
  const clearAll = useCallback(() => {
    cancelledIdsRef.current.clear();
    forceUpdate(prev => prev + 1);
  }, []);
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearAll();
    };
  }, [clearAll]);
  
  return {
    isCancelled,
    markCancelled,
    clearCancellation,
    clearAll
  };
}
