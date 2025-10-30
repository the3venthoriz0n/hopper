import { useState } from 'react'
import { Video, Destination, updateVideo, deleteVideo, triggerUpload } from '../utils/api'
import VideoItem from './VideoItem'
import './VideoList.css'

interface VideoListProps {
  videos: Video[]
  destinations: Destination[]
  onUpdate: () => void
}

function VideoList({ videos, destinations, onUpdate }: VideoListProps) {
  if (videos.length === 0) {
    return (
      <div className="video-list-empty">
        <p>No videos in the hopper yet. Drag and drop videos above to get started.</p>
      </div>
    )
  }

  return (
    <div className="video-list">
      <h2>Video Hopper ({videos.length})</h2>
      
      <div className="videos">
        {videos.map((video) => (
          <VideoItem
            key={video.id}
            video={video}
            destinations={destinations}
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  )
}

export default VideoList

