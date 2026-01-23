import React from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';
import { isVideoInProgress } from '../../../utils/videoStatus';

/**
 * Upload button component with TikTok compliance declaration
 * @param {object} props
 */
export default function UploadButton({
  videos,
  youtube,
  tiktok,
  instagram,
  tiktokSettings,
  globalSettings,
  isUploading,
  upload,
  cancelAllUploads, // Keep prop for compatibility but not used here
}) {
  if (videos.length === 0 || (!youtube.enabled && !tiktok.enabled && !instagram.enabled)) {
    return null;
  }

  const commercialContentOn = tiktokSettings.commercial_content_disclosure ?? false;
  const hasYourBrand = commercialContentOn && (tiktokSettings.commercial_content_your_brand ?? false);
  const hasBrandedContent = commercialContentOn && (tiktokSettings.commercial_content_branded ?? false);
  
  const musicUsageUrl = 'https://www.tiktok.com/legal/page/global/music-usage-confirmation/en';
  const brandedContentUrl = 'https://www.tiktok.com/legal/page/global/bc-policy/en';
  
  const getTikTokDeclaration = () => {
    if (!tiktok.enabled) return null;

    let declarationContent = (
      <>
        By posting, you agree to TikTok's{' '}
        <a 
          href={musicUsageUrl} 
          target="_blank" 
          rel="noopener noreferrer"
          style={{ 
            color: HOPPER_COLORS.infoBlue, 
            textDecoration: 'underline',
            fontWeight: '500'
          }}
        >
          Music Usage Confirmation
        </a>
      </>
    );
    
    if (commercialContentOn && hasBrandedContent) {
      declarationContent = (
        <>
          By posting, you agree to TikTok's{' '}
          <a 
            href={brandedContentUrl} 
            target="_blank" 
            rel="noopener noreferrer"
            style={{ 
              color: HOPPER_COLORS.infoBlue, 
              textDecoration: 'underline',
              fontWeight: '500'
            }}
          >
            Branded Content Policy
          </a>
          {' '}and{' '}
          <a 
            href={musicUsageUrl} 
            target="_blank" 
            rel="noopener noreferrer"
            style={{ 
              color: HOPPER_COLORS.infoBlue, 
              textDecoration: 'underline',
              fontWeight: '500'
            }}
          >
            Music Usage Confirmation
          </a>
        </>
      );
    }
    
    return (
      <div style={{
        padding: '0.75rem 1rem',
        background: rgba(HOPPER_COLORS.rgb.infoBlue, 0.1),
        border: `1px solid ${rgba(HOPPER_COLORS.rgb.infoBlue, 0.3)}`,
        borderRadius: '6px',
        marginBottom: '1rem',
        fontSize: '0.9rem',
        color: HOPPER_COLORS.infoBlue,
        textAlign: 'center'
      }}>
        {declarationContent}
      </div>
    );
  };

  // Upload button should be disabled if:
  // - Currently uploading
  // - Videos are in progress (active uploads happening)
  // - TikTok compliance issue
  const hasVideosInProgress = videos.some(v => isVideoInProgress(v));
  const isDisabled = isUploading || 
    hasVideosInProgress ||
    (tiktok.enabled && 
     commercialContentOn && 
     !(hasYourBrand || hasBrandedContent));

  return (
    <>
      {getTikTokDeclaration()}
      <button 
        className="upload-btn" 
        onClick={upload} 
        disabled={isDisabled}
        title={
          (tiktok.enabled && 
           commercialContentOn && 
           !(hasYourBrand || hasBrandedContent))
            ? "You need to indicate if your content promotes yourself, a third party, or both."
            : (hasVideosInProgress || isUploading)
            ? "Please wait for current uploads to complete"
            : undefined
        }
        style={{
          cursor: isDisabled ? 'not-allowed' : undefined
        }}
      >
        {isUploading 
          ? 'Uploading...' 
          : (globalSettings.upload_immediately ? 'Upload' : 'Schedule Videos')}
      </button>
    </>
  );
}
