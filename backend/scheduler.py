class UploadScheduler:
    """Simple uploader - immediate uploads only for v1"""
    
    def schedule_uploads(self, videos, uploader):
        """Upload all videos immediately"""
        print(f"⚡ Starting immediate upload of {len(videos)} video(s)...")
        
        for video in videos:
            self.upload_video(video, uploader)
    
    def upload_video(self, video, uploader):
        """Execute the upload"""
        try:
            print(f"\n🎬 Starting upload: {video['filename']}")
            result = uploader.upload_video(
                video['path'],
                video['metadata']['title'],
                video['metadata']['description']
            )
            video['status'] = 'completed'
            video['youtube_id'] = result['id']
            print(f"✅ Upload complete: {video['filename']}")
            
        except Exception as e:
            print(f"❌ Error uploading {video['filename']}: {str(e)}")
            video['status'] = 'failed'
            video['error'] = str(e)
