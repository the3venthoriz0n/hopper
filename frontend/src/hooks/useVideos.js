import { useState, useCallback, useMemo } from 'react';
import * as videoService from '../services/videoService';

/**
 * Hook for managing video state and operations
 * @param {object} user - Current user object
 * @param {function} setMessage - Message setter function
 * @param {function} setNotification - Notification setter function
 * @param {function} setConfirmDialog - Confirm dialog setter function
 * @param {function} loadSubscription - Function to reload subscription
 * @param {object} maxFileSize - Max file size config
 * @param {object} youtube - YouTube platform state
 * @param {object} tiktok - TikTok platform state
 * @param {object} instagram - Instagram platform state
 * @param {object} tiktokSettings - TikTok settings
 * @param {object} globalSettings - Global settings
 * @param {object} tokenBalance - Token balance
 * @param {object} subscription - Subscription
 * @returns {object} Video state and functions
 */
export function useVideos(
  user,
  setMessage,
  setNotification,
  setConfirmDialog,
  loadSubscription,
  maxFileSize,
  youtube,
  tiktok,
  instagram,
  tiktokSettings,
  globalSettings,
  tokenBalance,
  subscription
) {
  const [videos, setVideos] = useState([]);
  const [editingVideo, setEditingVideo] = useState(null);
  const [draggedVideo, setDraggedVideo] = useState(null);
  const [overrideInputValues, setOverrideInputValues] = useState({});
  const [expandedDestinationErrors, setExpandedDestinationErrors] = useState(new Set());

  const loadVideos = useCallback(async () => {
    try {
      const newData = await videoService.loadVideos();
      
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
        
        if (prevVideos && prevVideos.length > 0) {
          uniqueData.forEach(newVideo => {
            const prevVideo = prevVideos.find(v => v.id === newVideo.id);
            if (prevVideo && prevVideo.status !== 'failed' && newVideo.status === 'failed') {
              if (newVideo.error && newVideo.error.toLowerCase().includes('insufficient tokens')) {
                setNotification({
                  type: 'error',
                  title: 'Insufficient Tokens',
                  message: newVideo.error || `Not enough tokens to upload "${newVideo.filename}". Please upgrade your plan or wait for your token balance to reset.`,
                  videoFilename: newVideo.filename
                });
                setTimeout(() => setNotification(null), 10000);
              }
            }
          });
        }
        
        const prevRealVideos = prevVideos.filter(v => !tempVideoIds.has(v.id));
        if (JSON.stringify(prevRealVideos) === JSON.stringify(uniqueData)) {
          return prevVideos;
        }
        
        return [...uniqueData, ...tempVideos];
      });
      
      if (user) {
        loadSubscription();
      }
    } catch (err) {
      console.error('Error loading videos:', err);
    }
  }, [user, loadSubscription, setNotification]);

  const isUploading = useMemo(() => {
    return videos.some(v => 
      v.status === 'uploading' && 
      !(typeof v.id === 'string' && v.id.startsWith('temp-'))
    );
  }, [videos]);

  const derivedMessage = useMemo(() => {
    const uploadingCount = videos.filter(v => 
      v.status === 'uploading' && 
      !(typeof v.id === 'string' && v.id.startsWith('temp-'))
    ).length;
    
    const uploadedCount = videos.filter(v => 
      v.status === 'uploaded' || v.status === 'completed'
    ).length;
    
    const failedCount = videos.filter(v => v.status === 'failed').length;
    
    if (uploadingCount > 0) {
      return `⏳ Uploading ${uploadingCount} video(s)...`;
    }
    
    return '';
  }, [videos]);

  const calculateQueueTokenCost = useCallback(() => {
    return videos
      .filter(v => (v.status === 'pending' || v.status === 'scheduled') && v.tokens_consumed === 0)
      .reduce((total, video) => {
        return total + (video.tokens_required || 0);
      }, 0);
  }, [videos]);

  const formatFileSize = useCallback((bytes) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(2)} ${units[unitIndex]}`;
  }, []);

  const addVideo = useCallback(async (file) => {
    // Temporary: 100MB limit due to Cloudflare restrictions
    const maxSizeBytes = 100 * 1024 * 1024; // 100MB
    const maxSizeDisplay = '100 MB';
    
    if (file.size > maxSizeBytes) {
      const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
      const errorMsg = `File too large: ${file.name} is ${fileSizeMB} MB. Maximum file size is ${maxSizeDisplay}.`;
      
      setNotification({
        type: 'error',
        title: 'File Too Large',
        message: errorMsg,
        videoFilename: file.name
      });
      setTimeout(() => setNotification(null), 10000);
      if (setMessage) setMessage(`❌ ${errorMsg}`);
      return;
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
      const videoData = await videoService.uploadVideo(
        file,
        (progressEvent) => {
          if (progressEvent.total) {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setVideos(prev => prev.map(v =>
              v.id === tempId ? { ...v, progress: percent } : v
            ));
          }
        },
        timeoutMs
      );
      
      setVideos(prev => {
        const withoutTemp = prev.filter(v => v.id !== tempId);
        const exists = withoutTemp.some(v => v.id === videoData.id);
        if (exists) {
          return withoutTemp.map(v => v.id === videoData.id ? videoData : v);
        }
        return [...withoutTemp, videoData];
      });
      
      const tokensRequired = videoData.tokens_required || 0;
      if (setMessage) setMessage(`✅ Added ${file.name} to queue (will cost ${tokensRequired} ${tokensRequired === 1 ? 'token' : 'tokens'} on upload)`);
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
        
        setNotification({
          type: 'error',
          title: 'Upload Timeout',
          message: errorMsg,
          videoFilename: file.name
        });
        setTimeout(() => setNotification(null), 20000);
      } else if (isNetworkError) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        errorMsg = `Network error: The upload of "${file.name}" (${fileSizeMB} MB) was interrupted. This may be due to file size limits, network issues, or server timeout. Please try a smaller file.`;
        
        setNotification({
          type: 'error',
          title: 'Upload Failed',
          message: errorMsg,
          videoFilename: file.name
        });
        setTimeout(() => setNotification(null), 15000);
      } else if (isFileSizeError) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        const maxSizeDisplay = '100 MB';
        errorMsg = err.response?.data?.detail || `File too large: ${file.name} is ${fileSizeMB} MB. Maximum file size is ${maxSizeDisplay}.`;
        
        setNotification({
          type: 'error',
          title: 'File Too Large',
          message: errorMsg,
          videoFilename: file.name
        });
        setTimeout(() => setNotification(null), 10000);
      } else if (err.response?.status === 400 && (errorMsg.includes('Insufficient tokens') || errorMsg.includes('Insufficient'))) {
        setNotification({
          type: 'error',
          title: 'Insufficient Tokens',
          message: errorMsg,
          videoFilename: file.name
        });
        setTimeout(() => setNotification(null), 15000);
      } else if (!isTimeout && !isNetworkError && !isFileSizeError && err.response?.status !== 401) {
        const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
        errorMsg = `Upload failed: "${file.name}" (${fileSizeMB} MB). Please check your connection and try again.`;
        
        setNotification({
          type: 'error',
          title: 'Upload Failed',
          message: errorMsg,
          videoFilename: file.name
        });
        setTimeout(() => setNotification(null), 10000);
      }
      
      if (!isTimeout && !isNetworkError && !isFileSizeError && err.response?.status !== 401) {
        if (setMessage) setMessage(`❌ ${errorMsg}`);
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
  }, [maxFileSize, setMessage, setNotification]);

  const uploadFilesSequentially = useCallback(async (files) => {
    for (const file of files) {
      try {
        await addVideo(file);
      } catch (err) {
        console.error(`Failed to upload ${file.name}:`, err);
      }
    }
  }, [addVideo]);

  const handleFileDrop = useCallback((e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(f => 
      f.type.startsWith('video/')
    );
    if (files.length > 0) {
      uploadFilesSequentially(files);
    }
  }, [uploadFilesSequentially]);

  const removeVideo = useCallback(async (id) => {
    try {
      await videoService.deleteVideo(id);
      setVideos(prev => prev.filter(v => v.id !== id));
    } catch (err) {
      if (setMessage) setMessage(`❌ Error removing video: ${err.response?.data?.detail || err.message}`);
      console.error('Error removing video:', err);
    }
  }, [setMessage]);

  const clearAllVideos = useCallback(async () => {
    const nonUploadingVideos = videos.filter(v => v.status !== 'uploading');
    
    if (nonUploadingVideos.length === 0) {
      if (setMessage) setMessage('No videos to clear (all videos are currently uploading)');
      return;
    }
    
    setConfirmDialog({
      title: 'Clear All Videos',
      message: `Are you sure you want to clear all ${nonUploadingVideos.length} video(s) from the queue? This action cannot be undone.`,
      onConfirm: async () => {
        setConfirmDialog(null);
        try {
          const res = await videoService.deleteAllVideos();
          setVideos(prev => prev.filter(v => v.status === 'uploading'));
          if (setMessage) setMessage(`✅ Cleared ${res.deleted} video(s) from queue`);
        } catch (err) {
          const errorMsg = err.response?.data?.detail || err.message || 'Error clearing videos';
          if (setMessage) setMessage(`❌ ${errorMsg}`);
          console.error('Error clearing videos:', err);
        }
      },
      onCancel: () => {
        setConfirmDialog(null);
      }
    });
  }, [videos, setMessage, setConfirmDialog]);

  const clearUploadedVideos = useCallback(async () => {
    const uploadedVideos = videos.filter(v => v.status === 'uploaded' || v.status === 'completed');
    
    if (uploadedVideos.length === 0) {
      if (setMessage) setMessage('No uploaded videos to clear');
      return;
    }
    
    setConfirmDialog({
      title: 'Clear Uploaded Videos',
      message: `Are you sure you want to clear ${uploadedVideos.length} uploaded video(s) from the queue? This action cannot be undone.`,
      onConfirm: async () => {
        setConfirmDialog(null);
        try {
          const res = await videoService.deleteUploadedVideos();
          setVideos(prev => prev.filter(v => v.status !== 'uploaded' && v.status !== 'completed'));
          if (setMessage) setMessage(`✅ Cleared ${res.deleted} uploaded video(s) from queue`);
        } catch (err) {
          const errorMsg = err.response?.data?.detail || err.message || 'Error clearing uploaded videos';
          if (setMessage) setMessage(`❌ ${errorMsg}`);
          console.error('Error clearing uploaded videos:', err);
        }
      },
      onCancel: () => {
        setConfirmDialog(null);
      }
    });
  }, [videos, setMessage, setConfirmDialog]);

  const cancelScheduled = useCallback(async () => {
    try {
      const res = await videoService.cancelScheduled();
      if (setMessage) setMessage(`✅ Cancelled ${res.cancelled} scheduled videos`);
      await loadVideos();
    } catch (err) {
      if (setMessage) setMessage('❌ Error cancelling scheduled videos');
      console.error('Error cancelling scheduled videos:', err);
    }
  }, [setMessage, loadVideos]);

  const updateVideoSettings = useCallback(async (videoId, settings) => {
    try {
      await videoService.updateVideoSettings(videoId, settings);
      await loadVideos();
      if (setMessage) setMessage('✅ Video settings updated');
      setEditingVideo(null);
    } catch (err) {
      if (setMessage) setMessage('❌ Error updating video');
      console.error('Error updating video:', err);
    }
  }, [setMessage, loadVideos]);

  const saveDestinationOverrides = useCallback(async (videoId, platform, overrides) => {
    try {
      await videoService.updateVideoSettings(videoId, overrides);
      await loadVideos();
      const platformName = platform === 'youtube' ? 'YouTube' : platform === 'tiktok' ? 'TikTok' : 'Instagram';
      if (setMessage) setMessage(`✅ ${platformName} overrides saved`);
      return true;
    } catch (err) {
      if (setMessage) setMessage(`❌ Failed to save overrides: ${err.response?.data?.detail || err.message}`);
      console.error('Error saving destination overrides:', err);
      return false;
    }
  }, [setMessage, loadVideos]);

  const recomputeVideoTitle = useCallback(async (videoId) => {
    try {
      await videoService.recomputeVideoTitle(videoId);
      await loadVideos();
      if (setMessage) setMessage('✅ Title recomputed from template');
    } catch (err) {
      if (setMessage) setMessage('❌ Error recomputing title');
      console.error('Error recomputing title:', err);
    }
  }, [setMessage, loadVideos]);

  const recomputeVideoField = useCallback(async (videoId, platform, field) => {
    try {
      await videoService.recomputeVideoField(videoId, platform);
      await loadVideos();
      if (setMessage) setMessage(`✅ ${field === 'title' ? 'Title' : field === 'description' ? 'Description' : field === 'tags' ? 'Tags' : 'Caption'} recomputed from template`);
    } catch (err) {
      console.error(`Error recomputing ${field}:`, err);
      if (setMessage) setMessage(`❌ Error recomputing ${field}`);
    }
  }, [setMessage, loadVideos]);

  const recomputeAllVideos = useCallback(async (platform) => {
    try {
      const res = await videoService.recomputeAllVideos(platform);
      await loadVideos();
      const platformName = platform.charAt(0).toUpperCase() + platform.slice(1);
      if (setMessage) setMessage(`✅ Recomputed ${res.updated_count} ${platformName} video${res.updated_count !== 1 ? 's' : ''}`);
    } catch (err) {
      console.error(`Error recomputing ${platform} videos:`, err);
      const platformName = platform.charAt(0).toUpperCase() + platform.slice(1);
      if (setMessage) setMessage(`❌ Error recomputing ${platformName} videos`);
    }
  }, [setMessage, loadVideos]);

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

  const handleDrop = useCallback(async (e, targetVideo) => {
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
      await videoService.reorderVideos(videoIds);
    } catch (err) {
      console.error('Error reordering videos:', err);
      if (setMessage) setMessage('❌ Error reordering videos');
      setVideos(originalVideos);
    }
  }, [draggedVideo, videos, setMessage]);

  const cancelAllUploads = useCallback(async () => {
    const uploadingVideos = videos.filter(v => 
      v.status === 'uploading' && 
      !(typeof v.id === 'string' && v.id.startsWith('temp-'))
    );
    if (uploadingVideos.length === 0) {
      return;
    }
    
    if (setMessage) setMessage('⏳ Cancelling uploads...');
    
    setVideos(prev => prev.map(video => 
      uploadingVideos.some(uv => uv.id === video.id) 
        ? { ...video, status: 'cancelled' } 
        : video
    ));
    
    try {
      const cancelPromises = uploadingVideos.map(v => videoService.cancelVideoUpload(v.id));
      await Promise.all(cancelPromises);
      
      const updatedVideos = await videoService.loadVideos();
      setVideos(updatedVideos);
      
      if (setMessage) setMessage(`✅ Cancelled ${uploadingVideos.length} upload(s)`);
    } catch (err) {
      const updatedVideos = await videoService.loadVideos();
      setVideos(updatedVideos);
      
      const errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Failed to cancel uploads';
      if (setMessage) setMessage(`❌ ${errorMsg}`);
    }
  }, [videos, setMessage]);

  const upload = useCallback(async () => {
    if (tiktok.enabled && tiktokSettings.commercial_content_disclosure) {
      const hasYourBrand = tiktokSettings.commercial_content_your_brand ?? false;
      const hasBranded = tiktokSettings.commercial_content_branded ?? false;
      
      if (!hasYourBrand && !hasBranded) {
        if (setMessage) setMessage('❌ You need to indicate if your content promotes yourself, a third party, or both.');
        return;
      }
    }
    
    if (!youtube.enabled && !tiktok.enabled && !instagram.enabled) {
      if (setMessage) setMessage('❌ Enable at least one destination first');
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
        setNotification({
          type: 'error',
          title: 'Insufficient Tokens',
          message: `You need ${totalTokensRequired} tokens to upload ${pendingVideos.length} video${pendingVideos.length === 1 ? '' : 's'}, but you only have ${tokenBalance.tokens_remaining} tokens remaining. You need ${shortfall} more token${shortfall === 1 ? '' : 's'}. Please upgrade your plan or wait for your token balance to reset.`,
        });
        setTimeout(() => setNotification(null), 10000);
        return;
      }
    }
    
    const isScheduling = !globalSettings.upload_immediately;
    if (isScheduling && setMessage) {
      setMessage('⏳ Scheduling videos...');
    }
    
    try {
      const res = await videoService.uploadVideos();
      
      const updatedVideos = await videoService.loadVideos();
      setVideos(updatedVideos);
      
      const hasSuccessfulTiktokUploads = updatedVideos.some(video => {
        const tiktokId = video.custom_settings?.tiktok_id;
        const tiktokPublishId = video.custom_settings?.tiktok_publish_id;
        const hasTiktokUpload = tiktokId || tiktokPublishId;
        const isUploaded = video.status === 'uploaded' || video.platform_statuses?.tiktok === 'uploaded';
        return hasTiktokUpload && isUploaded;
      });
      
      if (res.scheduled !== undefined && setMessage) {
        setMessage(`✅ ${res.scheduled} videos scheduled! ${res.message}`);
      }
      
      if (res.videos_uploaded !== undefined && res.videos_uploaded > 0) {
        if (tiktok.enabled && hasSuccessfulTiktokUploads) {
          setNotification({
            type: 'info',
            title: 'Content Processing',
            message: 'Your content has been published successfully. It may take a few minutes for the content to process and be visible on your TikTok profile.',
          });
          setTimeout(() => setNotification(null), 15000);
        }
      } else if (res.videos_failed === 0 && res.scheduled === undefined) {
        if (tiktok.enabled && hasSuccessfulTiktokUploads) {
          setNotification({
            type: 'info',
            title: 'Content Processing',
            message: 'Your content has been published successfully. It may take a few minutes for the content to process and be visible on your TikTok profile.',
          });
          setTimeout(() => setNotification(null), 15000);
        }
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Unknown error';
      console.error('Upload error:', err);
      
      if (errorMsg.toLowerCase().includes('insufficient') || errorMsg.toLowerCase().includes('token')) {
        setNotification({
          type: 'error',
          title: 'Insufficient Tokens',
          message: errorMsg,
        });
        setTimeout(() => setNotification(null), 10000);
      } else {
        if (setMessage) setMessage(`❌ Upload failed: ${errorMsg}`);
      }
      
      const updatedVideos = await videoService.loadVideos();
      setVideos(updatedVideos);
    }
  }, [youtube, tiktok, instagram, tiktokSettings, globalSettings, tokenBalance, subscription, videos, setMessage, setNotification]);

  return {
    videos,
    editingVideo,
    draggedVideo,
    overrideInputValues,
    expandedDestinationErrors,
    isUploading,
    derivedMessage,
    setVideos,
    setEditingVideo,
    setDraggedVideo,
    setOverrideInputValues,
    setExpandedDestinationErrors,
    loadVideos,
    addVideo,
    uploadFilesSequentially,
    handleFileDrop,
    removeVideo,
    clearAllVideos,
    clearUploadedVideos,
    cancelScheduled,
    updateVideoSettings,
    saveDestinationOverrides,
    recomputeVideoTitle,
    recomputeVideoField,
    recomputeAllVideos,
    handleDragStart,
    handleDragEnd,
    handleDragOver,
    handleDrop,
    cancelAllUploads,
    upload,
    calculateQueueTokenCost,
    formatFileSize,
  };
}
