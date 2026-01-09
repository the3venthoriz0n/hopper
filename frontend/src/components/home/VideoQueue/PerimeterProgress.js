import React from 'react';
import { HOPPER_COLORS } from '../../../utils/colors';

/**
 * PerimeterProgress - Circular progress indicator that animates around destination icons
 * 
 * @param {number} progress - Progress percentage (0-100)
 * @param {string} status - Status: 'uploading', 'success', 'failed', 'pending'
 * @param {number} size - Size of the circle in pixels (default: 32)
 * @param {number} strokeWidth - Width of the stroke (default: 2)
 */
export default function PerimeterProgress({ progress = 0, status = 'pending', size = 32, strokeWidth = 2 }) {
  // Calculate stroke-dasharray and stroke-dashoffset for circular progress
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (progress / 100) * circumference;
  
  // Determine color based on status
  let strokeColor;
  if (status === 'success') {
    strokeColor = HOPPER_COLORS.success;
  } else if (status === 'failed') {
    strokeColor = HOPPER_COLORS.error;
  } else if (status === 'uploading') {
    strokeColor = HOPPER_COLORS.info || '#00bcd4'; // Cyan/blue for uploading
  } else {
    strokeColor = 'rgba(255, 255, 255, 0.3)'; // Default: semi-transparent white
  }
  
  // For success/failure, show full circle
  const isComplete = status === 'success' || status === 'failed';
  const finalProgress = isComplete ? 100 : progress;
  const finalOffset = circumference - (finalProgress / 100) * circumference;
  
  return (
    <svg
      width={size}
      height={size}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        transform: 'rotate(-90deg)', // Start from top (0% = top)
        pointerEvents: 'none'
      }}
    >
      {/* Background circle (full circle, semi-transparent) */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(255, 255, 255, 0.1)"
        strokeWidth={strokeWidth}
      />
      {/* Progress circle */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray={circumference}
        strokeDashoffset={finalOffset}
        strokeLinecap="round"
        style={{
          transition: 'stroke-dashoffset 0.3s ease, stroke 0.3s ease',
          filter: status === 'uploading' ? 'drop-shadow(0 0 4px rgba(0, 188, 212, 0.5))' : 'none'
        }}
      />
    </svg>
  );
}
