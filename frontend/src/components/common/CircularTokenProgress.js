import React from 'react';
import { HOPPER_COLORS, rgba } from '../../utils/colors';

/**
 * Circular Progress Component for Token Usage
 * @param {number} tokensRemaining - Tokens remaining
 * @param {number} tokensUsed - Tokens used this period
 * @param {number} monthlyTokens - Starting balance for period (plan + granted tokens)
 * @param {number} overageTokens - Overage tokens used
 * @param {boolean} unlimited - Whether user has unlimited tokens
 * @param {boolean} isLoading - Whether data is loading
 */
export default function CircularTokenProgress({ 
  tokensRemaining, 
  tokensUsed, 
  monthlyTokens, 
  overageTokens, 
  unlimited, 
  isLoading 
}) {
  if (unlimited) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
        <div style={{
          width: '48px',
          height: '48px',
          borderRadius: '50%',
          background: `conic-gradient(from 0deg, ${HOPPER_COLORS.success} 0deg 360deg)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative'
        }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: HOPPER_COLORS.base,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1rem',
            fontWeight: '700',
            color: HOPPER_COLORS.success
          }}>
            ∞
          </div>
        </div>
        <div style={{ fontSize: '0.6rem', color: HOPPER_COLORS.grey, textAlign: 'center' }}>Unlimited</div>
      </div>
    );
  }

  const effectiveMonthlyTokens = monthlyTokens || 0;
  const percentage = effectiveMonthlyTokens > 0 ? (tokensUsed / effectiveMonthlyTokens) * 100 : 0;
  const hasOverage = overageTokens > 0;
  
  let progressColor = HOPPER_COLORS.success;
  if (hasOverage) {
    progressColor = HOPPER_COLORS.error;
  } else if (percentage >= 90) {
    progressColor = HOPPER_COLORS.warning;
  }
  
  const radius = 21;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
      <div style={{ position: 'relative', width: '48px', height: '48px' }}>
        <svg width="48" height="48" style={{ transform: 'rotate(-90deg)' }}>
          <circle
            cx="24"
            cy="24"
            r={radius}
            fill="none"
            stroke={rgba(HOPPER_COLORS.rgb.white, 0.1)}
            strokeWidth="3"
          />
          <circle
            cx="24"
            cy="24"
            r={radius}
            fill="none"
            stroke={progressColor}
            strokeWidth="3"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.5s ease', opacity: isLoading ? 0.5 : 1 }}
          />
        </svg>
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '36px',
          height: '36px',
          borderRadius: '50%',
          background: HOPPER_COLORS.base,
          zIndex: 1
        }} />
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '0.05rem',
          zIndex: 2
        }}>
          <div style={{ fontSize: '0.65rem', fontWeight: '700', color: isLoading ? HOPPER_COLORS.grey : HOPPER_COLORS.light, lineHeight: '1' }}>
            {tokensUsed}
          </div>
          <div style={{ fontSize: '0.5rem', color: isLoading ? HOPPER_COLORS.grey : HOPPER_COLORS.grey, lineHeight: '1' }}>
            / {effectiveMonthlyTokens}
          </div>
        </div>
      </div>
    </div>
  );
}

