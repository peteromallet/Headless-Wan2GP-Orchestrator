import os
import asyncio
import json
import logging
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv


# Load environment variables from .env at import time so module-level reads work
load_dotenv()

CONCURRENCY = int(os.getenv("API_WORKER_CONCURRENCY", "20"))
RUN_TYPE = os.getenv("API_RUN_TYPE", "api")  # one of: api|gpu|unset
PARENT_POLL_SEC = int(os.getenv("API_PARENT_POLL_SEC", "10"))


logger = logging.getLogger(__name__)


def _get_supabase_edge_urls() -> Dict[str, str]:
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    return {
        "claim": f"{base_url}/functions/v1/claim-next-task" if base_url else "",
        "complete": f"{base_url}/functions/v1/mark-task-complete" if base_url else "",
        "fail": f"{base_url}/functions/v1/mark-task-failed" if base_url else "",
    }


def _auth_headers() -> Dict[str, str]:
    token = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ACCESS_TOKEN")
    return {
        "Authorization": f"Bearer {token}" if token else "",
        "Content-Type": "application/json",
    }


async def count_tasks(client: httpx.AsyncClient, run_type: Optional[str]) -> Dict[str, Any]:
    """Count tasks using the new task-counts endpoint."""
    try:
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        task_counts_url = f"{supabase_url}/functions/v1/task-counts"
        
        if not supabase_url:
            logger.error("SUPABASE_URL not configured")
            return {"queued_plus_active": 0, "raw": None}
        
        headers = _auth_headers()
        if not headers["Authorization"]:
            logger.error("Missing authentication token")
            return {"queued_plus_active": 0, "raw": None}

        payload: Dict[str, Any] = {}
        if run_type:
            payload["run_type"] = run_type

        resp = await client.post(task_counts_url, headers=headers, json=payload, timeout=15)
        
        if resp.status_code != 200:
            logger.warning(f"Task counts failed with status {resp.status_code}")
            return {"queued_plus_active": 0, "raw": None}
            
        data = resp.json()
        
        # Extract the counts from the new endpoint format
        # Assuming it returns the same structure as the old endpoint
        if "totals" in data:
            totals = data["totals"]
            available_count = int(totals.get("queued_plus_active", 0))
        else:
            # Fallback: look for common count fields
            available_count = int(data.get("queued_plus_active", data.get("available_tasks", 0)))
        
        logger.info(f"Available tasks: {available_count}")
        return {"queued_plus_active": available_count, "raw": data}
        
    except Exception as e:
        logger.error(f"Count tasks failed: {e}")
        return {"queued_plus_active": 0, "raw": None}


_missing_env_logged = False


async def claim_next_task(client: httpx.AsyncClient, worker_id: str, run_type: Optional[str]) -> Optional[Dict[str, Any]]:
    urls = _get_supabase_edge_urls()
    headers = _auth_headers()
    if not urls["claim"] or not headers["Authorization"]:
        global _missing_env_logged
        if not _missing_env_logged:
            logger.error("Missing SUPABASE_URL or token; cannot claim tasks")
            _missing_env_logged = True
        await asyncio.sleep(1)
        return None

    payload: Dict[str, Any] = {"worker_id": worker_id}
    if run_type:
        payload["run_type"] = run_type
    try:
        resp = await client.post(urls["claim"], headers=headers, json=payload, timeout=15)
        
        if resp.status_code == 204:
            logger.debug("No tasks available to claim (204)")
            return None
            
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Claimed task: {data.get('task_id')} ({data.get('task_type')})")
        
        # No task type filtering - process any task with matching run_type
        # The run_type filtering is handled by the edge function
            
        return data
    except Exception as exc:
        logger.warning(f"Claim failed: {exc}")
        await asyncio.sleep(0.5)
        return None


async def mark_complete_via_edge_function(client: httpx.AsyncClient, task_id: str, output_location: str = None) -> bool:
    """Mark task complete via update-task-status edge function"""
    try:
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        edge_url = (
            os.getenv("SUPABASE_EDGE_UPDATE_TASK_URL") 
            or (f"{supabase_url}/functions/v1/update-task-status" if supabase_url else None)
        )
        
        if not edge_url:
            logger.error(f"No update-task-status edge URL configured")
            return False
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('SUPABASE_ACCESS_TOKEN') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')}"
        }
        
        payload = {
            "task_id": task_id,
            "status": "Complete"
        }
        if output_location:
            payload["output_location"] = output_location
            
        resp = await client.post(edge_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        logger.info(f"Task {task_id} marked complete")
        return True
        
    except Exception as exc:
        logger.error(f"Failed to mark task {task_id} complete: {exc}")
        return False


async def mark_failed_via_edge_function(client: httpx.AsyncClient, task_id: str, error_message: str) -> bool:
    """Mark task failed via update-task-status edge function"""
    try:
        supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        edge_url = (
            os.getenv("SUPABASE_EDGE_UPDATE_TASK_URL")
            or (f"{supabase_url}/functions/v1/update-task-status" if supabase_url else None)
        )
        
        if not edge_url:
            logger.error(f"No update-task-status edge URL configured")
            return False
            
        headers = {
            "Content-Type": "application/json", 
            "Authorization": f"Bearer {os.getenv('SUPABASE_ACCESS_TOKEN') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')}"
        }
        
        payload = {
            "task_id": task_id,
            "status": "Failed",
            "output_location": error_message[:500]  # Truncate long error messages
        }
        
        resp = await client.post(edge_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        logger.info(f"Task {task_id} marked failed")
        return True
        
    except Exception as exc:
        logger.error(f"Failed to mark task {task_id} as failed: {exc}")
        return False


async def mark_complete(client: httpx.AsyncClient, task_id: str, result: Dict[str, Any]) -> None:
    """Mark task complete - wrapper for backward compatibility"""
    output_location = result.get("output_location")
    await mark_complete_via_edge_function(client, task_id, output_location)


async def mark_failed(client: httpx.AsyncClient, task_id: str, error_message: str) -> None:
    """Mark task failed - wrapper for backward compatibility"""
    await mark_failed_via_edge_function(client, task_id, error_message)


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


async def upload_to_supabase_storage(client: httpx.AsyncClient, task_id: str, file_data: bytes, filename: str) -> str:
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
        
        logger.info(f"Uploading {len(file_data)} bytes to Supabase storage as {safe_filename}")
        
        response = await client.post(edge_url, headers=headers, json=payload, timeout=120)
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


async def download_and_upload_to_supabase(client: httpx.AsyncClient, task_id: str, external_url: str) -> str:
    """
    Download content from external URL and re-upload to Supabase storage.
    Returns the new Supabase public URL.
    """
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
        
        # Upload to Supabase storage
        supabase_url = await upload_to_supabase_storage(client, task_id, file_data, filename)
        
        logger.info(f"Successfully migrated {external_url} -> {supabase_url}")
        return supabase_url
        
    except Exception as e:
        logger.error(f"Failed to download and upload {external_url}: {e}")
        # Return original URL as fallback
        logger.warning(f"Falling back to original URL: {external_url}")
        return external_url


async def call_wavespeed_api(endpoint_path: str, params: Dict[str, Any], client: httpx.AsyncClient) -> Dict[str, Any]:
    """Call Wavespeed AI API with async polling for results"""
    api_key = os.getenv("WAVESPEED_API_KEY")
    if not api_key:
        raise Exception("WAVESPEED_API_KEY not found in environment")
    
    base_url = "https://api.wavespeed.ai/api/v3"
    submit_url = f"{base_url}/{endpoint_path}"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    
    # Build payload from params with sensible defaults
    payload = {
        "enable_base64_output": params.get("enable_base64_output", False),
        "enable_sync_mode": params.get("enable_sync_mode", False),
        "output_format": params.get("output_format", "jpeg"),
        **{k: v for k, v in params.items() if k not in ["enable_base64_output", "enable_sync_mode", "output_format"]}
    }
    
    # Submit the task
    begin_time = asyncio.get_event_loop().time()
    resp = await client.post(submit_url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    
    submit_result = resp.json()
    logger.debug(f"Wavespeed submission response: {submit_result}")
    if submit_result.get("code") != 200:
        logger.error(f"Wavespeed submission failed with response: {submit_result}")
        raise Exception(f"Wavespeed submission failed: {submit_result.get('message', 'Unknown error')}")
    
    data = submit_result["data"]
    request_id = data["id"]
    logger.info(f"Wavespeed task submitted: {request_id}")
    
    # Poll for results
    poll_url = f"{base_url}/predictions/{request_id}/result"
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    
    max_wait_time = params.get("max_wait_seconds", 300)  # 5 minute default timeout
    poll_interval = 0.5  # Start with 0.5s polling
    
    while True:
        elapsed = asyncio.get_event_loop().time() - begin_time
        if elapsed > max_wait_time:
            raise Exception(f"Wavespeed task {request_id} timed out after {max_wait_time}s")
        
        resp = await client.get(poll_url, headers=poll_headers, timeout=15)
        resp.raise_for_status()
        
        poll_result = resp.json()
        logger.debug(f"Wavespeed poll response: {poll_result}")
        if poll_result.get("code") != 200:
            logger.error(f"Wavespeed polling failed with response: {poll_result}")
            raise Exception(f"Wavespeed polling failed: {poll_result.get('message', 'Unknown error')}")
        
        data = poll_result["data"]
        status = data["status"]
        logger.debug(f"Wavespeed task {request_id} status: {status}")
        
        if status == "completed":
            end_time = asyncio.get_event_loop().time()
            duration = end_time - begin_time
            output_url = data["outputs"][0] if data.get("outputs") else None
            logger.info(f"Wavespeed task {request_id} completed in {duration:.2f}s, output: {output_url}")
            return {
                "request_id": request_id,
                "status": "completed",
                "output_url": output_url,
                "outputs": data.get("outputs", []),
                "duration_seconds": duration,
                "timings": data.get("timings", {}),
                "has_nsfw_contents": data.get("has_nsfw_contents")
            }
        elif status == "failed":
            error_msg = data.get("error", "Unknown error")
            raise Exception(f"Wavespeed task {request_id} failed: {error_msg}")
        else:
            # Still processing, wait before next poll
            await asyncio.sleep(poll_interval)
            # Gradually increase poll interval to be nice to API
            poll_interval = min(poll_interval * 1.1, 5.0)





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
        # Wavespeed AI image editing
        # Use the correct Wavespeed endpoint for Qwen image editing with LoRA
        endpoint_path = params.get("wavespeed_endpoint", "wavespeed-ai/qwen-image/edit-lora")
        logger.info(f"Calling Wavespeed API endpoint: {endpoint_path}")
        result = await call_wavespeed_api(endpoint_path, params, client)
        
        # Download and re-upload to Supabase if we got an external URL
        if result.get("output_url"):
            external_url = result["output_url"]
            logger.info(f"Downloaded external URL, re-uploading to Supabase: {external_url}")
            
            try:
                # Download from external URL and upload to Supabase
                supabase_url = await download_and_upload_to_supabase(client, task_id, external_url)
                result["output_location"] = supabase_url
                
                # Keep the original URL for reference
                result["original_external_url"] = external_url
                
                logger.info(f"Successfully migrated to Supabase storage: {supabase_url}")
                
            except Exception as e:
                logger.error(f"Failed to migrate {external_url} to Supabase: {e}")
                # Fallback to original external URL
                result["output_location"] = external_url
                result["migration_error"] = str(e)
                logger.warning(f"Using original external URL as fallback: {external_url}")
        
        logger.info(f"Processed {task_type} task via Wavespeed API")
        return result
        
    elif task_type == "qwen_image_style":
        # Wavespeed AI Qwen image style transfer with LoRA
        endpoint_path = "wavespeed-ai/qwen-image/edit-lora"
        logger.info(f"Calling Wavespeed API endpoint: {endpoint_path}")
        
        # Map parameters to Wavespeed API format for style transfer
        wavespeed_params = {
            "enable_base64_output": params.get("enable_base64_output", False),
            "enable_sync_mode": params.get("enable_sync_mode", False),
            "output_format": params.get("output_format", "jpeg"),
            "prompt": params.get("prompt", ""),
            "seed": params.get("seed", -1),
            "image": params.get("style_reference_image", ""),
            "model_id": params.get("model_id", "wavespeed-ai/qwen-image/edit-lora"),
            "loras": []
        }
        
        # Add LoRA configuration for style transfer
        # Use a default style transfer LoRA if style_reference_strength is provided
        style_strength = params.get("style_reference_strength", 1.0)
        if style_strength and params.get("style_reference_image"):
            # Default style transfer LoRA path - can be overridden via params
            default_lora_path = "https://huggingface.co/peteromallet/ad_motion_loras/resolve/main/style_transfer_qwen_edit_2_000011250.safetensors"
            lora_path = params.get("style_lora_path", default_lora_path)
            
            wavespeed_params["loras"].append({
                "path": lora_path,
                "scale": float(style_strength)
            })
            logger.info(f"Added style transfer LoRA: {lora_path} with strength {style_strength}")
        
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
        
        # Download and re-upload to Supabase if we got an external URL
        if result.get("output_url"):
            external_url = result["output_url"]
            logger.info(f"Downloaded external URL, re-uploading to Supabase: {external_url}")
            
            try:
                # Download from external URL and upload to Supabase
                supabase_url = await download_and_upload_to_supabase(client, task_id, external_url)
                result["output_location"] = supabase_url
                
                # Keep the original URL for reference
                result["original_external_url"] = external_url
                
                logger.info(f"Successfully migrated to Supabase storage: {supabase_url}")
                
            except Exception as e:
                logger.error(f"Failed to migrate {external_url} to Supabase: {e}")
                # Fallback to original external URL
                result["output_location"] = external_url
                result["migration_error"] = str(e)
                logger.warning(f"Using original external URL as fallback: {external_url}")
        
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
        
        # Download and re-upload to Supabase if we got an external URL
        if result.get("output_url"):
            external_url = result["output_url"]
            logger.info(f"Downloaded external URL, re-uploading to Supabase: {external_url}")
            
            try:
                # Download from external URL and upload to Supabase
                supabase_url = await download_and_upload_to_supabase(client, task_id, external_url)
                result["output_location"] = supabase_url
                
                # Keep the original URL for reference
                result["original_external_url"] = external_url
                
                logger.info(f"Successfully migrated to Supabase storage: {supabase_url}")
                
            except Exception as e:
                logger.error(f"Failed to migrate {external_url} to Supabase: {e}")
                # Fallback to original external URL
                result["output_location"] = external_url
                result["migration_error"] = str(e)
                logger.warning(f"Using original external URL as fallback: {external_url}")
        
        logger.info(f"Processed {task_type} task via Wavespeed API")
        return result
        
    else:
        # Unsupported task type
        raise Exception(f"Unsupported task type: {task_type}. Supported types: 'qwen_image_edit', 'qwen_image_style', 'wan_2_2_t2i'.")


async def worker_loop(index: int, worker_id: str, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> None:
    # Deprecated continuous claim-per-worker loop; kept for reference
    while True:
        await asyncio.sleep(1)


async def main_async() -> None:
    # Minimal logging setup
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

    worker_id = os.getenv("API_WORKER_ID", "api-worker-main")
    limits = httpx.Limits(max_connections=max(64, CONCURRENCY * 4), max_keepalive_connections=max(32, CONCURRENCY * 2))
    active_tasks: set[asyncio.Task] = set()

    async def spawn_task(task_payload: Dict[str, Any], client: httpx.AsyncClient):
        task_id = task_payload.get("task_id") or task_payload.get("id")
        try:
            result = await process_api_task(task_payload, client)
            await mark_complete(client, task_id, result)
        except Exception as exc:
            logger.error(f"Task {task_id} failed with exception: {exc}")
            logger.error(f"Exception type: {type(exc).__name__}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            await mark_failed(client, task_id, str(exc))

    async with httpx.AsyncClient(limits=limits, timeout=20.0) as client:
        while True:
            # prune finished subtasks
            done = {t for t in active_tasks if t.done()}
            if done:
                active_tasks -= done

            capacity = max(0, CONCURRENCY - len(active_tasks))
            
            if capacity > 0:
                count_info = await count_tasks(client, RUN_TYPE)
                available_tasks = int(count_info.get("queued_plus_active") or 0)
                to_claim = min(capacity, available_tasks)
                
                if to_claim > 0:
                    logger.info(f"Claiming {to_claim} tasks (capacity: {capacity}, available: {available_tasks})")
                    
                    claimed_count = 0
                    for i in range(to_claim):
                        claimed = await claim_next_task(client, worker_id, RUN_TYPE)
                        if not claimed:
                            logger.warning(f"Failed to claim task {i+1}/{to_claim} - no tasks available despite count showing {available_tasks}")
                            break
                        claimed_count += 1
                        t = asyncio.create_task(spawn_task(claimed, client))
                        active_tasks.add(t)
                        
                    if claimed_count > 0:
                        logger.info(f"Spawned {claimed_count} tasks")
                    elif available_tasks > 0:
                        logger.warning(f"Could not claim any tasks despite {available_tasks} being available - check task filters and dependencies")

            await asyncio.sleep(PARENT_POLL_SEC)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()


