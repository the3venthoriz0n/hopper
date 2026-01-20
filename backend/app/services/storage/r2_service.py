"""Cloudflare R2 storage service using S3-compatible API"""
import logging
import tempfile
from pathlib import Path
from typing import Optional
from botocore.exceptions import ClientError, BotoCoreError
import boto3
from botocore.config import Config

from app.core.config import settings

logger = logging.getLogger(__name__)


class R2Service:
    """Service for interacting with Cloudflare R2 storage"""
    
    def __init__(self):
        """Initialize R2 service with configuration from settings"""
        if not settings.R2_ACCOUNT_ID or not settings.R2_ACCESS_KEY_ID or not settings.R2_SECRET_ACCESS_KEY:
            raise ValueError("R2 configuration is missing. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY environment variables.")
        
        if not settings.R2_BUCKET_NAME:
            raise ValueError("R2_BUCKET_NAME is not set. Set R2_BUCKET_NAME environment variable.")
        
        if not settings.R2_ENDPOINT_URL:
            raise ValueError("R2_ENDPOINT_URL is not set. Set R2_ENDPOINT_URL environment variable.")
        
        self.bucket = settings.R2_BUCKET_NAME
        self.endpoint_url = settings.R2_ENDPOINT_URL
        
        # Create S3 client with R2 endpoint
        self.s3_client = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version='s3v4')
        )
        logger.info(f"R2Service initialized for bucket: {self.bucket}")
    
    def generate_upload_url(self, object_key: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for direct upload to R2
        
        Args:
            object_key: R2 object key (path in bucket)
            expires_in: URL expiration time in seconds (default: 1 hour)
            
        Returns:
            Presigned PUT URL for uploading directly to R2
            
        Raises:
            ValueError: If object_key is empty
            Exception: If URL generation fails
        """
        if not object_key:
            raise ValueError("object_key cannot be empty")
        
        try:
            url = self.s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': self.bucket,
                    'Key': object_key
                },
                ExpiresIn=expires_in
            )
            logger.debug(f"Generated upload URL for {object_key} (expires in {expires_in}s)")
            return url
        except Exception as e:
            logger.error(f"Failed to generate upload URL for {object_key}: {e}", exc_info=True)
            raise Exception(f"Failed to generate upload URL: {str(e)}")
    
    def generate_download_url(self, object_key: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for direct download from R2
        
        Args:
            object_key: R2 object key (path in bucket)
            expires_in: URL expiration time in seconds (default: 1 hour)
            
        Returns:
            Presigned GET URL for downloading directly from R2
            
        Raises:
            ValueError: If object_key is empty
            Exception: If URL generation fails
        """
        if not object_key:
            raise ValueError("object_key cannot be empty")
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket,
                    'Key': object_key
                },
                ExpiresIn=expires_in
            )
            logger.debug(f"Generated download URL for {object_key} (expires in {expires_in}s)")
            return url
        except Exception as e:
            logger.error(f"Failed to generate download URL for {object_key}: {e}", exc_info=True)
            raise Exception(f"Failed to generate download URL: {str(e)}")
    
    def upload_file(self, file_path: Path, object_key: str) -> bool:
        """Upload file to R2 (for backend-initiated uploads)
        
        Args:
            file_path: Local file path to upload
            object_key: R2 object key (path in bucket)
            
        Returns:
            True if upload succeeded, False otherwise
        """
        if not file_path or not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False
        
        if not object_key:
            logger.error("object_key cannot be empty")
            return False
        
        try:
            self.s3_client.upload_file(
                str(file_path),
                self.bucket,
                object_key
            )
            logger.info(f"Successfully uploaded {file_path} to R2 as {object_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to upload {file_path} to R2 as {object_key}: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error uploading {file_path} to R2: {e}", exc_info=True)
            return False
    
    def download_file(self, object_key: str, local_path: Path) -> bool:
        """Download file from R2 to local path
        
        Args:
            object_key: R2 object key (path in bucket)
            local_path: Local file path to save downloaded file
            
        Returns:
            True if download succeeded, False otherwise
        """
        if not object_key:
            logger.error("object_key cannot be empty")
            return False
        
        try:
            # Ensure parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)
            
            self.s3_client.download_file(
                self.bucket,
                object_key,
                str(local_path)
            )
            logger.info(f"Successfully downloaded {object_key} from R2 to {local_path}")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                logger.warning(f"Object not found in R2: {object_key}")
            else:
                logger.error(f"Failed to download {object_key} from R2: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error downloading {object_key} from R2: {e}", exc_info=True)
            return False
    
    def delete_object(self, object_key: str) -> bool:
        """Delete object from R2
        
        Args:
            object_key: R2 object key (path in bucket)
            
        Returns:
            True if deletion succeeded or object doesn't exist, False on error
        """
        if not object_key:
            logger.error("object_key cannot be empty")
            return False
        
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket,
                Key=object_key
            )
            logger.info(f"Successfully deleted {object_key} from R2")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                logger.debug(f"Object already deleted or doesn't exist: {object_key}")
                return True  # Consider it success if already gone
            else:
                logger.error(f"Failed to delete {object_key} from R2: {e}", exc_info=True)
                return False
        except Exception as e:
            logger.error(f"Unexpected error deleting {object_key} from R2: {e}", exc_info=True)
            return False
    
    def object_exists(self, object_key: str) -> bool:
        """Check if object exists in R2
        
        Args:
            object_key: R2 object key (path in bucket)
            
        Returns:
            True if object exists, False otherwise
        """
        if not object_key:
            return False
        
        try:
            self.s3_client.head_object(
                Bucket=self.bucket,
                Key=object_key
            )
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404' or error_code == 'NoSuchKey':
                return False
            else:
                logger.warning(f"Error checking if object exists {object_key}: {e}")
                return False
        except Exception as e:
            logger.warning(f"Unexpected error checking if object exists {object_key}: {e}")
            return False
    
    def get_object_size(self, object_key: str) -> Optional[int]:
        """Get object size in bytes
        
        Args:
            object_key: R2 object key (path in bucket)
            
        Returns:
            Object size in bytes, or None if object doesn't exist or error occurs
        """
        if not object_key:
            return None
        
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket,
                Key=object_key
            )
            size = response.get('ContentLength')
            return size
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404' or error_code == 'NoSuchKey':
                logger.debug(f"Object not found: {object_key}")
            else:
                logger.warning(f"Error getting object size for {object_key}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error getting object size for {object_key}: {e}")
            return None
    
    def copy_object(self, source_key: str, dest_key: str) -> bool:
        """Copy object within same bucket (used for renaming)
        
        Args:
            source_key: Source R2 object key
            dest_key: Destination R2 object key
            
        Returns:
            True if copy succeeded, False otherwise
        """
        if not source_key or not dest_key:
            logger.error("source_key and dest_key cannot be empty")
            return False
        
        try:
            self.s3_client.copy_object(
                CopySource={'Bucket': self.bucket, 'Key': source_key},
                Bucket=self.bucket,
                Key=dest_key
            )
            logger.info(f"Successfully copied {source_key} to {dest_key} in R2")
            return True
        except ClientError as e:
            logger.error(f"Failed to copy {source_key} to {dest_key} in R2: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error copying {source_key} to {dest_key} in R2: {e}", exc_info=True)
            return False


# Global R2 service instance (lazy initialization)
_r2_service: Optional[R2Service] = None


def get_r2_service() -> R2Service:
    """Get or create R2 service instance (lazy initialization)
    
    Returns:
        R2Service instance
        
    Raises:
        ValueError: If R2 configuration is missing
    """
    global _r2_service
    if _r2_service is None:
        _r2_service = R2Service()
    return _r2_service
