import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

// Use current host for API (works in Docker and locally)
const API = `http://${window.location.hostname}:8000/api`;

function App() {
  const [youtube, setYoutube] = useState({ connected: false, enabled: false });
  const [videos, setVideos] = useState([]);
  const [message, setMessage] = useState('');

  useEffect(() => {
    loadDestinations();
    
    // Check OAuth callback
    if (window.location.search.includes('connected=youtube')) {
      setMessage('✅ YouTube connected!');
      loadDestinations();
      window.history.replaceState({}, '', '/');
    }
  }, []);

  const loadDestinations = async () => {
    const res = await axios.get(`${API}/destinations`);
    setYoutube(res.data.youtube);
  };

  const connectYoutube = async () => {
    const res = await axios.get(`${API}/auth/youtube`);
    window.location.href = res.data.url;
  };

  const disconnectYoutube = async () => {
    await axios.post(`${API}/auth/youtube/disconnect`);
    setYoutube({ connected: false, enabled: false });
    setMessage('Disconnected from YouTube');
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => 
      f.type.startsWith('video/')
    );
    files.forEach(addVideo);
  };

  const addVideo = async (file) => {
    const form = new FormData();
    form.append('file', file);
    
    try {
      const res = await axios.post(`${API}/videos`, form);
      setVideos([...videos, res.data]);
      setMessage(`✅ Added ${file.name}`);
    } catch (err) {
      setMessage('❌ Error adding video');
    }
  };

  const removeVideo = async (id) => {
    await axios.delete(`${API}/videos/${id}`);
    setVideos(videos.filter(v => v.id !== id));
  };

  const toggleYoutube = () => {
    setYoutube({ ...youtube, enabled: !youtube.enabled });
  };

  const upload = async () => {
    if (!youtube.enabled) {
      setMessage('❌ Enable YouTube first');
      return;
    }
    
    setMessage('⏳ Uploading...');
    
    try {
      const res = await axios.post(`${API}/upload`);
      setMessage(`✅ Uploaded ${res.data.uploaded} videos!`);
      
      // Refresh
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    } catch (err) {
      setMessage('❌ Upload failed');
    }
  };

  return (
    <div className="app">
      <h1>🎥 Hopper</h1>
      
      {message && <div className="message">{message}</div>}
      
      {/* Destinations */}
      <div className="card">
        <h2>Destinations</h2>
        <div className="destination">
          <div>
            <span>▶️ YouTube</span>
            {youtube.connected && <span className="badge">Connected</span>}
          </div>
          {youtube.connected ? (
            <>
              <label className="toggle">
                <input 
                  type="checkbox" 
                  checked={youtube.enabled}
                  onChange={toggleYoutube}
                />
                <span className="slider"></span>
              </label>
              <button onClick={disconnectYoutube} className="btn-disconnect">
                Disconnect
              </button>
            </>
          ) : (
            <button onClick={connectYoutube}>Connect</button>
          )}
        </div>
      </div>
      
      {/* Drop Zone */}
      <div 
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => document.getElementById('file').click()}
      >
        <p>Drop videos here</p>
        <input 
          id="file"
          type="file"
          multiple
          accept="video/*"
          onChange={(e) => Array.from(e.target.files).forEach(addVideo)}
          style={{display: 'none'}}
        />
      </div>
      
      {/* Queue */}
      <div className="card">
        <h2>Queue ({videos.length})</h2>
        {videos.length === 0 ? (
          <p className="empty">No videos</p>
        ) : (
          videos.map(v => (
            <div key={v.id} className="video">
              <div>
                <div className="name">{v.filename}</div>
                <div className="status">{v.status}</div>
              </div>
              <button onClick={() => removeVideo(v.id)}>×</button>
            </div>
          ))
        )}
      </div>
      
      {/* Upload */}
      {videos.length > 0 && youtube.enabled && (
        <button className="upload-btn" onClick={upload}>
          Upload to YouTube
        </button>
      )}
    </div>
  );
}

export default App;

