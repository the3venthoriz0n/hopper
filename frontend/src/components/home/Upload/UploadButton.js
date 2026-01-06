import React from 'react';
import { HOPPER_COLORS, rgba } from '../../../utils/colors';

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
  cancelAllUploads,
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

  const hasUploadingVideos = false; // Temporarily disabled
  const isCancelMode = hasUploadingVideos;
  const isDisabled = !isCancelMode && (
    isUploading || 
    (tiktok.enabled && 
     commercialContentOn && 
     !(hasYourBrand || hasBrandedContent))
  );

  const cancelBgGradient = `linear-gradient(135deg, ${HOPPER_COLORS.error} 0%, ${rgba(HOPPER_COLORS.rgb.error, 0.8)} 100%)`;
  const cancelShadow = `0px 4px 20px ${rgba(HOPPER_COLORS.rgb.error, 0.2)}`;
  const cancelShadowHover = `0 4px 12px ${rgba(HOPPER_COLORS.rgb.error, 0.5)}`;

  return (
    <>
      {getTikTokDeclaration()}
      <button 
        className="upload-btn" 
        onClick={isCancelMode ? cancelAllUploads : upload} 
        disabled={isDisabled}
        title={
          isCancelMode
            ? "Cancel all in-progress uploads"
            : (tiktok.enabled && 
               commercialContentOn && 
               !(hasYourBrand || hasBrandedContent))
              ? "You need to indicate if your content promotes yourself, a third party, or both."
              : undefined
        }
        style={{
          cursor: isDisabled ? 'not-allowed' : undefined,
          ...(isCancelMode ? {
            background: cancelBgGradient,
            boxShadow: cancelShadow
          } : {})
        }}
        onMouseEnter={(e) => {
          if (isCancelMode && !isDisabled) {
            e.target.style.transform = 'translateY(-2px)';
            e.target.style.boxShadow = cancelShadowHover;
            e.target.style.filter = 'brightness(1.1)';
          }
        }}
        onMouseLeave={(e) => {
          if (isCancelMode && !isDisabled) {
            e.target.style.transform = 'translateY(0)';
            e.target.style.boxShadow = cancelShadow;
            e.target.style.filter = 'none';
          }
        }}
      >
        {isCancelMode 
          ? 'Cancel Upload' 
          : (isUploading 
             ? 'Uploading...' 
             : (globalSettings.upload_immediately ? 'Upload' : 'Schedule Videos'))}
      </button>
    </>
  );
}
