from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
import json
from pathlib import Path


async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    privacy: str,
    credentials_json: str
) -> dict:
    """
    Upload a video to YouTube
    
    Args:
        video_path: Path to the video file
        title: Video title
        description: Video description
        privacy: Privacy status (public, private, unlisted)
        credentials_json: JSON string of OAuth credentials
        
    Returns:
        dict with upload result
    """
    print(f"\n{'='*60}")
    print(f"[YouTube Upload] Starting upload process")
    print(f"[YouTube Upload] Video path: {video_path}")
    print(f"[YouTube Upload] Title: {title}")
    print(f"[YouTube Upload] Privacy: {privacy}")
    
    try:
        # Check if file exists
        video_file = Path(video_path)
        if not video_file.exists():
            error_msg = f"Video file not found: {video_path}"
            print(f"[YouTube Upload] ERROR: {error_msg}")
            return {'success': False, 'error': error_msg}
        
        file_size = video_file.stat().st_size / (1024 * 1024)  # MB
        print(f"[YouTube Upload] File size: {file_size:.2f} MB")
        
        # Parse credentials
        print(f"[YouTube Upload] Parsing OAuth credentials...")
        creds_dict = json.loads(credentials_json)
        credentials = Credentials(
            token=creds_dict['token'],
            refresh_token=creds_dict['refresh_token'],
            token_uri=creds_dict['token_uri'],
            client_id=creds_dict['client_id'],
            client_secret=creds_dict['client_secret'],
            scopes=creds_dict['scopes']
        )
        
        # Build YouTube API client
        print(f"[YouTube Upload] Building YouTube API client...")
        youtube = build('youtube', 'v3', credentials=credentials)
        print(f"[YouTube Upload] YouTube API client created successfully")
        
        # Prepare video metadata
        body = {
            'snippet': {
                'title': title,
                'description': description or '',
                'categoryId': '22'  # People & Blogs category
            },
            'status': {
                'privacyStatus': privacy,
                'selfDeclaredMadeForKids': False
            }
        }
        print(f"[YouTube Upload] Metadata prepared")
        
        # Create media upload
        print(f"[YouTube Upload] Creating media upload object...")
        media = MediaFileUpload(
            str(video_path),
            chunksize=1024*1024,  # 1MB chunks
            resumable=True
        )
        print(f"[YouTube Upload] Media upload object created")
        
        # Execute upload
        print(f"[YouTube Upload] Starting video upload to YouTube...")
        request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )
        
        response = None
        last_progress = -1
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                if progress != last_progress and progress % 10 == 0:
                    print(f"[YouTube Upload] Progress: {progress}%")
                    last_progress = progress
        
        video_id = response['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        print(f"[YouTube Upload] ✅ Upload successful!")
        print(f"[YouTube Upload] Video ID: {video_id}")
        print(f"[YouTube Upload] Video URL: {video_url}")
        print(f"{'='*60}\n")
        
        return {
            'success': True,
            'video_id': video_id,
            'url': video_url
        }
        
    except Exception as e:
        error_msg = str(e)
        print(f"[YouTube Upload] ❌ ERROR: {error_msg}")
        print(f"[YouTube Upload] Error type: {type(e).__name__}")
        import traceback
        print(f"[YouTube Upload] Traceback:")
        traceback.print_exc()
        print(f"{'='*60}\n")
        
        return {
            'success': False,
            'error': error_msg
        }

