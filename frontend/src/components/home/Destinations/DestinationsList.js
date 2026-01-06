import React from 'react';
import YouTubeDestination from './YouTubeDestination';
import TikTokDestination from './TikTokDestination';
import InstagramDestination from './InstagramDestination';

/**
 * Destinations list container component
 * @param {object} props
 */
export default function DestinationsList(props) {
  return (
    <div className="card">
      <h2>Destinations</h2>
      <YouTubeDestination {...props} />
      <TikTokDestination {...props} />
      <InstagramDestination {...props} />
    </div>
  );
}
