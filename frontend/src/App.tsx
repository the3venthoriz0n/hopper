import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { useState, useEffect } from 'react'
import Dashboard from './pages/Dashboard'
import AuthCallback from './pages/AuthCallback'
import { getStoredUserId, setStoredUserId } from './utils/storage'

function App() {
  const [userId, setUserId] = useState<number | null>(getStoredUserId())

  const handleLogin = (id: number) => {
    setUserId(id)
    setStoredUserId(id)
  }

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Dashboard userId={userId} onLogin={handleLogin} />} />
        <Route path="/auth/callback" element={<AuthCallback onLogin={handleLogin} />} />
      </Routes>
    </Router>
  )
}

export default App

