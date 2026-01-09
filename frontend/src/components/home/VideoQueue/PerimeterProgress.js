import React from 'react';
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
  
  // Calculate perimeter: 4 sides + 4 corner arcs (square)
  const sides = 4 * (pathSize - 2 * pathRadius);
  const cornerArcs = 4 * (Math.PI * pathRadius);
  const perimeter = sides + cornerArcs;
  
  // Determine color based on status - this is the progress color
  let progressColor;
  if (status === 'success') {
    progressColor = HOPPER_COLORS.success;
  } else if (status === 'failed') {
    progressColor = HOPPER_COLORS.error;
  } else if (status === 'uploading') {
    progressColor = HOPPER_COLORS.info || '#00bcd4'; // Cyan/blue for uploading
  } else {
    progressColor = 'rgba(255, 255, 255, 0.2)'; // Neutral color for pending
  }
  
  // Background stroke is always grey and always visible (full perimeter)
  const backgroundStrokeColor = 'rgba(255, 255, 255, 0.2)';
  const backgroundOffset = 0; // Full background stroke (always visible)
  
  // Progress stroke: for uploading, show animated progress; for others, show full colored border
  const isUploading = status === 'uploading';
  const finalProgress = isUploading ? Math.max(0, Math.min(100, progress)) : 100;
  // strokeDashoffset: 0 = full stroke visible, perimeter = no stroke visible
  // We want: progress 0% = offset perimeter (invisible), progress 100% = offset 0 (fully visible)
  const progressOffset = perimeter - (finalProgress / 100) * perimeter;
  
  // Create rounded square path following the perimeter
  // Start from top-left corner, go clockwise: top -> right -> bottom -> left
  const x = pathX;
  const y = pathY;
  const size = pathSize;
  const r = pathRadius;
  
  // Path: M (start), L (line), A (arc)
  // Start from top-left, go clockwise around
  const pathData = `
    M ${x + r},${y}
    L ${x + size - r},${y}
    A ${r},${r} 0 0 1 ${x + size},${y + r}
    L ${x + size},${y + size - r}
    A ${r},${r} 0 0 1 ${x + size - r},${y + size}
    L ${x + r},${y + size}
    A ${r},${r} 0 0 1 ${x},${y + size - r}
    L ${x},${y + r}
    A ${r},${r} 0 0 1 ${x + r},${y}
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
        transform: 'rotate(-90deg)', // Start from top (0% = top)
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
        strokeDasharray={perimeter}
        strokeDashoffset={backgroundOffset}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Progress stroke - colored overlay showing upload progress */}
      <path
        d={pathData}
        fill="none"
        stroke={progressColor}
        strokeWidth={strokeWidth}
        strokeDasharray={perimeter}
        strokeDashoffset={progressOffset}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{
          transition: 'stroke-dashoffset 0.3s ease, stroke 0.3s ease',
          filter: status === 'uploading' ? 'drop-shadow(0 0 4px rgba(0, 188, 212, 0.5))' : 'none'
        }}
      />
    </svg>
  );
}
