"""
Main orchestrator control loop for the Runpod GPU Worker Orchestrator.
Handles scaling decisions, health checks, and worker lifecycle management.
"""

import os
import asyncio
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from dotenv import load_dotenv

from .database import DatabaseClient
from .runpod_client import create_runpod_client, spawn_runpod_gpu, terminate_runpod_gpu

logger = logging.getLogger(__name__)

class OrchestratorControlLoop:
    """Main orchestrator control loop."""
    
    def __init__(self):
        load_dotenv()
        
        self.db = DatabaseClient()
        self.runpod = create_runpod_client()
        
        # Configuration from environment
        self.min_active_gpus = int(os.getenv("MIN_ACTIVE_GPUS", "2"))
        self.max_active_gpus = int(os.getenv("MAX_ACTIVE_GPUS", "10"))
        self.tasks_per_gpu_threshold = int(os.getenv("TASKS_PER_GPU_THRESHOLD", "3"))
        
        # Timeout settings (in seconds)
        self.gpu_idle_timeout = int(os.getenv("GPU_IDLE_TIMEOUT_SEC", "300"))
        self.task_stuck_timeout = int(os.getenv("TASK_STUCK_TIMEOUT_SEC", "300"))
        self.spawning_timeout = int(os.getenv("SPAWNING_TIMEOUT_SEC", "300"))
        self.graceful_shutdown_timeout = int(os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT_SEC", "600"))
        
        # Cycle counter for continuous mode
        self.cycle_count = 0
        
        logger.info(f"OrchestratorControlLoop initialized with scaling: {self.min_active_gpus}-{self.max_active_gpus} GPUs")
    
    async def run_single_cycle(self) -> Dict[str, Any]:
        """
        Run a single orchestrator cycle.
        Returns summary of actions taken.
        """
        cycle_start = datetime.now(timezone.utc)
        summary = {
            "timestamp": cycle_start.isoformat(),
            "actions": {
                "workers_promoted": 0,
                "workers_failed": 0,
                "workers_spawned": 0,
                "workers_terminated": 0,
                "tasks_reset": 0
            },
            "status": {}
        }
        
        try:
            # Increment cycle counter
            self.cycle_count += 1
            
            # Visual separator for continuous mode
            print("\n" + "="*80)
            print(f"🔄 ORCHESTRATOR CYCLE #{self.cycle_count}")
            print("="*80 + "\n")
            
            logger.info("Starting orchestrator cycle")
            
            # 1. Get current state – pull every worker except those already terminated.
            # Brand-new rows start with status="inactive" but we still need to treat them as
            # capacity because the Runpod pod is already requested.  We therefore rely on
            # the metadata.orchestrator_status field ("spawning"/"terminating"/etc.) to
            # classify lifecycle stages, falling back to the bare DB status when metadata
            # is missing.
            workers = await self.db.get_workers(['inactive', 'spawning', 'active', 'terminating'])
            
            # Use the same edge function that workers use to get available task count
            # This ensures orchestrator scaling decisions are based on the exact same data workers see
            # Get TOTAL tasks (queued + in-progress) for accurate capacity planning
            total_tasks = await self.db.count_available_tasks_via_edge_function(include_active=True)
            # Also get just queued for backwards compatibility and logging
            queued_count = await self.db.count_available_tasks_via_edge_function(include_active=False)

            # Split workers by derived lifecycle state
            spawning_workers = []
            active_workers = []
            terminating_workers = []

            for w in workers:
                orch_status = w.get('metadata', {}).get('orchestrator_status')

                # Prioritise the authoritative DB status first
                if w['status'] == 'active':
                    active_workers.append(w)
                elif w['status'] == 'spawning':
                    spawning_workers.append(w)
                elif w['status'] == 'terminating':
                    terminating_workers.append(w)
                else:
                    # Fall back to orchestrator_status in metadata when DB status is still "inactive"
                    if orch_status == 'spawning':
                        spawning_workers.append(w)
                    elif orch_status == 'terminating':
                        terminating_workers.append(w)
            
            logger.info(f"Current state: {len(spawning_workers)} spawning, {len(active_workers)} active, {len(terminating_workers)} terminating, {total_tasks} total tasks ({queued_count} queued)")
            
            # 2. SPAWNING WORKERS: Check status and initialize when ready
            for worker in spawning_workers:
                metadata = worker.get('metadata', {})
                runpod_id = metadata.get('runpod_id')
                
                if not runpod_id:
                    # No runpod ID means spawn failed
                    await self._mark_worker_error(worker, 'No Runpod ID')
                    summary["actions"]["workers_failed"] += 1
                    continue
                
                # Check if pod is ready and initialize it
                status_update = self.runpod.check_and_initialize_worker(worker['id'], runpod_id)
                
                if status_update['status'] == 'active':
                    # Worker is ready and initialized
                    # Remove status from update to avoid conflicts with orchestrator_status
                    metadata_update = {k: v for k, v in status_update.items() if k != 'status'}
                    # Add promotion timestamp for grace period tracking
                    metadata_update['promoted_to_active_at'] = datetime.now(timezone.utc).isoformat()
                    await self.db.update_worker_status(worker['id'], 'active', metadata_update)
                    summary["actions"]["workers_promoted"] += 1
                    logger.debug(f"Promoted worker {worker['id']} to active")
                    
                    # Start worker process if configured
                    auto_start = os.getenv("AUTO_START_WORKER_PROCESS", "true").lower() == "true"
                    if auto_start:
                        if self.runpod.start_worker_process(runpod_id, worker['id']):
                            logger.debug(f"Worker process started for {worker['id']}")
                        else:
                            logger.warning(f"Failed to start worker process for {worker['id']}")
                            
                    
                elif status_update['status'] == 'error':
                    # Pod failed or initialization failed
                    await self._mark_worker_error(worker, status_update.get('error', 'Unknown error'))
                    summary["actions"]["workers_failed"] += 1
                    
                elif self._is_past_timeout(worker['created_at'], self.spawning_timeout):
                    # Timeout waiting for pod to be ready
                    await self._mark_worker_error(worker, 'Spawning timeout')
                    summary["actions"]["workers_failed"] += 1
                # else: still spawning, will check again next cycle
            
            # 2. HEALTH CHECKS on active workers
            active_workers = [w for w in workers if w['status'] == 'active']
            for worker in active_workers:
                try:
                    # First, check if worker has completed any tasks recently
                    # This serves as an implicit heartbeat
                    recent_completions = await self._check_recent_task_completions(worker['id'])
                    
                    if recent_completions > 0:
                        # Worker completed tasks recently - update heartbeat
                        await self.db.update_worker_heartbeat(worker['id'])
                        logger.debug(f"Updated heartbeat for worker {worker['id']} - completed {recent_completions} tasks")
                    elif queued_count == 0:
                        # No tasks in queue - do a basic health check
                        if await self._perform_basic_health_check(worker):
                            # Worker is responsive but idle - don't update heartbeat
                            # Let the worker remain idle so it can be terminated after timeout
                            logger.debug(f"Worker {worker['id']} passed health check but is idle - not updating heartbeat")
                        else:
                            # Worker not responsive
                            await self._mark_worker_error(worker, 'Failed basic health check')
                            summary['actions']['workers_failed'] += 1
                            continue
                    else:
                        # Tasks are queued but worker hasn't completed any recently
                        # Check if worker is actively processing a task
                        has_active_task = await self.db.has_running_tasks(worker['id'])
                        
                        if has_active_task:
                            # Worker is processing a task - update heartbeat to show it's active
                            await self.db.update_worker_heartbeat(worker['id'])
                            logger.debug(f"Updated heartbeat for worker {worker['id']} - has active task")
                        else:
                            # No active task and hasn't completed any - check heartbeat age
                            last_heartbeat = worker.get('last_heartbeat')
                            if last_heartbeat:
                                heartbeat_dt = datetime.fromisoformat(last_heartbeat.replace('Z', '+00:00'))
                                if heartbeat_dt.tzinfo is None:
                                    heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
                                
                                heartbeat_age = (datetime.now(timezone.utc) - heartbeat_dt).total_seconds()
                                if heartbeat_age > self.gpu_idle_timeout:
                                    await self._mark_worker_error(worker, 'Idle with tasks queued')
                                    summary['actions']['workers_failed'] += 1
                                    continue
                            else:
                                # No heartbeat ever received with tasks queued
                                worker_age = (datetime.now(timezone.utc) - datetime.fromisoformat(worker['created_at'].replace('Z', '+00:00'))).total_seconds()
                                if worker_age > self.gpu_idle_timeout:
                                    await self._mark_worker_error(worker, 'No heartbeat or activity')
                                    summary['actions']['workers_failed'] += 1
                                    continue
                    
                    # Check for stuck tasks
                    running_tasks = await self.db.get_running_tasks_for_worker(worker['id'])
                    for task in running_tasks:
                        # Skip travel_orchestrator tasks - they manage other tasks and run longer
                        if task.get('task_type') == 'travel_orchestrator':
                            logger.debug(f"Skipping stuck check for travel_orchestrator task {task['id']}")
                            continue
                            
                        if task.get('generation_started_at'):
                            # Parse the task start timestamp and ensure it's timezone-aware
                            task_start_dt = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                            if task_start_dt.tzinfo is None:
                                task_start_dt = task_start_dt.replace(tzinfo=timezone.utc)
                            
                            task_age = (datetime.now(timezone.utc) - task_start_dt).total_seconds()
                            if task_age > self.task_stuck_timeout:
                                await self._mark_worker_error(worker, f'Stuck task {task["id"]}')
                                summary['actions']['workers_failed'] += 1
                                break
                                
                except Exception as e:
                    logger.error(f"Error checking health of worker {worker['id']}: {e}")
            
            # 3. REASSIGN orphaned tasks from failed workers
            # Note: This is now handled immediately in _mark_worker_error() to prevent
            # tasks from being stuck in 'In Progress' state. This section is kept for
            # any edge cases where workers might be marked as error outside the control loop.
            failed_worker_ids = [w['id'] for w in workers if w['status'] in ['error', 'terminated']]
            if failed_worker_ids:
                reset_count = await self.db.reset_orphaned_tasks(failed_worker_ids)
                summary['actions']['tasks_reset'] = reset_count
            
            # 4. SCALE DOWN: Idle workers above minimum
            # Refresh active workers list after health checks
            active_workers = [w for w in workers if w['status'] == 'active' and w['id'] not in failed_worker_ids]
            total_workers = len(active_workers) + len(spawning_workers)

            # Calculate desired number of workers based on TOTAL tasks (queued + in-progress)
            if total_tasks > 0:
                desired_workers = max(1, math.ceil(total_tasks / self.tasks_per_gpu_threshold))
            else:
                desired_workers = self.min_active_gpus
            desired_workers = min(desired_workers, self.max_active_gpus)
            
            logger.info(f"Desired workers: {desired_workers} (based on {total_tasks} total tasks, threshold={self.tasks_per_gpu_threshold})")

            # Dynamic idle timeout: use short timeout when over-capacity
            if total_workers > desired_workers:
                # Over-provisioned: use aggressive 30-second timeout
                dynamic_idle_timeout = 30
                logger.debug(f"Over-capacity ({total_workers} > {desired_workers}), using short idle timeout: {dynamic_idle_timeout}s")
            else:
                # At or below capacity: use normal timeout
                dynamic_idle_timeout = self.gpu_idle_timeout

            if total_workers > desired_workers:
                idle_workers = []
                for worker in active_workers:
                    if await self._is_worker_idle_with_timeout(worker, dynamic_idle_timeout):
                        idle_workers.append(worker)
                
                # Sort by last activity (oldest first) to terminate least recently used
                idle_workers.sort(key=lambda w: w.get('last_heartbeat', w['created_at']))
                
                # Only terminate enough to reach desired capacity
                workers_to_terminate = min(len(idle_workers), total_workers - desired_workers)
                
                for i in range(workers_to_terminate):
                    worker = idle_workers[i]
                    # Immediately terminate the worker since there's no 'terminating' status
                    if await self._terminate_worker(worker):
                        summary["actions"]["workers_terminated"] += 1
                        logger.info(f"Terminated idle worker {worker['id']} (over-capacity, idle > {dynamic_idle_timeout}s)")
            
            # Note: No graceful shutdown handling needed since we terminate immediately
            
            # 6. SCALE UP: Queue depth exceeds capacity
            active_count = len(active_workers)
            spawning_count = len(spawning_workers)
            # Count spawning workers as capacity to prevent over-provisioning
            effective_capacity = active_count + spawning_count
            
            # Scale up based on total tasks vs desired workers
            if effective_capacity < desired_workers:
                workers_needed = desired_workers - effective_capacity
                workers_needed = min(workers_needed, self.max_active_gpus - total_workers)
                
                logger.info(f"Scaling up: need {workers_needed} more workers (current: {effective_capacity}, desired: {desired_workers})")
                
                for _ in range(workers_needed):
                    if await self._spawn_worker():
                        summary["actions"]["workers_spawned"] += 1
            
            # 7. Update summary with final status
            summary["status"] = {
                "total_tasks": total_tasks,
                "queued_tasks": queued_count,
                "spawning_workers": len(spawning_workers),
                "active_workers": len(active_workers),
                "terminating_workers": len(terminating_workers),
                "total_workers": total_workers,
                "desired_workers": desired_workers
            }
            
            cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.info(f"Orchestrator cycle completed in {cycle_duration:.2f}s: {summary['actions']}")
            
            return summary
            
        except Exception as e:
            logger.error(f"Error in orchestrator cycle: {e}")
            summary["error"] = str(e)
            return summary
    
    async def _check_worker_health(self, worker: Dict[str, Any]) -> bool:
        """
        Check if a worker is healthy. Returns True if worker should be marked as error.
        """
        worker_id = worker['id']
        
        # Check heartbeat expiry
        if worker.get('last_heartbeat'):
            if self._is_past_timeout(worker['last_heartbeat'], self.gpu_idle_timeout):
                await self._mark_worker_error(worker, 'Heartbeat expired')
                return True
        elif worker['status'] == 'active':
            # Active worker with no heartbeat is problematic
            await self._mark_worker_error(worker, 'No heartbeat received')
            return True
        
        # Check for stuck tasks
        running_tasks = await self.db.get_running_tasks_for_worker(worker_id)
        for task in running_tasks:
            # Skip travel_orchestrator tasks - they manage other tasks and run longer
            if task.get('task_type') == 'travel_orchestrator':
                logger.debug(f"Skipping stuck check for travel_orchestrator task {task['id']}")
                continue
                
            if self._is_past_timeout(task['generation_started_at'], self.task_stuck_timeout):
                await self._mark_worker_error(worker, f'Stuck task {task["id"]}')
                return True
        
        # Check VRAM health (if available)
        metadata = worker.get('metadata', {})
        if 'vram_timestamp' in metadata:
            vram_age_seconds = datetime.now(timezone.utc).timestamp() - float(metadata['vram_timestamp'])
            gpu_health_timeout = int(os.getenv("GPU_HEALTH_CHECK_TIMEOUT_SEC", "120"))
            if vram_age_seconds > gpu_health_timeout:
                # VRAM data is stale but not necessarily an error - just log it
                logger.warning(f"Worker {worker_id} has stale VRAM data ({vram_age_seconds:.1f} sec old)")
        
        return False
    
    async def _mark_worker_error(self, worker: Dict[str, Any], reason: str):
        """Mark a worker as error and attempt to terminate it."""
        worker_id = worker['id']
        
        # First, reset any orphaned tasks from this worker before marking it as error
        # This ensures tasks get re-queued immediately and aren't lost
        reset_count = await self.db.reset_orphaned_tasks([worker_id])
        if reset_count > 0:
            logger.info(f"Reset {reset_count} orphaned tasks from worker {worker_id}")
        
        # Mark worker as error in DB
        await self.db.mark_worker_error(worker_id, reason)

        # Also update local copy so the rest of this cycle treats it as error
        worker['status'] = 'error'
        
        # Attempt to terminate the Runpod instance
        runpod_id = worker.get('metadata', {}).get('runpod_id')
        if runpod_id:
            self.runpod.terminate_worker(runpod_id)
        
        logger.error(f"Marked worker {worker_id} as error: {reason}")
    
    async def _is_worker_idle(self, worker: Dict[str, Any]) -> bool:
        """
        Check if a worker is idle and has been idle long enough to terminate.
        Uses GPU_IDLE_TIMEOUT_SEC to determine when an idle worker should be scaled down.
        """
        return await self._is_worker_idle_with_timeout(worker, self.gpu_idle_timeout)
    
    async def _is_worker_idle_with_timeout(self, worker: Dict[str, Any], timeout_seconds: int) -> bool:
        """
        Check if a worker is idle and has been idle long enough to terminate.
        Uses a dynamic timeout based on whether we're over capacity.
        """
        # First check if worker has any running tasks
        has_tasks = await self.db.has_running_tasks(worker['id'])
        if has_tasks:
            return False  # Worker is busy, not idle
        
        # Worker has no tasks - check how long it's been idle
        # Look for the most recent activity (task completion or heartbeat)
        last_activity = worker.get('last_heartbeat', worker['created_at'])
        
        # Check if we have recent task completions
        recent_completions = await self._check_recent_task_completions(worker['id'])
        if recent_completions > 0:
            # Worker completed tasks recently, so it's not idle long enough
            return False
        
        # Parse the last activity timestamp
        last_activity_dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
        if last_activity_dt.tzinfo is None:
            last_activity_dt = last_activity_dt.replace(tzinfo=timezone.utc)
        
        # Calculate idle time
        idle_time = (datetime.now(timezone.utc) - last_activity_dt).total_seconds()
        
        # Use the provided timeout to determine if worker has been idle too long
        return idle_time > timeout_seconds
    
    async def _should_scale_up(self, queued_count: int, active_count: int) -> bool:
        """Determine if we should scale up based on queue depth."""
        if active_count == 0:
            return queued_count > 0  # Always scale up if we have tasks but no workers
        
        tasks_per_worker = queued_count / active_count
        return tasks_per_worker > self.tasks_per_gpu_threshold
    
    def _calculate_workers_needed(self, queued_count: int, active_count: int) -> int:
        """Calculate how many additional workers are needed."""
        if active_count == 0 and queued_count > 0:
            # No active workers but have queued tasks
            # Spawn at least 1 worker, or MIN_ACTIVE_GPUS if higher
            return max(1, self.min_active_gpus)
        
        # Calculate based on threshold
        # Use ceiling division to ensure we don't exceed tasks per GPU
        ideal_workers = max(self.min_active_gpus, math.ceil(queued_count / self.tasks_per_gpu_threshold))
        return max(0, ideal_workers - active_count)
    
    async def _spawn_worker(self) -> bool:
        """Spawn a new worker."""
        try:
            worker_id = self.runpod.generate_worker_id()
            
            # Create worker record first (optimistic registration)
            if not await self.db.create_worker_record(worker_id, self.runpod.gpu_type):
                return False
            
            # Spawn the Runpod instance
            result = self.runpod.spawn_worker(worker_id)
            
            if result and result.get("runpod_id"):
                pod_id = result["runpod_id"]
                
                # Handle different status outcomes from spawn_worker
                status = result.get('status', 'spawning')
                
                # Map to our worker status system
                if status == 'running':
                    final_status = 'active'  # Worker is ready and initialized
                elif status == 'error':
                    final_status = 'error'   # Initialization failed
                else:
                    final_status = 'spawning'  # Still initializing
                
                # Update worker record with Runpod ID and metadata
                metadata = {'runpod_id': pod_id}
                if 'ssh_details' in result:
                    metadata['ssh_details'] = result['ssh_details']
                if 'pod_details' in result:
                    metadata['pod_details'] = result['pod_details']
                
                await self.db.update_worker_status(worker_id, final_status, metadata)
                
                # If worker is ready, optionally start the worker process
                if final_status == 'active':
                    logger.debug(f"Successfully spawned and initialized worker {worker_id} (pod {pod_id})")
                    
                    # Optionally start the worker process automatically
                    auto_start = os.getenv("AUTO_START_WORKER_PROCESS", "true").lower() == "true"
                    if auto_start:
                        if self.runpod.start_worker_process(pod_id, worker_id):
                            logger.debug(f"Worker process started for {worker_id}")
                        else:
                            logger.warning(f"Failed to start worker process for {worker_id}, but worker is still active")
                else:
                    logger.debug(f"Worker {worker_id} spawned with status: {final_status}")
                
                return final_status != 'error'
            else:
                # Mark worker as error since spawn failed
                await self.db.mark_worker_error(worker_id, 'Failed to spawn Runpod instance')
                return False
                
        except Exception as e:
            logger.error(f"Error spawning worker: {e}")
            return False
    
    async def _terminate_worker(self, worker: Dict[str, Any]) -> bool:
        """Terminate a worker and update its status."""
        worker_id = worker['id']
        runpod_id = worker.get('metadata', {}).get('runpod_id')
        
        try:
            # Terminate Runpod instance
            if runpod_id:
                success = self.runpod.terminate_worker(runpod_id)
                if not success:
                    logger.warning(f"Failed to terminate Runpod instance {runpod_id} for worker {worker_id}")
            
            # Update worker status
            termination_metadata = {'terminated_at': datetime.now(timezone.utc).isoformat()}
            await self.db.update_worker_status(worker_id, 'terminated', termination_metadata)
            
            logger.debug(f"Terminated worker {worker_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error terminating worker {worker_id}: {e}")
            return False
    
    def _is_past_timeout(self, timestamp_str: str, timeout_seconds: int) -> bool:
        """Check if a timestamp is past the timeout threshold."""
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
            return age_seconds > timeout_seconds
        except Exception as e:
            logger.warning(f"Error parsing timestamp {timestamp_str}: {e}")
            return False  # Assume not past timeout if we can't parse
    
    async def _check_recent_task_completions(self, worker_id: str) -> int:
        """Check how many tasks this worker completed since the last cycle (30 seconds)."""
        try:
            # Look for tasks completed by this worker in the last polling interval
            cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=int(os.getenv("ORCHESTRATOR_POLL_SEC", "30")))
            
            result = self.db.supabase.table('tasks').select('id', count='exact') \
                .eq('worker_id', worker_id) \
                .eq('status', 'Complete') \
                .gte('generation_processed_at', cutoff_time.isoformat()) \
                .execute()
            
            return result.count or 0
        except Exception as e:
            logger.error(f"Error checking recent completions for worker {worker_id}: {e}")
            return 0
    
    async def _perform_basic_health_check(self, worker: Dict[str, Any]) -> bool:
        """Perform a basic health check on an idle worker."""
        try:
            metadata = worker.get('metadata', {})
            runpod_id = metadata.get('runpod_id')
            
            if not runpod_id:
                return False
            
            # Check if the pod is still running
            pod_status = self.runpod.get_pod_status(runpod_id)
            if not pod_status:
                return False
            
            # Pod should be in RUNNING state
            if pod_status.get('desired_status') != 'RUNNING':
                return False
            
            # Optionally check SSH connectivity (quick timeout)
            ssh_details = metadata.get('ssh_details', {})
            if ssh_details and 'ip' in ssh_details and 'port' in ssh_details:
                # This is a lightweight check - just see if port is open
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)  # 5 second timeout
                try:
                    result = sock.connect_ex((ssh_details['ip'], ssh_details['port']))
                    sock.close()
                    return result == 0  # 0 means connection successful
                except:
                    return False
            
            # If we can't check SSH, assume healthy if pod is running
            return True
            
        except Exception as e:
            logger.error(f"Error performing health check for worker {worker['id']}: {e}")
            return False 