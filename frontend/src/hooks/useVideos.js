import { useState, useCallback, useMemo } from 'react';
import axios from '../services/api';
import { getApiUrl } from '../services/api';
import Cookies from 'js-cookie';

/**
 * Hook for managing video state and operations
 */
export function useVideos(user, loadSubscription) {
  const [videos, setVideos] = useState([]);
  const [expandedVideos, setExpandedVideos] = useState(new Set());
  const [editingVideo, setEditingVideo] = useState(null);
  const [draggedVideo, setDraggedVideo] = useState(null);
  const [editTitleLength, setEditTitleLength] = useState(0);
  const [editCommercialContentDisclosure, setEditCommercialContentDisclosure] = useState(false);
  const [editCommercialContentYourBrand, setEditCommercialContentYourBrand] = useState(false);
  const [editCommercialContentBranded, setEditCommercialContentBranded] = useState(false);
  const [editTiktokPrivacy, setEditTiktokPrivacy] = useState('');
  const [youtubeVideos, setYoutubeVideos] = useState([]);
  const [youtubeVideosPage, setYoutubeVideosPage] = useState(1);
  const [youtubeVideosTotalPages, setYoutubeVideosTotalPages] = useState(0);
  const [loadingYoutubeVideos, setLoadingYoutubeVideos] = useState(false);
  const [overrideInputValues, setOverrideInputValues] = useState({});
  const [expandedDestinationErrors, setExpandedDestinationErrors] = useState(new Set());

  const API = getApiUrl();
  const csrfToken = Cookies.get('csrf_token_client');

  const loadVideos = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/videos`);
      const newData = res.data;
      
      const seenIds = new Set();
      const uniqueData = newData.filter(video => {
        if (seenIds.has(video.id)) {
          console.warn(`⚠️ Duplicate video ID from API: ${video.id}, skipping`);
          return false;
        }
        seenIds.add(video.id);
        return true;
      });
      
      setVideos(prevVideos => {
        const tempVideos = prevVideos.filter(v => typeof v.id === 'string' && v.id.startsWith('temp-'));
        const tempVideoIds = new Set(tempVideos.map(v => v.id));
        
        const prevRealVideos = prevVideos.filter(v => !tempVideoIds.has(v.id));
        if (JSON.stringify(prevRealVideos) === JSON.stringify(uniqueData)) {
          return prevVideos;
        }
        
        return [...uniqueData, ...tempVideos];
      });
      
      if (user && loadSubscription) {
        loadSubscription();
      }
    } catch (err) {
      console.error('Error loading videos:', err);
    }
  }, [API, user, loadSubscription]);

  const isUploading = useMemo(() => {
    return videos.some(v => 
      v.status === 'uploading' && 
      !(typeof v.id === 'string' && v.id.startsWith('temp-'))
    );
  }, [videos]);

  const addVideo = useCallback(async (file, maxFileSize, setMessage, setNotification) => {
    const maxSizeBytes = maxFileSize?.max_file_size_bytes || 10 * 1024 * 1024 * 1024;
    if (file.size > maxSizeBytes) {
      const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
      const fileSizeGB = (file.size / (1024 * 1024 * 1024)).toFixed(2);
      const maxSizeDisplay = maxFileSize?.max_file_size_display || '10 GB';
      const errorMsg = `File too large: ${file.name} is ${fileSizeMB} MB (${fileSizeGB} GB). Maximum file size is ${maxSizeDisplay}.`;
      
      if (setNotification) {
        setNotification({
          type: 'error',
          title: 'File Too Large',
          message: errorMsg,
          videoFilename: file.name
        });
        setTimeout(() => setNotification(null), 10000);
      }
      if (setMessage) {
        setMessage(`❌ ${errorMsg}`);
      }
      return;
    }
    
    const form = new FormData();
    form.append('file', file);
    
    if (csrfToken) {
      form.append('csrf_token', csrfToken);
    }
    
    const tempId = `temp-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const tempVideo = {
      id: tempId,
      filename: file.name,
      status: 'uploading',
      progress: 0,
      file_size_bytes: file.size,
      tokens_consumed: 0
    };
    setVideos(prev => [...prev, tempVideo]);
    
    const timeoutMs = Math.max(5 * 60 * 1000, Math.min(2 * 60 * 60 * 1000, (file.size / (100 * 1024 * 1024)) * 60 * 1000));
    
    try {
      const res = await axios.post(`${API}/videos`, form, {
        timeout: timeoutMs,
        maxContentLength: Infinity,
        maxBodyLength: Infinity,
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setVideos(prev => prev.map(v =>
              v.id === tempId ? { ...v, progress: percent } : v
            ));
          }
        }
      });
      
      setVideos(prev => {
        const withoutTemp = prev.filter(v => v.id !== tempId);
        const exists = withoutTemp.some(v => v.id === res.data.id);
        if (exists) {
          return withoutTemp.map(v => v.id === res.data.id ? res.data : v);
        }
        return [...withoutTemp, res.data];
      });
      
      const tokensRequired = res.data.tokens_required || 0;
      if (setMessage) {
        setMessage(`✅ Added ${file.name} to queue (will cost ${tokensRequired} ${tokensRequired === 1 ? 'token' : 'tokens'} on upload)`);
      }
    } catch (err) {
      setVideos(prev => prev.filter(v => v.id !== tempId));
      
      const isTimeout = err.code === 'ECONNABORTED' || err.message?.includes('timeout');
      const isNetworkError = !err.response && (err.code === 'ERR_NETWORK' || err.code === 'ECONNRESET');
      const isFileSizeError = err.response?.status === 413 || 
                              (!err.response && file.size > maxSizeBytes) ||
                              (err.message && (err.message.includes('413') || err.message.includes('Payload Too Large')));
      
      let errorMsg = err.response?.data?.detail || err.message || 'Error adding video';
      
      if (isTimeout) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        const timeoutMinutes = (timeoutMs / (60 * 1000)).toFixed(1);
        const isLikelyProxyTimeout = timeoutMs >= 100000 && fileSizeMB < 500;
        
        if (isLikelyProxyTimeout) {
          errorMsg = `Upload timeout: The file "${file.name}" (${fileSizeMB} MB) timed out after ${timeoutMinutes} minutes. This is likely due to a proxy timeout (e.g., Cloudflare has a 100-second limit on free plans). Please try again or contact support.`;
        } else {
          errorMsg = `Upload timeout: The file "${file.name}" (${fileSizeMB} MB) timed out after ${timeoutMinutes} minutes. The connection may be too slow or there may be a proxy timeout. Please try a smaller file or check your internet connection.`;
        }
        
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Upload Timeout',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 20000);
        }
      } else if (isNetworkError) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        errorMsg = `Network error: The upload of "${file.name}" (${fileSizeMB} MB) was interrupted. This may be due to file size limits, network issues, or server timeout. Please try a smaller file.`;
        
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Upload Failed',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 15000);
        }
      } else if (isFileSizeError) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        const fileSizeGB = (file.size / (1024 * 1024 * 1024)).toFixed(2);
        const maxSizeDisplay = maxFileSize?.max_file_size_display || '10 GB';
        errorMsg = err.response?.data?.detail || `File too large: ${file.name} is ${fileSizeMB} MB (${fileSizeGB} GB). Maximum file size is ${maxSizeDisplay}.`;
        
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'File Too Large',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 10000);
        }
      } else if (err.response?.status === 400 && (errorMsg.includes('Insufficient tokens') || errorMsg.includes('Insufficient'))) {
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Insufficient Tokens',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 15000);
        }
      } else if (err.response?.status === 401) {
        errorMsg = 'Session expired. Please refresh the page.';
      } else if (!err.response && !isTimeout && !isNetworkError) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        errorMsg = `Upload failed: "${file.name}" (${fileSizeMB} MB). Please check your connection and try again.`;
        
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Upload Failed',
            message: errorMsg,
            videoFilename: file.name
          });
          setTimeout(() => setNotification(null), 10000);
        }
      }
      
      if (setMessage && !isTimeout && !isNetworkError && !isFileSizeError && err.response?.status !== 401) {
        setMessage(`❌ ${errorMsg}`);
      }
      
      console.error('Error adding video:', {
        error: err,
        code: err.code,
        message: err.message,
        response: err.response?.status,
        fileSize: file.size,
        fileName: file.name
      });
    }
  }, [API, csrfToken]);

  const uploadFilesSequentially = useCallback(async (files, maxFileSize, setMessage, setNotification) => {
    for (const file of files) {
      try {
        await addVideo(file, maxFileSize, setMessage, setNotification);
      } catch (err) {
        console.error(`Failed to upload ${file.name}:`, err);
      }
    }
  }, [addVideo]);

  const removeVideo = useCallback(async (id, setMessage) => {
    try {
      await axios.delete(`${API}/videos/${id}`);
      setVideos(prev => prev.filter(v => v.id !== id));
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error deleting video');
      }
      console.error('Error deleting video:', err);
    }
  }, [API]);

  const clearAllVideos = useCallback(async (setMessage, setConfirmDialog) => {
    const nonUploadingVideos = videos.filter(v => v.status !== 'uploading');
    
    if (nonUploadingVideos.length === 0) {
      if (setMessage) {
        setMessage('No videos to clear (all videos are currently uploading)');
      }
      return;
    }
    
    if (setConfirmDialog) {
      setConfirmDialog({
        title: 'Clear All Videos',
        message: `Are you sure you want to clear all ${nonUploadingVideos.length} video(s) from the queue? This action cannot be undone.`,
        onConfirm: async () => {
          if (setConfirmDialog) setConfirmDialog(null);
          try {
            const res = await axios.delete(`${API}/videos`);
            setVideos(prev => prev.filter(v => v.status === 'uploading'));
            if (setMessage) {
              setMessage(`✅ Cleared ${res.data.deleted} video(s) from queue`);
            }
          } catch (err) {
            const errorMsg = err.response?.data?.detail || err.message || 'Error clearing videos';
            if (setMessage) {
              setMessage(`❌ ${errorMsg}`);
            }
            console.error('Error clearing videos:', err);
          }
        },
        onCancel: () => {
          if (setConfirmDialog) setConfirmDialog(null);
        }
      });
    }
  }, [API, videos]);

  const clearUploadedVideos = useCallback(async (setMessage, setConfirmDialog) => {
    const uploadedVideos = videos.filter(v => v.status === 'uploaded' || v.status === 'completed');
    
    if (uploadedVideos.length === 0) {
      if (setMessage) {
        setMessage('No uploaded videos to clear');
      }
      return;
    }
    
    if (setConfirmDialog) {
      setConfirmDialog({
        title: 'Clear Uploaded Videos',
        message: `Are you sure you want to clear ${uploadedVideos.length} uploaded video(s) from the queue? This action cannot be undone.`,
        onConfirm: async () => {
          if (setConfirmDialog) setConfirmDialog(null);
          try {
            const res = await axios.delete(`${API}/videos/uploaded`);
            setVideos(prev => prev.filter(v => v.status !== 'uploaded' && v.status !== 'completed'));
            if (setMessage) {
              setMessage(`✅ Cleared ${res.data.deleted} uploaded video(s) from queue`);
            }
          } catch (err) {
            const errorMsg = err.response?.data?.detail || err.message || 'Error clearing uploaded videos';
            if (setMessage) {
              setMessage(`❌ ${errorMsg}`);
            }
            console.error('Error clearing uploaded videos:', err);
          }
        },
        onCancel: () => {
          if (setConfirmDialog) setConfirmDialog(null);
        }
      });
    }
  }, [API, videos]);

  const cancelScheduled = useCallback(async (setMessage) => {
    try {
      const res = await axios.post(`${API}/videos/cancel-scheduled`);
      await loadVideos();
      if (setMessage) {
        setMessage(`✅ Cancelled ${res.data.cancelled} scheduled videos`);
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error cancelling scheduled videos');
      }
      console.error('Error cancelling scheduled videos:', err);
    }
  }, [API, loadVideos]);

  const cancelAllUploads = useCallback(async (setMessage) => {
    const uploadingVideos = videos.filter(v => 
      v.status === 'uploading' && 
      !(typeof v.id === 'string' && v.id.startsWith('temp-'))
    );
    if (uploadingVideos.length === 0) {
      return;
    }
    
    if (setMessage) {
      setMessage('⏳ Cancelling uploads...');
    }
    
    setVideos(prev => prev.map(video => 
      uploadingVideos.some(uv => uv.id === video.id) 
        ? { ...video, status: 'cancelled' } 
        : video
    ));
    
    try {
      const cancelPromises = uploadingVideos.map(v => 
        axios.post(`${API}/videos/${v.id}/cancel`, {}, {
          headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
        })
      );
      
      await Promise.all(cancelPromises);
      
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
      
      if (setMessage) {
        setMessage(`✅ Cancelled ${uploadingVideos.length} upload(s)`);
      }
    } catch (err) {
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
      
      const errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Failed to cancel uploads';
      if (setMessage) {
        setMessage(`❌ ${errorMsg}`);
      }
    }
  }, [API, videos, csrfToken]);

  const upload = useCallback(async (youtube, tiktok, instagram, tiktokSettings, globalSettings, tokenBalance, subscription, setMessage, setNotification) => {
    if (tiktok.enabled && tiktokSettings.commercial_content_disclosure) {
      const hasYourBrand = tiktokSettings.commercial_content_your_brand ?? false;
      const hasBranded = tiktokSettings.commercial_content_branded ?? false;
      
      if (!hasYourBrand && !hasBranded) {
        if (setMessage) {
          setMessage('❌ You need to indicate if your content promotes yourself, a third party, or both.');
        }
        return;
      }
    }
    
    if (!youtube.enabled && !tiktok.enabled && !instagram.enabled) {
      if (setMessage) {
        setMessage('❌ Enable at least one destination first');
      }
      return;
    }
    
    if (tokenBalance && !tokenBalance.unlimited && subscription && subscription.plan_type && subscription.plan_type === 'free') {
      const pendingVideos = videos.filter(v => 
        v.status === 'pending' || v.status === 'failed' || v.status === 'uploading'
      );
      
      const totalTokensRequired = pendingVideos
        .filter(v => v.tokens_consumed === 0)
        .reduce((sum, video) => {
          return sum + (video.tokens_required || 0);
        }, 0);
      
      if (totalTokensRequired > 0 && tokenBalance.tokens_remaining < totalTokensRequired) {
        const shortfall = totalTokensRequired - tokenBalance.tokens_remaining;
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Insufficient Tokens',
            message: `You need ${totalTokensRequired} tokens to upload ${pendingVideos.length} video${pendingVideos.length === 1 ? '' : 's'}, but you only have ${tokenBalance.tokens_remaining} tokens remaining. You need ${shortfall} more token${shortfall === 1 ? '' : 's'}. Please upgrade your plan or wait for your token balance to reset.`,
          });
          setTimeout(() => setNotification(null), 10000);
        }
        return;
      }
    }
    
    const isScheduling = !globalSettings.upload_immediately;
    if (setMessage) {
      if (isScheduling) {
        setMessage('⏳ Scheduling videos...');
      }
    }
    
    try {
      const res = await axios.post(`${API}/upload`);
      
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
      
      const hasSuccessfulTiktokUploads = videosRes.data.some(video => {
        const tiktokId = video.custom_settings?.tiktok_id;
        const tiktokPublishId = video.custom_settings?.tiktok_publish_id;
        const hasTiktokUpload = tiktokId || tiktokPublishId;
        const isUploaded = video.status === 'uploaded' || video.platform_statuses?.tiktok === 'uploaded';
        return hasTiktokUpload && isUploaded;
      });
      
      if (res.data.scheduled !== undefined && setMessage) {
        setMessage(`✅ ${res.data.scheduled} videos scheduled! ${res.data.message}`);
      }
      
      if (res.data.videos_uploaded !== undefined && res.data.videos_uploaded > 0) {
        if (tiktok.enabled && hasSuccessfulTiktokUploads && setNotification) {
          setNotification({
            type: 'info',
            title: 'Content Processing',
            message: 'Your content has been published successfully. It may take a few minutes for the content to process and be visible on your TikTok profile.',
          });
          setTimeout(() => setNotification(null), 15000);
        }
      } else if (res.data.videos_failed === 0 && res.data.scheduled === undefined && tiktok.enabled && hasSuccessfulTiktokUploads && setNotification) {
        setNotification({
          type: 'info',
          title: 'Content Processing',
          message: 'Your content has been published successfully. It may take a few minutes for the content to process and be visible on your TikTok profile.',
        });
        setTimeout(() => setNotification(null), 15000);
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Unknown error';
      console.error('Upload error:', err);
      
      if (errorMsg.toLowerCase().includes('insufficient') || errorMsg.toLowerCase().includes('token')) {
        if (setNotification) {
          setNotification({
            type: 'error',
            title: 'Insufficient Tokens',
            message: errorMsg,
          });
          setTimeout(() => setNotification(null), 10000);
        }
      } else if (setMessage) {
        setMessage(`❌ Upload failed: ${errorMsg}`);
      }
      
      const videosRes = await axios.get(`${API}/videos`);
      setVideos(videosRes.data);
    }
  }, [API, videos]);

  const updateVideoSettings = useCallback(async (videoId, settings, setMessage) => {
    try {
      const filteredSettings = {};
      Object.entries(settings).forEach(([key, value]) => {
        if (value !== null && value !== undefined) {
          filteredSettings[key] = value;
        }
      });
      
      await axios.patch(`${API}/videos/${videoId}`, filteredSettings);
      await loadVideos();
      
      if (setMessage) {
        setMessage('✅ Video settings updated');
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error updating video');
      }
      console.error('Error updating video:', err);
    }
  }, [API, loadVideos]);

  const recomputeVideoTitle = useCallback(async (videoId, setMessage) => {
    try {
      await axios.post(`${API}/videos/${videoId}/recompute-title`);
      await loadVideos();
      
      if (setMessage) {
        setMessage('✅ Title recomputed from template');
      }
    } catch (err) {
      if (setMessage) {
        setMessage('❌ Error recomputing title');
      }
      console.error('Error recomputing title:', err);
    }
  }, [API, loadVideos]);

  const recomputeVideoField = useCallback(async (videoId, platform, field, setMessage, setOverrideInputValues) => {
    try {
      await axios.post(`${API}/videos/${videoId}/recompute-title?platform=${platform}`);
      await loadVideos();
      
      const videosRes = await axios.get(`${API}/videos`);
      const updatedVideo = videosRes.data.find(v => v.id === videoId);
      
      if (updatedVideo && setOverrideInputValues) {
        const modalKey = `${videoId}-${platform}`;
        const newValue = field === 'title' 
          ? (platform === 'youtube' ? updatedVideo.youtube_title : updatedVideo.tiktok_title)
          : field === 'description'
          ? updatedVideo.youtube_description
          : field === 'tags'
          ? updatedVideo.youtube_tags
          : field === 'caption'
          ? updatedVideo.instagram_caption
          : null;
        
        if (newValue !== null) {
          setOverrideInputValues(prev => ({
            ...prev,
            [modalKey]: {
              ...(prev[modalKey] || {}),
              [platform === 'youtube' && field === 'title' ? 'youtube_title' : 
               field === 'title' || field === 'caption' ? 'title' : 
               field]: newValue
            }
          }));
        }
      }
      
      if (setMessage) {
        setMessage(`✅ ${field === 'title' ? 'Title' : field === 'description' ? 'Description' : field === 'tags' ? 'Tags' : 'Caption'} recomputed from template`);
      }
    } catch (err) {
      if (setMessage) {
        setMessage(`❌ Error recomputing ${field}`);
      }
      console.error(`Error recomputing ${field}:`, err);
    }
  }, [API, loadVideos]);

  const saveDestinationOverrides = useCallback(async (videoId, platform, overrides, setMessage) => {
    try {
      const filteredOverrides = {};
      Object.entries(overrides).forEach(([key, value]) => {
        if (value !== null && value !== undefined) {
          filteredOverrides[key] = value;
        }
      });
      
      await axios.patch(`${API}/videos/${videoId}`, filteredOverrides);
      await loadVideos();
      
      if (setMessage) {
        setMessage(`✅ ${platform === 'youtube' ? 'YouTube' : platform === 'tiktok' ? 'TikTok' : 'Instagram'} overrides saved`);
      }
      return true;
    } catch (err) {
      if (setMessage) {
        setMessage(`❌ Failed to save overrides: ${err.response?.data?.detail || err.message}`);
      }
      console.error('Error saving destination overrides:', err);
      return false;
    }
  }, [API, loadVideos]);

  const handleDragStart = useCallback((e, video) => {
    if (video.status === 'uploading') {
      e.preventDefault();
      return;
    }
    setDraggedVideo(video);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(video.id));
  }, []);

  const handleDragEnd = useCallback((e) => {
    setDraggedVideo(null);
    e.currentTarget.style.opacity = '1';
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const handleDrop = useCallback(async (e, targetVideo, setMessage) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (!draggedVideo || draggedVideo.id === targetVideo.id) {
      setDraggedVideo(null);
      return;
    }

    const originalVideos = [...videos];
    const newVideos = [...videos];
    const draggedIdx = newVideos.findIndex(v => v.id === draggedVideo.id);
    const targetIdx = newVideos.findIndex(v => v.id === targetVideo.id);
    
    if (draggedIdx === -1 || targetIdx === -1) {
      setDraggedVideo(null);
      return;
    }
    
    const [draggedItem] = newVideos.splice(draggedIdx, 1);
    const insertIdx = draggedIdx < targetIdx ? targetIdx - 1 : targetIdx;
    newVideos.splice(insertIdx, 0, draggedItem);
    
    setDraggedVideo(null);
    setVideos(newVideos);
    
    try {
      const videoIds = newVideos.map(v => v.id);
      await axios.post(`${API}/videos/reorder`, { video_ids: videoIds });
    } catch (err) {
      console.error('Error reordering videos:', err);
      if (setMessage) {
        setMessage('❌ Error reordering videos');
      }
      setVideos(originalVideos);
    }
  }, [API, videos, draggedVideo]);

  const loadYoutubeVideos = useCallback(async (youtube, page = 1, hideShorts = false, setMessage) => {
    if (!youtube.connected) return;
    
    setLoadingYoutubeVideos(true);
    try {
      const res = await axios.get(`${API}/youtube/videos?page=${page}&per_page=50&hide_shorts=${hideShorts}`);
      setYoutubeVideos(res.data.videos);
      setYoutubeVideosPage(res.data.page);
      setYoutubeVideosTotalPages(res.data.total_pages);
    } catch (err) {
      console.error('Error loading YouTube videos:', err);
      if (setMessage) {
        setMessage('❌ Error loading YouTube videos');
      }
    } finally {
      setLoadingYoutubeVideos(false);
    }
  }, [API]);

  const closeEditModal = useCallback(() => {
    setEditingVideo(null);
    setEditTitleLength(0);
    setEditCommercialContentDisclosure(false);
    setEditCommercialContentYourBrand(false);
    setEditCommercialContentBranded(false);
    setEditTiktokPrivacy('');
  }, []);

  return {
    // State
    videos,
    expandedVideos,
    editingVideo,
    draggedVideo,
    editTitleLength,
    editCommercialContentDisclosure,
    editCommercialContentYourBrand,
    editCommercialContentBranded,
    editTiktokPrivacy,
    youtubeVideos,
    youtubeVideosPage,
    youtubeVideosTotalPages,
    loadingYoutubeVideos,
    overrideInputValues,
    expandedDestinationErrors,
    isUploading,
    // Setters
    setVideos,
    setExpandedVideos,
    setEditingVideo,
    setDraggedVideo,
    setEditTitleLength,
    setEditCommercialContentDisclosure,
    setEditCommercialContentYourBrand,
    setEditCommercialContentBranded,
    setEditTiktokPrivacy,
    setOverrideInputValues,
    setExpandedDestinationErrors,
    // Functions
    loadVideos,
    addVideo,
    uploadFilesSequentially,
    removeVideo,
    clearAllVideos,
    clearUploadedVideos,
    cancelScheduled,
    cancelAllUploads,
    upload,
    updateVideoSettings,
    recomputeVideoTitle,
    recomputeVideoField,
    saveDestinationOverrides,
    handleDragStart,
    handleDragEnd,
    handleDragOver,
    handleDrop,
    loadYoutubeVideos,
    closeEditModal,
  };
}

