import React, { useState, useEffect, useRef } from 'react';
import { HOPPER_COLORS } from '../../../utils/colors';

/**
 * PerimeterProgress - Square progress indicator that animates around destination icons
 * Acts as the border for the button, showing upload status with colored progress
 * 
 * @param {number} progress - Progress percentage (0-100)
 * @param {string} status - Status: 'uploading', 'success', 'failed', 'pending'
 * @param {number} buttonSize - Total outer size of the square button (with box-sizing: border-box, includes padding)
 * @param {number} padding - Padding on all sides (default: 4) - used for reference only
 * @param {number} borderRadius - Border radius to match button (default: 6)
 * @param {number} strokeWidth - Width of the stroke/border (default: 2)
 */
export default function PerimeterProgress({ 
  progress = 0, 
  status = 'pending', 
  buttonSize = 32, 
  padding = 4,
  borderRadius = 6,
  strokeWidth = 2
}) {
  // Smooth interpolation for progress updates
  const [displayProgress, setDisplayProgress] = useState(progress);
  const animationFrameRef = useRef(null);
  const displayProgressRef = useRef(progress);
  const [pathLength, setPathLength] = useState(0);
  
  // Update ref whenever displayProgress changes
  useEffect(() => {
    displayProgressRef.current = displayProgress;
  }, [displayProgress]);
  
  // Callback ref to measure path length when path is rendered
  const pathRefCallback = (pathElement) => {
    if (pathElement) {
      const length = pathElement.getTotalLength();
      if (length > 0 && length !== pathLength) {
        setPathLength(length);
      }
    }
  };
  
  useEffect(() => {
    // Cleanup any ongoing animation
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    
    // Only interpolate if status is uploading (for smooth animation)
    if (status === 'uploading') {
      const targetProgress = Math.max(0, Math.min(100, progress));
      const startProgress = displayProgressRef.current;
      const difference = targetProgress - startProgress;
      
      // If the difference is small, just set it directly
      if (Math.abs(difference) < 0.1) {
        setDisplayProgress(targetProgress);
        return;
      }
      
      // Use requestAnimationFrame for smooth interpolation
      let startTime = null;
      const duration = 500; // 500ms for smooth animation
      
      const animate = (currentTime) => {
        if (startTime === null) {
          startTime = currentTime;
        }
        
        const elapsed = currentTime - startTime;
        const progressRatio = Math.min(elapsed / duration, 1);
        
        // Easing function (ease-out)
        const easeOut = 1 - Math.pow(1 - progressRatio, 3);
        const currentProgress = startProgress + (difference * easeOut);
        
        setDisplayProgress(currentProgress);
        
        if (progressRatio < 1) {
          animationFrameRef.current = requestAnimationFrame(animate);
        } else {
          setDisplayProgress(targetProgress);
          animationFrameRef.current = null;
        }
      };
      
      animationFrameRef.current = requestAnimationFrame(animate);
    } else {
      // For non-uploading states, update immediately
      setDisplayProgress(progress);
    }
    
    // Cleanup function
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [progress, status]);
  
  // Calculate total button outer dimensions
  // With box-sizing: border-box, width/height includes padding
  // Button has: width = buttonSize (total outer size), padding = padding on all sides
  // So totalSize = buttonSize (the width/height already includes padding)
  const totalSize = buttonSize;
  
  // Path dimensions: stroke is centered on the edge, so we account for half stroke width
  // The path should be inset by strokeWidth/2 from the outer edge
  const pathX = strokeWidth / 2;
  const pathY = strokeWidth / 2;
  const pathSize = totalSize - strokeWidth; // Total size minus full stroke width
  const pathRadius = Math.max(0, borderRadius - strokeWidth / 2);
  
  // Determine color based on status - this is the progress color
  let progressColor;
  if (status === 'success') {
    progressColor = HOPPER_COLORS.success;
  } else if (status === 'failed') {
    progressColor = HOPPER_COLORS.error;
  } else if (status === 'uploading') {
    // Use orange color for uploading progress
    progressColor = HOPPER_COLORS.warning;
  } else {
    progressColor = 'rgba(255, 255, 255, 0.2)'; // Neutral color for pending
  }
  
  // Background stroke is always grey and always visible (full perimeter)
  const backgroundStrokeColor = 'rgba(255, 255, 255, 0.2)';
  const backgroundOffset = 0; // Full background stroke (always visible)
  
  // Progress stroke: for uploading, show animated progress; for success/failed show full border; for pending show empty
  const isUploading = status === 'uploading';
  const isSuccessOrFailed = status === 'success' || status === 'failed';
  const finalProgress = isUploading 
    ? Math.max(0, Math.min(100, displayProgress))
    : isSuccessOrFailed 
    ? 100 
    : 0; // Pending states show 0% (empty border)
  
  // Use measured path length for accurate progress calculation
  // strokeDashoffset: 0 = full stroke visible, pathLength = no stroke visible
  // We want: progress 0% = offset pathLength (invisible), progress 100% = offset 0 (fully visible)
  const progressOffset = pathLength > 0 ? pathLength - (finalProgress / 100) * pathLength : 0;
  
  // Create rounded square path following the perimeter
  // Start from top center (12 o'clock), go clockwise: top -> right -> bottom -> left -> back to top
  const x = pathX;
  const y = pathY;
  const size = pathSize;
  const r = pathRadius;
  const centerX = x + size / 2;
  
  // Path: M (start), L (line), A (arc)
  // Start from top center, go clockwise around
  const pathData = `
    M ${centerX},${y}
    L ${x + size - r},${y}
    A ${r},${r} 0 0 1 ${x + size},${y + r}
    L ${x + size},${y + size - r}
    A ${r},${r} 0 0 1 ${x + size - r},${y + size}
    L ${x + r},${y + size}
    A ${r},${r} 0 0 1 ${x},${y + size - r}
    L ${x},${y + r}
    A ${r},${r} 0 0 1 ${x + r},${y}
    L ${centerX},${y}
    Z
  `;
  
  return (
    <svg
      width={totalSize}
      height={totalSize}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: `${totalSize}px`,
        height: `${totalSize}px`,
        // No rotation needed - path starts at top center
        transformOrigin: `${totalSize / 2}px ${totalSize / 2}px`,
        pointerEvents: 'none',
        overflow: 'visible'
      }}
      viewBox={`0 0 ${totalSize} ${totalSize}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Background stroke - always visible grey border */}
      <path
        d={pathData}
        fill="none"
        stroke={backgroundStrokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray={pathLength > 0 ? pathLength : undefined}
        strokeDashoffset={backgroundOffset}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Progress stroke - colored overlay showing upload progress */}
      <path
        ref={pathRefCallback}
        d={pathData}
        fill="none"
        stroke={progressColor}
        strokeWidth={strokeWidth}
        strokeDasharray={pathLength > 0 ? pathLength : undefined}
        strokeDashoffset={progressOffset}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{
          transition: status === 'uploading' ? 'stroke-dashoffset 0.1s linear, stroke 0.3s ease' : 'stroke-dashoffset 0.3s ease, stroke 0.3s ease',
          filter: status === 'uploading' ? 'drop-shadow(0 0 4px rgba(255, 179, 0, 0.5))' : 'none'
        }}
      />
    </svg>
  );
}
