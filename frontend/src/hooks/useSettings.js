import { useState, useCallback } from 'react';
import axios from '../services/api';
import { getApiUrl } from '../services/api';

/**
 * Hook for managing all settings (global, YouTube, TikTok, Instagram)
 */
export function useSettings() {
  const [globalSettings, setGlobalSettings] = useState({
    title_template: '{filename}',
    description_template: 'Uploaded via Hopper',
    wordbank: [],
    upload_immediately: true,
    schedule_mode: 'spaced',
    schedule_interval_value: 1,
    schedule_interval_unit: 'hours',
    schedule_start_time: '',
    upload_first_immediately: true,
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
    privacy_level: '',
    allow_comments: false,
    allow_duet: false,
    allow_stitch: false,
    title_template: '',
    description_template: '',
    commercial_content_disclosure: false,
    commercial_content_your_brand: false,
    commercial_content_branded: false
  });
  const [instagramSettings, setInstagramSettings] = useState({
    caption_template: '',
    disable_comments: false,
    disable_likes: false,
    media_type: 'REELS',
    share_to_feed: true,
    cover_url: ''
  });

  const API = getApiUrl();

  const loadGlobalSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/global/settings`);
      setGlobalSettings({
        title_template: '{filename}',
        description_template: 'Uploaded via Hopper',
        wordbank: [],
        upload_immediately: true,
        schedule_mode: 'spaced',
        schedule_interval_value: 1,
        schedule_interval_unit: 'hours',
        schedule_start_time: '',
        upload_first_immediately: true,
        allow_duplicates: false,
        ...res.data
      });
    } catch (err) {
      console.error('Error loading global settings:', err);
    }
  }, [API]);

  const loadYoutubeSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/youtube/settings`);
      setYoutubeSettings(res.data);
    } catch (err) {
      console.error('Error loading YouTube settings:', err);
    }
  }, [API]);

  const loadTiktokSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/tiktok/settings`);
      setTiktokSettings(res.data);
    } catch (err) {
      console.error('Error loading TikTok settings:', err);
    }
  }, [API]);

  const loadInstagramSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/instagram/settings`);
      setInstagramSettings({
        caption_template: '',
        disable_comments: false,
        disable_likes: false,
        media_type: 'REELS',
        share_to_feed: true,
        cover_url: '',
        ...res.data
      });
    } catch (err) {
      console.error('Error loading Instagram settings:', err);
    }
  }, [API]);

  const updateGlobalSettings = useCallback(async (key, value, setMessage) => {
    try {
      const res = await axios.post(`${API}/global/settings`, { [key]: value });
      setGlobalSettings(prev => ({
        ...prev,
        ...res.data
      }));
      if (setMessage) {
        setMessage(`✅ Settings updated`);
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error updating settings');
      }
      console.error('Error updating settings:', err);
    }
  }, [API]);

  const updateYoutubeSettings = useCallback(async (key, value, setMessage) => {
    try {
      const res = await axios.post(`${API}/youtube/settings`, { [key]: value });
      setYoutubeSettings(res.data);
      
      if (setMessage) {
        if (key === 'visibility') {
          setMessage(`✅ Default visibility set to ${value}`);
        } else if (key === 'made_for_kids') {
          setMessage(`✅ Made for kids: ${value ? 'Yes' : 'No'}`);
        } else {
          setMessage(`✅ Settings updated`);
        }
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error updating settings');
      }
      console.error('Error updating YouTube settings:', err);
    }
  }, [API]);

  const updateTiktokSettings = useCallback(async (key, value, setMessage) => {
    try {
      if (key === 'privacy_level' && (!value || value === 'null' || value === '')) {
        return;
      }
      const res = await axios.post(`${API}/tiktok/settings`, { [key]: value });
      setTiktokSettings(res.data);
      
      if (setMessage) {
        if (key === 'privacy_level') {
          setMessage(`✅ Privacy level set to ${value}`);
        } else if (key.startsWith('commercial_content')) {
          setMessage(`✅ Commercial content settings updated`);
        } else {
          setMessage(`✅ TikTok settings updated`);
        }
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error updating TikTok settings');
      }
      console.error('Error updating TikTok settings:', err);
    }
  }, [API]);

  const updateInstagramSettings = useCallback(async (key, value, setMessage) => {
    try {
      const res = await axios.post(`${API}/instagram/settings`, { [key]: value });
      setInstagramSettings(res.data);
      if (setMessage) {
        setMessage(`✅ Instagram settings updated`);
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error updating Instagram settings');
      }
      console.error('Error updating Instagram settings:', err);
    }
  }, [API]);

  const addWordToWordbank = useCallback(async (input, setMessage) => {
    try {
      const words = input.split(',').map(w => w.trim()).filter(w => w);
      
      if (words.length === 0) {
        if (setMessage) {
          setMessage('❌ No valid words to add');
        }
        return;
      }
      
      let addedCount = 0;
      for (const word of words) {
        try {
          const res = await axios.post(`${API}/global/wordbank`, {
            word: word
          });
          setGlobalSettings(prev => ({...prev, wordbank: res.data.wordbank}));
          addedCount++;
        } catch (err) {
          console.error(`Error adding word "${word}":`, err);
        }
      }
      
      if (setMessage) {
        if (addedCount === words.length) {
          setMessage(`✅ Added ${addedCount} word${addedCount !== 1 ? 's' : ''} to wordbank`);
        } else {
          setMessage(`✅ Added ${addedCount} of ${words.length} words (some were duplicates)`);
        }
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error adding word to wordbank');
      }
      console.error('Error adding word to wordbank:', err);
    }
  }, [API]);

  const removeWordFromWordbank = useCallback(async (word, setMessage) => {
    try {
      const res = await axios.delete(`${API}/global/wordbank`, {
        data: { word }
      });
      setGlobalSettings(prev => ({...prev, wordbank: res.data.wordbank}));
      if (setMessage) {
        setMessage(`✅ Removed word from wordbank`);
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error removing word from wordbank');
      }
      console.error('Error removing word from wordbank:', err);
    }
  }, [API]);

  const clearWordbank = useCallback(async (setMessage) => {
    try {
      const res = await axios.delete(`${API}/global/wordbank/clear`);
      setGlobalSettings(prev => ({...prev, wordbank: res.data.wordbank}));
      if (setMessage) {
        setMessage(`✅ Cleared wordbank`);
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error clearing wordbank');
      }
      console.error('Error clearing wordbank:', err);
    }
  }, [API]);

  return {
    // State
    globalSettings,
    youtubeSettings,
    tiktokSettings,
    instagramSettings,
    setGlobalSettings,
    setYoutubeSettings,
    setTiktokSettings,
    setInstagramSettings,
    // Load functions
    loadGlobalSettings,
    loadYoutubeSettings,
    loadTiktokSettings,
    loadInstagramSettings,
    // Update functions
    updateGlobalSettings,
    updateYoutubeSettings,
    updateTiktokSettings,
    updateInstagramSettings,
    // Wordbank functions
    addWordToWordbank,
    removeWordFromWordbank,
    clearWordbank,
  };
}

