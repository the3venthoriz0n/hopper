import React from 'react';

/**
 * Banner component - displays system-wide banner message
 * @param {object} props
 * @param {string} props.message - Banner message text
 * @param {boolean} props.enabled - Whether banner is enabled
 */
export default function Banner({ message, enabled }) {
  if (!enabled || !message || message.trim() === '') {
    return null;
  }

  return (
    <div className="banner-container">
      <div className="banner-content">
        {message}
      </div>
    </div>
  );
}
