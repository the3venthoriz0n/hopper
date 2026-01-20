import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { getApiUrl } from '../../services/api';
import { useWebSocket } from '../../hooks/useWebSocket';
import { usePlatforms } from '../../hooks/usePlatforms';
import { useVideos } from '../../hooks/useVideos';
import { useSettings } from '../../hooks/useSettings';
import { useSubscription } from '../../hooks/useSubscription';
import * as authService from '../../services/authService';
import HomeHeader from './HomeHeader';
import GlobalSettings from './GlobalSettings';
import DestinationsList from './Destinations/DestinationsList';
import UploadButton from './Upload/UploadButton';
import DropZone from './Upload/DropZone';
import VideoQueue from './VideoQueue/VideoQueue';
import EditVideoModal from './Modals/EditVideoModal';
import DestinationDetailsModal from './Modals/DestinationDetailsModal';
import AccountSettingsModal from './Modals/AccountSettingsModal';
import DeleteConfirmModal from './Modals/DeleteConfirmModal';
import NotificationPopup from './Modals/NotificationPopup';
import ConfirmDialog from './Modals/ConfirmDialog';
import Footer from '../common/Footer';

/**
 * Main Home component - orchestrates all hooks, services, and sub-components
 * @param {object} props
 */
export default function Home({ user, isAdmin, setUser, authLoading }) {
  const navigate = useNavigate();
  const location = useLocation();
  const API = getApiUrl();
  const isProduction = process.env.REACT_APP_ENVIRONMENT === 'production';
  const isSubscriptionView = location.pathname.startsWith('/app/subscription');

  const [message, setMessage] = useState('');
  const [notification, setNotification] = useState(null);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showTiktokSettings, setShowTiktokSettings] = useState(false);
  const [showInstagramSettings, setShowInstagramSettings] = useState(false);
  const [showAccountSettings, setShowAccountSettings] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showGlobalSettings, setShowGlobalSettings] = useState(false);
  const [newWord, setNewWord] = useState('');
  const [wordbankExpanded, setWordbankExpanded] = useState(false);
  const [destinationModal, setDestinationModal] = useState(null);
  const [maxFileSize, setMaxFileSize] = useState(null);

  const {
    youtube,
    tiktok,
    instagram,
    tiktokCreatorInfo,
    connectYoutube,
    connectTiktok,
    connectInstagram,
    disconnectYoutube,
    disconnectTiktok,
    disconnectInstagram,
    toggleYoutube,
    toggleTiktok,
    toggleInstagram,
    loadDestinations,
    loadYoutubeAccount,
    loadTiktokAccount,
    loadInstagramAccount,
  } = usePlatforms(setMessage);

  const {
    subscription,
    tokenBalance,
    availablePlans,
    loadingSubscription,
    loadingPlanKey,
    loadSubscription,
    handleUpgrade,
    handleOpenStripePortal,
    handleCancelSubscription,
  } = useSubscription(user, setMessage, setNotification, setConfirmDialog, []);

  const {
    globalSettings,
    youtubeSettings,
    tiktokSettings,
    instagramSettings,
    setGlobalSettings,
    setYoutubeSettings,
    setTiktokSettings,
    setInstagramSettings,
    updateGlobalSettings,
    updateYoutubeSettings,
    updateTiktokSettings,
    updateInstagramSettings,
    loadGlobalSettings,
    loadYoutubeSettings,
    loadTiktokSettings,
    loadInstagramSettings,
    addWordToWordbank,
    removeWordFromWordbank,
    clearWordbank,
  } = useSettings(setMessage);

  const {
    videos,
    editingVideo,
    draggedVideo,
    overrideInputValues,
    isUploading,
    derivedMessage: derivedMessageFromHook,
    setEditingVideo,
    setDraggedVideo,
    setOverrideInputValues,
    loadVideos,
    uploadFilesConcurrently,
    handleFileDrop: handleFileDropFromHook,
    removeVideo,
    updateVideoSettings,
    recomputeVideoTitle,
    recomputeVideoField,
    saveDestinationOverrides,
    cancelScheduled,
    cancelAllUploads,
    upload: uploadFromHook,
    clearUploadedVideos,
    clearAllVideos,
    handleDragStart,
    updateVideoProgress,
    handleDragEnd,
    handleDragOver,
    handleDrop,
    formatFileSize,
    calculateQueueTokenCost,
    expandedDestinationErrors,
    setExpandedDestinationErrors,
  } = useVideos(
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
  );

  const loadUploadLimits = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/upload/limits`);
      setMaxFileSize(res.data);
    } catch (err) {
      console.error('Error loading upload limits:', err);
    }
  }, [API]);

  useEffect(() => {
    if (user) {
      loadUploadLimits();
      loadDestinations();
      loadGlobalSettings();
      loadYoutubeSettings();
      loadTiktokSettings();
      loadInstagramSettings();
      loadVideos();
      loadSubscription();
    }
  }, [user, loadUploadLimits, loadDestinations, loadGlobalSettings, loadYoutubeSettings, loadTiktokSettings, loadInstagramSettings, loadVideos, loadSubscription]);

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const googleLogin = urlParams.get('google_login');
    
    if (googleLogin === 'success') {
      setMessage('✅ Successfully logged in with Google!');
      window.history.replaceState({}, '', '/app');
      if (window.opener) {
        window.close();
      }
    } else if (googleLogin === 'error') {
      setMessage('❌ Google login failed. Please try again.');
      window.history.replaceState({}, '', '/app');
      if (window.opener) {
        window.close();
      }
    }
  }, []);

  useEffect(() => {
    document.title = isProduction ? 'hopper' : 'dev hopper';
  }, [isProduction]);

  const handleWebSocketMessage = useCallback((data) => {
    // Handle backend message format: {event: "type", payload: {...}}
    // Also support legacy format: {type: "type", ...} for backward compatibility
    const eventType = data.event || data.type;
    const payload = data.payload || data;
    
    if (!eventType) {
      console.warn('WebSocket message missing event type:', data);
      return;
    }
    
    switch (eventType) {
      case 'video_added':
        loadVideos();
        break;
        
      case 'video_status_changed':
        loadVideos();
        if (payload.video) {
          const video = payload.video;
          if (video.status === 'failed') {
            setNotification({
              type: 'error',
              title: 'Upload Failed',
              message: video.error || 'Upload failed',
              videoFilename: video.filename
            });
            setTimeout(() => setNotification(null), 10000);
          }
        }
        break;
        
      case 'video_updated':
        loadVideos();
        break;
        
      case 'video_deleted':
        loadVideos();
        break;
        
      case 'video_title_recomputed':
        loadVideos();
        break;
        
      case 'videos_bulk_recomputed':
        loadVideos();
        break;
        
      case 'destination_toggled':
        loadDestinations();
        loadVideos();
        break;
        
      case 'upload_progress':
        const { video_id, progress_percent, platform } = payload;
        if (video_id && progress_percent !== undefined) {
          // Pass platform to updateVideoProgress for platform-specific tracking
          updateVideoProgress(video_id, progress_percent, platform);
        }
        break;
        
      case 'settings_changed':
        if (payload.category === 'global') {
          loadGlobalSettings();
        } else if (payload.category === 'youtube') {
          loadYoutubeSettings();
        } else if (payload.category === 'tiktok') {
          loadTiktokSettings();
        } else if (payload.category === 'instagram') {
          loadInstagramSettings();
        }
        break;
        
      case 'token_balance_changed':
        loadSubscription();
        break;
        
      // Legacy event type support for backward compatibility
      case 'video_update':
        loadVideos();
        if (payload.video) {
          if (payload.video.status === 'failed') {
            setNotification({
              type: 'error',
              title: 'Upload Failed',
              message: payload.video.error || 'Upload failed',
              videoFilename: payload.video.filename
            });
            setTimeout(() => setNotification(null), 10000);
          }
        }
        break;
        
      case 'token_balance_update':
        loadSubscription();
        break;
        
      case 'platform_status_update':
        loadDestinations();
        break;
        
      default:
        console.log('Unhandled WebSocket event type:', eventType, payload);
    }
  }, [loadVideos, loadSubscription, loadDestinations, loadGlobalSettings, loadYoutubeSettings, loadTiktokSettings, loadInstagramSettings, setNotification]);

  const { connected: wsConnected } = useWebSocket('/ws', handleWebSocketMessage, {
    reconnect: true,
    reconnectInterval: 3000,
    maxReconnectAttempts: 10,
  });

  const handleLogout = useCallback(async () => {
    try {
      await authService.logout();
      setUser(null);
      setMessage('✅ Logged out successfully');
      setShowAccountSettings(false);
    } catch (err) {
      console.error('Logout failed:', err);
      setMessage('❌ Logout failed');
    }
  }, [setUser]);

  const handleDeleteAccount = useCallback(async () => {
    try {
      await authService.deleteAccount();
      setMessage('✅ Your account has been permanently deleted');
      setShowDeleteConfirm(false);
      setShowAccountSettings(false);
      setTimeout(() => {
        window.location.href = '/login';
      }, 1500);
    } catch (err) {
      console.error('Error deleting account:', err);
      setMessage(err.response?.data?.detail || '❌ Failed to delete account');
      setShowDeleteConfirm(false);
    }
  }, []);

  const closeEditModal = useCallback(() => {
    setEditingVideo(null);
  }, [setEditingVideo]);

  const derivedMessage = message || derivedMessageFromHook;

  if (authLoading) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return null;
  }

  return (
    <div className="app">
      <NotificationPopup 
        notification={notification} 
        setNotification={setNotification}
        setShowAccountSettings={setShowAccountSettings}
      />
      
      <ConfirmDialog 
        confirmDialog={confirmDialog} 
        setConfirmDialog={setConfirmDialog}
      />

      <HomeHeader
        appTitle={isProduction ? 'hopper' : 'dev hopper'}
        user={user}
        isAdmin={isAdmin}
        tokenBalance={tokenBalance}
        setShowAccountSettings={setShowAccountSettings}
        setShowGlobalSettings={setShowGlobalSettings}
        showGlobalSettings={showGlobalSettings}
      />

      <GlobalSettings
        showGlobalSettings={showGlobalSettings}
        setShowGlobalSettings={setShowGlobalSettings}
        globalSettings={globalSettings}
        setGlobalSettings={setGlobalSettings}
        updateGlobalSettings={updateGlobalSettings}
        newWord={newWord}
        setNewWord={setNewWord}
        addWordToWordbank={addWordToWordbank}
        removeWordFromWordbank={removeWordFromWordbank}
        clearWordbank={clearWordbank}
        wordbankExpanded={wordbankExpanded}
        setWordbankExpanded={setWordbankExpanded}
      />

      <DestinationsList
        youtube={youtube}
        tiktok={tiktok}
        instagram={instagram}
        tiktokCreatorInfo={tiktokCreatorInfo}
        youtubeSettings={youtubeSettings}
        tiktokSettings={tiktokSettings}
        instagramSettings={instagramSettings}
        showSettings={showSettings}
        showTiktokSettings={showTiktokSettings}
        showInstagramSettings={showInstagramSettings}
        setShowSettings={setShowSettings}
        setShowTiktokSettings={setShowTiktokSettings}
        setShowInstagramSettings={setShowInstagramSettings}
        connectYoutube={connectYoutube}
        connectTiktok={connectTiktok}
        connectInstagram={connectInstagram}
        disconnectYoutube={disconnectYoutube}
        disconnectTiktok={disconnectTiktok}
        disconnectInstagram={disconnectInstagram}
        toggleYoutube={toggleYoutube}
        toggleTiktok={toggleTiktok}
        toggleInstagram={toggleInstagram}
        updateYoutubeSettings={updateYoutubeSettings}
        updateTiktokSettings={updateTiktokSettings}
        updateInstagramSettings={updateInstagramSettings}
        setYoutubeSettings={setYoutubeSettings}
        setTiktokSettings={setTiktokSettings}
        setInstagramSettings={setInstagramSettings}
      />

      <UploadButton
        videos={videos}
        youtube={youtube}
        tiktok={tiktok}
        instagram={instagram}
        tiktokSettings={tiktokSettings}
        globalSettings={globalSettings}
        isUploading={isUploading}
        upload={uploadFromHook}
        cancelAllUploads={cancelAllUploads}
      />

      {videos.some(v => v.status === 'scheduled') && (
        <button className="cancel-scheduled-btn" onClick={cancelScheduled}>
          Cancel Scheduled ({videos.filter(v => v.status === 'scheduled').length})
        </button>
      )}

      <DropZone
        handleFileDrop={handleFileDropFromHook}
        uploadFilesConcurrently={uploadFilesConcurrently}
        maxFileSize={maxFileSize}
      />

      {derivedMessage && <div className="message">{derivedMessage}</div>}
      
      <VideoQueue
        videos={videos}
        draggedVideo={draggedVideo}
        youtube={youtube}
        tiktok={tiktok}
        instagram={instagram}
        calculateQueueTokenCost={calculateQueueTokenCost}
        clearUploadedVideos={clearUploadedVideos}
        clearAllVideos={clearAllVideos}
        handleDragStart={handleDragStart}
        handleDragEnd={handleDragEnd}
        handleDragOver={handleDragOver}
        handleDrop={handleDrop}
        formatFileSize={formatFileSize}
        setDestinationModal={setDestinationModal}
        setEditingVideo={setEditingVideo}
        removeVideo={removeVideo}
        setMessage={setMessage}
        loadVideos={loadVideos}
        API={API}
        axios={axios}
      />

      {editingVideo && (
        <EditVideoModal
          editingVideo={editingVideo}
          videos={videos}
          youtubeSettings={youtubeSettings}
          tiktok={tiktok}
          tiktokCreatorInfo={tiktokCreatorInfo}
          closeEditModal={closeEditModal}
          recomputeVideoTitle={recomputeVideoTitle}
          updateVideoSettings={updateVideoSettings}
        />
      )}

      {destinationModal && (
        <DestinationDetailsModal
          destinationModal={destinationModal}
          setDestinationModal={setDestinationModal}
          videos={videos}
          recomputeVideoField={recomputeVideoField}
          saveDestinationOverrides={saveDestinationOverrides}
          expandedDestinationErrors={expandedDestinationErrors}
          setExpandedDestinationErrors={setExpandedDestinationErrors}
        />
      )}

      <AccountSettingsModal
        showAccountSettings={showAccountSettings}
        setShowAccountSettings={setShowAccountSettings}
        user={user}
        subscription={subscription}
        tokenBalance={tokenBalance}
        availablePlans={availablePlans}
        loadingSubscription={loadingSubscription}
        loadingPlanKey={loadingPlanKey}
        handleLogout={handleLogout}
        handleOpenStripePortal={handleOpenStripePortal}
        handleUpgrade={handleUpgrade}
        handleCancelSubscription={handleCancelSubscription}
        setShowDeleteConfirm={setShowDeleteConfirm}
        setConfirmDialog={setConfirmDialog}
      />

      <DeleteConfirmModal
        showDeleteConfirm={showDeleteConfirm}
        setShowDeleteConfirm={setShowDeleteConfirm}
        handleDeleteAccount={handleDeleteAccount}
      />

      <Footer />
    </div>
  );
}

