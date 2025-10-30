import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

function App() {
  const [connected, setConnected] = useState(false);
  const [videos, setVideos] = useState([]);
  const [message, setMessage] = useState('');

  useEffect(() => {
    checkConnection();
    
    // Check OAuth callback
    const params = new URLSearchParams(window.location.search);
    if (params.get('connected')) {
      setMessage('✅ Connected to YouTube!');
      checkConnection();
      window.history.replaceState({}, '', '/');
    }
  }, []);

  const checkConnection = async () => {
    try {
      const res = await axios.get('http://localhost:8000/api/youtube/status');
      setConnected(res.data.connected);
    } catch (error) {
      console.error('Error checking connection:', error);
    }
  };

  const connect = async () => {
    try {
      const res = await axios.get('http://localhost:8000/api/youtube/connect');
      window.location.href = res.data.url;
    } catch (error) {
      setMessage('❌ Error: ' + error.response?.data?.detail);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('video/'));
    files.forEach(addVideo);
  };

  const handleFiles = (e) => {
    const files = Array.from(e.target.files);
    files.forEach(addVideo);
  };

  const addVideo = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      const res = await axios.post('http://localhost:8000/api/videos/add', formData);
      setVideos([...videos, res.data]);
      setMessage(`✅ Added: ${file.name}`);
    } catch (error) {
      setMessage('❌ Error adding video');
    }
  };

  const upload = async () => {
    if (!connected) {
      setMessage('❌ Connect to YouTube first');
      return;
    }
    
    setMessage('⏳ Uploading...');
    
    try {
      await axios.post('http://localhost:8000/api/videos/upload');
      setMessage('✅ Upload complete!');
      
      // Refresh video list
      const res = await axios.get('http://localhost:8000/api/videos');
      setVideos(res.data.videos);
    } catch (error) {
      setMessage('❌ Upload failed: ' + error.response?.data?.detail);
    }
  };

  const removeVideo = async (id) => {
    try {
      await axios.delete(`http://localhost:8000/api/videos/${id}`);
      setVideos(videos.filter(v => v.id !== id));
    } catch (error) {
      console.error('Error removing video:', error);
    }
  };

  return (
    <div className="app">
      <div className="container">
        <h1>🎥 Hopper</h1>
        <p>Drag videos, upload to YouTube</p>
        
        {message && <div className="message">{message}</div>}
        
        {/* Connection */}
        <div className="section">
          <h2>YouTube</h2>
          {!connected ? (
            <button onClick={connect} className="btn">Connect YouTube</button>
          ) : (
            <div className="connected">✓ Connected</div>
          )}
        </div>
        
        {/* Drop Zone */}
        <div 
          className="dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => document.getElementById('file').click()}
        >
          <p>Drop videos here or click to browse</p>
          <input 
            id="file" 
            type="file" 
            multiple 
            accept="video/*" 
            onChange={handleFiles}
            style={{display: 'none'}}
          />
        </div>
        
        {/* Video List */}
        <div className="section">
          <h2>Queue ({videos.length})</h2>
          {videos.length === 0 ? (
            <p className="empty">No videos yet</p>
          ) : (
            <div className="videos">
              {videos.map(v => (
                <div key={v.id} className="video">
                  <div>
                    <div className="filename">{v.filename}</div>
                    <div className="status">{v.status}</div>
                  </div>
                  <button onClick={() => removeVideo(v.id)} className="remove">×</button>
                </div>
              ))}
            </div>
          )}
        </div>
        
        {/* Upload Button */}
        {videos.length > 0 && (
          <button onClick={upload} className="btn btn-upload">
            Upload to YouTube
          </button>
        )}
      </div>
    </div>
  );
}

export default App;
