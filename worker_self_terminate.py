"""
Worker Self-Terminate Utility

Simple function for GPU workers to mark themselves for termination when they encounter fatal errors.
Updates Supabase to mark worker as error and reset task. The orchestrator handles actual termination.

How it works:
1. Worker marks itself as 'error' in database
2. Worker resets current task to 'Queued'
3. Orchestrator detects error status and terminates the RunPod pod

Usage:
    from worker_self_terminate import self_terminate_worker
    
    # When you encounter a fatal error:
    self_terminate_worker(
        worker_id="gpu-20251006_030808-958ba804",
        task_id="8755aa83-a502-4089-990d-df4414f90d58",
        error_reason="CUDA driver initialization failed, you might not have a CUDA gpu.",
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
"""

import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def self_terminate_worker(
    worker_id: str,
    task_id: str,
    error_reason: str,
    supabase_url: str,
    supabase_key: str,
) -> bool:
    """
    Mark worker for termination when it encounters a fatal error.
    
    This function:
    1. Marks the worker as 'error' in Supabase
    2. Resets the task back to 'Queued' status
    3. Orchestrator will detect error status and terminate the RunPod pod
    
    The orchestrator's error cleanup runs every cycle and will:
    - Detect the error status
    - Terminate the RunPod pod
    - Clean up worker state
    
    Args:
        worker_id: The worker's unique ID (e.g., "gpu-20251006_030808-958ba804")
        task_id: The current task ID that failed
        error_reason: Description of the fatal error
        supabase_url: Supabase project URL
        supabase_key: Supabase service role key or JWT token
    
    Returns:
        bool: True if marking was successful, False otherwise
    
    Example:
        >>> self_terminate_worker(
        ...     worker_id="gpu-20251006_030808-958ba804",
        ...     task_id="8755aa83-a502-4089-990d-df4414f90d58",
        ...     error_reason="CUDA driver initialization failed",
        ...     supabase_url=os.getenv("SUPABASE_URL"),
        ...     supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        ... )
        True
    """
    try:
        from supabase import create_client
    except ImportError as e:
        logger.error(f"Missing required library: {e}")
        logger.error("Install with: pip install supabase")
        return False
    
    logger.info(f"🔄 Self-terminating worker {worker_id}")
    logger.info(f"   Task: {task_id}")
    logger.info(f"   Reason: {error_reason}")
    
    try:
        # Initialize Supabase client
        supabase = create_client(supabase_url, supabase_key)
        
        # 1. Get worker info to retrieve RunPod ID
        logger.info("📊 Fetching worker information...")
        worker_response = supabase.table('workers').select('id, metadata').eq('id', worker_id).single().execute()
        
        if not worker_response.data:
            logger.error(f"❌ Worker {worker_id} not found in database")
            return False
        
        worker = worker_response.data
        runpod_id = worker.get('metadata', {}).get('runpod_id')
        
        if not runpod_id:
            logger.warning(f"⚠️  Worker {worker_id} has no RunPod ID in metadata")
        else:
            logger.info(f"   RunPod ID: {runpod_id}")
        
        # 2. Mark worker as error
        logger.info("🔴 Marking worker as error...")
        error_time = datetime.now(timezone.utc).isoformat()
        
        update_response = supabase.table('workers').update({
            'status': 'error',
            'metadata': {
                **worker.get('metadata', {}),
                'error_reason': error_reason,
                'error_time': error_time,
                'self_terminated': True,
            }
        }).eq('id', worker_id).execute()
        
        if update_response.data:
            logger.info(f"   ✅ Worker marked as error")
        else:
            logger.error(f"   ❌ Failed to mark worker as error")
            return False
        
        # 3. Reset task to Queued
        logger.info(f"🔄 Resetting task {task_id} to Queued...")
        
        task_response = supabase.table('tasks').update({
            'status': 'Queued',
            'worker_id': None,
            'generation_started_at': None,
            'error_details': error_reason,
        }).eq('id', task_id).eq('worker_id', worker_id).eq('status', 'In Progress').execute()
        
        if task_response.data:
            logger.info(f"   ✅ Task reset to Queued")
        else:
            logger.warning(f"   ⚠️  Task may not have been reset (already completed or not assigned to this worker)")
        
        # 4. Worker marked as error - orchestrator will terminate the pod
        logger.info(f"✅ Worker marked for termination")
        logger.info(f"   Orchestrator will terminate RunPod pod {runpod_id if runpod_id else 'UNKNOWN'}")
        logger.info(f"   Expected termination: within 10 minutes (ERROR_CLEANUP_GRACE_PERIOD)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Self-termination failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def is_fatal_gpu_error(exception: Exception) -> bool:
    """
    Determine if an exception represents a fatal GPU error that requires termination.
    
    Args:
        exception: The exception to check
    
    Returns:
        bool: True if this is a fatal error requiring termination
    
    Examples of fatal errors:
        - CUDA initialization failures
        - GPU not found/not available
        - CUDA driver version mismatches
    """
    error_str = str(exception).lower()
    
    fatal_patterns = [
        "cuda driver initialization failed",
        "no cuda-capable device",
        "cuda not available",
        "cuda runtime error",
        "gpu not available",
        "cudnn not available",
        "cannot initialize cuda",
        "cuda driver version is insufficient",
        "cuda error",
    ]
    
    return any(pattern in error_str for pattern in fatal_patterns)


# Example usage
if __name__ == "__main__":
    import os
    import sys
    
    # Example: Check CUDA at startup and self-terminate if unavailable
    try:
        import torch
        
        worker_id = os.getenv("WORKER_ID")
        task_id = os.getenv("CURRENT_TASK_ID")  # Set this when claiming a task
        
        if not worker_id:
            print("❌ WORKER_ID environment variable not set")
            sys.exit(1)
        
        if not torch.cuda.is_available():
            print("❌ CUDA not available - self-terminating")
            
            success = self_terminate_worker(
                worker_id=worker_id,
                task_id=task_id if task_id else "NO_TASK",
                error_reason="CUDA driver initialization failed, you might not have a CUDA gpu.",
                supabase_url=os.getenv("SUPABASE_URL"),
                supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            )
            
            if success:
                print("✅ Self-termination successful")
            else:
                print("❌ Self-termination failed")
            
            sys.exit(1)
        else:
            print(f"✅ CUDA available: {torch.cuda.device_count()} GPU(s)")
            print(f"   Device: {torch.cuda.get_device_name(0)}")
            
    except Exception as e:
        print(f"❌ Error checking CUDA: {e}")
        
        if is_fatal_gpu_error(e):
            worker_id = os.getenv("WORKER_ID")
            task_id = os.getenv("CURRENT_TASK_ID")
            
            if worker_id:
                self_terminate_worker(
                    worker_id=worker_id,
                    task_id=task_id if task_id else "NO_TASK",
                    error_reason=f"Fatal GPU error: {str(e)}",
                    supabase_url=os.getenv("SUPABASE_URL"),
                    supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
                )
        
        sys.exit(1)
