import { useState } from 'react'
import { Destination, toggleDestination, removeDestination, getYouTubeAuthUrl } from '../utils/api'
import { getStoredUserEmail } from '../utils/storage'
import './DestinationList.css'

interface DestinationListProps {
  userId: number
  destinations: Destination[]
  onUpdate: () => void
}

function DestinationList({ userId, destinations, onUpdate }: DestinationListProps) {
  const [loading, setLoading] = useState(false)

  const handleToggle = async (destinationId: number, enabled: boolean) => {
    try {
      await toggleDestination(destinationId, enabled)
      onUpdate()
    } catch (error) {
      console.error('Error toggling destination:', error)
    }
  }

  const handleRemove = async (destinationId: number) => {
    if (!confirm('Remove this destination?')) return

    try {
      await removeDestination(destinationId)
      onUpdate()
    } catch (error) {
      console.error('Error removing destination:', error)
    }
  }

  const handleAddYouTube = async () => {
    const email = getStoredUserEmail()
    if (!email) {
      alert('Please log in again')
      return
    }

    setLoading(true)
    try {
      const { url } = await getYouTubeAuthUrl()
      window.location.href = url
    } catch (error) {
      console.error('Error getting auth URL:', error)
      alert('Failed to start authentication')
      setLoading(false)
    }
  }

  const hasYouTube = destinations.some(d => d.platform === 'youtube')

  return (
    <div className="destination-list">
      <h2>Upload Destinations</h2>

      {destinations.length === 0 ? (
        <p className="empty-message">No destinations connected</p>
      ) : (
        <ul className="destinations">
          {destinations.map((destination) => (
            <li key={destination.id} className="destination-item">
              <div className="destination-info">
                <span className="platform-name">
                  {destination.platform.charAt(0).toUpperCase() + destination.platform.slice(1)}
                </span>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={destination.enabled}
                    onChange={(e) => handleToggle(destination.id, e.target.checked)}
                  />
                  <span className="slider"></span>
                </label>
              </div>
              <button
                className="remove-button"
                onClick={() => handleRemove(destination.id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="add-destination">
        {!hasYouTube && (
          <button
            className="add-button"
            onClick={handleAddYouTube}
            disabled={loading}
          >
            {loading ? 'Connecting...' : '+ Add YouTube'}
          </button>
        )}
      </div>
    </div>
  )
}

export default DestinationList

