import React, { useState, useEffect } from 'react';
import { Routes, Route, Link } from 'react-router-dom';
import axios from 'axios';
import './App.css';
import Terms from './Terms';
import Privacy from './Privacy';

// Configure axios to send cookies with every request
axios.defaults.withCredentials = true;

function Home() {
  // Build API URL at runtime - always use HTTPS
  const getApiUrl = () => {
    const backendUrl = process.env.REACT_APP_BACKEND_URL || `https://${window.location.hostname}`;
    return `${backendUrl}/api`;
  };
  
  const API = getApiUrl();
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const appTitle = isProduction ? '🐸 hopper' : '🐸 DEV hopper';
  
  // Set document title based on environment
  useEffect(() => {
    document.title = isProduction ? 'hopper' : 'DEV HOPPER';
  }, [isProduction]);
  
  const [youtube, setYoutube] = useState({ connected: false, enabled: false, account: null });
  const [tiktok, setTiktok] = useState({ connected: false, enabled: false });
  const [videos, setVideos] = useState([]);
  const [message, setMessage] = useState('');
  const [globalSettings, setGlobalSettings] = useState({
    title_template: '{filename}',
    description_template: 'Uploaded via Hopper',
    wordbank: [],
    upload_immediately: true,
    schedule_mode: 'spaced',
    schedule_interval_value: 1,
    schedule_interval_unit: 'hours',
    schedule_start_time: '',
    allow_duplicates: false
  });
  const [youtubeSettings, setYoutubeSettings] = useState({ 
    visibility: 'private', 
    made_for_kids: false,
    title_template: '',
    description_template: '',
    tags_template: ''
  });
  const [tiktokSettings, setTiktokSettings] = useState({
    privacy_level: 'private',
    allow_comments: true,
    allow_duet: true,
    allow_stitch: true,
    title_template: '',
    description_template: ''
  });
  const [showSettings, setShowSettings] = useState(false);
  const [showTiktokSettings, setShowTiktokSettings] = useState(false);
  const [showGlobalSettings, setShowGlobalSettings] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [editingVideo, setEditingVideo] = useState(null);
  const [draggedVideo, setDraggedVideo] = useState(null);
  const [editTitleLength, setEditTitleLength] = useState(0);
  const [newWord, setNewWord] = useState('');
  const [wordbankExpanded, setWordbankExpanded] = useState(false);

  useEffect(() => {
    loadDestinations();
    loadGlobalSettings();
    loadYoutubeSettings();
    loadTiktokSettings();
    loadVideos();
    
    // Check OAuth callback
    if (window.location.search.includes('connected=youtube')) {
      setMessage('✅ YouTube connected!');
      loadDestinations();
      // Small delay to ensure account info is available
      setTimeout(() => {
        loadYoutubeAccount();
      }, 1000);
      window.history.replaceState({}, '', '/');
    } else if (window.location.search.includes('connected=tiktok')) {
      setMessage('✅ TikTok connected!');
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
      // Only update if the data has actually changed to avoid unnecessary re-renders
      setVideos(prevVideos => {
        const newData = res.data;
        // Check if the data is different
        if (JSON.stringify(prevVideos) === JSON.stringify(newData)) {
          return prevVideos;
        }
        return newData;
      });
    } catch (err) {
      console.error('Error loading videos:', err);
    }
  };

  const loadYoutubeAccount = async () => {
    try {
      const res = await axios.get(`${API}/auth/youtube/account`);
      if (res.data.error) {
        console.error('Error loading YouTube account:', res.data.error);
        setYoutube(prev => ({ ...prev, account: null }));
      } else {
        setYoutube(prev => ({ ...prev, account: res.data.account || null }));
      }
    } catch (error) {
      console.error('Error loading YouTube account:', error.response?.data || error.message);
      setYoutube(prev => ({ ...prev, account: null }));
    }
  };

  const loadDestinations = async () => {
    try {
      const res = await axios.get(`${API}/destinations`);
      setYoutube({ 
        connected: res.data.youtube.connected, 
        enabled: res.data.youtube.enabled,
        account: null  // Will be loaded separately
      });
      setTiktok({ 
        connected: res.data.tiktok.connected, 
        enabled: res.data.tiktok.enabled 
      });
      
      // Load account info if connected
      if (res.data.youtube.connected) {
        loadYoutubeAccount();
      }
    } catch (error) {
      console.error('Error loading destinations:', error);
    }
  };

  const loadGlobalSettings = async () => {
    try {
      const res = await axios.get(`${API}/global/settings`);
      setGlobalSettings(res.data);
    } catch (err) {
      console.error('Error loading global settings:', err);
    }
  };

  const updateGlobalSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      params.append(key, value);
      const res = await axios.post(`${API}/global/settings?${params.toString()}`);
      setGlobalSettings(res.data);
      setMessage(`✅ Settings updated`);
    } catch (err) {
      setMessage('❌ Error updating settings');
      console.error('Error updating settings:', err);
    }
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
      } else if (key === 'title_template' || key === 'description_template') {
        setMessage(`✅ Settings updated`);
      } else {
        setMessage(`✅ Settings updated`);
      }
    } catch (err) {
      setMessage('❌ Error updating settings');
    }
  };

  const loadTiktokSettings = async () => {
    try {
      const res = await axios.get(`${API}/tiktok/settings`);
      setTiktokSettings(res.data);
    } catch (err) {
      console.error('Error loading TikTok settings:', err);
    }
  };

  const updateTiktokSettings = async (key, value) => {
    try {
      const params = new URLSearchParams();
      params.append(key, value);
      const res = await axios.post(`${API}/tiktok/settings?${params.toString()}`);
      setTiktokSettings(res.data);
      
      if (key === 'privacy_level') {
        setMessage(`✅ Privacy level set to ${value}`);
      } else {
        setMessage(`✅ TikTok settings updated`);
      }
    } catch (err) {
      setMessage('❌ Error updating TikTok settings');
    }
  };

  const connectYoutube = async () => {
    const res = await axios.get(`${API}/auth/youtube`);
    window.location.href = res.data.url;
  };

  const disconnectYoutube = async () => {
    try {
      await axios.post(`${API}/auth/youtube/disconnect`);
      setYoutube({ connected: false, enabled: false, account: null });
      setMessage('✅ Disconnected from YouTube');
    } catch (err) {
      setMessage('❌ Error disconnecting');
      console.error('Error disconnecting:', err);
    }
  };

  const connectTiktok = async () => {
    try {
      const res = await axios.get(`${API}/auth/tiktok`);
      window.location.href = res.data.url;
    } catch (err) {
      setMessage(`❌ Error connecting to TikTok: ${err.response?.data?.detail || err.message}`);
      console.error('Error connecting TikTok:', err);
    }
  };

  const disconnectTiktok = async () => {
    try {
      await axios.post(`${API}/auth/tiktok/disconnect`);
      setTiktok({ connected: false, enabled: false });
      setMessage('✅ Disconnected from TikTok');
    } catch (err) {
      setMessage('❌ Error disconnecting from TikTok');
      console.error('Error disconnecting TikTok:', err);
    }
  };

  const addWordToWordbank = async (input) => {
    try {
      // Split by comma, trim, and filter empty strings
      const words = input.split(',').map(w => w.trim()).filter(w => w);
      
      if (words.length === 0) {
        setMessage('❌ No valid words to add');
        return;
      }
      
      // Add each word individually (backend prevents duplicates)
      let addedCount = 0;
      for (const word of words) {
        try {
          const params = new URLSearchParams();
          params.append('word', word);
          const res = await axios.post(`${API}/global/wordbank?${params.toString()}`);
          setGlobalSettings({...globalSettings, wordbank: res.data.wordbank});
          addedCount++;
        } catch (err) {
          console.error(`Error adding word "${word}":`, err);
        }
      }
      
      setNewWord('');
      if (addedCount === words.length) {
        setMessage(`✅ Added ${addedCount} word${addedCount !== 1 ? 's' : ''} to wordbank`);
      } else {
        setMessage(`✅ Added ${addedCount} of ${words.length} words (some were duplicates)`);
      }
      
      // Reload settings to get final wordbank state
      await loadGlobalSettings();
    } catch (err) {
      setMessage('❌ Error adding words');
      console.error('Error adding words:', err);
    }
  };

  const removeWordFromWordbank = async (word) => {
    try {
      await axios.delete(`${API}/global/wordbank/${encodeURIComponent(word)}`);
      setGlobalSettings({...globalSettings, wordbank: globalSettings.wordbank.filter(w => w !== word)});
      setMessage('✅ Word removed from wordbank');
    } catch (err) {
      setMessage('❌ Error removing word');
      console.error('Error removing word:', err);
    }
  };

  const clearWordbank = async () => {
    if (!window.confirm(`Clear all ${globalSettings.wordbank.length} words from wordbank?`)) {
      return;
    }
    try {
      await axios.delete(`${API}/global/wordbank`);
      setGlobalSettings({...globalSettings, wordbank: []});
      setWordbankExpanded(false);
      setMessage('✅ Wordbank cleared');
    } catch (err) {
      setMessage('❌ Error clearing wordbank');
      console.error('Error clearing wordbank:', err);
    }
  };

  const handleFileDrop = (e) => {
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
        const errorMsg = err.response?.data?.detail || 'Error adding video';
        setMessage(`❌ ${errorMsg}`);
        console.error('Error adding video:', err);
      }
  };

  const removeVideo = async (id) => {
    await axios.delete(`${API}/videos/${id}`);
    setVideos(videos.filter(v => v.id !== id));
  };

  const cancelScheduled = async () => {
    try {
      const res = await axios.post(`${API}/videos/cancel-scheduled`);
      setMessage(`✅ Cancelled ${res.data.cancelled} scheduled videos`);
      await loadVideos();
    } catch (err) {
      setMessage('❌ Error cancelling scheduled videos');
      console.error('Error cancelling scheduled videos:', err);
    }
  };

  const closeEditModal = () => {
    setEditingVideo(null);
    setEditTitleLength(0);
  };

  const updateVideoSettings = async (videoId, settings) => {
    try {
      const params = new URLSearchParams();
      Object.entries(settings).forEach(([key, value]) => {
        // Include empty strings (for clearing values like scheduled_time)
        if (value !== null && value !== undefined) {
          params.append(key, value);
        }
      });
      
      await axios.patch(`${API}/videos/${videoId}?${params.toString()}`);
      
      // Reload videos to get updated computed titles
      await loadVideos();
      
      setMessage('✅ Video settings updated');
      closeEditModal();
    } catch (err) {
      setMessage('❌ Error updating video');
      console.error('Error updating video:', err);
    }
  };

  const recomputeVideoTitle = async (videoId) => {
    try {
      await axios.post(`${API}/videos/${videoId}/recompute-title`);
      
      // Reload videos to get updated title
      await loadVideos();
      
      setMessage('✅ Title recomputed from template');
      
      // Update the edit modal title field if it's open
      const titleInput = document.getElementById('edit-title');
      if (titleInput) {
        // Get the updated video data
        const videosRes = await axios.get(`${API}/videos`);
        const updatedVideo = videosRes.data.find(v => v.id === videoId);
        if (updatedVideo) {
          titleInput.value = updatedVideo.youtube_title || '';
          setEditTitleLength(titleInput.value.length);
        }
      }
    } catch (err) {
      setMessage('❌ Error recomputing title');
      console.error('Error recomputing title:', err);
    }
  };

  const handleDragStart = (e, video) => {
    // Only allow dragging if not uploading
    if (video.status === 'uploading') {
      e.preventDefault();
      return;
    }
    setDraggedVideo(video);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(video.id));
  };

  const handleDragEnd = (e) => {
    setDraggedVideo(null);
    // Remove any visual artifacts
    e.currentTarget.style.opacity = '1';
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDrop = async (e, targetVideo) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (!draggedVideo || draggedVideo.id === targetVideo.id) {
      setDraggedVideo(null);
      return;
    }

    // Store original videos in case we need to revert
    const originalVideos = [...videos];
    
    const newVideos = [...videos];
    const draggedIdx = newVideos.findIndex(v => v.id === draggedVideo.id);
    const targetIdx = newVideos.findIndex(v => v.id === targetVideo.id);
    
    if (draggedIdx === -1 || targetIdx === -1) {
      setDraggedVideo(null);
      return;
    }
    
    // Remove dragged item from its current position
    const [draggedItem] = newVideos.splice(draggedIdx, 1);
    
    // Calculate correct insertion index after removal
    // If dragging down (original draggedIdx < targetIdx), 
    // the target has shifted up by 1, so we insert at targetIdx - 1
    // If dragging up (original draggedIdx > targetIdx),
    // the target hasn't shifted, so we insert at targetIdx
    const insertIdx = draggedIdx < targetIdx ? targetIdx - 1 : targetIdx;
    
    // Insert at new position  
    newVideos.splice(insertIdx, 0, draggedItem);
    
    // Clear dragged state immediately
    setDraggedVideo(null);
    
    // Update state optimistically for instant visual feedback
    setVideos(newVideos);
    
    // Save to backend
    try {
      const videoIds = newVideos.map(v => v.id);
      await axios.post(`${API}/videos/reorder`, { video_ids: videoIds });
    } catch (err) {
      console.error('Error reordering videos:', err);
      setMessage('❌ Error reordering videos');
      // Revert to original order on error
      setVideos(originalVideos);
    }
  };

  const toggleYoutube = async () => {
    const newEnabled = !youtube.enabled;
    setYoutube({ ...youtube, enabled: newEnabled });
    
    try {
      const params = new URLSearchParams();
      params.append('enabled', newEnabled);
      await axios.post(`${API}/destinations/youtube/toggle?${params.toString()}`);
    } catch (err) {
      console.error('Error toggling YouTube:', err);
      // Revert on error
      setYoutube({ ...youtube, enabled: !newEnabled });
    }
  };

  const toggleTiktok = async () => {
    const newEnabled = !tiktok.enabled;
    setTiktok({ ...tiktok, enabled: newEnabled });
    
    try {
      const params = new URLSearchParams();
      params.append('enabled', newEnabled);
      await axios.post(`${API}/destinations/tiktok/toggle?${params.toString()}`);
    } catch (err) {
      console.error('Error toggling TikTok:', err);
      // Revert on error
      setTiktok({ ...tiktok, enabled: !newEnabled });
    }
  };

  const upload = async () => {
    if (!youtube.enabled && !tiktok.enabled) {
      setMessage('❌ Enable at least one destination first');
      return;
    }
    
    setIsUploading(true);
    const isScheduling = !globalSettings.upload_immediately;
    setMessage(isScheduling ? '⏳ Scheduling videos...' : '⏳ Uploading...');
    
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
      const errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Unknown error';
      console.error('Upload error:', err);
      setMessage(`❌ Upload failed: ${errorMsg}`);
      
      // Refresh to get real status
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="app">
      <h1>{appTitle}</h1>
      
      {/* Global Settings */}
      <div className="card">
        <div className="card-header" onClick={() => setShowGlobalSettings(!showGlobalSettings)}>
          <h2>⚙️ Global Settings</h2>
          <button className="settings-toggle">{showGlobalSettings ? '−' : '+'}</button>
        </div>
        {showGlobalSettings && (
          <div className="settings-panel">
            <div className="setting-group">
              <label>
                Video Title Template <span className="char-counter">{globalSettings.title_template.length}/100</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Use {'{filename}'} for filename, {'{random}'} for random wordbank word</span>
                </span>
              </label>
              <input 
                type="text"
                value={globalSettings.title_template}
                onChange={(e) => setGlobalSettings({...globalSettings, title_template: e.target.value})}
                onBlur={(e) => updateGlobalSettings('title_template', e.target.value)}
                placeholder="{filename}"
                className="input-text"
                maxLength="100"
              />
            </div>

            <div className="setting-group">
              <label>
                Video Description Template
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Use {'{filename}'} for filename, {'{random}'} for random wordbank word</span>
                </span>
              </label>
              <textarea 
                value={globalSettings.description_template}
                onChange={(e) => setGlobalSettings({...globalSettings, description_template: e.target.value})}
                onBlur={(e) => updateGlobalSettings('description_template', e.target.value)}
                placeholder="Uploaded via hopper"
                className="textarea-text"
                rows="3"
              />
            </div>

            <div className="setting-divider"></div>

            <div className="setting-group">
              <div className="wordbank-label">
                <div className="wordbank-title">
                  <span>
                    Random Wordbank ({globalSettings.wordbank.length} words)
                    <span className="tooltip-wrapper">
                      <span className="tooltip-icon">i</span>
                      <span className="tooltip-text">Words to use with {'{random}'} placeholder. Enter comma-separated words to add multiple at once</span>
                    </span>
                  </span>
                  {globalSettings.wordbank.length > 0 && (
                    <span 
                      className={`wordbank-caret ${wordbankExpanded ? 'expanded' : ''}`}
                      onClick={() => setWordbankExpanded(!wordbankExpanded)}
                      title={wordbankExpanded ? 'Hide words' : 'Show words'}
                    >
                      ▼
                    </span>
                  )}
                </div>
                {globalSettings.wordbank.length > 0 && (
                  <button 
                    onClick={(e) => {
                      e.stopPropagation();
                      clearWordbank();
                    }}
                    className="btn-clear-wordbank"
                    title="Clear all words"
                  >
                    Clear All
                  </button>
                )}
              </div>
              <div className="wordbank-input">
                <input 
                  type="text"
                  value={newWord}
                  onChange={(e) => setNewWord(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && newWord.trim() && addWordToWordbank(newWord.trim())}
                  placeholder="Add word(s) - comma-separated for multiple"
                  className="input-text"
                />
                <button 
                  onClick={() => newWord.trim() && addWordToWordbank(newWord.trim())}
                  className="btn-add-word"
                  disabled={!newWord.trim()}
                >
                  Add
                </button>
              </div>
              
              {globalSettings.wordbank.length > 0 && wordbankExpanded && (
                <div className="wordbank-list">
                  {globalSettings.wordbank.map((word, idx) => (
                    <div key={idx} className="wordbank-item">
                      <span>{word}</span>
                      <button onClick={() => removeWordFromWordbank(word)} className="btn-remove-word">×</button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="setting-divider"></div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={globalSettings.upload_immediately}
                  onChange={(e) => updateGlobalSettings('upload_immediately', e.target.checked)}
                  className="checkbox"
                />
                <span>
                  Upload Immediately
                  <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">If disabled, videos will be scheduled</span>
                  </span>
                </span>
              </label>
            </div>

            {!globalSettings.upload_immediately && (
              <>
                <div className="setting-group">
                  <label>Schedule Mode</label>
                  <select 
                    value={globalSettings.schedule_mode}
                    onChange={(e) => updateGlobalSettings('schedule_mode', e.target.value)}
                    className="select"
                  >
                    <option value="spaced">Spaced Interval</option>
                    <option value="specific_time">Specific Time</option>
                  </select>
                </div>

                {globalSettings.schedule_mode === 'spaced' ? (
                  <div className="setting-group">
                    <label>
                      Upload Interval
                      <span className="tooltip-wrapper">
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">Videos upload one at a time with this interval</span>
                      </span>
                    </label>
                    <div className="interval-input">
                      <input 
                        type="number"
                        min="1"
                        value={globalSettings.schedule_interval_value}
                        onChange={(e) => {
                          const val = parseInt(e.target.value) || 1;
                          setGlobalSettings({...globalSettings, schedule_interval_value: val});
                        }}
                        onBlur={(e) => {
                          const val = parseInt(e.target.value) || 1;
                          updateGlobalSettings('schedule_interval_value', val);
                        }}
                        className="input-number"
                      />
                      <select 
                        value={globalSettings.schedule_interval_unit}
                        onChange={(e) => updateGlobalSettings('schedule_interval_unit', e.target.value)}
                        className="select-unit"
                      >
                        <option value="minutes">Minutes</option>
                        <option value="hours">Hours</option>
                        <option value="days">Days</option>
                      </select>
                    </div>
                  </div>
                ) : (
                  <div className="setting-group">
                    <label>
                      Start Time
                      <span className="tooltip-wrapper">
                        <span className="tooltip-icon">i</span>
                        <span className="tooltip-text">All videos will upload at this time</span>
                      </span>
                    </label>
                    <input 
                      type="datetime-local"
                      value={globalSettings.schedule_start_time}
                      onChange={(e) => updateGlobalSettings('schedule_start_time', e.target.value)}
                      className="input-text"
                    />
                  </div>
                )}
              </>
            )}

            <div className="setting-divider"></div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={globalSettings.allow_duplicates}
                  onChange={(e) => updateGlobalSettings('allow_duplicates', e.target.checked)}
                  className="checkbox"
                />
                <span>
                  Allow Duplicate Videos
                  <span className="tooltip-wrapper" style={{ marginLeft: '6px' }}>
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Allow uploading videos with the same filename</span>
                  </span>
                </span>
              </label>
            </div>
          </div>
        )}
      </div>
      
      {/* Destinations */}
      <div className="card">
        <h2>Destinations</h2>
        <div className="destination">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" fill="#FF0000"/>
              </svg>
              YouTube
            </span>
            <div style={{ 
              width: '10px', 
              height: '10px', 
              borderRadius: '50%', 
              backgroundColor: youtube.connected ? '#22c55e' : '#ef4444',
              flexShrink: 0
            }}></div>
            {youtube.connected && (
              <span className="account-info" style={{ fontSize: '0.9em', color: '#999', marginLeft: '4px' }}>
                {youtube.account ? (
                  youtube.account.channel_name ? 
                    youtube.account.channel_name + (youtube.account.email ? ` (${youtube.account.email})` : '') : 
                    youtube.account.email || 'Unknown account'
                ) : (
                  'Loading account...'
                )}
              </span>
            )}
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
              <label>
                YouTube Title Template (Override) <span className="char-counter">{youtubeSettings.title_template?.length || 0}/100</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Override global title template for YouTube only. Leave empty to use global</span>
                </span>
              </label>
              <input 
                type="text"
                value={youtubeSettings.title_template || ''}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, title_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('title_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="input-text"
                maxLength="100"
              />
            </div>

            <div className="setting-group">
              <label>
                YouTube Description Template (Override)
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Override global description template for YouTube only. Leave empty to use global</span>
                </span>
              </label>
              <textarea 
                value={youtubeSettings.description_template || ''}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, description_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('description_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="textarea-text"
                rows="3"
              />
            </div>

            <div className="setting-group">
              <label>
                Video Tags Template
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Comma-separated tags. Use {'{filename}'} or {'{random}'}</span>
                </span>
              </label>
              <input 
                type="text"
                value={youtubeSettings.tags_template}
                onChange={(e) => setYoutubeSettings({...youtubeSettings, tags_template: e.target.value})}
                onBlur={(e) => updateYoutubeSettings('tags_template', e.target.value)}
                placeholder="tag1, tag2, tag3"
                className="input-text"
              />
            </div>
            
            <div className="setting-divider"></div>
            
            <div className="setting-group">
              <button onClick={disconnectYoutube} className="btn-logout" style={{
                width: '100%',
                padding: '0.75rem',
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '6px',
                color: '#ef4444',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: '500',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.2)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.5)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.1)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.3)';
              }}>
                Log Out
              </button>
            </div>
          </div>
        )}

        {/* TikTok Destination */}
        <div className="destination">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z" fill="#FFFFFF"/>
              </svg>
              TikTok
            </span>
            <div style={{ 
              width: '10px', 
              height: '10px', 
              borderRadius: '50%', 
              backgroundColor: tiktok.connected ? '#22c55e' : '#ef4444',
              flexShrink: 0
            }}></div>
          </div>
          {tiktok.connected ? (
            <>
              <label className="toggle">
                <input 
                  type="checkbox" 
                  checked={tiktok.enabled}
                  onChange={toggleTiktok}
                />
                <span className="slider"></span>
              </label>
              <button onClick={() => setShowTiktokSettings(!showTiktokSettings)} className="btn-settings">
                ⚙️
              </button>
            </>
          ) : (
            <button onClick={connectTiktok}>Connect</button>
          )}
        </div>

        {/* TikTok Settings */}
        {showTiktokSettings && tiktok.connected && (
          <div className="settings-panel">
            <h3>TikTok Settings</h3>
            
            <div className="setting-group">
              <label>Privacy Level</label>
              <select 
                value={tiktokSettings.privacy_level}
                onChange={(e) => updateTiktokSettings('privacy_level', e.target.value)}
                className="select"
              >
                <option value="private">Private</option>
                <option value="friends">Friends</option>
                <option value="public">Public</option>
              </select>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_comments}
                  onChange={(e) => updateTiktokSettings('allow_comments', e.target.checked)}
                  className="checkbox"
                />
                <span>Allow Comments</span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_duet}
                  onChange={(e) => updateTiktokSettings('allow_duet', e.target.checked)}
                  className="checkbox"
                />
                <span>Allow Duet</span>
              </label>
            </div>

            <div className="setting-group">
              <label className="checkbox-label">
                <input 
                  type="checkbox"
                  checked={tiktokSettings.allow_stitch}
                  onChange={(e) => updateTiktokSettings('allow_stitch', e.target.checked)}
                  className="checkbox"
                />
                <span>Allow Stitch</span>
              </label>
            </div>

            <div className="setting-group">
              <label>
                TikTok Title Template (Caption) (Override) <span className="char-counter">{tiktokSettings.title_template?.length || 0}/2200</span>
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">Override global title template for TikTok only. This is the video caption (max 2200 characters). Leave empty to use global</span>
                </span>
              </label>
              <input 
                type="text"
                value={tiktokSettings.title_template || ''}
                onChange={(e) => setTiktokSettings({...tiktokSettings, title_template: e.target.value})}
                onBlur={(e) => updateTiktokSettings('title_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="input-text"
                maxLength="2200"
              />
            </div>

            <div className="setting-group">
              <label>
                TikTok Description Template (Override)
                <span className="tooltip-wrapper">
                  <span className="tooltip-icon">i</span>
                  <span className="tooltip-text">TikTok only uses the caption (title) field. Description is not supported by TikTok API.</span>
                </span>
              </label>
              <textarea 
                value={tiktokSettings.description_template || ''}
                onChange={(e) => setTiktokSettings({...tiktokSettings, description_template: e.target.value})}
                onBlur={(e) => updateTiktokSettings('description_template', e.target.value)}
                placeholder="Leave empty to use global template"
                className="textarea-text"
                rows="3"
                disabled
              />
            </div>
            
            <div className="setting-divider"></div>
            
            <div className="setting-group">
              <button onClick={disconnectTiktok} className="btn-logout" style={{
                width: '100%',
                padding: '0.75rem',
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '6px',
                color: '#ef4444',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: '500',
                transition: 'all 0.2s'
              }}
              onMouseEnter={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.2)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.5)';
              }}
              onMouseLeave={(e) => {
                e.target.style.background = 'rgba(239, 68, 68, 0.1)';
                e.target.style.borderColor = 'rgba(239, 68, 68, 0.3)';
              }}>
                Log Out
              </button>
            </div>
          </div>
        )}
      </div>
      
      {/* Upload Button */}
      {videos.length > 0 && (youtube.enabled || tiktok.enabled) && (
        <>
          <button className="upload-btn" onClick={upload} disabled={isUploading}>
            {isUploading ? 'Uploading...' : 
             globalSettings.upload_immediately ? 'Upload' : 'Schedule Videos'}
          </button>
          
          {/* Cancel Scheduled Button */}
          {videos.some(v => v.status === 'scheduled') && (
            <button className="cancel-scheduled-btn" onClick={cancelScheduled}>
              Cancel Scheduled ({videos.filter(v => v.status === 'scheduled').length})
            </button>
          )}
        </>
      )}
      
      {/* Drop Zone */}
      <div 
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleFileDrop}
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
      {message && <div className="message">{message}</div>}
      <div className="card">
        <h2>Queue ({videos.length})</h2>
        {videos.length === 0 ? (
          <p className="empty">No videos</p>
        ) : (
          videos.map(v => (
            <div 
              key={v.id} 
              className={`video ${draggedVideo?.id === v.id ? 'dragging' : ''}`}
              draggable={v.status !== 'uploading'}
              onDragStart={(e) => handleDragStart(e, v)}
              onDragEnd={handleDragEnd}
              onDragOver={handleDragOver}
              onDrop={(e) => handleDrop(e, v)}
            >
              <div className="drag-handle" title="Drag to reorder">⋮⋮</div>
              <div className="video-info-container">
                <div className="video-titles">
                  <div className="youtube-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" fill="#FF0000"/>
                    </svg>
                    {v.youtube_title || v.filename}
                    {v.title_too_long && (
                      <span className="title-warning" title={`Title truncated from ${v.title_original_length} to 100 characters`}>
                        ⚠️ {v.title_original_length}
                      </span>
                    )}
                  </div>
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
              <div className="video-actions">
                {v.status !== 'uploading' && v.status !== 'uploaded' && (
                  <button onClick={() => {
                    setEditingVideo(v);
                    setEditTitleLength((v.custom_settings?.title || v.youtube_title || '').length);
                  }} className="btn-edit" title="Edit video settings">
                    ✏️
                  </button>
                )}
                <button onClick={() => removeVideo(v.id)} disabled={v.status === 'uploading'}>×</button>
              </div>
            </div>
          ))
        )}
      </div>
      
      {/* Edit Video Modal */}
      {editingVideo && (
        <div className="modal-overlay" onClick={closeEditModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Edit Video Settings</h2>
              <button onClick={closeEditModal} className="btn-close">×</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <label>Video Title <span className="char-counter">{editTitleLength}/100</span></label>
                  <button 
                    type="button"
                    onClick={() => recomputeVideoTitle(editingVideo.id)}
                    className="btn-recompute-title"
                    style={{
                      padding: '0.4rem 0.8rem',
                      fontSize: '0.85rem',
                      background: 'rgba(139, 92, 246, 0.2)',
                      border: '1px solid rgba(139, 92, 246, 0.4)',
                      borderRadius: '4px',
                      color: '#8b5cf6',
                      cursor: 'pointer',
                      fontWeight: '500'
                    }}
                    title="Recompute title from current template"
                  >
                    🔄 Recompute
                  </button>
                </div>
                <input 
                  type="text"
                  defaultValue={editingVideo.custom_settings?.title || editingVideo.youtube_title}
                  id="edit-title"
                  className="input-text"
                  placeholder="Video title"
                  maxLength="100"
                  onInput={(e) => setEditTitleLength(e.target.value.length)}
                />
                <div style={{ marginTop: '0.5rem' }}>
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Leave empty to use template. Click "Recompute" to regenerate from current template.</span>
                  </span>
                </div>
              </div>
              
              <div className="form-group">
                <label>
                  Description
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Leave empty to use global template</span>
                  </span>
                </label>
                <textarea 
                  defaultValue={editingVideo.custom_settings?.description || ''}
                  id="edit-description"
                  className="textarea-text"
                  rows="4"
                  placeholder="Video description"
                />
              </div>
              
              <div className="form-group">
                <label>
                  Tags
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Comma-separated tags. Leave empty to use global template</span>
                  </span>
                </label>
                <input 
                  type="text"
                  defaultValue={editingVideo.custom_settings?.tags || ''}
                  id="edit-tags"
                  className="input-text"
                  placeholder="tag1, tag2, tag3"
                />
              </div>
              
              <div className="form-group">
                <label>Visibility</label>
                <select 
                  defaultValue={editingVideo.custom_settings?.visibility || youtubeSettings.visibility}
                  id="edit-visibility"
                  className="select"
                >
                  <option value="private">Private</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="public">Public</option>
                </select>
              </div>
              
              <div className="form-group">
                <label className="checkbox-label">
                  <input 
                    type="checkbox"
                    defaultChecked={editingVideo.custom_settings?.made_for_kids ?? youtubeSettings.made_for_kids}
                    id="edit-made-for-kids"
                    className="checkbox"
                  />
                  <span>Made for Kids</span>
                </label>
              </div>
              
              <div className="form-group">
                <label>
                  Scheduled Time
                  <span className="tooltip-wrapper">
                    <span className="tooltip-icon">i</span>
                    <span className="tooltip-text">Leave empty for immediate upload (if enabled) or use global schedule</span>
                  </span>
                </label>
                <input 
                  type="datetime-local"
                  defaultValue={editingVideo.scheduled_time ? (() => {
                    const date = new Date(editingVideo.scheduled_time);
                    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
                    return localDate.toISOString().slice(0, 16);
                  })() : ''}
                  id="edit-scheduled-time"
                  className="input-text"
                />
              </div>
            </div>
            <div className="modal-footer">
              <button onClick={closeEditModal} className="btn-cancel">
                Cancel
              </button>
              <button 
                onClick={() => {
                  const title = document.getElementById('edit-title').value;
                  const description = document.getElementById('edit-description').value;
                  const tags = document.getElementById('edit-tags').value;
                  const visibility = document.getElementById('edit-visibility').value;
                  const madeForKids = document.getElementById('edit-made-for-kids').checked;
                  const scheduledTime = document.getElementById('edit-scheduled-time').value;
                  
                  updateVideoSettings(editingVideo.id, {
                    title: title || null,
                    description: description || null,
                    tags: tags || null,
                    visibility,
                    made_for_kids: madeForKids,
                    scheduled_time: scheduledTime ? new Date(scheduledTime).toISOString() : ''
                  });
                }}
                className="btn-save"
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Footer */}
      <footer style={{
        marginTop: '3rem',
        padding: '1.5rem',
        textAlign: 'center',
        borderTop: '1px solid #eee',
        color: '#666',
        fontSize: '0.9rem'
      }}>
        <Link 
          to="/terms" 
          style={{ 
            color: '#666', 
            textDecoration: 'none', 
            marginRight: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = '#0066cc'}
          onMouseLeave={(e) => e.target.style.color = '#666'}
        >
          Terms of Service
        </Link>
        <span style={{ color: '#ccc' }}>|</span>
        <Link 
          to="/privacy" 
          style={{ 
            color: '#666', 
            textDecoration: 'none', 
            marginLeft: '1rem',
            transition: 'color 0.2s'
          }}
          onMouseEnter={(e) => e.target.style.color = '#0066cc'}
          onMouseLeave={(e) => e.target.style.color = '#666'}
        >
          Privacy Policy
        </Link>
      </footer>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />
    </Routes>
  );
}

export default App;

