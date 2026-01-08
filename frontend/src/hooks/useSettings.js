import { useState, useCallback } from 'react';
import * as settingsService from '../services/settingsService';

/**
 * Hook for managing settings state (global, YouTube, TikTok, Instagram)
 * @param {function} setMessage - Message setter function
 * @returns {object} Settings state and functions
 */
export function useSettings(setMessage) {
  const [globalSettings, setGlobalSettings] = useState({
    title_template: '{filename}',
    description_template: 'Uploaded via hopper',
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

  const loadGlobalSettings = useCallback(async () => {
    try {
      const data = await settingsService.loadGlobalSettings();
      setGlobalSettings({
        title_template: '{filename}',
        description_template: 'Uploaded via hopper',
        wordbank: [],
        upload_immediately: true,
        schedule_mode: 'spaced',
        schedule_interval_value: 1,
        schedule_interval_unit: 'hours',
        schedule_start_time: '',
        upload_first_immediately: true,
        allow_duplicates: false,
        ...data
      });
    } catch (err) {
      console.error('Error loading global settings:', err);
    }
  }, []);

  const loadYoutubeSettings = useCallback(async () => {
    try {
      const data = await settingsService.loadYoutubeSettings();
      setYoutubeSettings(data);
    } catch (err) {
      console.error('Error loading YouTube settings:', err);
    }
  }, []);

  const loadTiktokSettings = useCallback(async () => {
    try {
      const data = await settingsService.loadTiktokSettings();
      setTiktokSettings(data);
    } catch (err) {
      console.error('Error loading TikTok settings:', err);
    }
  }, []);

  const loadInstagramSettings = useCallback(async () => {
    try {
      const data = await settingsService.loadInstagramSettings();
      setInstagramSettings({
        caption_template: '',
        disable_comments: false,
        disable_likes: false,
        media_type: 'REELS',
        share_to_feed: true,
        cover_url: '',
        ...data
      });
    } catch (err) {
      console.error('Error loading Instagram settings:', err);
    }
  }, []);

  const updateGlobalSettings = useCallback(async (key, value) => {
    try {
      const data = await settingsService.updateGlobalSettings(key, value);
      setGlobalSettings(prev => ({ ...prev, ...data }));
    } catch (err) {
      if (setMessage) setMessage('❌ Error updating global settings');
      console.error('Error updating global settings:', err);
    }
  }, [setMessage]);

  const updateYoutubeSettings = useCallback(async (key, value) => {
    try {
      const data = await settingsService.updateYoutubeSettings(key, value);
      setYoutubeSettings(prev => ({ ...prev, ...data }));
    } catch (err) {
      if (setMessage) setMessage('❌ Error updating YouTube settings');
      console.error('Error updating YouTube settings:', err);
    }
  }, [setMessage]);

  const updateTiktokSettings = useCallback(async (key, value) => {
    try {
      const data = await settingsService.updateTiktokSettings(key, value);
      setTiktokSettings(prev => ({ ...prev, ...data }));
    } catch (err) {
      if (setMessage) setMessage('❌ Error updating TikTok settings');
      console.error('Error updating TikTok settings:', err);
    }
  }, [setMessage]);

  const updateInstagramSettings = useCallback(async (key, value) => {
    try {
      const data = await settingsService.updateInstagramSettings(key, value);
      setInstagramSettings(prev => ({ ...prev, ...data }));
    } catch (err) {
      if (setMessage) setMessage('❌ Error updating Instagram settings');
      console.error('Error updating Instagram settings:', err);
    }
  }, [setMessage]);

  const addWordToWordbank = useCallback(async (input) => {
    try {
      const words = input.split(',').map(w => w.trim()).filter(w => w);
      
      if (words.length === 0) {
        if (setMessage) setMessage('❌ No valid words to add');
        return;
      }
      
      let addedCount = 0;
      for (const word of words) {
        try {
          const data = await settingsService.addWordToWordbank(word);
          setGlobalSettings(prev => ({...prev, wordbank: data.wordbank}));
          addedCount++;
        } catch (err) {
          console.error(`Error adding word "${word}":`, err);
        }
      }
      
      if (addedCount === words.length) {
        if (setMessage) setMessage(`✅ Added ${addedCount} word${addedCount !== 1 ? 's' : ''} to wordbank`);
      } else {
        if (setMessage) setMessage(`✅ Added ${addedCount} of ${words.length} words (some were duplicates)`);
      }
      
      await loadGlobalSettings();
    } catch (err) {
      if (setMessage) setMessage('❌ Error adding words');
      console.error('Error adding words:', err);
    }
  }, [setMessage, loadGlobalSettings]);

  const removeWordFromWordbank = useCallback(async (word) => {
    try {
      await settingsService.removeWordFromWordbank(word);
      setGlobalSettings(prev => ({
        ...prev,
        wordbank: prev.wordbank.filter(w => w !== word)
      }));
      if (setMessage) setMessage(`✅ Removed "${word}" from wordbank`);
    } catch (err) {
      if (setMessage) setMessage('❌ Error removing word');
      console.error('Error removing word:', err);
    }
  }, [setMessage]);

  const clearWordbank = useCallback(async () => {
    try {
      await settingsService.clearWordbank();
      setGlobalSettings(prev => ({ ...prev, wordbank: [] }));
      if (setMessage) setMessage('✅ Cleared wordbank');
    } catch (err) {
      if (setMessage) setMessage('❌ Error clearing wordbank');
      console.error('Error clearing wordbank:', err);
    }
  }, [setMessage]);

  return {
    globalSettings,
    youtubeSettings,
    tiktokSettings,
    instagramSettings,
    setGlobalSettings,
    setYoutubeSettings,
    setTiktokSettings,
    setInstagramSettings,
    loadGlobalSettings,
    loadYoutubeSettings,
    loadTiktokSettings,
    loadInstagramSettings,
    updateGlobalSettings,
    updateYoutubeSettings,
    updateTiktokSettings,
    updateInstagramSettings,
    addWordToWordbank,
    removeWordFromWordbank,
    clearWordbank,
  };
}
