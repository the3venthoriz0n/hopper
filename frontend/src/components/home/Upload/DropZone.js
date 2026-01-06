import React from 'react';
import { HOPPER_COLORS } from '../../../utils/colors';

/**
 * File drop zone component
 * @param {object} props
 */
export default function DropZone({
  handleFileDrop,
  uploadFilesSequentially,
  maxFileSize,
}) {
  const handleClick = () => {
    document.getElementById('file-input').click();
  };

  const handleFileChange = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      uploadFilesSequentially(files);
    }
    e.target.value = ''; // Reset input
  };

  return (
    <div 
      className="dropzone"
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleFileDrop}
      onClick={handleClick}
    >
      <p>Drop videos here</p>
      {maxFileSize && (
        <p style={{ fontSize: '0.85rem', color: HOPPER_COLORS.grey, marginTop: '0.5rem' }}>
          Maximum file size: {maxFileSize.max_file_size_display}
        </p>
      )}
      <input 
        id="file-input"
        type="file"
        multiple
        accept="video/*"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />
    </div>
  );
}
