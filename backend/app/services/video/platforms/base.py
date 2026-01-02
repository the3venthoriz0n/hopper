"""Abstract base class for platform uploaders"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from sqlalchemy.orm import Session


class BasePlatformUploader(ABC):
    """Abstract base class defining the interface contract for platform uploaders.
    
    All platform uploaders must implement these methods. This ensures consistency
    and makes it clear what's required when adding new platforms (e.g., X/Twitter).
    """
    
    @abstractmethod
    def upload(self, user_id: int, video_id: int, db: Optional[Session] = None) -> None:
        """Upload a video to the platform.
        
        Args:
            user_id: User ID who owns the video
            video_id: Video ID to upload
            db: Database session (optional, will create if needed)
            
        Raises:
            Exception: If upload fails for any reason
        """
        pass
    
    @abstractmethod
    def validate_credentials(self, user_id: int, db: Optional[Session] = None) -> bool:
        """Validate that the user has valid credentials for this platform.
        
        Args:
            user_id: User ID to check credentials for
            db: Database session (optional, will create if needed)
            
        Returns:
            True if credentials are valid, False otherwise
        """
        pass
    
    @abstractmethod
    def get_upload_status(self, video_id: int, db: Optional[Session] = None) -> Dict:
        """Get the current upload status for a video.
        
        Args:
            video_id: Video ID to check status for
            db: Database session (optional, will create if needed)
            
        Returns:
            Dictionary with status information, including:
            - status: str - Current status (e.g., 'uploaded', 'pending', 'failed')
            - platform_id: Optional[str] - Platform-specific ID if uploaded
            - error: Optional[str] - Error message if failed
        """
        pass

