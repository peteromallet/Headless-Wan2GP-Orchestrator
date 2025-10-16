import os
import sys
import asyncio
import json
import logging
import tempfile
import base64
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

# Load environment variables from .env at import time so module-level reads work
load_dotenv()

# Configure structured logging before importing internal modules
from .logging_config import setup_logging, set_current_cycle, get_db_logging_stats
from .database import DatabaseClient

# Initial setup without database client
setup_logging()

# Import utility modules
from .storage_utils import process_external_url_result, upload_to_supabase_storage
from .task_utils import count_tasks, claim_next_task, mark_complete, mark_failed
from .wavespeed_utils import call_wavespeed_api
from .video_utils import download_video_to_temp, remove_last_frame_from_video, join_videos, extract_first_frame_bytes

CONCURRENCY = int(os.getenv("API_WORKER_CONCURRENCY", "20"))
RUN_TYPE = "api"  # Hardcoded for API workers - they process API tasks
PARENT_POLL_SEC = int(os.getenv("API_PARENT_POLL_SEC", "10"))


logger = logging.getLogger(__name__)


async def process_api_task(task: Dict[str, Any], client: httpx.AsyncClient) -> Dict[str, Any]:
    """Process Wavespeed AI tasks"""
    params = task.get("params") or {}
    task_type = task.get("task_type", "unknown")
    task_id = task.get("task_id") or task.get("id")
    
    # Parse params if it's a JSON string
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse params JSON: {e}")
            raise Exception(f"Invalid JSON in params field: {e}")
    
    if task_type == "qwen_image_edit" or params.get("api_type") == "wavespeed":
        # Check if loras are present to determine which endpoint to use
        loras = params.get("loras", [])
        has_loras = bool(loras)
        
        if has_loras:
            # Use the edit-plus-lora endpoint when loras are present
            endpoint_path = "wavespeed-ai/qwen-image/edit-plus-lora"
            logger.info(f"Calling Wavespeed API endpoint with LoRAs: {endpoint_path}")
            
            # Map parameters to match the edit-plus-lora API format
            image_url = params.get("image", "")
            wavespeed_params = {
                "enable_base64_output": params.get("enable_base64_output", False),
                "enable_sync_mode": params.get("enable_sync_mode", False),
                "images": [image_url] if image_url else [],  # API expects "images" as array
                "output_format": params.get("output_format", "jpeg"),
                "prompt": params.get("prompt", ""),
                "seed": params.get("seed", -1),
                "loras": []
            }
            
            # Add size parameter if resolution is provided
            resolution = params.get("resolution", "")
            if resolution:
                # Convert formats like "768x576" to "768*576" for the API
                size = resolution.replace("x", "*")
                wavespeed_params["size"] = size
                logger.info(f"Using resolution/size: {size}")
            
            # Map loras - support both {"url": ..., "strength": ...} and {"path": ..., "scale": ...} formats
            for lora in loras:
                if isinstance(lora, dict):
                    # Support both "url"/"strength" and "path"/"scale" formats
                    lora_url = lora.get("url") or lora.get("path", "")
                    lora_strength = lora.get("strength", lora.get("scale", 1.0))
                    
                    if lora_url:
                        wavespeed_params["loras"].append({
                            "path": lora_url,
                            "scale": float(lora_strength)
                        })
                        logger.info(f"Added LoRA: {lora_url} with strength {lora_strength}")
            
            logger.info(f"Processing with {len(wavespeed_params['loras'])} LoRAs")
        else:
            # Use the standard edit-plus endpoint without loras
            endpoint_path = params.get("wavespeed_endpoint", "wavespeed-ai/qwen-image/edit-plus")
            logger.info(f"Calling Wavespeed API endpoint: {endpoint_path}")
            
            # Map parameters to match the edit-plus API format
            image_url = params.get("image", "")
            wavespeed_params = {
                "enable_base64_output": params.get("enable_base64_output", False),
                "enable_sync_mode": params.get("enable_sync_mode", False),
                "images": [image_url] if image_url else [],  # API expects "images" as array
                "output_format": params.get("output_format", "jpeg"),
                "prompt": params.get("prompt", ""),
                "seed": params.get("seed", -1)
            }
        
        result = await call_wavespeed_api(endpoint_path, wavespeed_params, client)
        
        # Process external URL with automatic screenshot extraction for videos
        result = await process_external_url_result(client, task_id, result)
        
        logger.info(f"Processed {task_type} task via Wavespeed API")
        return result
        
    elif task_type == "qwen_image_style":
        # Wavespeed AI Qwen image style transfer with LoRA
        endpoint_path = "wavespeed-ai/qwen-image/edit-lora"
        logger.info(f"Calling Wavespeed API endpoint: {endpoint_path}")
        
        # Build the prompt with style and subject modifications
        original_prompt = params.get("prompt", "")
        modified_prompt = original_prompt
        
        # Get style and subject parameters
        style_strength = params.get("style_reference_strength", 0.0)
        subject_strength = params.get("subject_strength", 0.0)
        subject_description = params.get("subject_description", "")
        in_this_scene = params.get("in_this_scene", False)
        
        # Build prompt modifications
        prompt_parts = []
        has_style_prefix = False
        
        # Add style prefix if style_strength > 0
        if style_strength > 0.0:
            prompt_parts.append("In the style of this image,")
            has_style_prefix = True
        
        # Add subject prefix if subject_strength > 0
        if subject_strength > 0.0 and subject_description:
            # Use lowercase 'make' if style prefix is already present
            make_word = "make" if has_style_prefix else "Make"
            if in_this_scene:
                prompt_parts.append(f"{make_word} an image of this {subject_description} in this scene:")
            else:
                prompt_parts.append(f"{make_word} an image of this {subject_description}:")
        
        # Combine prompt parts with original prompt
        if prompt_parts:
            modified_prompt = " ".join(prompt_parts) + " " + original_prompt
            logger.info(f"Modified prompt from '{original_prompt}' to '{modified_prompt}'")
        
        # Determine which reference image to use (they should be the same)
        reference_image = params.get("style_reference_image") or params.get("subject_reference_image", "")
        
        # Map parameters to Wavespeed API format for style transfer
        wavespeed_params = {
            "enable_base64_output": params.get("enable_base64_output", False),
            "enable_sync_mode": params.get("enable_sync_mode", False),
            "output_format": params.get("output_format", "jpeg"),
            "prompt": modified_prompt,
            "seed": params.get("seed", -1),
            "image": reference_image,
            "model_id": params.get("model_id", "wavespeed-ai/qwen-image/edit-lora"),
            "loras": []
        }
        
        logger.info(f"Using reference image: {reference_image}")
        
        # Add LoRA configuration for style transfer
        # Use a default style transfer LoRA if style_reference_strength is provided
        if style_strength > 0.0:
            # Default style transfer LoRA path - can be overridden via params
            default_lora_path = "https://huggingface.co/peteromallet/ad_motion_loras/resolve/main/style_transfer_qwen_edit_2_000011250.safetensors"
            lora_path = params.get("style_lora_path", default_lora_path)
            
            wavespeed_params["loras"].append({
                "path": lora_path,
                "scale": float(style_strength)
            })
            logger.info(f"Added style transfer LoRA: {lora_path} with strength {style_strength}")
        
        # Add subject LoRA if subject_strength > 0
        if subject_strength > 0.0:
            # Add subject LoRA
            subject_lora_path = "https://huggingface.co/peteromallet/mystery_models/resolve/main/in_subject_qwen_edit_2_000006750.safetensors"
            wavespeed_params["loras"].append({
                "path": subject_lora_path,
                "scale": float(subject_strength)
            })
            logger.info(f"Added subject LoRA: {subject_lora_path} with strength {subject_strength}")
        
        # Add any additional LoRAs from params
        additional_loras = params.get("loras", [])
        if additional_loras:
            for lora in additional_loras:
                if isinstance(lora, dict) and "path" in lora and "scale" in lora:
                    wavespeed_params["loras"].append({
                        "path": lora["path"],
                        "scale": float(lora["scale"])
                    })
            logger.info(f"Added {len(additional_loras)} additional LoRAs")
        
        result = await call_wavespeed_api(endpoint_path, wavespeed_params, client)
        
        # Process external URL with automatic screenshot extraction for videos
        result = await process_external_url_result(client, task_id, result)
        
        logger.info(f"Processed {task_type} task via Wavespeed API")
        return result
        
    elif task_type == "wan_2_2_t2i":
        # Wavespeed AI WAN 2.2 Text-to-Image with LoRA
        endpoint_path = "wavespeed-ai/wan-2.2/text-to-image-lora"
        logger.info(f"Calling Wavespeed API endpoint: {endpoint_path}")
        
        # Extract orchestrator details or use top-level params
        orchestrator_details = params.get("orchestrator_details", {})
        effective_params = {**params, **orchestrator_details}
        
        # Map parameters to Wavespeed API format
        wavespeed_params = {
            "enable_base64_output": False,
            "enable_sync_mode": False,
            "output_format": "jpeg",
            "prompt": effective_params.get("prompt", ""),
            "seed": effective_params.get("seed", -1),
            "size": effective_params.get("resolution", "256*256").replace("x", "*"),
            "high_noise_loras": [],
            "low_noise_loras": [],
            "loras": []
        }
        
        # Extract and format LoRAs from additional_loras
        additional_loras = effective_params.get("additional_loras", {})
        if additional_loras:
            for lora_path, scale in additional_loras.items():
                wavespeed_params["loras"].append({
                    "path": lora_path,
                    "scale": float(scale)
                })
            logger.info(f"Added {len(additional_loras)} LoRAs to request")
        
        result = await call_wavespeed_api(endpoint_path, wavespeed_params, client)
        
        # Process external URL with automatic screenshot extraction for videos
        result = await process_external_url_result(client, task_id, result)
        
        logger.info(f"Processed {task_type} task via Wavespeed API")
        return result
        
    elif task_type == "animate_character":
        # Wavespeed AI WAN 2.2 Character Animation
        endpoint_path = "wavespeed-ai/wan-2.2/animate"
        logger.info(f"Processing {task_type} task via Wavespeed API endpoint: {endpoint_path}")
        
        # Extract orchestrator details or use top-level params
        orchestrator_details = params.get("orchestrator_details", {})
        effective_params = {**params, **orchestrator_details}
        
        # Map parameters to Wavespeed API format for character animation
        wavespeed_params = {
            "image": effective_params.get("character_image_url", ""),
            "mode": effective_params.get("mode", "animate"),
            "prompt": effective_params.get("prompt", ""),
            "resolution": effective_params.get("resolution", "480p"),
            "seed": effective_params.get("seed", -1),
            "video": effective_params.get("motion_video_url", "")
        }
        
        logger.info(f"Character animation params: image={wavespeed_params['image'][:50]}..., "
                   f"video={wavespeed_params['video'][:50]}..., "
                   f"mode={wavespeed_params['mode']}, "
                   f"resolution={wavespeed_params['resolution']}, "
                   f"seed={wavespeed_params['seed']}")
        
        result = await call_wavespeed_api(endpoint_path, wavespeed_params, client)
        
        # Process external URL with automatic screenshot extraction for videos
        result = await process_external_url_result(client, task_id, result)
        
        logger.info(f"Processed {task_type} task via Wavespeed API")
        return result
        
    elif task_type == "wan_2_2_i2v":
        # Wavespeed AI WAN 2.2 Image-to-Video
        logger.info(f"Processing {task_type} task via Wavespeed API")
        
        # Extract orchestrator details or use top-level params
        orchestrator_details = params.get("orchestrator_details", {})
        effective_params = {**params, **orchestrator_details}
        
        # Check if we have LoRAs to determine which endpoint to use
        additional_loras = effective_params.get("additional_loras", {})
        has_loras = bool(additional_loras)
        
        # Get input images and prompts
        input_images = effective_params.get("input_image_paths_resolved", [])
        base_prompts = effective_params.get("base_prompts_expanded", [])
        negative_prompts = effective_params.get("negative_prompts_expanded", [])
        
        # If we have more than 2 images, generate pairwise transitions and join
        if len(input_images) > 2:
            logger.info(f"Processing {len(input_images)} images as pairwise transitions")
            video_segments: list[str] = []
            num_segments = max(0, len(input_images) - 1)

            try:
                # Build per-segment videos for each consecutive image pair
                for i in range(num_segments):
                    image_url = input_images[i]
                    next_image_url = input_images[i + 1]
                    logger.info(f"Processing segment {i+1}/{num_segments}: {image_url} -> {next_image_url}")

                    # Per-segment prompts
                    prompt = base_prompts[i] if i < len(base_prompts) else (base_prompts[0] if base_prompts else "")
                    negative_prompt = negative_prompts[i] if i < len(negative_prompts) else (negative_prompts[0] if negative_prompts else "")

                    if has_loras:
                        endpoint_path = "wavespeed-ai/wan-2.2/i2v-480p-lora"
                        wavespeed_params = {
                            "duration": effective_params.get("duration", 5),
                            "high_noise_loras": [],
                            "image": image_url,
                            "last_image": next_image_url,
                            "loras": [],
                            "low_noise_loras": [],
                            "negative_prompt": negative_prompt,
                            "prompt": prompt,
                            "seed": effective_params.get("seed_base", -1) + i
                        }
                        for lora_path, scale in additional_loras.items():
                            wavespeed_params["loras"].append({"path": lora_path, "scale": float(scale)})
                    else:
                        endpoint_path = "wavespeed-ai/wan-2.2/i2v-480p"
                        wavespeed_params = {
                            "seed": effective_params.get("seed_base", -1) + i,
                            "image": image_url,
                            "last_image": next_image_url,
                            "prompt": prompt,
                            "duration": effective_params.get("duration", 5),
                            "negative_prompt": negative_prompt,
                            "model_id": "wavespeed-ai/wan-2.2/i2v-480p"
                        }

                    # Call Wavespeed for this segment
                    segment_result = await call_wavespeed_api(endpoint_path, wavespeed_params, client)

                    # Extract video URL directly from Wavespeed result
                    video_url = None
                    if isinstance(segment_result, dict):
                        if 'output_url' in segment_result:
                            video_url = segment_result['output_url']
                        elif 'url' in segment_result:
                            video_url = segment_result['url']
                        elif 'video_url' in segment_result:
                            video_url = segment_result['video_url']
                        elif 'outputs' in segment_result and segment_result['outputs']:
                            video_url = segment_result['outputs'][0]

                    if not video_url:
                        raise Exception(f"No video URL found in segment {i+1} result")

                    # Download to temp file
                    temp_video_path = await download_video_to_temp(client, video_url)
                    if not temp_video_path:
                        raise Exception(f"Failed to download video for segment {i+1}")

                    video_segments.append(temp_video_path)
                    logger.info(f"Segment {i+1}/{num_segments} ready: {temp_video_path}")

                # Remove last frame from all but the final segment and join
                if len(video_segments) > 1:
                    processed_segments: list[str] = []
                    for i, video_path in enumerate(video_segments[:-1]):
                        processed_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
                        processed_file.close()
                        if remove_last_frame_from_video(video_path, processed_file.name):
                            processed_segments.append(processed_file.name)
                            logger.info(f"Removed last frame from segment {i+1}")
                        else:
                            processed_segments.append(video_path)
                            logger.warning(f"Could not remove last frame from segment {i+1}; using original")
                    processed_segments.append(video_segments[-1])

                    final_video = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
                    final_video.close()
                    if not join_videos(processed_segments, final_video.name):
                        raise Exception("Failed to join video segments")
                    logger.info(f"Joined {len(processed_segments)} segments -> {final_video.name}")

                    # Upload final video to Supabase with first frame screenshot
                    with open(final_video.name, 'rb') as f:
                        file_bytes = f.read()
                    screenshot_bytes = extract_first_frame_bytes(file_bytes)
                    first_frame_b64 = base64.b64encode(screenshot_bytes).decode('utf-8') if screenshot_bytes else None
                    public_url = await upload_to_supabase_storage(
                        client,
                        task_id,
                        file_bytes,
                        filename=f"joined_{task_id}.mp4",
                        first_frame_data=first_frame_b64
                    )

                    # Cleanup temp files
                    for temp_path in video_segments + processed_segments:
                        try:
                            os.unlink(temp_path)
                        except Exception:
                            pass
                    try:
                        os.unlink(final_video.name)
                    except Exception:
                        pass

                    result = {
                        "output_location": public_url,
                        "output_url": public_url,
                        "segments_processed": num_segments,
                        "message": f"Successfully processed {num_segments} transitions into joined video",
                        "_task_completed_by_upload": True
                    }
                else:
                    # Degenerate case; return the only segment after uploading
                    only_path = video_segments[0]
                    with open(only_path, 'rb') as f:
                        file_bytes = f.read()
                    screenshot_bytes = extract_first_frame_bytes(file_bytes)
                    first_frame_b64 = base64.b64encode(screenshot_bytes).decode('utf-8') if screenshot_bytes else None
                    public_url = await upload_to_supabase_storage(
                        client,
                        task_id,
                        file_bytes,
                        filename=f"segment_{task_id}_0.mp4",
                        first_frame_data=first_frame_b64
                    )
                    try:
                        os.unlink(only_path)
                    except Exception:
                        pass
                    result = {
                        "output_location": public_url,
                        "output_url": public_url,
                        "segments_processed": 1,
                        "message": "Single transition processed",
                        "_task_completed_by_upload": True
                    }

            except Exception as e:
                # Clean up any temporary files on error
                for temp_path in list(locals().get('video_segments', [])):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
                raise e
        
        else:
            # Original logic for 1-2 images
            if has_loras:
                # Use LoRA endpoint: wan-2.2/i2v-480p-lora
                endpoint_path = "wavespeed-ai/wan-2.2/i2v-480p-lora"
                logger.info(f"Using LoRA endpoint: {endpoint_path}")
                
                # Map parameters to Wavespeed API format for LoRA endpoint
                wavespeed_params = {
                    "duration": effective_params.get("duration", 5),
                    "high_noise_loras": [],
                    "image": input_images[0] if input_images else "",
                    "last_image": "",
                    "loras": [],
                    "low_noise_loras": [],
                    "negative_prompt": negative_prompts[0] if negative_prompts else "",
                    "prompt": base_prompts[0] if base_prompts else "",
                    "seed": effective_params.get("seed_base", -1)
                }
                
                # Add last_image if we have multiple input images
                if len(input_images) > 1:
                    wavespeed_params["last_image"] = input_images[1]
                    logger.info(f"Using first image: {input_images[0]}")
                    logger.info(f"Using last image: {input_images[1]}")
                else:
                    logger.info(f"Using single image: {input_images[0] if input_images else 'None'}")
                
                # Add LoRAs from additional_loras
                for lora_path, scale in additional_loras.items():
                    wavespeed_params["loras"].append({
                        "path": lora_path,
                        "scale": float(scale)
                    })
                logger.info(f"Added {len(additional_loras)} LoRAs to i2v request")
                
            else:
                # Use non-LoRA endpoint: wan-2.2/i2v-480p
                endpoint_path = "wavespeed-ai/wan-2.2/i2v-480p"
                logger.info(f"Using non-LoRA endpoint: {endpoint_path}")
                
                # Map parameters to Wavespeed API format for non-LoRA endpoint
                wavespeed_params = {
                    "seed": effective_params.get("seed_base", -1),
                    "image": input_images[0] if input_images else "",
                    "prompt": base_prompts[0] if base_prompts else "",
                    "duration": effective_params.get("duration", 5),
                    "negative_prompt": negative_prompts[0] if negative_prompts else "",
                    "model_id": "wavespeed-ai/wan-2.2/i2v-480p"
                }
                
                # Set last_image to second input image if available
                if len(input_images) > 1:
                    wavespeed_params["last_image"] = input_images[1]
                    logger.info(f"Using first image: {input_images[0]}")
                    logger.info(f"Using last image (second input): {input_images[1]}")
                else:
                    wavespeed_params["last_image"] = ""
                    logger.info(f"Using single image: {input_images[0] if input_images else 'None'}")
            
            result = await call_wavespeed_api(endpoint_path, wavespeed_params, client)
            
            # Process external URL with automatic screenshot extraction for videos
            result = await process_external_url_result(client, task_id, result)
        
        logger.info(f"Processed {task_type} task via Wavespeed API")
        return result
        
    else:
        # Unsupported task type
        raise Exception(f"Unsupported task type: {task_type}. Supported types: 'qwen_image_edit', 'qwen_image_style', 'wan_2_2_t2i', 'wan_2_2_i2v', 'animate_character'.")


async def worker_loop(index: int, worker_id: str, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> None:
    # Deprecated continuous claim-per-worker loop; kept for reference
    while True:
        await asyncio.sleep(1)


def validate_api_environment():
    """Validate all required environment variables for API orchestrator."""
    logger.info("🔍 [STARTUP] Validating API orchestrator environment...")
    
    # Required environment variables
    required_vars = {
        'SUPABASE_URL': 'Supabase database URL for task management',
        'SUPABASE_SERVICE_ROLE_KEY': 'Supabase service role key for database access',
        'WAVESPEED_API_KEY': 'Wavespeed API key for processing tasks',
    }
    
    # Optional but important environment variables
    important_vars = {
        'API_WORKER_ID': 'Unique identifier for this API worker instance',
        'CONCURRENCY': 'Number of concurrent tasks to process',
        'RUN_TYPE': 'Type of tasks to process (cloud/local)',
        'PARENT_POLL_SEC': 'Polling interval for task checking',
        'LOG_LEVEL': 'Logging level (DEBUG/INFO/WARNING/ERROR)',
    }
    
    # Check required variables
    missing_required = []
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing_required.append(f"  ❌ {var}: {description}")
            logger.error(f"[STARTUP] Missing required environment variable: {var}")
        else:
            # Show partial value for security
            if 'KEY' in var or 'SECRET' in var:
                display_value = f"{value[:10]}..." if len(value) > 10 else "***"
            else:
                display_value = value
            logger.info(f"[STARTUP]   ✅ {var}: {display_value}")
    
    # Check important variables
    for var, description in important_vars.items():
        value = os.getenv(var)
        if not value:
            logger.warning(f"[STARTUP]   ⚠️  {var}: {description} (using default)")
        else:
            logger.info(f"[STARTUP]   ✅ {var}: {value}")
    
    # Report results
    if missing_required:
        logger.error("[STARTUP] ❌ CRITICAL: Missing required environment variables:")
        for msg in missing_required:
            logger.error(f"[STARTUP] {msg}")
        logger.error("[STARTUP] 🛑 Cannot start API orchestrator without required configuration!")
        return False
    
    logger.info("[STARTUP] ✅ Environment validation completed successfully")
    return True

async def main_async() -> None:
    logger.info(f"[STARTUP] API Orchestrator starting...")
    
    # Validate environment before proceeding
    if not validate_api_environment():
        logger.error("[STARTUP] 🛑 Exiting due to missing required configuration!")
        sys.exit(1)
    
    # Initialize database client for centralized logging
    try:
        db_client = DatabaseClient()
        
        # Re-initialize logging with database client if DB logging is enabled
        from .logging_config import setup_logging as reinit_logging
        reinit_logging(db_client=db_client, source_type="orchestrator_api")
        
        logger.info("[STARTUP] ✅ Centralized database logging initialized")
    except Exception as e:
        logger.warning(f"[STARTUP] ⚠️  Could not initialize database logging: {e}")
        logger.warning("[STARTUP] Continuing with console logging only...")
    
    # Log additional startup configuration
    logger.info(f"[STARTUP] CONCURRENCY: {CONCURRENCY}")
    logger.info(f"[STARTUP] RUN_TYPE: {RUN_TYPE}")
    logger.info(f"[STARTUP] PARENT_POLL_SEC: {PARENT_POLL_SEC}")

    worker_id = os.getenv("API_WORKER_ID", "api-worker-main")
    limits = httpx.Limits(max_connections=max(64, CONCURRENCY * 4), max_keepalive_connections=max(32, CONCURRENCY * 2))
    active_tasks: set[asyncio.Task] = set()

    async def spawn_task(task_payload: Dict[str, Any], client: httpx.AsyncClient):
        task_id = task_payload.get("task_id") or task_payload.get("id")
        try:
            result = await process_api_task(task_payload, client)
            
            # Check if task completion was already handled by the upload process
            if result.get("_task_completed_by_upload"):
                logger.info(f"Task {task_id} completion already handled by upload process, skipping additional mark_complete call")
            else:
                # Only call mark_complete if the upload process didn't handle it
                success = await mark_complete(client, task_id, result)
                if not success:
                    # If we can't mark the task complete, treat it as a failure to prevent stuck tasks
                    logger.error(f"Task {task_id} processed successfully but failed to save to database")
                    await mark_failed(client, task_id, "Task processed successfully but failed to save completion status to database")
        except Exception as exc:
            logger.error(f"Task {task_id} failed with exception: {exc}")
            logger.error(f"Exception type: {type(exc).__name__}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            failed_success = await mark_failed(client, task_id, str(exc))
            if not failed_success:
                logger.error(f"DOUBLE FAILURE: Task {task_id} failed AND could not mark as failed in database!")

    async with httpx.AsyncClient(limits=limits, timeout=20.0) as client:
        logger.info(f"[WORKER_LOOP] Starting worker loop for {worker_id} with RUN_TYPE: {RUN_TYPE}, CONCURRENCY: {CONCURRENCY}, POLL_SEC: {PARENT_POLL_SEC}")
        
        loop_count = 0
        while True:
            loop_count += 1
            
            # prune finished subtasks
            done = {t for t in active_tasks if t.done()}
            if done:
                logger.debug(f"[WORKER_LOOP] Pruned {len(done)} completed tasks")
                active_tasks -= done

            capacity = max(0, CONCURRENCY - len(active_tasks))
            
            # Log every 10 loops or when there's activity
            if loop_count % 10 == 1 or capacity > 0 or len(active_tasks) > 0:
                logger.info(f"[WORKER_LOOP] Loop #{loop_count}: Active tasks: {len(active_tasks)}, Capacity: {capacity}")
            
            # Log database logging stats periodically (every 100 loops)
            if loop_count % 100 == 0:
                db_stats = get_db_logging_stats()
                if db_stats:
                    logger.info(f"[WORKER_LOOP] 📊 Database logging stats: {db_stats}")
            
            if capacity > 0:
                logger.debug(f"[WORKER_LOOP] Checking for available tasks...")
                count_info = await count_tasks(client, RUN_TYPE)
                available_tasks = int(count_info.get("queued_plus_active") or 0)
                to_claim = min(capacity, available_tasks)
                
                logger.debug(f"[WORKER_LOOP] Task count result: {count_info}")
                logger.info(f"[WORKER_LOOP] Available tasks: {available_tasks}, Will attempt to claim: {to_claim}")
                
                if to_claim > 0:
                    logger.info(f"[WORKER_LOOP] Claiming {to_claim} tasks (capacity: {capacity}, available: {available_tasks})")
                    
                    claimed_count = 0
                    for i in range(to_claim):
                        logger.debug(f"[WORKER_LOOP] Attempting to claim task {i+1}/{to_claim}")
                        claimed = await claim_next_task(client, worker_id, RUN_TYPE)
                        if not claimed:
                            logger.warning(f"[WORKER_LOOP] Failed to claim task {i+1}/{to_claim} - no tasks available despite count showing {available_tasks}")
                            break
                        claimed_count += 1
                        logger.info(f"[WORKER_LOOP] Successfully claimed task {i+1}/{to_claim}: {claimed.get('task_id')}")
                        t = asyncio.create_task(spawn_task(claimed, client))
                        active_tasks.add(t)
                        
                    if claimed_count > 0:
                        logger.info(f"[WORKER_LOOP] Spawned {claimed_count} tasks")
                    elif available_tasks > 0:
                        logger.error(f"[WORKER_LOOP] CRITICAL: Could not claim any tasks despite {available_tasks} being available - check task filters and dependencies")
                elif available_tasks == 0:
                    logger.debug(f"[WORKER_LOOP] No tasks available to claim")
                else:
                    logger.debug(f"[WORKER_LOOP] No capacity to claim tasks")

            await asyncio.sleep(PARENT_POLL_SEC)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()


