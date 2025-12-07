"""Unified client for debugging data access."""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from collections import Counter
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from gpu_orchestrator.database import DatabaseClient
from supabase import create_client
from scripts.debug.models import (
    TaskInfo, WorkerInfo, TasksSummary, WorkersSummary,
    SystemHealth, OrchestratorStatus
)


class LogQueryClient:
    """Client for querying system logs from Supabase."""
    
    def __init__(self):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
        
        self.supabase = create_client(supabase_url, supabase_key)
    
    def get_logs(
        self,
        start_time: datetime = None,
        end_time: datetime = None,
        source_type: str = None,
        source_id: str = None,
        worker_id: str = None,
        task_id: str = None,
        log_level: str = None,
        cycle_number: int = None,
        search_term: str = None,
        limit: int = 1000,
        order_desc: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Query logs with flexible filters.
        
        Args:
            start_time: Filter logs after this time (default: 24 hours ago)
            end_time: Filter logs before this time (default: now)
            source_type: Filter by source type ('orchestrator_gpu', 'orchestrator_api', 'worker')
            source_id: Filter by specific source ID
            worker_id: Filter by worker ID
            task_id: Filter by task ID
            log_level: Filter by log level ('ERROR', 'WARNING', etc.)
            cycle_number: Filter by orchestrator cycle number
            search_term: Search in message text
            limit: Maximum number of results
            order_desc: Order by timestamp descending
        
        Returns:
            List of log entry dictionaries
        """
        
        # Default time range: last 24 hours
        if not start_time:
            start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        if not end_time:
            end_time = datetime.now(timezone.utc)
        
        # Build query
        query = self.supabase.table('system_logs').select('*')
        
        # Apply filters
        query = query.gte('timestamp', start_time.isoformat())
        query = query.lte('timestamp', end_time.isoformat())
        
        if source_type:
            query = query.eq('source_type', source_type)
        if source_id:
            query = query.eq('source_id', source_id)
        if worker_id:
            query = query.eq('worker_id', worker_id)
        if task_id:
            query = query.eq('task_id', task_id)
        if log_level:
            query = query.eq('log_level', log_level)
        if cycle_number is not None:
            query = query.eq('cycle_number', cycle_number)
        if search_term:
            query = query.ilike('message', f'%{search_term}%')
        
        # Order and limit
        query = query.order('timestamp', desc=order_desc)
        query = query.limit(limit)
        
        result = query.execute()
        return result.data or []
    
    def get_task_timeline(self, task_id: str) -> List[Dict[str, Any]]:
        """Get timeline of logs for a specific task."""
        return self.get_logs(
            task_id=task_id,
            limit=1000,
            order_desc=False  # Chronological order
        )


class DebugClient:
    """Unified client for all debugging data."""
    
    def __init__(self):
        self.log_client = LogQueryClient()
        self.db = DatabaseClient()
    
    # ==================== TASK METHODS ====================
    
    def get_task_info(self, task_id: str) -> TaskInfo:
        """Get complete task information: logs + DB state."""
        # Get logs for this task
        logs = self.log_client.get_task_timeline(task_id)
        
        # Get task state from DB
        result = self.db.supabase.table('tasks').select('*').eq('id', task_id).execute()
        state = result.data[0] if result.data else None
        
        return TaskInfo(
            task_id=task_id,
            state=state,
            logs=logs
        )
    
    # ==================== WORKER METHODS ====================
    
    def get_worker_info(self, worker_id: str, hours: int = 24, startup: bool = False) -> WorkerInfo:
        """Get complete worker information: logs + DB state + tasks."""
        # Get logs for this worker (both as worker_id and source_id)
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        if startup:
            # For startup mode, get startup-specific logs
            logs = self.log_client.get_logs(
                start_time=start_time,
                source_id=worker_id,
                limit=1000,
                order_desc=False
            )
            # Filter for startup-related messages
            logs_sorted = [log for log in logs if any(keyword in log.get('message', '').lower() 
                for keyword in ['startup', 'initializ', 'loading', 'installing', 'model', 'cuda', 'torch'])]
        else:
            # Query logs where worker is mentioned
            logs = self.log_client.get_logs(
                start_time=start_time,
                worker_id=worker_id,
                limit=5000,
                order_desc=False
            )
            
            # Also get logs where worker is the source
            source_logs = self.log_client.get_logs(
                start_time=start_time,
                source_id=worker_id,
                limit=5000,
                order_desc=False
            )
            
            # Combine and deduplicate by timestamp
            all_logs = {log['timestamp']: log for log in logs + source_logs}
            logs_sorted = sorted(all_logs.values(), key=lambda x: x['timestamp'])
        
        # Get worker state from DB
        result = self.db.supabase.table('workers').select('*').eq('id', worker_id).execute()
        state = result.data[0] if result.data else None
        
        # Get tasks assigned to this worker
        tasks_result = self.db.supabase.table('tasks').select('*').eq('worker_id', worker_id).order('created_at', desc=True).limit(20).execute()
        tasks = tasks_result.data or []
        
        return WorkerInfo(
            worker_id=worker_id,
            state=state,
            logs=logs_sorted,
            tasks=tasks
        )
    
    def check_worker_logging(self, worker_id: str) -> Dict[str, Any]:
        """Check if worker has started logging (i.e., worker.py is running)."""
        # Check for logs from worker.py (these have worker_id set)
        logs = self.log_client.get_logs(
            worker_id=worker_id,
            limit=10,
            order_desc=True
        )
        
        return {
            'is_logging': len(logs) > 0,
            'log_count': len(logs),
            'recent_logs': logs[:5] if logs else []
        }
    
    # ==================== MULTI-TASK METHODS ====================
    
    def get_recent_tasks(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        worker_id: Optional[str] = None,
        hours: Optional[int] = None
    ) -> TasksSummary:
        """Get recent tasks with analysis."""
        # Build query
        query = self.db.supabase.table('tasks').select('*')
        
        if status:
            query = query.eq('status', status)
        if task_type:
            query = query.eq('task_type', task_type)
        if worker_id:
            query = query.eq('worker_id', worker_id)
        if hours:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            query = query.gte('created_at', cutoff.isoformat())
        
        query = query.order('created_at', desc=True).limit(limit)
        result = query.execute()
        tasks = result.data or []
        
        # Calculate statistics
        status_dist = Counter(t.get('status') for t in tasks)
        type_dist = Counter(t.get('task_type') for t in tasks)
        
        # Calculate timing statistics
        processing_times = []
        queue_times = []
        
        for task in tasks:
            if task.get('generation_started_at') and task.get('generation_processed_at'):
                try:
                    started = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                    processed = datetime.fromisoformat(task['generation_processed_at'].replace('Z', '+00:00'))
                    processing_times.append((processed - started).total_seconds())
                except:
                    pass
            
            if task.get('created_at') and task.get('generation_started_at'):
                try:
                    created = datetime.fromisoformat(task['created_at'].replace('Z', '+00:00'))
                    started = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                    queue_times.append((started - created).total_seconds())
                except:
                    pass
        
        timing_stats = {
            'avg_processing_seconds': sum(processing_times) / len(processing_times) if processing_times else None,
            'avg_queue_seconds': sum(queue_times) / len(queue_times) if queue_times else None,
            'total_with_timing': len(processing_times)
        }
        
        # Get recent failures from logs
        recent_failures = []
        if hours:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        error_logs = self.log_client.get_logs(
            start_time=cutoff,
            log_level='ERROR',
            limit=100
        )
        
        # Extract task failures
        for log in error_logs:
            if log.get('task_id'):
                recent_failures.append({
                    'task_id': log['task_id'],
                    'timestamp': log['timestamp'],
                    'message': log['message'],
                    'worker_id': log.get('worker_id')
                })
        
        return TasksSummary(
            tasks=tasks,
            total_count=len(tasks),
            status_distribution=dict(status_dist),
            task_type_distribution=dict(type_dist),
            timing_stats=timing_stats,
            recent_failures=recent_failures[:10]
        )
    
    # ==================== MULTI-WORKER METHODS ====================
    
    def get_workers_summary(self, hours: int = 2, detailed: bool = False) -> WorkersSummary:
        """Get workers summary with health status."""
        # Get workers from specified time window
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        result = self.db.supabase.table('workers').select('*').gte('created_at', cutoff_time.isoformat()).order('created_at', desc=True).execute()
        workers = result.data or []
        
        # Calculate statistics
        now = datetime.now(timezone.utc)
        status_counts = Counter(w.get('status') for w in workers)
        
        active_healthy = 0
        active_stale = 0
        
        for worker in workers:
            if worker.get('status') == 'active':
                last_hb = worker.get('last_heartbeat')
                if last_hb:
                    try:
                        hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                        age_seconds = (now - hb_time).total_seconds()
                        if age_seconds < 60:
                            active_healthy += 1
                        else:
                            active_stale += 1
                    except:
                        active_stale += 1
        
        # Get recent failures from logs or metadata
        recent_failures = []
        for worker in workers:
            if worker.get('status') in ['error', 'terminated']:
                metadata = worker.get('metadata', {})
                recent_failures.append({
                    'worker_id': worker['id'],
                    'status': worker['status'],
                    'created_at': worker.get('created_at'),
                    'error_reason': metadata.get('error_reason', 'Unknown')
                })
        
        # Calculate failure rate
        failure_rate = None
        if len(workers) >= 5:
            failed = len([w for w in workers if w['status'] in ['error', 'terminated']])
            failure_rate = failed / len(workers)
        
        return WorkersSummary(
            workers=workers,
            total_count=len(workers),
            status_counts=dict(status_counts),
            active_healthy=active_healthy,
            active_stale=active_stale,
            recent_failures=recent_failures[:10],
            failure_rate=failure_rate
        )
    
    # ==================== SYSTEM HEALTH ====================
    
    def get_system_health(self) -> SystemHealth:
        """Get overall system health."""
        now = datetime.now(timezone.utc)
        
        # Get active workers
        workers_result = self.db.supabase.table('workers').select('*').neq('status', 'terminated').execute()
        workers = workers_result.data or []
        
        workers_active = len([w for w in workers if w['status'] == 'active'])
        workers_spawning = len([w for w in workers if w['status'] == 'spawning'])
        
        # Count healthy workers (heartbeat < 60s)
        workers_healthy = 0
        for worker in workers:
            if worker.get('status') == 'active' and worker.get('last_heartbeat'):
                try:
                    hb_time = datetime.fromisoformat(worker['last_heartbeat'].replace('Z', '+00:00'))
                    if (now - hb_time).total_seconds() < 60:
                        workers_healthy += 1
                except:
                    pass
        
        # Get task counts
        tasks_result = self.db.supabase.table('tasks').select('status').execute()
        tasks = tasks_result.data or []
        
        tasks_queued = len([t for t in tasks if t['status'] == 'Queued'])
        tasks_in_progress = len([t for t in tasks if t['status'] == 'In Progress'])
        
        # Get recent errors
        error_cutoff = now - timedelta(hours=1)
        recent_errors_result = self.log_client.get_logs(
            start_time=error_cutoff,
            log_level='ERROR',
            limit=50
        )
        recent_errors = recent_errors_result[:10]
        
        # Calculate failure rate
        failure_window = now - timedelta(minutes=30)
        recent_workers_result = self.db.supabase.table('workers').select('*').gte('created_at', failure_window.isoformat()).execute()
        recent_workers = recent_workers_result.data or []
        
        failure_rate = None
        failure_rate_status = 'OK'
        
        if len(recent_workers) >= 5:
            failed = len([w for w in recent_workers if w['status'] in ['error', 'terminated']])
            failure_rate = failed / len(recent_workers)
            
            if failure_rate > 0.8:
                failure_rate_status = 'BLOCKED'
            elif failure_rate > 0.5:
                failure_rate_status = 'WARNING'
        
        return SystemHealth(
            timestamp=now,
            workers_active=workers_active,
            workers_spawning=workers_spawning,
            workers_healthy=workers_healthy,
            tasks_queued=tasks_queued,
            tasks_in_progress=tasks_in_progress,
            recent_errors=recent_errors,
            failure_rate=failure_rate,
            failure_rate_status=failure_rate_status
        )
    
    # ==================== ORCHESTRATOR STATUS ====================
    
    def get_orchestrator_status(self, hours: int = 1) -> OrchestratorStatus:
        """Get orchestrator status from logs."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Get recent orchestrator logs
        logs = self.log_client.get_logs(
            start_time=cutoff,
            source_type='orchestrator_gpu',
            limit=1000,
            order_desc=True
        )
        
        # Find last activity and cycle
        last_activity = None
        last_cycle = None
        
        if logs:
            last_activity = datetime.fromisoformat(logs[0]['timestamp'].replace('Z', '+00:00'))
            last_cycle = logs[0].get('cycle_number')
        
        # Determine status
        if last_activity:
            age_minutes = (datetime.now(timezone.utc) - last_activity).total_seconds() / 60
            if age_minutes < 5:
                status = 'HEALTHY'
            elif age_minutes < 15:
                status = 'WARNING'
            else:
                status = 'STALE'
        else:
            status = 'NO_LOGS'
        
        # Extract cycle information
        cycle_starts = [log for log in logs if 'Starting orchestrator cycle' in log.get('message', '')]
        recent_cycles = []
        
        for log in cycle_starts[:10]:
            recent_cycles.append({
                'cycle_number': log.get('cycle_number'),
                'timestamp': log['timestamp'],
                'message': log['message']
            })
        
        return OrchestratorStatus(
            last_activity=last_activity,
            last_cycle=last_cycle,
            status=status,
            recent_cycles=recent_cycles,
            recent_logs=logs[:50]
        )

