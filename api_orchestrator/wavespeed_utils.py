"""
Wavespeed AI API utilities for the API orchestrator.
Handles API calls, polling, and response processing for Wavespeed AI services.
"""

import os
import asyncio
import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


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
    
    # Log the request details for debugging
    logger.info(f"Wavespeed API request to {submit_url}")
    logger.info(f"Request payload: {payload}")
    
    # Submit the task
    begin_time = asyncio.get_event_loop().time()
    resp = await client.post(submit_url, headers=headers, json=payload, timeout=30)
    
    # Log response details before raising for status
    if resp.status_code != 200:
        error_text = resp.text
        logger.error(f"Wavespeed API error {resp.status_code}: {error_text}")
        logger.error(f"Request URL: {submit_url}")
        logger.error(f"Request payload: {payload}")
    
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
