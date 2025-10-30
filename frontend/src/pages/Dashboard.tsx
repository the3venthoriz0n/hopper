import { useState, useEffect } from 'react'
import { getUserDestinations, getUserVideos, Destination, Video } from '../utils/api'
import { getStoredUserEmail, setStoredUserEmail } from '../utils/storage'
import DestinationList from '../components/DestinationList'
import VideoDropzone from '../components/VideoDropzone'
import VideoList from '../components/VideoList'
import LoginPrompt from '../components/LoginPrompt'
import './Dashboard.css'

interface DashboardProps {
  userId: number | null
  onLogin: (userId: number) => void
}

function Dashboard({ userId, onLogin }: DashboardProps) {
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(false)
  const [userEmail, setUserEmail] = useState<string>(getStoredUserEmail() || '')

  useEffect(() => {
    if (userId) {
      loadData()
    }
  }, [userId])

  const loadData = async () => {
    if (!userId) return
    
    setLoading(true)
    try {
      const [dests, vids] = await Promise.all([
        getUserDestinations(userId),
        getUserVideos(userId)
      ])
      setDestinations(dests)
      setVideos(vids)
    } catch (error) {
      console.error('Error loading data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleEmailSubmit = (email: string) => {
    setUserEmail(email)
    setStoredUserEmail(email)
  }

  if (!userId) {
    return <LoginPrompt onLogin={onLogin} onEmailSubmit={handleEmailSubmit} />
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Hopper</h1>
        <p className="user-email">{userEmail}</p>
      </header>

      <div className="dashboard-content">
        <aside className="sidebar">
          <DestinationList
            userId={userId}
            destinations={destinations}
            onUpdate={loadData}
          />
        </aside>

        <main className="main-content">
          <VideoDropzone userId={userId} onUpload={loadData} />
          
          {loading ? (
            <div className="loading">Loading...</div>
          ) : (
            <VideoList
              videos={videos}
              destinations={destinations}
              onUpdate={loadData}
            />
          )}
        </main>
      </div>
    </div>
  )
}

export default Dashboard

