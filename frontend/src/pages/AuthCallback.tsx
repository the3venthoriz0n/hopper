import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { completeYouTubeAuth } from '../utils/api'
import { getStoredUserEmail } from '../utils/storage'
import './AuthCallback.css'

interface AuthCallbackProps {
  onLogin: (userId: number) => void
}

function AuthCallback({ onLogin }: AuthCallbackProps) {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const handleCallback = async () => {
      const code = searchParams.get('code')
      const email = getStoredUserEmail()

      if (!code) {
        setError('No authorization code received')
        return
      }

      if (!email) {
        setError('No email found. Please start over.')
        return
      }

      try {
        const result = await completeYouTubeAuth(code, email)
        onLogin(result.user_id)
        navigate('/')
      } catch (err) {
        console.error('Auth error:', err)
        setError('Failed to complete authentication')
      }
    }

    handleCallback()
  }, [searchParams, navigate, onLogin])

  if (error) {
    return (
      <div className="auth-callback">
        <div className="auth-error">
          <h2>Authentication Error</h2>
          <p>{error}</p>
          <button onClick={() => navigate('/')}>Return Home</button>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-callback">
      <div className="auth-loading">
        <h2>Completing authentication...</h2>
        <p>Please wait while we connect your YouTube account.</p>
      </div>
    </div>
  )
}

export default AuthCallback

