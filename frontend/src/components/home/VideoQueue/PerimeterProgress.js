import React from 'react';
import { HOPPER_COLORS } from '../../../utils/colors';

/**
 * PerimeterProgress - Square/rectangular progress indicator that animates around destination icons
 * Matches the square shape of the destination icon buttons
 * 
 * @param {number} progress - Progress percentage (0-100)
 * @param {string} status - Status: 'uploading', 'success', 'failed', 'pending'
 * @param {number} width - Width of the rectangle in pixels (default: 32)
 * @param {number} height - Height of the rectangle in pixels (default: 28)
 * @param {number} strokeWidth - Width of the stroke (default: 2)
 * @param {number} borderRadius - Border radius to match button (default: 6)
 */
export default function PerimeterProgress({ 
  progress = 0, 
  status = 'pending', 
  width = 32, 
  height = 28, 
  strokeWidth = 2,
  borderRadius = 6
}) {
  // Calculate perimeter of rounded rectangle
  // For a rounded rectangle: perimeter = 2*(width + height) - 8*radius + 2*PI*radius
  // But we need to account for stroke width, so we use inner dimensions
  const innerWidth = width - strokeWidth;
  const innerHeight = height - strokeWidth;
  const innerRadius = Math.max(0, borderRadius - strokeWidth / 2);
  
  // Calculate perimeter: top + right + bottom + left + 4 corner arcs
  const topBottom = 2 * (innerWidth - 2 * innerRadius);
  const leftRight = 2 * (innerHeight - 2 * innerRadius);
  const cornerArcs = 4 * (Math.PI * innerRadius);
  const perimeter = topBottom + leftRight + cornerArcs;
  
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
  
  // For success/failure, show full perimeter
  const isComplete = status === 'success' || status === 'failed';
  const finalProgress = isComplete ? 100 : progress;
  const finalOffset = perimeter - (finalProgress / 100) * perimeter;
  
  // Create rounded rectangle path following the perimeter
  // Start from top-left corner, go clockwise: top -> right -> bottom -> left
  const x = strokeWidth / 2;
  const y = strokeWidth / 2;
  const w = innerWidth;
  const h = innerHeight;
  const r = innerRadius;
  
  // Path: M (start), L (line), A (arc)
  // Start from top-left, go clockwise around
  const pathData = `
    M ${x + r},${y}
    L ${x + w - r},${y}
    A ${r},${r} 0 0 1 ${x + w},${y + r}
    L ${x + w},${y + h - r}
    A ${r},${r} 0 0 1 ${x + w - r},${y + h}
    L ${x + r},${y + h}
    A ${r},${r} 0 0 1 ${x},${y + h - r}
    L ${x},${y + r}
    A ${r},${r} 0 0 1 ${x + r},${y}
    Z
  `;
  
  return (
    <svg
      width={width}
      height={height}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        transform: 'rotate(-90deg)', // Start from top (0% = top)
        transformOrigin: `${width / 2}px ${height / 2}px`,
        pointerEvents: 'none'
      }}
    >
      {/* Background rectangle (full perimeter, semi-transparent) */}
      <rect
        x={strokeWidth / 2}
        y={strokeWidth / 2}
        width={innerWidth}
        height={innerHeight}
        rx={innerRadius}
        ry={innerRadius}
        fill="none"
        stroke="rgba(255, 255, 255, 0.1)"
        strokeWidth={strokeWidth}
      />
      {/* Progress path (rounded rectangle perimeter) */}
      <path
        d={pathData}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray={perimeter}
        strokeDashoffset={finalOffset}
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
