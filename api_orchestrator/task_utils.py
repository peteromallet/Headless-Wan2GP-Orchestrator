"""
Task management utilities for the API orchestrator.
Handles task claiming, completion, status updates, and task counting.
"""

import os
import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


def _get_supabase_edge_urls() -> Dict[str, str]:
    """Get Supabase edge function URLs for task operations."""
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    return {
        "claim": f"{base_url}/functions/v1/claim-next-task" if base_url else "",
        "complete": f"{base_url}/functions/v1/mark-task-complete" if base_url else "",
        "fail": f"{base_url}/functions/v1/mark-task-failed" if base_url else "",
    }


def _auth_headers() -> Dict[str, str]:
    """Get authentication headers for Supabase requests."""
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

        payload: Dict[str, Any] = {"include_active": False}
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
            # For API workers, only consider queued tasks as claimable
            available_count = int(totals.get("queued_only", totals.get("queued_plus_active", 0)))
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
    """Claim the next available task for processing."""
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
            
        logger.info(f"Attempting to mark task {task_id} complete via {edge_url}")
        logger.debug(f"Payload: {payload}")
        
        resp = await client.post(edge_url, json=payload, headers=headers, timeout=30)
        
        # Log response details for debugging
        logger.info(f"Mark complete response: status={resp.status_code}, headers={dict(resp.headers)}")
        if resp.status_code != 200:
            response_text = resp.text
            logger.error(f"Mark complete failed with status {resp.status_code}: {response_text}")
            
        resp.raise_for_status()
        
        # Log response body for successful requests too
        try:
            response_json = resp.json()
            logger.info(f"Task {task_id} marked complete successfully: {response_json}")
        except:
            logger.info(f"Task {task_id} marked complete (no JSON response)")
            
        return True
        
    except Exception as exc:
        logger.error(f"Failed to mark task {task_id} complete: {exc}")
        logger.error(f"Exception type: {type(exc).__name__}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
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
        
        logger.info(f"Attempting to mark task {task_id} failed via {edge_url}")
        logger.debug(f"Payload: {payload}")
        
        resp = await client.post(edge_url, json=payload, headers=headers, timeout=30)
        
        # Log response details for debugging
        logger.info(f"Mark failed response: status={resp.status_code}, headers={dict(resp.headers)}")
        if resp.status_code != 200:
            response_text = resp.text
            logger.error(f"Mark failed failed with status {resp.status_code}: {response_text}")
            
        resp.raise_for_status()
        
        # Log response body for successful requests too
        try:
            response_json = resp.json()
            logger.info(f"Task {task_id} marked failed successfully: {response_json}")
        except:
            logger.info(f"Task {task_id} marked failed (no JSON response)")
            
        return True
        
    except Exception as exc:
        logger.error(f"Failed to mark task {task_id} as failed: {exc}")
        logger.error(f"Exception type: {type(exc).__name__}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False


async def mark_complete(client: httpx.AsyncClient, task_id: str, result: Dict[str, Any]) -> bool:
    """Mark task complete - wrapper for backward compatibility"""
    output_location = result.get("output_location")
    success = await mark_complete_via_edge_function(client, task_id, output_location)
    if not success:
        logger.error(f"CRITICAL: Failed to mark task {task_id} as complete in database - task may remain stuck!")
        logger.error(f"Task result that failed to save: {result}")
    return success


async def mark_failed(client: httpx.AsyncClient, task_id: str, error_message: str) -> bool:
    """Mark task failed - wrapper for backward compatibility"""
    success = await mark_failed_via_edge_function(client, task_id, error_message)
    if not success:
        logger.error(f"CRITICAL: Failed to mark task {task_id} as failed in database - task may remain stuck!")
        logger.error(f"Error message that failed to save: {error_message}")
    return success
