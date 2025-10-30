import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = 'http://localhost:8000';

function App() {
  const [destinations, setDestinations] = useState({
    youtube: { enabled: false, connected: false }
  });
  
  const [videos, setVideos] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    // Check connection status on mount
    checkDestinations();
    
    // Check if OAuth callback succeeded
    const params = new URLSearchParams(window.location.search);
    if (params.get('connected') === 'youtube') {
      setMessage('✅ YouTube connected successfully!');
      setTimeout(() => setMessage(''), 3000);
      checkDestinations();
      window.history.replaceState({}, '', '/');
    }
  }, []);

  const checkDestinations = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/destinations`);
      setDestinations(response.data);
    } catch (error) {
      console.error('Error checking destinations:', error);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    
    const files = Array.from(e.dataTransfer.files).filter(file => 
      file.type.startsWith('video/')
    );
    
    handleFiles(files);
  };

  const handleFileInput = (e) => {
    const files = Array.from(e.target.files);
    handleFiles(files);
  };

  const handleFiles = async (files) => {
    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);
      
      try {
        const response = await axios.post(`${API_URL}/api/videos/upload`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        
        setVideos(prev => [...prev, {
          ...response.data,
          title: file.name.replace(/\.[^/.]+$/, ''),
          file: file
        }]);
        
        setMessage(`✅ Added: ${file.name}`);
        setTimeout(() => setMessage(''), 2000);
      } catch (error) {
        setMessage(`❌ Error uploading: ${file.name}`);
        console.error('Upload error:', error);
      }
    }
  };

  const removeVideo = async (id) => {
    try {
      await axios.delete(`${API_URL}/api/queue/${id}`);
      setVideos(videos.filter(v => v.id !== id));
    } catch (error) {
      console.error('Error removing video:', error);
    }
  };

  const toggleDestination = (dest) => {
    setDestinations({
      ...destinations,
      [dest]: { ...destinations[dest], enabled: !destinations[dest].enabled }
    });
  };

  const connectOAuth = async (dest) => {
    try {
      const response = await axios.get(`${API_URL}/api/auth/${dest}`);
      if (response.data.url) {
        window.location.href = response.data.url;
      }
    } catch (error) {
      setMessage(`❌ Error connecting to ${dest}`);
      console.error('OAuth error:', error);
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  };

  const startUpload = async () => {
    if (!destinations.youtube.enabled || !destinations.youtube.connected) {
      setMessage('❌ Please connect and enable YouTube');
      return;
    }
    
    if (videos.length === 0) {
      setMessage('❌ Please add videos to upload');
      return;
    }
    
    setUploading(true);
    
    try {
      const response = await axios.post(`${API_URL}/api/upload/start`);
      
      setMessage(`✅ ${response.data.message}`);
      console.log('Upload started:', response.data);
    } catch (error) {
      setMessage(`❌ Error: ${error.response?.data?.detail || error.message}`);
      console.error('Upload error:', error);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="App">
      <div className="container">
        <header>
          <h1>🎥 Hopper</h1>
          <p>Simple video uploader for YouTube</p>
          {message && <div className="message">{message}</div>}
        </header>

        <div className="grid">
          {/* Destinations Panel */}
          <div className="panel">
            <h2>⚙️ Destinations</h2>
            
            <div className="destination-card">
              <div className="destination-header">
                <div className="destination-info">
                  <span className="youtube-icon">▶️</span>
                  <span>YouTube</span>
                </div>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={destinations.youtube.enabled}
                    onChange={() => toggleDestination('youtube')}
                    disabled={!destinations.youtube.connected}
                  />
                  <span className="slider"></span>
                </label>
              </div>
              
              {!destinations.youtube.connected ? (
                <button onClick={() => connectOAuth('youtube')} className="btn btn-primary">
                  Connect Account
                </button>
              ) : (
                <div className="status-connected">
                  <span className="dot"></span>
                  Connected
                </div>
              )}
            </div>
          </div>

          {/* Video Queue */}
          <div className="panel panel-large">
            <h2>📤 Upload Queue ({videos.length})</h2>

            <div
              className="drop-zone"
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={() => document.getElementById('fileInput').click()}
            >
              <div className="drop-zone-content">
                <span className="upload-icon">⬆️</span>
                <p>Drag & drop videos here</p>
                <p className="drop-zone-hint">or click to browse</p>
              </div>
              <input
                id="fileInput"
                type="file"
                multiple
                accept="video/*"
                onChange={handleFileInput}
                style={{ display: 'none' }}
              />
            </div>

            <div className="video-list">
              {videos.map((video) => (
                <div key={video.id} className="video-item">
                  <div className="video-info">
                    <h3>{video.title}</h3>
                    <p>{formatFileSize(video.size)} • {video.status}</p>
                  </div>
                  <button onClick={() => removeVideo(video.id)} className="btn-remove">
                    🗑️
                  </button>
                </div>
              ))}
              
              {videos.length === 0 && (
                <p className="empty-state">No videos in queue</p>
              )}
            </div>

            <div className="action-bar">
              <button
                onClick={startUpload}
                disabled={uploading || videos.length === 0}
                className="btn btn-success btn-large"
              >
                {uploading ? '⏳ Uploading...' : '▶️ Upload Now'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
