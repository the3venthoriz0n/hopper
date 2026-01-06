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
  const [destinationModal, setDestinationModal] = useState(null);
  const [maxFileSize, setMaxFileSize] = useState(null);
  const [expandedDestinationErrors, setExpandedDestinationErrors] = useState(new Set());

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
  } = useSettings(setMessage);

  const {
    videos,
    expandedVideos,
    editingVideo,
    draggedVideo,
    overrideInputValues,
    isUploading,
    derivedMessage: derivedMessageFromHook,
    setExpandedVideos,
    setEditingVideo,
    setDraggedVideo,
    setOverrideInputValues,
    loadVideos,
    uploadFilesSequentially,
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
    handleDragEnd,
    handleDragOver,
    handleDrop,
    formatFileSize,
    calculateQueueTokenCost,
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
    document.title = isProduction ? 'hopper' : 'DEV HOPPER';
  }, [isProduction]);

  const handleWebSocketMessage = useCallback((data) => {
    if (data.type === 'video_update') {
      loadVideos();
      if (data.video) {
        if (data.video.status === 'uploaded' || data.video.status === 'failed') {
          setNotification({
            type: data.video.status === 'uploaded' ? 'success' : 'error',
            title: data.video.status === 'uploaded' ? 'Upload Complete' : 'Upload Failed',
            message: data.video.status === 'uploaded' 
              ? `${data.video.filename} has been uploaded successfully`
              : data.video.error || 'Upload failed',
            videoFilename: data.video.filename
          });
          setTimeout(() => setNotification(null), 10000);
        }
      }
    } else if (data.type === 'token_balance_update') {
      loadSubscription();
    } else if (data.type === 'platform_status_update') {
      loadDestinations();
    }
  }, [loadVideos, loadSubscription, loadDestinations]);

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
        user={user}
        isAdmin={isAdmin}
        tokenBalance={tokenBalance}
        setShowAccountSettings={setShowAccountSettings}
        setShowGlobalSettings={setShowGlobalSettings}
        showGlobalSettings={showGlobalSettings}
      />

      {showGlobalSettings && (
        <GlobalSettings
          globalSettings={globalSettings}
          setGlobalSettings={setGlobalSettings}
          updateGlobalSettings={updateGlobalSettings}
        />
      )}

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
        uploadFilesSequentially={uploadFilesSequentially}
        maxFileSize={maxFileSize}
      />

      {derivedMessage && <div className="message">{derivedMessage}</div>}
      
      <VideoQueue
        videos={videos}
        derivedMessage={derivedMessage}
        expandedVideos={expandedVideos}
        setExpandedVideos={setExpandedVideos}
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

