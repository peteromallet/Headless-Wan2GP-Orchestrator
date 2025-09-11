import os
import asyncio
import json
import logging
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

# Import utility modules
from .storage_utils import process_external_url_result
from .task_utils import count_tasks, claim_next_task, mark_complete, mark_failed
from .wavespeed_utils import call_wavespeed_api


# Load environment variables from .env at import time so module-level reads work
load_dotenv()

CONCURRENCY = int(os.getenv("API_WORKER_CONCURRENCY", "20"))
RUN_TYPE = os.getenv("API_RUN_TYPE", "api")  # one of: api|gpu|unset
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
        # Wavespeed AI image editing
        # Use the correct Wavespeed endpoint for Qwen image editing with LoRA
        endpoint_path = params.get("wavespeed_endpoint", "wavespeed-ai/qwen-image/edit-lora")
        logger.info(f"Calling Wavespeed API endpoint: {endpoint_path}")
        result = await call_wavespeed_api(endpoint_path, params, client)
        
        # Process external URL with automatic screenshot extraction for videos
        result = await process_external_url_result(client, task_id, result)
        
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
        
    elif task_type == "wan_2_2_i2v":
        # Wavespeed AI WAN 2.2 Image-to-Video
        logger.info(f"Processing {task_type} task via Wavespeed API")
        
        # Extract orchestrator details or use top-level params
        orchestrator_details = params.get("orchestrator_details", {})
        effective_params = {**params, **orchestrator_details}
        
        # Check if we have LoRAs to determine which endpoint to use
        additional_loras = effective_params.get("additional_loras", {})
        has_loras = bool(additional_loras)
        
        if has_loras:
            # Use LoRA endpoint: wan-2.2/i2v-480p-lora
            endpoint_path = "wavespeed-ai/wan-2.2/i2v-480p-lora"
            logger.info(f"Using LoRA endpoint: {endpoint_path}")
            
            # Map parameters to Wavespeed API format for LoRA endpoint
            input_images = effective_params.get("input_image_paths_resolved", [])
            
            wavespeed_params = {
                "duration": effective_params.get("duration", 5),
                "high_noise_loras": [],
                "image": input_images[0] if input_images else "",
                "last_image": "",
                "loras": [],
                "low_noise_loras": [],
                "negative_prompt": effective_params.get("negative_prompts_expanded", [""])[0] if effective_params.get("negative_prompts_expanded") else "",
                "prompt": effective_params.get("base_prompts_expanded", [""])[0] if effective_params.get("base_prompts_expanded") else "",
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
            input_images = effective_params.get("input_image_paths_resolved", [])
            
            wavespeed_params = {
                "seed": effective_params.get("seed_base", -1),
                "image": input_images[0] if input_images else "",
                "prompt": effective_params.get("base_prompts_expanded", [""])[0] if effective_params.get("base_prompts_expanded") else "",
                "duration": effective_params.get("duration", 5),
                "negative_prompt": effective_params.get("negative_prompts_expanded", [""])[0] if effective_params.get("negative_prompts_expanded") else "",
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
        raise Exception(f"Unsupported task type: {task_type}. Supported types: 'qwen_image_edit', 'qwen_image_style', 'wan_2_2_t2i', 'wan_2_2_i2v'.")


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


