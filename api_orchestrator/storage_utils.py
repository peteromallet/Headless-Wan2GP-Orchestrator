"""
Storage utilities for the API orchestrator.
Handles file downloads, uploads, and storage operations with Supabase.
"""

import os
import logging
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


async def download_url_content(client: httpx.AsyncClient, url: str) -> bytes:
    """Download content from a URL and return as bytes."""
    try:
        logger.info(f"Downloading content from: {url}")
        response = await client.get(url, timeout=60)
        response.raise_for_status()
        
        content = response.content
        logger.info(f"Downloaded {len(content)} bytes from {url}")
        return content
        
    except Exception as e:
        logger.error(f"Failed to download from {url}: {e}")
        raise


async def upload_to_supabase_storage(client: httpx.AsyncClient, task_id: str, file_data: bytes, filename: str, first_frame_data: str = None) -> str:
    """
    Upload file data to Supabase storage via the complete-task Edge Function.
    Returns the public URL of the uploaded file.
    """
    try:
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        edge_url = f"{supabase_url}/functions/v1/complete_task"
        
        if not edge_url:
            raise Exception("SUPABASE_URL not configured")
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('SUPABASE_ACCESS_TOKEN') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')}"
        }
        
        # Encode file data as base64
        file_base64 = base64.b64encode(file_data).decode('utf-8')
        
        # Sanitize filename
        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-").strip()
        if not safe_filename:
            # Fallback filename based on task_id and content type
            parsed_url = urlparse(filename) if filename else None
            ext = Path(parsed_url.path).suffix if parsed_url else ".bin"
            safe_filename = f"task_{task_id}{ext}"
        
        payload = {
            "task_id": task_id,
            "file_data": file_base64,
            "filename": safe_filename
        }
        
        # Include first frame data if provided (matching original approach)
        if first_frame_data:
            payload["first_frame_data"] = first_frame_data
        
        logger.info(f"Uploading {len(file_data)} bytes to Supabase storage as {safe_filename}")
        
        # Log payload size for debugging
        payload_size = len(str(payload).encode('utf-8'))
        logger.info(f"Total JSON payload size: {payload_size} bytes")
        if first_frame_data:
            logger.info(f"Payload includes first_frame_data of {len(first_frame_data)} chars")
        
        response = await client.post(edge_url, headers=headers, json=payload, timeout=120)
        
        # Log response details before raising for status
        logger.info(f"Upload response: status={response.status_code}, content-length={response.headers.get('content-length', 'unknown')}")
        if response.status_code != 200:
            response_text = response.text
            logger.error(f"Upload failed with status {response.status_code}: {response_text}")
            
        response.raise_for_status()
        
        result = response.json()
        
        # Extract the public URL from the response
        public_url = result.get("public_url") or result.get("output_location")
        
        if not public_url:
            raise Exception(f"No public URL returned from upload: {result}")
            
        logger.info(f"Successfully uploaded to Supabase: {public_url}")
        return public_url
        
    except Exception as e:
        logger.error(f"Failed to upload to Supabase storage: {e}")
        raise


async def download_and_upload_to_supabase(client: httpx.AsyncClient, task_id: str, external_url: str, extract_screenshot: bool = True) -> Dict[str, str]:
    """
    Download content from external URL and re-upload to Supabase storage.
    If the content is a video and extract_screenshot=True, also extracts and uploads first frame.
    Returns dict with 'url' and optionally 'screenshot_url'.
    """
    from .video_utils import is_video_file, extract_first_frame_bytes
    
    try:
        # Extract filename from URL
        parsed_url = urlparse(external_url)
        filename = Path(parsed_url.path).name
        
        # If no filename in URL, create one based on task_id
        if not filename or filename == '/':
            # Try to guess extension from Content-Type header
            head_response = await client.head(external_url, timeout=10)
            content_type = head_response.headers.get('content-type', 'application/octet-stream')
            ext = mimetypes.guess_extension(content_type) or '.bin'
            filename = f"task_{task_id}{ext}"
        
        # Download the content
        file_data = await download_url_content(client, external_url)
        
        # Check if this is a video file and extract screenshot if requested
        # Skip screenshot extraction for large files to avoid edge function limits
        MAX_FILE_SIZE_FOR_SCREENSHOT = 1024 * 1024  # 1MB limit
        first_frame_data = None
        if extract_screenshot and is_video_file(filename):
            if len(file_data) <= MAX_FILE_SIZE_FOR_SCREENSHOT:
                logger.info(f"Video detected ({len(file_data)} bytes), extracting first frame screenshot for task {task_id}")
                screenshot_bytes = extract_first_frame_bytes(file_data)
                if screenshot_bytes:
                    # Convert to base64 for inclusion in main upload (matching original approach)
                    first_frame_data = base64.b64encode(screenshot_bytes).decode('utf-8')
                    logger.info(f"First frame extracted and will be included in upload")
            else:
                logger.info(f"Video file too large ({len(file_data)} bytes > {MAX_FILE_SIZE_FOR_SCREENSHOT}), skipping screenshot extraction to avoid upload limits")
        
        # Upload to Supabase storage (with first frame data if available)
        supabase_url = await upload_to_supabase_storage(
            client, task_id, file_data, filename, first_frame_data
        )
        
        result = {"url": supabase_url}
        if first_frame_data:
            result["screenshot_included"] = True
        
        logger.info(f"Successfully migrated {external_url} -> {supabase_url}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to download and upload {external_url}: {e}")
        # Return original URL as fallback
        logger.warning(f"Falling back to original URL: {external_url}")
        return {"url": external_url}


async def process_external_url_result(client: httpx.AsyncClient, task_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a task result that contains an external URL, downloading and re-uploading to Supabase.
    Automatically extracts first frame screenshots for video files.
    Updates the result dict in place and returns it.
    """
    if not result.get("output_url"):
        return result
    
    external_url = result["output_url"]
    logger.info(f"Processing external URL for task {task_id}: {external_url}")
    
    try:
        # Download and upload with automatic screenshot extraction
        upload_result = await download_and_upload_to_supabase(client, task_id, external_url)
        
        # Update result with new URLs
        result["output_location"] = upload_result["url"]
        result["original_external_url"] = external_url
        
        # Add screenshot URL if extracted
        if "screenshot_url" in upload_result:
            result["screenshot_url"] = upload_result["screenshot_url"]
        
        logger.info(f"Successfully processed external URL for task {task_id}")
        
    except Exception as e:
        logger.error(f"Failed to process external URL {external_url} for task {task_id}: {e}")
        # Fallback to original external URL
        result["output_location"] = external_url
        result["migration_error"] = str(e)
        logger.warning(f"Using original external URL as fallback: {external_url}")
    
    return result
