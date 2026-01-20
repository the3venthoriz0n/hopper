"""Cloudflare R2 storage service using S3-compatible API"""
import logging
import tempfile
from pathlib import Path
from typing import Optional, List, Dict
from botocore.exceptions import ClientError, BotoCoreError
import boto3
from botocore.config import Config

from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_old_local_path(object_key: str) -> bool:
    """Check if object_key is an old local file path (pre-R2 migration)
    
    Args:
        object_key: R2 object key to check
        
    Returns:
        True if the key appears to be an old local file path, False otherwise
    """
    if not object_key:
        return False
    # Old paths typically start with /app/uploads/ (old Docker container path)
    # Valid R2 keys are relative paths like "user_123/video_456.mp4" or "user_123/pending_1234567890_file.mp4"
    # They never start with / and always start with "user_"
    # Any absolute path (starting with /) is an old local path
    return object_key.startswith('/')


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
    
    def generate_upload_url(self, object_key: str, content_type: Optional[str] = None, expires_in: int = None) -> str:
        """Generate presigned URL for direct upload to R2
        
        Args:
            object_key: R2 object key (path in bucket)
            content_type: Optional content type (MIME type) for the upload
            expires_in: URL expiration time in seconds (default: from settings)
            
        Returns:
            Presigned PUT URL for uploading directly to R2
            
        Raises:
            ValueError: If object_key is empty
            Exception: If URL generation fails
        """
        if not object_key:
            raise ValueError("object_key cannot be empty")
        
        if expires_in is None:
            expires_in = settings.R2_PRESIGNED_URL_EXPIRY
        
        try:
            params = {
                'Bucket': self.bucket,
                'Key': object_key
            }
            if content_type:
                params['ContentType'] = content_type
            
            url = self.s3_client.generate_presigned_url(
                'put_object',
                Params=params,
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
        
        # Check if this is an old local file path (pre-R2 migration)
        if _is_old_local_path(object_key):
            logger.debug(f"Object key appears to be old local path (pre-R2 migration): {object_key}")
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
    
    def create_multipart_upload(self, object_key: str, content_type: Optional[str] = None) -> str:
        """Initiate multipart upload to R2
        
        Args:
            object_key: R2 object key (path in bucket)
            content_type: Optional content type (MIME type) for the upload
            
        Returns:
            Upload ID for the multipart upload
            
        Raises:
            ValueError: If object_key is empty
            Exception: If multipart upload initiation fails
        """
        if not object_key:
            raise ValueError("object_key cannot be empty")
        
        try:
            params = {
                'Bucket': self.bucket,
                'Key': object_key
            }
            if content_type:
                params['ContentType'] = content_type
            
            response = self.s3_client.create_multipart_upload(**params)
            upload_id = response['UploadId']
            logger.debug(f"Created multipart upload for {object_key} (upload_id: {upload_id})")
            return upload_id
        except ClientError as e:
            logger.error(f"Failed to create multipart upload for {object_key}: {e}", exc_info=True)
            raise Exception(f"Failed to create multipart upload: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error creating multipart upload for {object_key}: {e}", exc_info=True)
            raise Exception(f"Failed to create multipart upload: {str(e)}")
    
    def generate_presigned_url_for_part(self, object_key: str, upload_id: str, part_number: int, expires_in: int = None) -> str:
        """Generate presigned URL for uploading a part in multipart upload
        
        Args:
            object_key: R2 object key (path in bucket)
            upload_id: Multipart upload ID from create_multipart_upload
            part_number: Part number (1-indexed)
            expires_in: URL expiration time in seconds (default: from settings)
            
        Returns:
            Presigned PUT URL for uploading the part
            
        Raises:
            ValueError: If object_key, upload_id, or part_number is invalid
            Exception: If URL generation fails
        """
        if not object_key:
            raise ValueError("object_key cannot be empty")
        if not upload_id:
            raise ValueError("upload_id cannot be empty")
        if part_number < 1:
            raise ValueError("part_number must be >= 1")
        
        if expires_in is None:
            expires_in = settings.R2_PRESIGNED_URL_EXPIRY
        
        try:
            url = self.s3_client.generate_presigned_url(
                'upload_part',
                Params={
                    'Bucket': self.bucket,
                    'Key': object_key,
                    'UploadId': upload_id,
                    'PartNumber': part_number
                },
                ExpiresIn=expires_in
            )
            logger.debug(f"Generated presigned URL for part {part_number} of {object_key} (expires in {expires_in}s)")
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for part {part_number} of {object_key}: {e}", exc_info=True)
            raise Exception(f"Failed to generate presigned URL for part: {str(e)}")
    
    def complete_multipart_upload(self, object_key: str, upload_id: str, parts: List[Dict[str, any]]) -> bool:
        """Complete multipart upload in R2
        
        Args:
            object_key: R2 object key (path in bucket)
            upload_id: Multipart upload ID from create_multipart_upload
            parts: List of dicts with 'PartNumber' and 'ETag' keys
            
        Returns:
            True if completion succeeded, False otherwise
            
        Raises:
            ValueError: If object_key, upload_id, or parts are invalid
            Exception: If completion fails
        """
        if not object_key:
            raise ValueError("object_key cannot be empty")
        if not upload_id:
            raise ValueError("upload_id cannot be empty")
        if not parts or len(parts) == 0:
            raise ValueError("parts cannot be empty")
        
        try:
            # Format parts for boto3 (needs PartNumber and ETag)
            formatted_parts = [
                {'PartNumber': part['PartNumber'], 'ETag': part['ETag']}
                for part in parts
            ]
            
            self.s3_client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=object_key,
                UploadId=upload_id,
                MultipartUpload={'Parts': formatted_parts}
            )
            logger.info(f"Successfully completed multipart upload for {object_key} ({len(parts)} parts)")
            return True
        except ClientError as e:
            logger.error(f"Failed to complete multipart upload for {object_key}: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error completing multipart upload for {object_key}: {e}", exc_info=True)
            return False
    
    def abort_multipart_upload(self, object_key: str, upload_id: str) -> bool:
        """Abort multipart upload in R2 (cleanup on failure)
        
        Args:
            object_key: R2 object key (path in bucket)
            upload_id: Multipart upload ID from create_multipart_upload
            
        Returns:
            True if abort succeeded, False otherwise
            
        Raises:
            ValueError: If object_key or upload_id is empty
        """
        if not object_key:
            raise ValueError("object_key cannot be empty")
        if not upload_id:
            raise ValueError("upload_id cannot be empty")
        
        try:
            self.s3_client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=object_key,
                UploadId=upload_id
            )
            logger.info(f"Successfully aborted multipart upload for {object_key}")
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchUpload':
                logger.debug(f"Multipart upload already aborted or doesn't exist: {object_key}")
                return True  # Consider it success if already gone
            else:
                logger.error(f"Failed to abort multipart upload for {object_key}: {e}", exc_info=True)
                return False
        except Exception as e:
            logger.error(f"Unexpected error aborting multipart upload for {object_key}: {e}", exc_info=True)
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
