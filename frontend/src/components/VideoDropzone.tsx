import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { uploadVideo } from '../utils/api'
import './VideoDropzone.css'

interface VideoDropzoneProps {
  userId: number
  onUpload: () => void
}

function VideoDropzone({ userId, onUpload }: VideoDropzoneProps) {
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<string | null>(null)

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return

    setUploading(true)
    
    for (let i = 0; i < acceptedFiles.length; i++) {
      const file = acceptedFiles[i]
      setUploadProgress(`Uploading ${file.name} (${i + 1}/${acceptedFiles.length})`)
      
      try {
        await uploadVideo(userId, file)
      } catch (error) {
        console.error('Upload error:', error)
        alert(`Failed to upload ${file.name}`)
      }
    }

    setUploading(false)
    setUploadProgress(null)
    onUpload()
  }, [userId, onUpload])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'video/*': ['.mp4', '.mov', '.avi', '.mkv', '.webm']
    },
    disabled: uploading
  })

  return (
    <div
      {...getRootProps()}
      className={`dropzone ${isDragActive ? 'active' : ''} ${uploading ? 'uploading' : ''}`}
    >
      <input {...getInputProps()} />
      
      {uploading ? (
        <div className="upload-status">
          <p>{uploadProgress}</p>
        </div>
      ) : (
        <div className="dropzone-content">
          <svg
            className="upload-icon"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          <p className="dropzone-text">
            {isDragActive
              ? 'Drop videos here'
              : 'Drag and drop videos here, or click to select'}
          </p>
          <p className="dropzone-hint">Supports: MP4, MOV, AVI, MKV, WebM</p>
        </div>
      )}
    </div>
  )
}

export default VideoDropzone

