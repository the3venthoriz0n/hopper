import { useState } from 'react'
import { Video, Destination, updateVideo, deleteVideo, triggerUpload } from '../utils/api'
import './VideoItem.css'

interface VideoItemProps {
  video: Video
  destinations: Destination[]
  onUpdate: () => void
}

function VideoItem({ video, destinations, onUpdate }: VideoItemProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [title, setTitle] = useState(video.title || '')
  const [description, setDescription] = useState(video.description || '')
  const [privacy, setPrivacy] = useState(video.privacy || 'private')
  const [scheduledTime, setScheduledTime] = useState(() => {
    if (!video.scheduled_time) return ''
    // Convert UTC time to local datetime-local format
    const date = new Date(video.scheduled_time)
    const offset = date.getTimezoneOffset() * 60000
    const localDate = new Date(date.getTime() - offset)
    return localDate.toISOString().slice(0, 16)
  })
  const [selectedDestinations, setSelectedDestinations] = useState<number[]>(
    video.upload_destinations || []
  )

  const handleSave = async () => {
    try {
      await updateVideo(video.id, {
        title: title || undefined,
        description: description || undefined,
        privacy: privacy,
        scheduled_time: scheduledTime || null,
        upload_destinations: selectedDestinations
      })
      setIsEditing(false)
      onUpdate()
    } catch (error) {
      console.error('Error updating video:', error)
      alert('Failed to update video')
    }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this video?')) return

    try {
      await deleteVideo(video.id)
      onUpdate()
    } catch (error) {
      console.error('Error deleting video:', error)
      alert('Failed to delete video')
    }
  }

  const handleUpload = async () => {
    if (selectedDestinations.length === 0) {
      alert('Please select at least one destination')
      return
    }

    try {
      const result = await triggerUpload(video.id)
      onUpdate()
      
      if (result.status === 'failed') {
        alert(`Upload failed:\n${result.errors.join('\n')}`)
      } else {
        alert('Upload started successfully!')
      }
    } catch (error: any) {
      console.error('Error triggering upload:', error)
      const errorMsg = error.response?.data?.detail || error.message || 'Unknown error'
      alert(`Failed to trigger upload: ${errorMsg}`)
    }
  }

  const handleSaveAndUpload = async () => {
    if (selectedDestinations.length === 0) {
      alert('Please select at least one destination')
      return
    }

    try {
      // Save the video settings
      await updateVideo(video.id, {
        title: title || undefined,
        description: description || undefined,
        privacy: privacy,
        scheduled_time: null, // Upload immediately, no schedule
        upload_destinations: selectedDestinations
      })
      
      // Trigger upload immediately
      const result = await triggerUpload(video.id)
      setIsEditing(false)
      onUpdate()
      
      if (result.status === 'failed') {
        alert(`Upload failed:\n${result.errors.join('\n')}`)
      } else {
        alert('Upload started successfully!')
      }
    } catch (error: any) {
      console.error('Error uploading:', error)
      const errorMsg = error.response?.data?.detail || error.message || 'Unknown error'
      alert(`Failed to upload video: ${errorMsg}`)
    }
  }

  const toggleDestination = (destId: number) => {
    setSelectedDestinations(prev =>
      prev.includes(destId)
        ? prev.filter(id => id !== destId)
        : [...prev, destId]
    )
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return '#4caf50'
      case 'uploading': return '#2196f3'
      case 'scheduled': return '#ff9800'
      case 'failed': return '#f44336'
      default: return '#999'
    }
  }

  return (
    <div className="video-item">
      <div className="video-header">
        <div className="video-title-section">
          <h3>{video.filename}</h3>
          <span 
            className="video-status" 
            style={{ color: getStatusColor(video.status) }}
          >
            {video.status}
          </span>
        </div>
        <div className="video-actions">
          {!isEditing && (
            <>
              <button onClick={() => setIsEditing(true)} className="btn-edit">
                Edit
              </button>
              <button onClick={handleDelete} className="btn-delete">
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      {isEditing && (
        <div className="video-edit-form">
          <div className="form-row">
            <label>
              Title
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Video title"
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              Description
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Video description"
                rows={3}
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              Privacy
              <select
                value={privacy}
                onChange={(e) => setPrivacy(e.target.value)}
              >
                <option value="private">Private</option>
                <option value="unlisted">Unlisted</option>
                <option value="public">Public</option>
              </select>
            </label>
          </div>

          <div className="form-row">
            <label>
              Schedule Upload (Optional)
              <input
                type="datetime-local"
                value={scheduledTime}
                onChange={(e) => setScheduledTime(e.target.value)}
                placeholder="Leave empty for immediate upload"
              />
            </label>
            <small className="form-hint">Leave empty to upload immediately</small>
          </div>

          <div className="form-row">
            <label>Upload Destinations</label>
            <div className="destination-checkboxes">
              {destinations.map((dest) => (
                <label key={dest.id} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={selectedDestinations.includes(dest.id)}
                    onChange={() => toggleDestination(dest.id)}
                    disabled={!dest.enabled}
                  />
                  {dest.platform}
                  {!dest.enabled && ' (disabled)'}
                </label>
              ))}
            </div>
          </div>

          <div className="form-actions">
            <button onClick={handleSaveAndUpload} className="btn-upload-now">
              Upload Now
            </button>
            <button onClick={handleSave} className="btn-save">
              Save
            </button>
            <button onClick={() => setIsEditing(false)} className="btn-cancel">
              Cancel
            </button>
          </div>
        </div>
      )}

      {!isEditing && (
        <div className="video-details">
          {title && <p><strong>Title:</strong> {title}</p>}
          {description && <p><strong>Description:</strong> {description}</p>}
          <p><strong>Privacy:</strong> <span className="privacy-badge">{privacy}</span></p>
          {video.scheduled_time && (
            <p><strong>Scheduled:</strong> {new Date(video.scheduled_time).toLocaleString()}</p>
          )}
          {selectedDestinations.length > 0 && (
            <p>
              <strong>Destinations:</strong>{' '}
              {selectedDestinations.map(id => {
                const dest = destinations.find(d => d.id === id)
                return dest?.platform
              }).join(', ')}
            </p>
          )}

          {video.status === 'pending' && selectedDestinations.length > 0 && (
            <button onClick={handleUpload} className="btn-upload">
              Upload Now
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default VideoItem

