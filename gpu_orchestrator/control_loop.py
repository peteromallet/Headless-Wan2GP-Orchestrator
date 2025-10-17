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

from database import DatabaseClient
from runpod_client import create_runpod_client, spawn_runpod_gpu, terminate_runpod_gpu
from health_monitor import OrchestratorHealthMonitor

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
        self.machines_to_keep_idle = int(os.getenv("MACHINES_TO_KEEP_IDLE", "0"))
        
        # Timeout settings (in seconds)
        self.gpu_idle_timeout = int(os.getenv("GPU_IDLE_TIMEOUT_SEC", "300"))
        self.task_stuck_timeout = int(os.getenv("TASK_STUCK_TIMEOUT_SEC", "1200"))
        self.spawning_timeout = int(os.getenv("SPAWNING_TIMEOUT_SEC", "300"))
        self.graceful_shutdown_timeout = int(os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT_SEC", "600"))
        # Shorter idle timeout used only when we are over desired capacity
        self.overcapacity_idle_timeout = int(os.getenv("GPU_OVERCAPACITY_IDLE_TIMEOUT_SEC", "30"))
        # Scaling stability controls (anti-thrashing)
        self.spawning_grace_period = int(os.getenv("SPAWNING_GRACE_PERIOD_SEC", "180"))
        self.scale_down_grace_period = int(os.getenv("SCALE_DOWN_GRACE_PERIOD_SEC", "60"))
        self.scale_up_multiplier = float(os.getenv("SCALE_UP_MULTIPLIER", "1.0"))
        self.scale_down_multiplier = float(os.getenv("SCALE_DOWN_MULTIPLIER", "0.9"))
        self.min_scaling_interval = int(os.getenv("MIN_SCALING_INTERVAL_SEC", "45"))
        
        # Failure rate protection (prevent endless spin-ups)
        self.max_failure_rate = float(os.getenv("MAX_WORKER_FAILURE_RATE", "0.8"))  # 80% failure rate threshold
        self.failure_window_minutes = int(os.getenv("FAILURE_WINDOW_MINUTES", "5"))  # Look at last 5 minutes
        self.min_workers_for_rate_check = int(os.getenv("MIN_WORKERS_FOR_RATE_CHECK", "5"))  # Need at least 5 workers to calculate rate
        
        # Validate and clamp machines_to_keep_idle
        if self.machines_to_keep_idle < 0:
            logger.warning(f"MACHINES_TO_KEEP_IDLE cannot be negative, setting to 0")
            self.machines_to_keep_idle = 0
        elif self.machines_to_keep_idle > self.max_active_gpus:
            logger.warning(f"MACHINES_TO_KEEP_IDLE ({self.machines_to_keep_idle}) exceeds MAX_ACTIVE_GPUS ({self.max_active_gpus}), clamping to {self.max_active_gpus}")
            self.machines_to_keep_idle = self.max_active_gpus
        
        # Cycle counter for continuous mode
        self.cycle_count = 0
        # Track recent scale actions to apply grace periods
        self.last_scale_down_at = None
        self.last_scale_up_at = None
        
        # Health monitor
        self.health_monitor = OrchestratorHealthMonitor()
        
        logger.info(f"OrchestratorControlLoop initialized with scaling: {self.min_active_gpus}-{self.max_active_gpus} GPUs, idle buffer: {self.machines_to_keep_idle}")
        
        # Log critical environment variables for debugging
        logger.info("🔧 ENV_VALIDATION Starting orchestrator with environment validation")
        
        # SSH Configuration
        ssh_private_key = os.getenv("RUNPOD_SSH_PRIVATE_KEY")
        ssh_public_key = os.getenv("RUNPOD_SSH_PUBLIC_KEY")
        ssh_private_key_path = os.getenv("RUNPOD_SSH_PRIVATE_KEY_PATH")
        
        logger.info("🔧 ENV_VALIDATION SSH Configuration:")
        logger.info(f"🔧 ENV_VALIDATION   - RUNPOD_SSH_PRIVATE_KEY: {'✅ SET' if ssh_private_key else '❌ MISSING'}")
        logger.info(f"🔧 ENV_VALIDATION   - RUNPOD_SSH_PUBLIC_KEY: {'✅ SET' if ssh_public_key else '❌ MISSING'}")
        logger.info(f"🔧 ENV_VALIDATION   - RUNPOD_SSH_PRIVATE_KEY_PATH: {'✅ SET' if ssh_private_key_path else '❌ MISSING'}")
        
        if not ssh_private_key and not ssh_private_key_path:
            logger.error("🔧 ENV_VALIDATION ❌ CRITICAL: No SSH private key configured!")
            logger.error("🔧 ENV_VALIDATION This will cause SSH authentication failures and worker terminations")
        elif ssh_private_key:
            logger.info(f"🔧 ENV_VALIDATION ✅ Using SSH key from environment variable ({len(ssh_private_key)} chars)")
        else:
            logger.info(f"🔧 ENV_VALIDATION ✅ Using SSH key from file path: {ssh_private_key_path}")
        
        # Log timeout configuration
        logger.info("🔧 ENV_VALIDATION Timeout Configuration:")
        logger.info(f"🔧 ENV_VALIDATION   - GPU_IDLE_TIMEOUT_SEC: {self.gpu_idle_timeout}")
        logger.info(f"🔧 ENV_VALIDATION   - TASK_STUCK_TIMEOUT_SEC: {self.task_stuck_timeout}")
        logger.info(f"🔧 ENV_VALIDATION   - SPAWNING_TIMEOUT_SEC: {self.spawning_timeout}")
        logger.info("🔧 ENV_VALIDATION Orchestrator initialization complete")
    
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
            
            # Set cycle number in logging context for database logging
            try:
                from logging_config import set_current_cycle
                set_current_cycle(self.cycle_count)
            except Exception:
                pass  # Database logging not enabled, that's okay
            
            # Visual separator for continuous mode
            print("\n" + "="*80)
            print(f"🔄 ORCHESTRATOR CYCLE #{self.cycle_count}")
            print("="*80 + "\n")
            
            logger.info("Starting orchestrator cycle")
            
            # 1. Get current state – pull ALL workers including error status for comprehensive health checks
            # We need to check error workers for cleanup and terminated workers for garbage collection
            # Brand-new rows start with status="inactive" but we still need to treat them as
            # capacity because the Runpod pod is already requested.  We therefore rely on
            # the metadata.orchestrator_status field ("spawning"/"terminating"/etc.) to
            # classify lifecycle stages, falling back to the bare DB status when metadata
            # is missing.
            workers = await self.db.get_workers()  # Get ALL workers for comprehensive health checks
            
            # Use the new detailed count mode to get comprehensive task breakdown
            # This provides much more debugging information for scaling decisions
            detailed_counts = await self.db.get_detailed_task_counts_via_edge_function()
            
            if detailed_counts:
                # Extract counts from the detailed response
                totals = detailed_counts.get('totals', {})
                total_tasks = totals.get('queued_plus_active', 0)
                queued_count = totals.get('queued_only', 0)
                active_cloud_count = totals.get('active_only', 0)
                
                # CRITICAL: Log task counts with MAXIMUM visibility
                # These logs go to: stdout, file, AND database (if working)
                logger.critical(f"🔢 TASK COUNT (Cycle #{self.cycle_count}): Queued={queued_count}, Active={active_cloud_count}, Total={total_tasks}")
                
                # Also log to stdout directly (bypass logging system for redundancy)
                import sys
                print(f"\n{'='*80}", file=sys.stderr)
                print(f"ORCHESTRATOR CYCLE #{self.cycle_count} - TASK COUNT", file=sys.stderr)
                print(f"  Queued only: {queued_count}", file=sys.stderr)
                print(f"  Active (cloud): {active_cloud_count}", file=sys.stderr)
                print(f"  Total workload: {total_tasks}", file=sys.stderr)
                print(f"{'='*80}\n", file=sys.stderr)
                
                # Log detailed breakdown for debugging
                logger.info(f"📊 DETAILED TASK BREAKDOWN:")
                logger.info(f"   • Queued only: {queued_count}")
                logger.info(f"   • Active (cloud-claimed): {active_cloud_count}")
                logger.info(f"   • Total (queued + active): {total_tasks}")
                
                # Log global task breakdown if available
                if 'global_task_breakdown' in detailed_counts:
                    breakdown = detailed_counts['global_task_breakdown']
                    logger.info(f"   • In Progress (total): {breakdown.get('in_progress_total', 0)}")
                    logger.info(f"   • In Progress (cloud): {breakdown.get('in_progress_cloud', 0)}")
                    logger.info(f"   • In Progress (local): {breakdown.get('in_progress_local', 0)}")
                    logger.info(f"   • Orchestrator tasks: {breakdown.get('orchestrator_tasks', 0)}")
                
                # Log user stats for debugging (first few users)
                users = detailed_counts.get('users', [])
                if users:
                    logger.info(f"   • Users with tasks: {len(users)}")
                    at_limit_users = [u for u in users if u.get('at_limit', False)]
                    if at_limit_users:
                        logger.info(f"   • Users at concurrency limit (≥5): {len(at_limit_users)}")
                    
                    # Show top users with queued tasks
                    top_users = sorted(users, key=lambda u: u.get('queued_tasks', 0), reverse=True)[:3]
                    for user in top_users:
                        if user.get('queued_tasks', 0) > 0:
                            status = "AT LIMIT" if user.get('at_limit') else "under limit"
                            logger.info(f"   • User {user.get('user_id', 'unknown')}: {user.get('queued_tasks', 0)} queued, {user.get('in_progress_tasks', 0)} in progress ({status})")
                
                # Log recent task patterns if available
                recent_tasks = detailed_counts.get('recent_tasks', [])
                if recent_tasks:
                    cloud_tasks = [t for t in recent_tasks if t.get('is_cloud')]
                    local_tasks = [t for t in recent_tasks if not t.get('is_cloud')]
                    logger.info(f"   • Recent tasks: {len(cloud_tasks)} cloud, {len(local_tasks)} local")
            else:
                # Fallback to old method if detailed counts fail
                logger.warning("⚠️  Failed to get detailed task counts, falling back to simple counting")
                logger.warning("   This means the edge function count mode is not working - check logs above")
                total_tasks = await self.db.count_available_tasks_via_edge_function(include_active=True)
                queued_count = await self.db.count_available_tasks_via_edge_function(include_active=False)
                active_cloud_count = total_tasks - queued_count
                logger.warning(f"   Fallback returned: {total_tasks} total, {queued_count} queued (OLD METHOD - may over-scale)")

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
            
            # 1.5. EARLY TERMINATION: Check if we have too many workers before processing spawning
            # Calculate desired workers first to avoid wasting time promoting workers we'll terminate
            current_capacity = len(active_workers) + len(spawning_workers)

            if total_tasks > 0:
                # Use a slightly conservative target when scaling down to avoid thrashing
                down_scaled_tasks = math.ceil(total_tasks * self.scale_down_multiplier)
                task_based_workers = max(1, down_scaled_tasks)
            else:
                task_based_workers = 0

            early_desired_workers = max(self.min_active_gpus, task_based_workers, self.machines_to_keep_idle)
            early_desired_workers = min(early_desired_workers, self.max_active_gpus)

            # If we have too many workers, terminate excess spawning workers first
            # BUT: apply grace periods and do not terminate while there is queued work
            now_ts = datetime.now(timezone.utc)
            time_since_last_down = (now_ts - self.last_scale_down_at).total_seconds() if self.last_scale_down_at else None

            if current_capacity > early_desired_workers:
                # Skip early termination if there is still queued work; we likely need upcoming capacity
                if queued_count and queued_count > 0:
                    logger.debug("Skipping early termination because queued work exists")
                else:
                    # Respect scale-down grace period between consecutive downs
                    if (time_since_last_down is None) or (time_since_last_down >= self.scale_down_grace_period):
                        excess_workers = current_capacity - early_desired_workers
                        spawning_sorted = sorted(spawning_workers, key=lambda w: w['created_at'], reverse=True)

                        # Only consider spawning workers older than grace period
                        eligible = []
                        for w in spawning_sorted:
                            try:
                                created_dt = datetime.fromisoformat(w['created_at'].replace('Z', '+00:00'))
                                age_sec = (now_ts - created_dt).total_seconds()
                            except Exception:
                                age_sec = self.spawning_grace_period + 1  # fail-open to allow termination if timestamp bad
                            if age_sec > self.spawning_grace_period:
                                eligible.append(w)

                        spawning_to_terminate = min(excess_workers, len(eligible))

                        if spawning_to_terminate > 0:
                            logger.info(
                                f"Early termination: {current_capacity} workers > {early_desired_workers} desired, "
                                f"terminating {spawning_to_terminate} spawning workers (past grace {self.spawning_grace_period}s)"
                            )

                            for i in range(spawning_to_terminate):
                                worker = eligible[i]
                                runpod_id = worker.get('metadata', {}).get('runpod_id')

                                # Terminate the RunPod instance
                                if runpod_id:
                                    success = self.runpod.terminate_worker(runpod_id)
                                    if success:
                                        logger.info(f"Terminated spawning worker {worker['id']} (RunPod {runpod_id})")
                                    else:
                                        logger.warning(f"Failed to terminate spawning worker {worker['id']} (RunPod {runpod_id})")

                                # Mark as terminated in database
                                await self.db.update_worker_status(worker['id'], 'terminated')
                                summary["actions"]["workers_terminated"] += 1

                            # Remove terminated workers from spawning list
                            terminated_ids = {eligible[i]['id'] for i in range(spawning_to_terminate)}
                            spawning_workers = [w for w in spawning_workers if w['id'] not in terminated_ids]
                            self.last_scale_down_at = now_ts
                        else:
                            logger.debug("No spawning workers eligible for early termination (within grace period)")
                    else:
                        logger.debug(
                            f"Skipping early termination due to scale-down grace period: {time_since_last_down:.0f}s < {self.scale_down_grace_period}s"
                        )
            
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
                    # Check if worker has active tasks assigned
                    # Note: Only the WORKER should update its own heartbeat!
                    # The orchestrator must NOT update worker heartbeats (would defeat the purpose)
                    has_active_task = await self.db.has_running_tasks(worker['id'])
                    
                    if has_active_task:
                        # Worker has tasks assigned - ALWAYS check heartbeat regardless of queued_count
                        # This catches frozen workers even when user concurrency limits hide queued tasks
                        logger.debug(f"[WORKER_HEALTH] Worker {worker['id']}: Has active task, checking heartbeat")
                        last_heartbeat = worker.get('last_heartbeat')
                        if last_heartbeat:
                            heartbeat_dt = datetime.fromisoformat(last_heartbeat.replace('Z', '+00:00'))
                            if heartbeat_dt.tzinfo is None:
                                heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
                            
                            heartbeat_age = (datetime.now(timezone.utc) - heartbeat_dt).total_seconds()
                            if heartbeat_age > self.gpu_idle_timeout:
                                logger.warning(f"[WORKER_HEALTH] Worker {worker['id']}: Stale heartbeat with active tasks ({heartbeat_age:.0f}s old)")
                                await self._mark_worker_error(worker, f'Stale heartbeat with active tasks ({heartbeat_age:.0f}s old)')
                                summary['actions']['workers_failed'] += 1
                                continue
                            else:
                                logger.debug(f"Worker {worker['id']} has active tasks and recent heartbeat ({heartbeat_age:.0f}s old)")
                        else:
                            # No heartbeat but has active tasks - mark as error immediately
                            logger.warning(f"[WORKER_HEALTH] Worker {worker['id']}: No heartbeat with active tasks")
                            await self._mark_worker_error(worker, 'No heartbeat with active tasks')
                            summary['actions']['workers_failed'] += 1
                            continue
                    elif queued_count > 0:
                        # No active task but tasks are queued - check if worker is idle
                        logger.info(f"[WORKER_HEALTH] Worker {worker['id']}: {queued_count} tasks queued but worker is idle")
                        last_heartbeat = worker.get('last_heartbeat')
                        if last_heartbeat:
                            heartbeat_dt = datetime.fromisoformat(last_heartbeat.replace('Z', '+00:00'))
                            if heartbeat_dt.tzinfo is None:
                                heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
                            
                            heartbeat_age = (datetime.now(timezone.utc) - heartbeat_dt).total_seconds()
                            logger.info(f"[WORKER_HEALTH] Worker {worker['id']}: Idle worker with tasks queued. Heartbeat age: {heartbeat_age:.0f}s, Timeout: {self.gpu_idle_timeout}s")
                            if heartbeat_age > self.gpu_idle_timeout:
                                logger.warning(f"[WORKER_HEALTH] Worker {worker['id']}: Marking as failed - idle too long with tasks available (heartbeat: {heartbeat_age:.0f}s > {self.gpu_idle_timeout}s)")
                                await self._mark_worker_error(worker, 'Idle with tasks queued')
                                summary['actions']['workers_failed'] += 1
                                continue
                        else:
                            # No heartbeat ever received with tasks queued
                            worker_age = (datetime.now(timezone.utc) - datetime.fromisoformat(worker['created_at'].replace('Z', '+00:00'))).total_seconds()
                            if worker_age > self.gpu_idle_timeout:
                                logger.warning(f"[WORKER_HEALTH] Worker {worker['id']}: No heartbeat or activity with tasks queued")
                                await self._mark_worker_error(worker, 'No heartbeat or activity')
                                summary['actions']['workers_failed'] += 1
                                continue
                    else:
                        # No active task and no queued tasks - worker is idle
                        # Check if idle too long (regardless of capacity to prevent indefinite idle workers)
                        logger.debug(f"[WORKER_HEALTH] Worker {worker['id']}: No tasks queued or assigned, checking idle timeout")
                        
                        # Check if worker has been idle too long
                        if await self._is_worker_idle_with_timeout(worker, self.gpu_idle_timeout):
                            # Worker has been idle longer than timeout
                            # Only terminate if we're above minimum capacity OR if idle is excessive
                            current_active_count = len([w for w in workers if w['status'] == 'active'])
                            
                            if current_active_count > self.min_active_gpus:
                                logger.info(f"[WORKER_HEALTH] Worker {worker['id']}: Idle for >{self.gpu_idle_timeout}s with no queued tasks, terminating (above min capacity)")
                                await self._mark_worker_error(worker, f'Idle timeout ({self.gpu_idle_timeout}s) with no work available')
                                summary['actions']['workers_failed'] += 1
                                continue
                            else:
                                logger.debug(f"[WORKER_HEALTH] Worker {worker['id']}: Idle for >{self.gpu_idle_timeout}s but at minimum capacity, keeping alive")
                        
                        # Perform basic health check (pod responsive?)
                        if await self._perform_basic_health_check(worker):
                            logger.debug(f"[WORKER_HEALTH] Worker {worker['id']}: Passed health check, monitoring idle time")
                        else:
                            # Worker not responsive
                            logger.warning(f"[WORKER_HEALTH] Worker {worker['id']}: Failed basic health check")
                            await self._mark_worker_error(worker, 'Failed basic health check')
                            summary['actions']['workers_failed'] += 1
                            continue
                    
                    # Check for stuck tasks
                    running_tasks = await self.db.get_running_tasks_for_worker(worker['id'])
                    for task in running_tasks:
                        task_type = task.get('task_type', '')
                        
                        # Skip timeout checks for orchestrator tasks - they run indefinitely
                        if '_orchestrator' in task_type.lower():
                            logger.debug(f"Skipping stuck check for orchestrator task {task['id']} (type: {task_type}) - runs indefinitely")
                            continue
                        
                        # Set timeout for non-orchestrator tasks
                        timeout = self.task_stuck_timeout
                            
                        if task.get('generation_started_at'):
                            # Parse the task start timestamp and ensure it's timezone-aware
                            task_start_dt = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                            if task_start_dt.tzinfo is None:
                                task_start_dt = task_start_dt.replace(tzinfo=timezone.utc)
                            
                            task_age = (datetime.now(timezone.utc) - task_start_dt).total_seconds()
                            # FIX: Use calculated timeout variable, not base timeout
                            if task_age > timeout:
                                await self._mark_worker_error(worker, f'Stuck task {task["id"]} (timeout: {timeout}s)')
                                summary['actions']['workers_failed'] += 1
                                break
                                
                except Exception as e:
                    logger.error(f"Error checking health of worker {worker['id']}: {e}")
            
            # 2b. ERROR WORKER CLEANUP - Check workers marked as error for RunPod cleanup
            error_workers = [w for w in workers if w['status'] == 'error']
            for worker in error_workers:
                try:
                    await self._check_error_worker_cleanup(worker)
                    summary["actions"]["workers_failed"] += 1  # Count cleanup actions
                except Exception as e:
                    logger.error(f"Error during error worker cleanup for {worker['id']}: {e}")
            
            # 2c. FAILSAFE HEALTH CHECK - Catch any workers that slipped through normal checks
            await self._failsafe_stale_worker_check(workers, summary)
            
            # 3. REASSIGN orphaned tasks from failed workers
            # Note: This is now handled immediately in _mark_worker_error() to prevent
            # tasks from being stuck in 'In Progress' state. This section is kept for
            # any edge cases where workers might be marked as error outside the control loop.
            # Only include recently failed workers to avoid processing hundreds of old terminated workers
            recent_failed_workers = []
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            
            for w in workers:
                if w['status'] in ['error', 'terminated']:
                    # Check if worker failed/terminated recently
                    worker_time = w.get('updated_at', w.get('created_at'))
                    if worker_time:
                        try:
                            worker_dt = datetime.fromisoformat(worker_time.replace('Z', '+00:00'))
                            if worker_dt > cutoff_time:
                                recent_failed_workers.append(w['id'])
                        except Exception:
                            pass  # Skip workers with unparseable timestamps
            
            if recent_failed_workers:
                reset_count = await self.db.reset_orphaned_tasks(recent_failed_workers)
                summary['actions']['tasks_reset'] = reset_count
                if len(recent_failed_workers) < 20:  # Only log if reasonable number
                    logger.debug(f"Checked {len(recent_failed_workers)} recently failed workers for orphaned tasks")
                else:
                    logger.debug(f"Checked {len(recent_failed_workers)} recently failed workers for orphaned tasks (list truncated)")
            else:
                summary['actions']['tasks_reset'] = 0
            
            # Also check for tasks stuck in progress with no worker assigned (edge case bug fix)
            unassigned_reset_count = await self.db.reset_unassigned_orphaned_tasks(timeout_minutes=15)
            if unassigned_reset_count > 0:
                summary['actions']['tasks_reset'] += unassigned_reset_count
            
            # 4. SCALE DOWN: Idle workers above minimum
            # Refresh active workers list after health checks
            active_workers = [w for w in workers if w['status'] == 'active' and w['id'] not in recent_failed_workers]
            total_workers = len(active_workers) + len(spawning_workers)

            # Calculate idle vs busy workers for buffer logic
            idle_workers = []
            for worker in active_workers:
                # Check if worker is idle (no timeout requirement for buffer calculation)
                if await self._is_worker_idle_with_timeout(worker, 0):
                    idle_workers.append(worker)
            
            busy_workers_count = len(active_workers) - len(idle_workers)

            # Calculate desired number of workers based on total workload (queued + active)
            # This scales for both tasks waiting to be claimed AND tasks currently being processed
            # The edge function already filters for user concurrency limits, credits, etc.
            
            total_workload = queued_count + active_cloud_count
            if total_workload > 0:
                # Apply hysteresis: scale-up uses multiplier >= 1.0 to avoid under-shoot
                up_scaled = math.ceil(total_workload * self.scale_up_multiplier)
                task_based_workers = max(1, up_scaled)
            else:
                task_based_workers = 0
            
            # Apply idle buffer: need at least busy_workers + idle_buffer
            buffer_based_workers = busy_workers_count + self.machines_to_keep_idle
            
            # Take the maximum of MIN_ACTIVE_GPUS, task-based, and buffer-based requirements
            desired_workers = max(self.min_active_gpus, task_based_workers, buffer_based_workers)
            desired_workers = min(desired_workers, self.max_active_gpus)
            
            # Check failure rate before scaling up to prevent endless spin-ups
            failure_rate_ok = await self._check_worker_failure_rate()
            
            # Enhanced logging for scaling decision analysis
            # CRITICAL: Make scaling decisions ABUNDANTLY CLEAR
            import sys
            
            logger.critical(f"🎯 SCALING DECISION (Cycle #{self.cycle_count}): Current={len(active_workers)}+{len(spawning_workers)}, Desired={desired_workers}")
            logger.info(f"🎯 SCALING DECISION ANALYSIS:")
            logger.info(f"   • Task-based scaling (queued + active): {task_based_workers} workers")
            logger.info(f"     - Queued tasks: {queued_count}")
            logger.info(f"     - Active cloud tasks: {active_cloud_count}")
            logger.info(f"     - Total workload: {total_workload}")
            logger.info(f"   • Buffer requirement: {buffer_based_workers} workers")
            logger.info(f"   • Minimum requirement: {self.min_active_gpus} workers")
            logger.info(f"   → FINAL DESIRED: {desired_workers} workers")
            logger.info(f"   • Current capacity: {len(idle_workers)} idle + {busy_workers_count} busy = {len(active_workers)} active, {len(spawning_workers)} spawning")
            logger.info(f"   • Failure rate check: {'✅ PASS' if failure_rate_ok else '❌ FAIL (blocking scale-up)'}")
            
            # Also log to stderr for absolute visibility
            print(f"\n{'='*80}", file=sys.stderr)
            print(f"SCALING DECISION (Cycle #{self.cycle_count})", file=sys.stderr)
            print(f"  Task Count: {queued_count} queued + {active_cloud_count} active = {total_workload} total", file=sys.stderr)
            print(f"  Current: {len(active_workers)} active + {len(spawning_workers)} spawning = {len(active_workers) + len(spawning_workers)} total", file=sys.stderr)
            print(f"  Desired: {desired_workers} workers", file=sys.stderr)
            print(f"  Decision: ", end='', file=sys.stderr)
            
            current_total = len(active_workers) + len(spawning_workers)
            if current_total < desired_workers:
                print(f"SCALE UP by {desired_workers - current_total}", file=sys.stderr)
            elif current_total > desired_workers:
                print(f"SCALE DOWN by {current_total - desired_workers}", file=sys.stderr)
            else:
                print(f"MAINTAIN (at capacity)", file=sys.stderr)
            print(f"{'='*80}\n", file=sys.stderr)

            # Dynamic idle timeout: use short timeout when over-capacity
            if total_workers > desired_workers:
                # Over-provisioned: use configured over-capacity idle timeout
                dynamic_idle_timeout = self.overcapacity_idle_timeout
                logger.debug(f"Over-capacity ({total_workers} > {desired_workers}), using over-capacity idle timeout: {dynamic_idle_timeout}s")
            else:
                # At or below capacity: use normal timeout
                dynamic_idle_timeout = self.gpu_idle_timeout

            if total_workers > desired_workers:
                # Find workers that are idle AND have been idle long enough to be candidates for termination
                terminatable_idle_workers = []
                for worker in active_workers:
                    if await self._is_worker_idle_with_timeout(worker, dynamic_idle_timeout):
                        terminatable_idle_workers.append(worker)
                
                # Sort by last activity (oldest first) to terminate least recently used
                terminatable_idle_workers.sort(key=lambda w: w.get('last_heartbeat', w['created_at']))
                
                # Calculate how many we can terminate while respecting idle buffer
                # We need to keep at least machines_to_keep_idle workers idle
                max_terminatable_by_buffer = max(0, len(idle_workers) - self.machines_to_keep_idle)
                max_terminatable_by_capacity = total_workers - desired_workers
                workers_to_terminate = min(len(terminatable_idle_workers), max_terminatable_by_buffer, max_terminatable_by_capacity)
                
                if workers_to_terminate > 0:
                    logger.info(f"Terminating {workers_to_terminate} workers (over-capacity: {total_workers} > {desired_workers}, idle buffer requires keeping {self.machines_to_keep_idle} idle)")
                
                for i in range(workers_to_terminate):
                    worker = terminatable_idle_workers[i]
                    # Immediately terminate the worker since there's no 'terminating' status
                    if await self._terminate_worker(worker):
                        summary["actions"]["workers_terminated"] += 1
                        logger.info(f"Terminated idle worker {worker['id']} (over-capacity, idle > {dynamic_idle_timeout}s)")
            
            # Note: No graceful shutdown handling needed since we terminate immediately
            
            # 6. SCALE UP: Queue depth exceeds capacity
            # IMPORTANT: Recalculate worker counts AFTER processing spawning/active workers
            # to include any newly promoted workers in capacity calculations
            current_active_workers = [w for w in workers if w['status'] == 'active' and w['id'] not in recent_failed_workers]
            current_spawning_workers = [w for w in workers if w['status'] == 'spawning']
            
            active_count = len(current_active_workers)
            spawning_count = len(current_spawning_workers)
            # Count spawning workers as capacity to prevent over-provisioning
            effective_capacity = active_count + spawning_count
            
            # Scale up based on total tasks vs desired workers
            if effective_capacity < desired_workers:
                workers_needed = desired_workers - effective_capacity
                workers_needed = min(workers_needed, self.max_active_gpus - (active_count + spawning_count))
                
                if not failure_rate_ok:
                    logger.error(f"⚠️  SCALING BLOCKED: High failure rate detected, not spawning {workers_needed} workers")
                    logger.error(f"⚠️  Fix the underlying issue (SSH auth, image problems, etc.) before scaling resumes")
                    
                    # Also log to stderr
                    import sys
                    print(f"\n⚠️  SCALING BLOCKED: High failure rate, refusing to spawn {workers_needed} workers\n", file=sys.stderr)
                else:
                    logger.critical(f"🚀 SCALING UP: Spawning {workers_needed} workers (current: {effective_capacity}, desired: {desired_workers})")
                    logger.info(f"Scaling up: need {workers_needed} more workers (current: {effective_capacity}, desired: {desired_workers})")
                    
                    # Also log to stderr
                    import sys
                    print(f"\n🚀 SCALING UP: Creating {workers_needed} new workers\n", file=sys.stderr)
                    
                    for i in range(workers_needed):
                        if await self._spawn_worker():
                            summary["actions"]["workers_spawned"] += 1
                            logger.critical(f"✅ Worker {i+1}/{workers_needed} spawned successfully")
                        else:
                            logger.error(f"❌ Failed to spawn worker {i+1}/{workers_needed}")
            
            # 7. Update summary with final status
            summary["status"] = {
                "total_tasks": total_tasks,
                "queued_tasks": queued_count,
                "spawning_workers": len(spawning_workers),
                "active_workers": len(active_workers),
                "idle_workers": len(idle_workers),
                "busy_workers": busy_workers_count,
                "terminating_workers": len(terminating_workers),
                "total_workers": total_workers,
                "desired_workers": desired_workers,
                "idle_buffer_target": self.machines_to_keep_idle,
                "task_based_workers": task_based_workers,
                "buffer_based_workers": buffer_based_workers
            }
            
            cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.info(f"Orchestrator cycle completed in {cycle_duration:.2f}s: {summary['actions']}")
            
            # Health monitoring
            self.health_monitor.check_scaling_anomaly(
                task_count=total_tasks,
                worker_count=total_workers,
                workers_spawned=summary["actions"]["workers_spawned"]
            )
            
            # Periodic health summary
            self.health_monitor.log_health_summary(self.cycle_count)
            
            # Check logging health every 10 cycles
            if self.cycle_count % 10 == 0:
                if not self.health_monitor.check_logging_health():
                    logger.error("⚠️  Database logging is degraded - check logs above")
            
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
        logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] Starting health check")
        
        # Check heartbeat expiry
        if worker.get('last_heartbeat'):
            heartbeat_age_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(worker['last_heartbeat'].replace('Z', '+00:00'))).total_seconds()
            logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] Heartbeat age: {heartbeat_age_seconds:.1f}s (timeout: {self.gpu_idle_timeout}s)")
            
            if self._is_past_timeout(worker['last_heartbeat'], self.gpu_idle_timeout):
                logger.error(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] ❌ HEARTBEAT EXPIRED ({heartbeat_age_seconds:.1f}s > {self.gpu_idle_timeout}s)")
                await self._mark_worker_error(worker, f'Heartbeat expired ({heartbeat_age_seconds:.1f}s old)')
                return True
            else:
                logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] ✅ Heartbeat is fresh")
        elif worker['status'] == 'active':
            # Active worker with no heartbeat is problematic
            logger.error(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] ❌ ACTIVE WORKER WITH NO HEARTBEAT")
            await self._mark_worker_error(worker, 'No heartbeat received')
            return True
        else:
            logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] No heartbeat expected (status: {worker['status']})")
        
        # Check for stuck tasks
        logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] Checking for stuck tasks...")
        running_tasks = await self.db.get_running_tasks_for_worker(worker_id)
        logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] Found {len(running_tasks)} running tasks")
        
        for task in running_tasks:
            task_id = task['id']
            task_type = task.get('task_type', '')
            
            # Skip timeout checks for orchestrator tasks - they run indefinitely
            if '_orchestrator' in task_type.lower():
                logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] Task {task_id}: Skipping timeout check for orchestrator task (type: {task_type})")
                continue
            
            # Set timeout for non-orchestrator tasks
            timeout = self.task_stuck_timeout
            
            task_age_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))).total_seconds()
            logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] Task {task_id}: Age {task_age_seconds:.1f}s (timeout: {timeout}s)")
                
            if self._is_past_timeout(task['generation_started_at'], timeout):
                logger.error(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] ❌ STUCK TASK DETECTED: {task_id} ({task_age_seconds:.1f}s > {timeout}s)")
                await self._mark_worker_error(worker, f'Stuck task {task_id} (timeout: {timeout}s, age: {task_age_seconds:.1f}s)')
                return True
        
        # Check VRAM health (if available)
        metadata = worker.get('metadata', {})
        if 'vram_timestamp' in metadata:
            vram_age_seconds = datetime.now(timezone.utc).timestamp() - float(metadata['vram_timestamp'])
            gpu_health_timeout = int(os.getenv("GPU_HEALTH_CHECK_TIMEOUT_SEC", "120"))
            logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] VRAM data age: {vram_age_seconds:.1f}s (timeout: {gpu_health_timeout}s)")
            
            if vram_age_seconds > gpu_health_timeout:
                # VRAM data is stale but not necessarily an error - just log it
                logger.warning(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] ⚠️  VRAM data is stale ({vram_age_seconds:.1f}s old)")
        else:
            logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] No VRAM data available")
        
        logger.info(f"💓 HEARTBEAT_CHECK [Worker {worker_id}] ✅ Health check passed")
        return False
    
    async def _collect_worker_diagnostics(self, worker: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """Collect comprehensive diagnostic information from a failing worker before termination."""
        worker_id = worker['id']
        runpod_id = worker.get('metadata', {}).get('runpod_id')
        
        diagnostics = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'worker_id': worker_id,
            'runpod_id': runpod_id,
            'error_reason': reason,
            'collection_success': False
        }
        
        logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] Collecting diagnostic information before termination")
        
        try:
            # 1. Collect worker metadata (VRAM, heartbeat, etc.)
            metadata = worker.get('metadata', {})
            diagnostics['last_heartbeat'] = worker.get('last_heartbeat')
            diagnostics['worker_status'] = worker.get('status')
            diagnostics['worker_created_at'] = worker.get('created_at')
            
            # VRAM information
            if 'vram_total_mb' in metadata:
                diagnostics['vram_total_mb'] = metadata['vram_total_mb']
                diagnostics['vram_used_mb'] = metadata.get('vram_used_mb')
                diagnostics['vram_timestamp'] = metadata.get('vram_timestamp')
                if diagnostics['vram_total_mb'] and diagnostics['vram_used_mb']:
                    diagnostics['vram_usage_percent'] = (diagnostics['vram_used_mb'] / diagnostics['vram_total_mb']) * 100
                logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] VRAM: {diagnostics.get('vram_used_mb', 0)}/{diagnostics.get('vram_total_mb', 0)} MB ({diagnostics.get('vram_usage_percent', 0):.1f}%)")
            
            # 2. Get running tasks information
            try:
                running_tasks = await self.db.get_running_tasks_for_worker(worker_id)
                diagnostics['running_tasks_count'] = len(running_tasks)
                diagnostics['running_tasks'] = [
                    {
                        'id': str(task['id']),
                        'task_type': task.get('task_type'),
                        'started_at': task.get('generation_started_at'),
                        'age_seconds': (datetime.now(timezone.utc) - datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))).total_seconds() if task.get('generation_started_at') else None
                    }
                    for task in running_tasks[:5]  # Limit to first 5 tasks
                ]
                logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] Running tasks: {len(running_tasks)}")
            except Exception as e:
                logger.warning(f"📋 DIAGNOSTICS [Worker {worker_id}] Could not fetch running tasks: {e}")
                diagnostics['running_tasks_error'] = str(e)
            
            # 3. Get RunPod pod status
            if runpod_id:
                try:
                    pod_status = self.runpod.get_pod_status(runpod_id)
                    if pod_status:
                        diagnostics['pod_status'] = {
                            'desired_status': pod_status.get('desired_status'),
                            'actual_status': pod_status.get('actual_status'),
                            'uptime_seconds': pod_status.get('uptime_seconds'),
                            'cost_per_hr': pod_status.get('cost_per_hr'),
                            'last_status_change': pod_status.get('last_status_change')
                        }
                        logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] Pod status: {pod_status.get('desired_status')} (uptime: {pod_status.get('uptime_seconds', 0)}s)")
                    else:
                        logger.warning(f"📋 DIAGNOSTICS [Worker {worker_id}] Could not get pod status from RunPod API")
                        diagnostics['pod_status_error'] = 'RunPod API returned None'
                except Exception as e:
                    logger.warning(f"📋 DIAGNOSTICS [Worker {worker_id}] Error getting pod status: {e}")
                    diagnostics['pod_status_error'] = str(e)
                
                # 4. Try to get git deployment info via SSH (critical for debugging)
                try:
                    if runpod_id and metadata.get('ssh_details'):
                        logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] Fetching git deployment information")
                        
                        # Get git commit hash and branch
                        git_cmd = "cd /workspace/Headless-Wan2GP && git rev-parse HEAD && git rev-parse --abbrev-ref HEAD && git status --porcelain | wc -l"
                        
                        try:
                            result = self.runpod.execute_command_on_worker(runpod_id, git_cmd, timeout=5)
                            if result:
                                exit_code, stdout, stderr = result
                                if exit_code == 0 and stdout:
                                    lines = stdout.strip().split('\n')
                                    if len(lines) >= 2:
                                        diagnostics['git_commit'] = lines[0].strip()
                                        diagnostics['git_branch'] = lines[1].strip()
                                        if len(lines) >= 3:
                                            uncommitted = lines[2].strip()
                                            diagnostics['git_uncommitted_changes'] = int(uncommitted) if uncommitted.isdigit() else 0
                                        logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] ✅ Git: {lines[1].strip()}@{lines[0].strip()[:8]}")
                                else:
                                    diagnostics['git_info_error'] = f'Command failed: exit {exit_code}'
                            else:
                                diagnostics['git_info_error'] = 'SSH command returned None'
                        except Exception as e:
                            logger.warning(f"📋 DIAGNOSTICS [Worker {worker_id}] Could not fetch git info: {e}")
                            diagnostics['git_info_error'] = str(e)
                    else:
                        diagnostics['git_info_error'] = 'No SSH details available'
                except Exception as e:
                    logger.warning(f"📋 DIAGNOSTICS [Worker {worker_id}] Error collecting git info: {e}")
                    diagnostics['git_info_error'] = str(e)
                
                # 5. Save reference to system_logs for later viewing
                # NOTE: We don't copy logs here - they're already in system_logs table
                # The viewer script will query system_logs directly to display logs
                diagnostics['logs_available_in_system_logs'] = True
                diagnostics['logs_note'] = 'Worker logs are stored in system_logs table. Use query_logs.py --worker-timeline to view.'
                logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] Worker logs available in system_logs table")
            
            diagnostics['collection_success'] = True
            logger.info(f"📋 DIAGNOSTICS [Worker {worker_id}] ✅ Diagnostic collection completed successfully")
            
        except Exception as e:
            logger.error(f"📋 DIAGNOSTICS [Worker {worker_id}] ❌ Error collecting diagnostics: {e}")
            diagnostics['collection_error'] = str(e)
        
        return diagnostics
    
    async def _mark_worker_error(self, worker: Dict[str, Any], reason: str):
        """Mark a worker as error and attempt to terminate it."""
        worker_id = worker['id']
        
        logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] MARKING AS ERROR: {reason}")
        
        # FIRST: Collect comprehensive diagnostics before we lose the worker
        diagnostics = await self._collect_worker_diagnostics(worker, reason)
        
        # Save diagnostics to database in worker metadata
        try:
            metadata_update = {
                'error_reason': reason,
                'error_time': datetime.now(timezone.utc).isoformat(),
                'diagnostics': diagnostics
            }
            logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] Saving diagnostic data to database")
        except Exception as e:
            logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] Failed to prepare diagnostic metadata: {e}")
            # Fall back to simple error metadata
            metadata_update = {
                'error_reason': reason,
                'error_time': datetime.now(timezone.utc).isoformat()
            }
        
        # Reset any orphaned tasks from this worker before marking it as error
        # This ensures tasks get re-queued immediately and aren't lost
        reset_count = await self.db.reset_orphaned_tasks([worker_id])
        if reset_count > 0:
            logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] Reset {reset_count} orphaned tasks")
        
        # Mark worker as error in DB with diagnostics
        success = await self.db.update_worker_status(worker_id, 'error', metadata_update)
        if success:
            logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ✅ Database updated with error status and diagnostics")
        else:
            logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ❌ Failed to update database with error status")

        # Also update local copy so the rest of this cycle treats it as error
        worker['status'] = 'error'
        
        # Attempt to terminate the Runpod instance
        runpod_id = worker.get('metadata', {}).get('runpod_id')
        if runpod_id:
            logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] Attempting to terminate RunPod instance: {runpod_id}")
            try:
                success = self.runpod.terminate_worker(runpod_id)
                if success:
                    logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ✅ RunPod instance terminated successfully")
                else:
                    logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ❌ Failed to terminate RunPod instance")
            except Exception as e:
                logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ❌ Exception terminating RunPod instance: {e}")
        else:
            logger.warning(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] No RunPod ID found - cannot terminate instance")
        
        logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] Error marking completed - Reason: {reason}")
    
    async def _is_worker_idle(self, worker: Dict[str, Any]) -> bool:
        """
        Check if a worker is idle and has been idle long enough to terminate.
        Uses GPU_IDLE_TIMEOUT_SEC to determine when an idle worker should be scaled down.
        """
        return await self._is_worker_idle_with_timeout(worker, self.gpu_idle_timeout)
    
    async def _is_worker_idle_with_timeout(self, worker: Dict[str, Any], timeout_seconds: int) -> bool:
        """
        Check if a worker is idle and has been idle long enough to terminate.
        Uses actual last task completion time, NOT heartbeat time.
        """
        # First check if worker has any running tasks
        has_tasks = await self.db.has_running_tasks(worker['id'])
        if has_tasks:
            return False  # Worker is busy, not idle
        
        # Check if we have recent task completions (last 30 seconds)
        recent_completions = await self._check_recent_task_completions(worker['id'])
        if recent_completions > 0:
            # Worker completed tasks recently, so it's not idle long enough
            return False
        
        # Worker has no recent completions - find the actual last task completion time
        # We need to query the database for the most recent completed task
        try:
            result = self.db.supabase.table('tasks').select('generation_processed_at, updated_at') \
                .eq('worker_id', worker['id']) \
                .eq('status', 'Complete') \
                .order('generation_processed_at', desc=True) \
                .limit(1) \
                .execute()
            
            if result.data:
                # Use generation_processed_at if available, otherwise updated_at
                last_completion_time = result.data[0].get('generation_processed_at') or result.data[0].get('updated_at')
                if last_completion_time:
                    last_completion_dt = datetime.fromisoformat(last_completion_time.replace('Z', '+00:00'))
                    if last_completion_dt.tzinfo is None:
                        last_completion_dt = last_completion_dt.replace(tzinfo=timezone.utc)
                    
                    # Calculate time since last task completion
                    idle_time = (datetime.now(timezone.utc) - last_completion_dt).total_seconds()
                    
                    # Worker is idle if it hasn't completed a task in timeout_seconds
                    return idle_time > timeout_seconds
            
            # No completed tasks found - use worker creation time as baseline
            created_dt = datetime.fromisoformat(worker['created_at'].replace('Z', '+00:00'))
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            
            worker_age = (datetime.now(timezone.utc) - created_dt).total_seconds()
            return worker_age > timeout_seconds
            
        except Exception as e:
            logger.error(f"Error checking idle time for worker {worker['id']}: {e}")
            # Fall back to original behavior (use heartbeat)
            last_activity = worker.get('last_heartbeat', worker['created_at'])
            last_activity_dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
            if last_activity_dt.tzinfo is None:
                last_activity_dt = last_activity_dt.replace(tzinfo=timezone.utc)
            idle_time = (datetime.now(timezone.utc) - last_activity_dt).total_seconds()
            return idle_time > timeout_seconds
    
    async def _should_scale_up(self, queued_count: int, active_count: int) -> bool:
        """Determine if we should scale up based on queue depth."""
        if active_count == 0:
            return queued_count > 0  # Always scale up if we have tasks but no workers
        
        # With 1:1 mapping, scale up if we have more queued tasks than active workers
        return queued_count > active_count
    
    def _calculate_workers_needed(self, queued_count: int, active_count: int) -> int:
        """Calculate how many additional workers are needed."""
        if active_count == 0 and queued_count > 0:
            # No active workers but have queued tasks
            # Spawn at least 1 worker, or MIN_ACTIVE_GPUS if higher
            return max(1, self.min_active_gpus)
        
        # Use 1:1 mapping - one worker per total task (stable)
        # Note: This uses queued_count since it's for calculating additional workers needed
        ideal_workers = max(self.min_active_gpus, queued_count)
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
                if 'ram_tier' in result:
                    metadata['ram_tier'] = result['ram_tier']  # Track which RAM tier was allocated
                if 'storage_volume' in result:
                    metadata['storage_volume'] = result['storage_volume']  # Track which storage volume was used
                
                # CRITICAL: Check if database update succeeds
                update_success = await self.db.update_worker_status(worker_id, final_status, metadata)
                if not update_success:
                    logger.error(f"CRITICAL: Failed to update worker {worker_id} in database but RunPod pod {pod_id} was created!")
                    logger.error(f"This will create an orphaned pod. Attempting to terminate pod {pod_id}")
                    
                    # Attempt to terminate the orphaned pod immediately
                    try:
                        self.runpod.terminate_worker(pod_id)
                        logger.info(f"Successfully terminated orphaned pod {pod_id}")
                    except Exception as cleanup_e:
                        logger.error(f"Failed to cleanup orphaned pod {pod_id}: {cleanup_e}")
                        logger.error(f"MANUAL INTERVENTION REQUIRED: Orphaned pod {pod_id} for worker {worker_id}")
                    
                    return False
                
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
        
        logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] TERMINATING worker")
        logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] RunPod ID: {runpod_id or 'None'}")
        
        try:
            # Terminate Runpod instance
            if runpod_id:
                logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] Calling RunPod API to terminate instance...")
                success = self.runpod.terminate_worker(runpod_id)
                if not success:
                    logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ❌ RunPod termination FAILED")
                    logger.warning(f"Failed to terminate Runpod instance {runpod_id} for worker {worker_id}")
                    return False  # Don't update database if RunPod termination failed
                
                logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ✅ RunPod instance terminated successfully")
                
                # Only update worker status if RunPod termination succeeded
                termination_metadata = {'terminated_at': datetime.now(timezone.utc).isoformat()}
                await self.db.update_worker_status(worker_id, 'terminated', termination_metadata)
                
                logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ✅ Database status updated to 'terminated'")
                return True
            else:
                # No runpod_id means worker was never spawned successfully
                logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] No RunPod instance to terminate")
                termination_metadata = {'terminated_at': datetime.now(timezone.utc).isoformat()}
                await self.db.update_worker_status(worker_id, 'terminated', termination_metadata)
                
                logger.info(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ✅ Database status updated to 'terminated' (no RunPod instance)")
                return True
            
        except Exception as e:
            logger.error(f"🔄 WORKER_LIFECYCLE [Worker {worker_id}] ❌ TERMINATION FAILED: {e}")
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
    
    async def _check_worker_failure_rate(self) -> bool:
        """
        Check if the worker failure rate is too high, indicating a systemic issue.
        Returns True if failure rate is acceptable, False if too high.
        """
        try:
            # Get workers from the last failure_window_minutes
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=self.failure_window_minutes)
            
            recent_workers = []
            workers = await self.db.get_workers(['spawning', 'active', 'terminating', 'error', 'terminated'])
            
            for worker in workers:
                worker_time = worker.get('updated_at', worker.get('created_at'))
                if worker_time:
                    try:
                        worker_dt = datetime.fromisoformat(worker_time.replace('Z', '+00:00'))
                        if worker_dt > cutoff_time:
                            recent_workers.append(worker)
                    except Exception:
                        pass
            
            if len(recent_workers) < self.min_workers_for_rate_check:
                # Not enough workers to calculate meaningful failure rate
                return True
            
            failed_workers = [w for w in recent_workers if w['status'] in ['error', 'terminated']]
            failure_rate = len(failed_workers) / len(recent_workers)
            
            logger.info(f"[FAILURE_RATE] Recent workers: {len(recent_workers)}, Failed: {len(failed_workers)}, Rate: {failure_rate:.2%}")
            
            if failure_rate > self.max_failure_rate:
                logger.error(f"[FAILURE_RATE] CRITICAL: Worker failure rate ({failure_rate:.2%}) exceeds threshold ({self.max_failure_rate:.2%})")
                logger.error(f"[FAILURE_RATE] This indicates a systemic issue (SSH auth, image problems, etc.)")
                logger.error(f"[FAILURE_RATE] Stopping new worker spawning to prevent endless spin-ups")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking worker failure rate: {e}")
            return True  # Default to allowing spawning if we can't check
    
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
        worker_id = worker['id']
        logger.info(f"💓 HEALTH_CHECK [Worker {worker_id}] Starting basic health check")
        
        try:
            metadata = worker.get('metadata', {})
            runpod_id = metadata.get('runpod_id')
            
            if not runpod_id:
                logger.error(f"💓 HEALTH_CHECK [Worker {worker_id}] ❌ No RunPod ID found")
                return False
            
            logger.info(f"💓 HEALTH_CHECK [Worker {worker_id}] Checking RunPod status for pod {runpod_id}")
            
            # Check if the pod is still running
            pod_status = self.runpod.get_pod_status(runpod_id)
            if not pod_status:
                logger.error(f"💓 HEALTH_CHECK [Worker {worker_id}] ❌ Could not get pod status from RunPod API")
                return False
            
            logger.info(f"💓 HEALTH_CHECK [Worker {worker_id}] Pod status: {pod_status.get('desired_status', 'UNKNOWN')}")
            
            # Pod should be in RUNNING state
            if pod_status.get('desired_status') != 'RUNNING':
                logger.warning(f"💓 HEALTH_CHECK [Worker {worker_id}] ⚠️  Pod not in RUNNING state: {pod_status.get('desired_status')}")
                return False
            
            # Optionally check SSH connectivity (quick timeout)
            ssh_details = metadata.get('ssh_details', {})
            if ssh_details and 'ip' in ssh_details and 'port' in ssh_details:
                logger.info(f"💓 HEALTH_CHECK [Worker {worker_id}] Testing SSH connectivity to {ssh_details['ip']}:{ssh_details['port']}")
                
                # This is a lightweight check - just see if port is open
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)  # 5 second timeout
                try:
                    result = sock.connect_ex((ssh_details['ip'], ssh_details['port']))
                    sock.close()
                    if result == 0:
                        logger.info(f"💓 HEALTH_CHECK [Worker {worker_id}] ✅ SSH port is accessible")
                        return True
                    else:
                        logger.warning(f"💓 HEALTH_CHECK [Worker {worker_id}] ⚠️  SSH port not accessible (result: {result})")
                        return False
                except Exception as ssh_e:
                    logger.warning(f"💓 HEALTH_CHECK [Worker {worker_id}] ⚠️  SSH connectivity test failed: {ssh_e}")
                    return False
            
            # If we can't check SSH, assume healthy if pod is running
            logger.info(f"💓 HEALTH_CHECK [Worker {worker_id}] ✅ Pod is running (SSH check skipped)")
            return True
            
        except Exception as e:
            logger.error(f"💓 HEALTH_CHECK [Worker {worker_id}] ❌ Health check failed: {e}")
            return False 
    
    async def _check_error_worker_cleanup(self, worker: Dict[str, Any]) -> None:
        """
        Check workers marked as error and ensure RunPod instances are properly terminated.
        This catches cases where _mark_worker_error failed to terminate the RunPod instance.
        """
        worker_id = worker['id']
        metadata = worker.get('metadata', {})
        runpod_id = metadata.get('runpod_id')
        error_reason = metadata.get('error_reason', 'Unknown error')
        self_terminated = metadata.get('self_terminated', False)
        
        # Log the error reason for visibility
        if self_terminated:
            logger.info(f"[ERROR_CLEANUP] Worker {worker_id} self-terminated: {error_reason}")
        else:
            logger.debug(f"[ERROR_CLEANUP] Error worker {worker_id}: {error_reason}")
        
        # Check how long the worker has been in error state
        error_time_str = metadata.get('error_time')
        if error_time_str:
            try:
                error_time = datetime.fromisoformat(error_time_str.replace('Z', '+00:00'))
                error_age = (datetime.now(timezone.utc) - error_time).total_seconds()
                
                # Grace period before forced cleanup (10 minutes)
                ERROR_CLEANUP_GRACE_PERIOD = int(os.getenv("ERROR_CLEANUP_GRACE_PERIOD_SEC", "600"))
                
                if error_age > ERROR_CLEANUP_GRACE_PERIOD:
                    logger.info(f"[ERROR_CLEANUP] Worker {worker_id} past grace period ({error_age:.0f}s), forcing cleanup")
                    logger.info(f"[ERROR_CLEANUP] Reason: {error_reason}")
                    
                    # Check if RunPod instance is still running
                    if runpod_id:
                        pod_status = self.runpod.get_pod_status(runpod_id)
                        if pod_status and pod_status.get('desired_status') not in ['TERMINATED', 'FAILED']:
                            logger.warning(f"RunPod {runpod_id} still running for error worker {worker_id}, force terminating")
                            try:
                                self.runpod.terminate_worker(runpod_id)
                                logger.info(f"Force terminated RunPod {runpod_id}")
                            except Exception as e:
                                logger.error(f"Failed to force terminate RunPod {runpod_id}: {e}")
                    
                    # Mark as terminated to move it out of error state
                    await self.db.update_worker_status(worker_id, 'terminated')
                    logger.info(f"Marked error worker {worker_id} as terminated")
                else:
                    logger.debug(f"[ERROR_CLEANUP] Worker {worker_id} still in grace period ({error_age:.0f}s < {ERROR_CLEANUP_GRACE_PERIOD}s) - Reason: {error_reason}")
                    
            except Exception as e:
                logger.error(f"Error parsing error_time for worker {worker_id}: {e}")
                # If we can't parse the time, assume it's been long enough
                if runpod_id:
                    try:
                        self.runpod.terminate_worker(runpod_id)
                        await self.db.update_worker_status(worker_id, 'terminated')
                        logger.info(f"Force cleaned up unparseable error worker {worker_id}")
                    except Exception as cleanup_e:
                        logger.error(f"Failed to cleanup error worker {worker_id}: {cleanup_e}")
        else:
            # No error_time means old error format - clean it up
            logger.warning(f"[ERROR_CLEANUP] Worker {worker_id} has no error_time, forcing immediate cleanup")
            logger.warning(f"[ERROR_CLEANUP] Reason: {error_reason}")
            if runpod_id:
                try:
                    self.runpod.terminate_worker(runpod_id)
                    await self.db.update_worker_status(worker_id, 'terminated')
                    logger.info(f"[ERROR_CLEANUP] Cleaned up legacy error worker {worker_id}")
                except Exception as e:
                    logger.error(f"[ERROR_CLEANUP] Failed to cleanup legacy error worker {worker_id}: {e}")
    
    async def _failsafe_stale_worker_check(self, workers: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
        """
        Failsafe check for workers with very stale heartbeats regardless of status.
        This catches edge cases where workers slip through normal health checks.
        Also checks for zombie workers marked as 'terminated' but still running in RunPod.
        
        Uses the same timeout as other heartbeat checks (GPU_IDLE_TIMEOUT_SEC) for consistency.
        All workers should be detected as dead within the same timeframe, regardless of state.
        """
        # Use same timeout as other heartbeat checks for consistency (default 300s = 5 minutes)
        FAILSAFE_STALE_THRESHOLD = self.gpu_idle_timeout
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=FAILSAFE_STALE_THRESHOLD)
        
        stale_workers = []
        zombie_workers = []
        
        for worker in workers:
            # Check for zombie workers (marked terminated but may still be running in RunPod)
            if worker['status'] == 'terminated':
                runpod_id = worker.get('metadata', {}).get('runpod_id')
                if runpod_id:
                    # Only check recently terminated workers to avoid performance issues
                    # Workers terminated more than 1 hour ago are likely truly terminated
                    try:
                        terminated_at = worker.get('metadata', {}).get('terminated_at')
                        if terminated_at:
                            terminated_dt = datetime.fromisoformat(terminated_at.replace('Z', '+00:00'))
                            # Only check workers terminated in the last hour
                            if (datetime.now(timezone.utc) - terminated_dt).total_seconds() < 3600:
                                zombie_workers.append(worker)
                        else:
                            # No termination timestamp - check it (old worker)
                            zombie_workers.append(worker)
                    except Exception as e:
                        logger.error(f"Error parsing terminated_at for zombie check on {worker['id']}: {e}")
                        # If we can't parse the date, check it to be safe
                        zombie_workers.append(worker)
                continue
            
            last_heartbeat = worker.get('last_heartbeat')
            if last_heartbeat:
                try:
                    heartbeat_dt = datetime.fromisoformat(last_heartbeat.replace('Z', '+00:00'))
                    if heartbeat_dt < cutoff_time:
                        stale_workers.append(worker)
                except Exception as e:
                    logger.error(f"Error parsing heartbeat for failsafe check on {worker['id']}: {e}")
            else:
                # No heartbeat at all - check creation time
                try:
                    created_dt = datetime.fromisoformat(worker['created_at'].replace('Z', '+00:00'))
                    if created_dt < cutoff_time:
                        stale_workers.append(worker)
                except Exception as e:
                    logger.error(f"Error parsing created_at for failsafe check on {worker['id']}: {e}")
        
        for worker in stale_workers:
            worker_id = worker['id']
            last_heartbeat = worker.get('last_heartbeat', 'never')
            current_status = worker['status']
            
            logger.warning(f"FAILSAFE: Worker {worker_id} has stale heartbeat ({last_heartbeat}) and status {current_status}")
            
            # Force cleanup regardless of current status
            try:
                metadata = worker.get('metadata', {})
                runpod_id = metadata.get('runpod_id')
                
                if runpod_id:
                    # Check if RunPod is still running
                    pod_status = self.runpod.get_pod_status(runpod_id)
                    if pod_status and pod_status.get('desired_status') not in ['TERMINATED', 'FAILED']:
                        logger.warning(f"FAILSAFE: Terminating RunPod {runpod_id} for stale worker {worker_id}")
                        self.runpod.terminate_worker(runpod_id)
                
                # Reset any orphaned tasks
                reset_count = await self.db.reset_orphaned_tasks([worker_id])
                if reset_count > 0:
                    logger.info(f"FAILSAFE: Reset {reset_count} orphaned tasks from {worker_id}")
                    summary['actions']['tasks_reset'] += reset_count
                
                # Mark as terminated
                await self.db.update_worker_status(worker_id, 'terminated')
                summary['actions']['workers_failed'] += 1
                
                logger.warning(f"FAILSAFE: Cleaned up stale worker {worker_id}")
                
            except Exception as e:
                logger.error(f"FAILSAFE: Failed to cleanup stale worker {worker_id}: {e}")
        
        # EFFICIENT ZOMBIE DETECTION: Check RunPod directly (runs every 10th cycle to avoid performance issues)
        await self._efficient_zombie_check(summary)
    
    async def _efficient_zombie_check(self, summary: Dict[str, Any]) -> None:
        """
        Bidirectional zombie detection (runs every 10th cycle):
        
        1. Forward check: RunPod pods without DB records (orphaned pods)
           - Finds pods in RunPod that don't exist in database
           - Terminates them to prevent billing
        
        2. Reverse check: DB workers without RunPod pods (externally terminated)
           - Finds active/spawning workers in DB that don't exist in RunPod
           - Marks them as error and resets their tasks
           - Catches workers manually terminated in RunPod console
        
        This provides fast detection (within 5 minutes) of external terminations,
        much faster than waiting for heartbeat timeout.
        """
        # Only run zombie check every 10th cycle to avoid performance impact
        if self.cycle_count % 10 != 0:
            return
            
        try:
            logger.info("Running efficient zombie check (every 10th cycle)")
            
            # Get all active pods from RunPod
            import runpod
            runpod.api_key = os.getenv('RUNPOD_API_KEY')
            
            pods = runpod.get_pods()
            gpu_worker_pods = [
                pod for pod in pods 
                if pod.get('name', '').startswith('gpu-') and 
                   pod.get('desiredStatus') not in ['TERMINATED', 'FAILED']
            ]
            
            if not gpu_worker_pods:
                logger.debug("No active GPU worker pods found in RunPod")
                return
                
            logger.info(f"Found {len(gpu_worker_pods)} active GPU worker pods in RunPod")
            
            # Get all workers from database
            db_workers = await self.db.get_workers()
            db_worker_names = {w['id'] for w in db_workers if w['status'] != 'terminated'}
            
            # Find zombies: RunPod pods that don't exist in DB or are marked terminated
            zombies_found = 0
            for pod in gpu_worker_pods:
                pod_name = pod.get('name')
                runpod_id = pod.get('id')
                
                if pod_name not in db_worker_names:
                    logger.warning(f"ZOMBIE DETECTED: RunPod pod {pod_name} ({runpod_id}) not found in active database workers")
                    
                    # Terminate the zombie pod
                    try:
                        success = self.runpod.terminate_worker(runpod_id)
                        if success:
                            logger.warning(f"ZOMBIE CLEANUP: Successfully terminated orphaned RunPod {runpod_id}")
                            summary['actions']['workers_terminated'] += 1
                            zombies_found += 1
                        else:
                            logger.error(f"ZOMBIE CLEANUP: Failed to terminate orphaned RunPod {runpod_id}")
                    except Exception as e:
                        logger.error(f"ZOMBIE CLEANUP: Error terminating orphaned RunPod {runpod_id}: {e}")
            
            if zombies_found > 0:
                logger.warning(f"Efficient zombie check: Found and terminated {zombies_found} orphaned RunPod pods")
            else:
                logger.debug("Efficient zombie check: No orphaned RunPod pods found")
            
            # BIDIRECTIONAL CHECK: Find DB workers that don't exist in RunPod (externally terminated)
            # This catches workers that were manually terminated in RunPod console
            runpod_pod_ids = {pod.get('id') for pod in gpu_worker_pods}
            runpod_pod_names = {pod.get('name') for pod in gpu_worker_pods}
            
            externally_terminated = 0
            for worker in db_workers:
                if worker['status'] in ['active', 'spawning']:
                    runpod_id = worker.get('metadata', {}).get('runpod_id')
                    worker_id = worker['id']
                    
                    # Check if this worker's RunPod pod still exists
                    if runpod_id and runpod_id not in runpod_pod_ids and worker_id not in runpod_pod_names:
                        logger.warning(f"EXTERNALLY TERMINATED: Worker {worker_id} (RunPod {runpod_id}) no longer exists in RunPod")
                        
                        # Mark as error and reset any orphaned tasks
                        try:
                            await self._mark_worker_error(worker, 'Pod externally terminated - not found in RunPod')
                            summary['actions']['workers_failed'] += 1
                            externally_terminated += 1
                        except Exception as e:
                            logger.error(f"Error marking externally terminated worker {worker_id}: {e}")
            
            if externally_terminated > 0:
                logger.warning(f"Bidirectional check: Found {externally_terminated} externally terminated workers")
            else:
                logger.debug("Bidirectional check: No externally terminated workers found")
                
        except Exception as e:
            logger.error(f"Error during efficient zombie check: {e}")