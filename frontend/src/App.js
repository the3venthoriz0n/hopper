import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

// Use current host for API (works in Docker and locally)
const API = `http://${window.location.hostname}:8000/api`;

function App() {
  const [youtube, setYoutube] = useState({ connected: false, enabled: false });
  const [videos, setVideos] = useState([]);
  const [message, setMessage] = useState('');
  const [youtubeSettings, setYoutubeSettings] = useState({ 
    visibility: 'private', 
    made_for_kids: false,
    title_template: '{filename}',
    description_template: 'Uploaded via Hopper',
    upload_immediately: true,
    schedule_mode: 'spaced',
    schedule_interval_value: 1,
    schedule_interval_unit: 'hours',
    schedule_start_time: ''
  });
  const [showSettings, setShowSettings] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    loadDestinations();
    loadYoutubeSettings();
    loadVideos();
    
    // Check OAuth callback
    if (window.location.search.includes('connected=youtube')) {
      setMessage('✅ YouTube connected!');
      loadDestinations();
      window.history.replaceState({}, '', '/');
    }
    
    // Poll for video updates every 5 seconds to catch scheduled uploads
    const pollInterval = setInterval(() => {
      loadVideos();
    }, 5000);
    
    return () => clearInterval(pollInterval);
  }, []);
  
  const loadVideos = async () => {
    try {
      const res = await axios.get(`${API}/videos`);
      setVideos(res.data);
    } catch (err) {
      console.error('Error loading videos:', err);
    }
  };

  const loadDestinations = async () => {
    const res = await axios.get(`${API}/destinations`);
    setYoutube(res.data.youtube);
  };

  const loadYoutubeSettings = async () => {
    try {
      const res = await axios.get(`${API}/youtube/settings`);
      setYoutubeSettings(res.data);
    } catch (err) {
      console.error('Error loading settings:', err);
    }
  };

  const updateYoutubeSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      params.append(key, value);
      const res = await axios.post(`${API}/youtube/settings?${params.toString()}`);
      setYoutubeSettings(res.data);
      
      if (key === 'visibility') {
        setMessage(`✅ Default visibility set to ${value}`);
      } else if (key === 'made_for_kids') {
        setMessage(`✅ Made for kids: ${value ? 'Yes' : 'No'}`);
      } else if (key === 'upload_immediately') {
        setMessage(`✅ Upload mode: ${value ? 'Immediate' : 'Scheduled'}`);
      } else if (key === 'title_template' || key === 'description_template') {
        setMessage(`✅ Settings updated`);
      } else {
        setMessage(`✅ Settings updated`);
      }
    } catch (err) {
      setMessage('❌ Error updating settings');
    }
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
    
    // Add temp entry with uploading status
    const tempId = Date.now();
    const tempVideo = {
      id: tempId,
      filename: file.name,
      status: 'uploading',
      progress: 0
    };
    setVideos(prev => [...prev, tempVideo]);
    
    try {
      const res = await axios.post(`${API}/videos`, form, {
        onUploadProgress: (progressEvent) => {
          const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setVideos(prev => prev.map(v => 
            v.id === tempId ? { ...v, progress: percent } : v
          ));
        }
      });
      
      // Replace temp with real video data
      setVideos(prev => prev.map(v => 
        v.id === tempId ? { ...res.data, progress: 100 } : v
      ));
      setMessage(`✅ Added ${file.name}`);
    } catch (err) {
      setVideos(prev => prev.filter(v => v.id !== tempId));
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
    
    setIsUploading(true);
    const isScheduling = !youtubeSettings.upload_immediately;
    setMessage(isScheduling ? '⏳ Scheduling videos...' : '⏳ Uploading to YouTube...');
    
    // Only poll for progress if uploading immediately
    let pollInterval;
    if (!isScheduling) {
      pollInterval = setInterval(async () => {
        try {
          const res = await axios.get(`${API}/videos`);
          setVideos(res.data);
        } catch (err) {
          console.error('Error polling videos:', err);
        }
      }, 1000);
    }
    
    try {
      const res = await axios.post(`${API}/upload`);
      if (pollInterval) clearInterval(pollInterval);
      
      if (res.data.uploaded !== undefined) {
        setMessage(`✅ Uploaded ${res.data.uploaded} videos!`);
      } else if (res.data.scheduled !== undefined) {
        setMessage(`✅ ${res.data.scheduled} videos scheduled! ${res.data.message}`);
      } else {
        setMessage(`✅ ${res.data.message || 'Success'}`);
      }
      
      // Final refresh
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    } catch (err) {
      if (pollInterval) clearInterval(pollInterval);
      setMessage(`❌ ${err.response?.data?.detail || 'Operation failed'}`);
      
      // Refresh to get real status
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    } finally {
      setIsUploading(false);
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
              <button onClick={() => setShowSettings(!showSettings)} className="btn-settings">
                ⚙️
              </button>
              <button onClick={disconnectYoutube} className="btn-disconnect">
                Disconnect
              </button>
            </>
          ) : (
            <button onClick={connectYoutube}>Connect</button>
          )}
        </div>

        {/* YouTube Settings */}
        {showSettings && youtube.connected && (
          <div className="settings-panel">
            <h3>YouTube Settings</h3>
            
            <div className="setting-group">
              <label>Default Visibility</label>
              <select 
                value={youtubeSettings.visibility}
                onChange={(e) => updateYoutubeSettings('visibility', e.target.value)}
                className="select"
              >
                <option value="private">Private</option>
                <option value="unlisted">Unlisted</option>
                <option value="public">Public</option>
              </select>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={youtubeSettings.made_for_kids}
                  onChange={(e) => updateYoutubeSettings('made_for_kids', e.target.checked)}
                  className="checkbox"
                />
                <span>Made for Kids</span>
              </label>
            </div>

            <div className="setting-group">
              <label>Video Title Template</label>
              <input 
                type="text"
                value={youtubeSettings.title_template}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, title_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('title_template', e.target.value)}
                placeholder="{filename}"
                className="input-text"
              />
              <small className="hint">Use {'{filename}'} for video filename</small>
            </div>

            <div className="setting-group">
              <label>Video Description Template</label>
              <textarea 
                value={youtubeSettings.description_template}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, description_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('description_template', e.target.value)}
                placeholder="Uploaded via Hopper"
                className="textarea-text"
                rows="3"
              />
              <small className="hint">Use {'{filename}'} for video filename</small>
            </div>

            <div className="setting-divider"></div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={youtubeSettings.upload_immediately}
                  onChange={(e) => updateYoutubeSettings('upload_immediately', e.target.checked)}
                  className="checkbox"
                />
                <span>Upload Immediately</span>
              </label>
              <small className="hint">If disabled, videos will be scheduled</small>
            </div>

            {!youtubeSettings.upload_immediately && (
              <>
                <div className="setting-group">
                  <label>Schedule Mode</label>
                  <select 
                    value={youtubeSettings.schedule_mode}
                    onChange={(e) => updateYoutubeSettings('schedule_mode', e.target.value)}
                    className="select"
                  >
                    <option value="spaced">Spaced Interval</option>
                    <option value="specific_time">Specific Time</option>
                  </select>
                </div>

                {youtubeSettings.schedule_mode === 'spaced' ? (
                  <div className="setting-group">
                    <label>Upload Interval</label>
                    <div className="interval-input">
                      <input 
                        type="number"
                        min="1"
                        value={youtubeSettings.schedule_interval_value}
                        onChange={(e) => {
                          const val = parseInt(e.target.value) || 1;
                          setYoutubeSettings({...youtubeSettings, schedule_interval_value: val});
                        }}
                        onBlur={(e) => {
                          const val = parseInt(e.target.value) || 1;
                          updateYoutubeSettings('schedule_interval_value', val);
                        }}
                        className="input-number"
                      />
                      <select 
                        value={youtubeSettings.schedule_interval_unit}
                        onChange={(e) => updateYoutubeSettings('schedule_interval_unit', e.target.value)}
                        className="select-unit"
                      >
                        <option value="minutes">Minutes</option>
                        <option value="hours">Hours</option>
                        <option value="days">Days</option>
                      </select>
                    </div>
                    <small className="hint">Videos upload one at a time with this interval</small>
                  </div>
                ) : (
                  <div className="setting-group">
                    <label>Start Time</label>
                    <input 
                      type="datetime-local"
                      value={youtubeSettings.schedule_start_time}
                      onChange={(e) => updateYoutubeSettings('schedule_start_time', e.target.value)}
                      className="input-text"
                    />
                    <small className="hint">All videos will upload at this time</small>
                  </div>
                )}
              </>
            )}
          </div>
        )}
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
      
      {/* Upload Button */}
      {videos.length > 0 && youtube.enabled && (
        <button className="upload-btn" onClick={upload} disabled={isUploading}>
          {isUploading ? 'Uploading...' : 
           youtubeSettings.upload_immediately ? 'Upload to YouTube' : 'Schedule Videos'}
        </button>
      )}
      
      {/* Queue */}
      <div className="card">
        <h2>Queue ({videos.length})</h2>
        {videos.length === 0 ? (
          <p className="empty">No videos</p>
        ) : (
          videos.map(v => (
            <div key={v.id} className="video">
              <div className="video-info-container">
                <div className="video-titles">
                  <div className="youtube-title">▶️ {v.youtube_title || v.filename}</div>
                  <div className="filename">File: {v.filename}</div>
                </div>
                <div className="status">
                  {v.status === 'uploading' ? (
                    v.upload_progress !== undefined ? (
                      <span>Uploading to YouTube {v.upload_progress}%</span>
                    ) : v.progress !== undefined && v.progress < 100 ? (
                      <span>Uploading to server {v.progress}%</span>
                    ) : (
                      <span>Processing...</span>
                    )
                  ) : v.status === 'scheduled' && v.scheduled_time ? (
                    <span>Scheduled for {new Date(v.scheduled_time).toLocaleString(undefined, {
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit'
                    })}</span>
                  ) : (
                    <span>{v.status}</span>
                  )}
                </div>
                {v.status === 'uploading' && (
                  <div className="progress-bar">
                    <div 
                      className="progress-fill" 
                      style={{ 
                        width: `${v.upload_progress !== undefined ? v.upload_progress : (v.progress || 0)}%` 
                      }}
                    ></div>
                  </div>
                )}
              </div>
              <button onClick={() => removeVideo(v.id)} disabled={v.status === 'uploading'}>×</button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default App;

