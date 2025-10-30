import { useState } from 'react'
import { getYouTubeAuthUrl } from '../utils/api'
import './LoginPrompt.css'

interface LoginPromptProps {
  onLogin: (userId: number) => void
  onEmailSubmit: (email: string) => void
}

function LoginPrompt({ onLogin, onEmailSubmit }: LoginPromptProps) {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (!email || !email.includes('@')) {
      setError('Please enter a valid email address')
      return
    }

    setLoading(true)
    setError(null)

    try {
      const { url } = await getYouTubeAuthUrl()
      onEmailSubmit(email)
      window.location.href = url
    } catch (err) {
      console.error('Error getting auth URL:', err)
      setError('Failed to start authentication. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div className="login-prompt">
      <div className="login-card">
        <h1>Welcome to Hopper</h1>
        <p className="subtitle">Manage and schedule your video uploads</p>

        <form onSubmit={handleConnect} className="login-form">
          <div className="form-group">
            <label htmlFor="email">Email Address</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="your@email.com"
              required
            />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button type="submit" disabled={loading} className="connect-button">
            {loading ? 'Connecting...' : 'Connect YouTube Account'}
          </button>
        </form>

        <p className="info-text">
          You'll be redirected to Google to authorize YouTube uploads
        </p>
      </div>
    </div>
  )
}

export default LoginPrompt

