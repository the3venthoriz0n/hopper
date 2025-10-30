from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

class YouTubeUploader:
    def __init__(self, credentials_dict):
        self.credentials = Credentials(
            token=credentials_dict['token'],
            refresh_token=credentials_dict['refresh_token'],
            token_uri=credentials_dict['token_uri'],
            client_id=credentials_dict['client_id'],
            client_secret=credentials_dict['client_secret'],
            scopes=credentials_dict['scopes']
        )
        self.youtube = build('youtube', 'v3', credentials=self.credentials)
    
    def upload_video(self, video_path, title, description="", privacy="private", category="22"):
        """
        Upload a video to YouTube
        
        Args:
            video_path: Path to video file
            title: Video title
            description: Video description
            privacy: 'public', 'private', or 'unlisted'
            category: YouTube category ID (22 = People & Blogs)
        """
        try:
            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'categoryId': category
                },
                'status': {
                    'privacyStatus': privacy
                }
            }
            
            media = MediaFileUpload(
                video_path,
                chunksize=-1,
                resumable=True,
                mimetype='video/*'
            )
            
            request = self.youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    print(f"Upload progress: {progress}%")
            
            print(f"✅ Video uploaded successfully! Video ID: {response['id']}")
            return response
            
        except HttpError as e:
            print(f"❌ An HTTP error occurred: {e.resp.status} - {e.content}")
            raise
        except Exception as e:
            print(f"❌ An error occurred: {str(e)}")
            raise