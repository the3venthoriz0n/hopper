import React from 'react';
import { HOPPER_COLORS } from '../../../utils/colors';

/**
 * PerimeterProgress - Square/rectangular progress indicator that animates around destination icons
 * Acts as the border for the button, showing upload status with colored progress
 * 
 * @param {number} progress - Progress percentage (0-100)
 * @param {string} status - Status: 'uploading', 'success', 'failed', 'pending'
 * @param {number} buttonWidth - Minimum width of the button (minWidth, excluding padding)
 * @param {number} buttonHeight - Height of the button (excluding padding)
 * @param {number} paddingVertical - Vertical padding of the button
 * @param {number} paddingHorizontal - Horizontal padding of the button
 * @param {number} borderRadius - Border radius to match button (default: 6)
 * @param {number} strokeWidth - Width of the stroke/border (default: 2)
 */
export default function PerimeterProgress({ 
  progress = 0, 
  status = 'pending', 
  buttonWidth = 32, 
  buttonHeight = 28, 
  paddingVertical = 4,
  paddingHorizontal = 6,
  borderRadius = 6,
  strokeWidth = 2
}) {
  // Calculate total button outer dimensions (button size + padding on both sides)
  // Note: buttonWidth is minWidth, actual width may be wider, but SVG will scale
  const totalWidth = buttonWidth + (paddingHorizontal * 2);
  const totalHeight = buttonHeight + (paddingVertical * 2);
  
  // Calculate path dimensions - stroke is centered on the edge, so we need to account for half stroke width
  const pathX = strokeWidth / 2;
  const pathY = strokeWidth / 2;
  const pathWidth = totalWidth - strokeWidth;
  const pathHeight = totalHeight - strokeWidth;
  const pathRadius = Math.max(0, borderRadius - strokeWidth / 2);
  
  // Calculate perimeter: top + right + bottom + left + 4 corner arcs
  const topBottom = 2 * (pathWidth - 2 * pathRadius);
  const leftRight = 2 * (pathHeight - 2 * pathRadius);
  const cornerArcs = 4 * (Math.PI * pathRadius);
  const perimeter = topBottom + leftRight + cornerArcs;
  
  // Determine color based on status - this is the border color
  let strokeColor;
  if (status === 'success') {
    strokeColor = HOPPER_COLORS.success;
  } else if (status === 'failed') {
    strokeColor = HOPPER_COLORS.error;
  } else if (status === 'uploading') {
    strokeColor = HOPPER_COLORS.info || '#00bcd4'; // Cyan/blue for uploading
  } else {
    strokeColor = 'rgba(255, 255, 255, 0.2)'; // Neutral border for pending
  }
  
  // For success/failure/pending, show full perimeter. For uploading, show progress.
  const isComplete = status === 'success' || status === 'failed' || status === 'pending';
  const finalProgress = isComplete ? 100 : progress;
  const finalOffset = perimeter - (finalProgress / 100) * perimeter;
  
  // Create rounded rectangle path following the perimeter
  // Start from top-left corner, go clockwise: top -> right -> bottom -> left
  const x = pathX;
  const y = pathY;
  const w = pathWidth;
  const h = pathHeight;
  const r = pathRadius;
  
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
      width="100%"
      height="100%"
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        transform: 'rotate(-90deg)', // Start from top (0% = top)
        transformOrigin: 'center',
        pointerEvents: 'none',
        overflow: 'visible'
      }}
      viewBox={`0 0 ${totalWidth} ${totalHeight}`}
      preserveAspectRatio="none"
    >
      {/* Progress path (rounded rectangle perimeter) - this IS the border */}
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
