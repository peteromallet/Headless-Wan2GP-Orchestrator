"""
Video processing utilities for the API orchestrator.
Handles video file detection, first frame extraction, and screenshot generation.
"""

import os
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, List

import cv2
import httpx

logger = logging.getLogger(__name__)


def is_video_file(filename: str) -> bool:
    """Check if a filename indicates a video file based on extension."""
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v', '.flv', '.wmv'}
    return Path(filename).suffix.lower() in video_extensions


def save_frame_from_video(video_path: Path, frame_index: int, output_image_path: Path, resolution: tuple[int, int]) -> bool:
    """
    Extracts a specific frame from video and saves as image.
    Matches the original travel_between_images.py implementation.
    """
    if not video_path.exists() or video_path.stat().st_size == 0:
        logger.error(f"Video file not found or empty: {video_path}")
        return False

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.error(f"Could not open video file: {video_path}")
        return False

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Support negative indexing (e.g., -1 for last frame)
    if frame_index < 0:
        frame_index = total_frames + frame_index

    if frame_index < 0 or frame_index >= total_frames:
        logger.error(f"Frame index {frame_index} out of bounds (total: {total_frames})")
        cap.release()
        return False

    # Seek to specific frame and extract
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index))
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        logger.error(f"Could not read frame {frame_index}")
        return False

    try:
        # Resize frame if needed (matching original implementation)
        if frame.shape[1] != resolution[0] or frame.shape[0] != resolution[1]:
            frame = cv2.resize(frame, resolution, interpolation=cv2.INTER_AREA)
        
        # Save frame as image
        output_image_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_image_path), frame)
        logger.info(f"Successfully saved frame {frame_index} to {output_image_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving frame: {e}")
        return False


def extract_first_frame_bytes(video_data: bytes) -> Optional[bytes]:
    """
    Extract the first frame from video data and return it as PNG bytes.
    Uses the save_frame_from_video function to match original implementation.
    """
    try:
        # Create temporary file for video processing
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_video:
            temp_video.write(video_data)
            temp_video_path = temp_video.name

        try:
            # Get video dimensions first (matching original approach)
            cap = cv2.VideoCapture(temp_video_path)
            if not cap.isOpened():
                logger.error("Could not open video file for first frame extraction")
                return None
                
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            
            if width <= 0 or height <= 0:
                logger.error("Invalid video dimensions")
                return None

            # Create temporary file for screenshot
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_screenshot:
                temp_screenshot_path = temp_screenshot.name

            try:
                # Use the original-style function to extract frame
                if save_frame_from_video(Path(temp_video_path), 0, Path(temp_screenshot_path), (width, height)):
                    # Read screenshot data
                    with open(temp_screenshot_path, 'rb') as f:
                        screenshot_data = f.read()
                    return screenshot_data
                else:
                    return None

            finally:
                # Clean up temporary screenshot file
                try:
                    os.unlink(temp_screenshot_path)
                except Exception:
                    pass

        finally:
            # Clean up temporary video file
            try:
                os.unlink(temp_video_path)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Failed to extract first frame from video: {e}")
        return None


def remove_last_frame_from_video(video_path: str, output_path: str) -> bool:
    """
    Remove the last frame from a video using ffmpeg.
    Returns True if successful, False otherwise.
    """
    try:
        # Get video info to determine frame count
        probe_cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-count_frames', '-show_entries', 'stream=nb_frames',
            '-of', 'csv=p=0', video_path
        ]
        
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        total_frames = int(result.stdout.strip())
        
        if total_frames <= 1:
            logger.warning(f"Video has {total_frames} frames, cannot remove last frame")
            return False
        
        # Remove last frame using ffmpeg
        frames_to_keep = total_frames - 1
        cmd = [
            'ffmpeg', '-i', video_path, '-vf', f'select=lt(n\\,{frames_to_keep})',
            '-vsync', 'vfr', '-y', output_path
        ]
        
        subprocess.run(cmd, capture_output=True, check=True)
        logger.info(f"Successfully removed last frame from {video_path}, saved to {output_path}")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error removing last frame: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Error removing last frame from video: {e}")
        return False


def join_videos(video_paths: List[str], output_path: str) -> bool:
    """
    Join multiple videos together using ffmpeg concat filter.
    Returns True if successful, False otherwise.
    """
    if not video_paths:
        logger.error("No video paths provided for joining")
        return False
    
    if len(video_paths) == 1:
        # Just copy the single video
        try:
            subprocess.run(['cp', video_paths[0], output_path], check=True)
            logger.info(f"Single video copied to {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error copying single video: {e}")
            return False
    
    try:
        # Create filter complex for concatenation
        filter_parts = []
        for i in range(len(video_paths)):
            filter_parts.append(f"[{i}:v]")
        
        filter_complex = f"{''.join(filter_parts)}concat=n={len(video_paths)}:v=1:a=0[outv]"
        
        # Build ffmpeg command
        cmd = ['ffmpeg']
        for video_path in video_paths:
            cmd.extend(['-i', video_path])
        
        cmd.extend([
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-y', output_path
        ])
        
        subprocess.run(cmd, capture_output=True, check=True)
        logger.info(f"Successfully joined {len(video_paths)} videos to {output_path}")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error joining videos: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Error joining videos: {e}")
        return False


async def download_video_to_temp(client: httpx.AsyncClient, video_url: str) -> Optional[str]:
    """
    Download a video from URL to a temporary file.
    Returns the temporary file path if successful, None otherwise.
    """
    try:
        response = await client.get(video_url)
        response.raise_for_status()
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        temp_file.write(response.content)
        temp_file.close()
        
        logger.info(f"Downloaded video from {video_url} to {temp_file.name}")
        return temp_file.name
        
    except Exception as e:
        logger.error(f"Error downloading video from {video_url}: {e}")
        return None
