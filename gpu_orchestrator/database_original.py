"""
Database helper functions for the Runpod GPU Worker Orchestrator.
Provides interface to Supabase for worker and task management.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from supabase import create_client, Client
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class DatabaseClient:
    """Database client for orchestrator operations."""
    
    def __init__(self):
        load_dotenv()
        
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        
        self.supabase: Client = create_client(supabase_url, supabase_key)
    
    # Task operations
    async def get_tasks(self, status: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get tasks by status."""
        try:
            query = self.supabase.table('tasks').select('*')
            
            if status:
                query = query.in_('status', status)
            
            result = query.execute()
            return result.data or []
            
        except Exception as e:
            logger.error(f"Failed to get tasks: {e}")
            return []
    
    async def count_queued_tasks(self) -> int:
        """Count tasks in Queued status."""
        try:
            result = self.supabase.table('tasks').select('id', count='exact').eq('status', 'Queued').execute()
            return result.count or 0
        except Exception as e:
            logger.error(f"Failed to count queued tasks: {e}")
            return 0
    
    async def get_running_tasks_for_worker(self, worker_id: str) -> List[Dict[str, Any]]:
        """Get running tasks for a specific worker."""
        try:
            result = self.supabase.table('tasks').select('*').eq('worker_id', worker_id).eq('status', 'Running').execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get running tasks for worker {worker_id}: {e}")
            return []
    
    async def reset_orphaned_tasks(self, failed_worker_ids: List[str]) -> int:
        """Reset tasks from failed workers back to Queued status."""
        try:
            result = await self.supabase.rpc('reset_orphaned_tasks', {'failed_worker_ids': failed_worker_ids}).execute()
            return result.data if result.data is not None else 0
        except Exception as e:
            logger.error(f"Failed to reset orphaned tasks: {e}")
            return 0
    
    # Worker operations
    async def get_workers(self, status: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get workers by status."""
        try:
            query = self.supabase.table('workers').select('*')
            
            if status:
                query = query.in_('status', status)
            
            result = query.order('created_at', desc=True).execute()
            return result.data or []
            
        except Exception as e:
            logger.error(f"Failed to get workers: {e}")
            return []
    
    async def get_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific worker by ID."""
        try:
            result = self.supabase.table('workers').select('*').eq('id', worker_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to get worker {worker_id}: {e}")
            return None
    
    async def create_worker_record(self, worker_id: str, instance_type: str, runpod_id: str = None) -> bool:
        """Create a new worker record (optimistic registration)."""
        try:
            metadata = {}
            if runpod_id:
                metadata['runpod_id'] = runpod_id
            
            result = self.supabase.table('workers').insert({
                'id': worker_id,
                'instance_type': instance_type,
                'status': 'spawning',
                'metadata': metadata
            }).execute()
            
            logger.info(f"Created worker record: {worker_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create worker record {worker_id}: {e}")
            return False
    
    async def update_worker_status(self, worker_id: str, status: str, metadata_update: Dict[str, Any] = None) -> bool:
        """Update worker status and optionally metadata."""
        try:
            update_data = {'status': status}
            
            if metadata_update:
                # Get current metadata and merge
                worker = await self.get_worker(worker_id)
                if worker:
                    current_metadata = worker.get('metadata', {})
                    current_metadata.update(metadata_update)
                    update_data['metadata'] = current_metadata
            
            result = self.supabase.table('workers').update(update_data).eq('id', worker_id).execute()
            
            logger.info(f"Updated worker {worker_id} status to {status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update worker {worker_id} status: {e}")
            return False
    
    async def mark_worker_error(self, worker_id: str, reason: str) -> bool:
        """Mark a worker as error with reason."""
        metadata_update = {
            'error_reason': reason,
            'error_timestamp': datetime.utcnow().isoformat()
        }
        return await self.update_worker_status(worker_id, 'error', metadata_update)
    
    async def count_active_workers(self) -> int:
        """Count workers in active status."""
        try:
            result = self.supabase.table('workers').select('id', count='exact').eq('status', 'active').execute()
            return result.count or 0
        except Exception as e:
            logger.error(f"Failed to count active workers: {e}")
            return 0
    
    async def count_workers_by_status(self, status: str) -> int:
        """Count workers by specific status."""
        try:
            result = self.supabase.table('workers').select('id', count='exact').eq('status', status).execute()
            return result.count or 0
        except Exception as e:
            logger.error(f"Failed to count workers with status {status}: {e}")
            return 0
    
    # Health checks
    async def get_stale_workers(self, timeout_minutes: int = 5) -> List[Dict[str, Any]]:
        """Get workers with stale heartbeats."""
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
            
            result = self.supabase.table('workers').select('*').eq('status', 'active').lt('last_heartbeat', cutoff_time.isoformat()).execute()
            return result.data or []
            
        except Exception as e:
            logger.error(f"Failed to get stale workers: {e}")
            return []
    
    async def get_stuck_tasks(self, timeout_minutes: int = 10) -> List[Dict[str, Any]]:
        """Get tasks that have been running too long (excludes orchestrator tasks)."""
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
            
            result = self.supabase.table('tasks').select('*').eq('status', 'Running').lt('generation_started_at', cutoff_time.isoformat()).execute()
            
            if not result.data:
                return []
            
            # Filter out orchestrator tasks since they can legitimately run for extended periods
            non_orchestrator_tasks = [
                task for task in result.data 
                if '_orchestrator' not in task.get('task_type', '').lower()
            ]
            
            return non_orchestrator_tasks
            
        except Exception as e:
            logger.error(f"Failed to get stuck tasks: {e}")
            return []
    
    async def get_spawning_workers_past_timeout(self, timeout_minutes: int = 5) -> List[Dict[str, Any]]:
        """Get workers that have been in spawning state too long."""
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
            
            result = self.supabase.table('workers').select('*').eq('status', 'spawning').lt('created_at', cutoff_time.isoformat()).execute()
            return result.data or []
            
        except Exception as e:
            logger.error(f"Failed to get spawning workers past timeout: {e}")
            return []
    
    async def has_worker_processed_tasks(self, worker_id: str) -> bool:
        """Check if a worker has processed any tasks (for promoting from spawning to active)."""
        try:
            result = self.supabase.table('tasks').select('id', count='exact').eq('worker_id', worker_id).neq('status', 'Queued').execute()
            return (result.count or 0) > 0
        except Exception as e:
            logger.error(f"Failed to check if worker {worker_id} has processed tasks: {e}")
            return False
    
    async def has_running_tasks(self, worker_id: str) -> bool:
        """Check if worker has running tasks."""
        try:
            result = self.supabase.table('tasks').select('id', count='exact').eq('worker_id', worker_id).eq('status', 'Running').execute()
            return (result.count or 0) > 0
        except Exception as e:
            logger.error(f"Failed to check running tasks for worker {worker_id}: {e}")
            return False
    
    # Monitoring
    async def get_orchestrator_status(self) -> Dict[str, Any]:
        """Get overall system status."""
        try:
            result = self.supabase.table('orchestrator_status').select('*').execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error(f"Failed to get orchestrator status: {e}")
            return {}
    
    async def get_active_workers_health(self) -> List[Dict[str, Any]]:
        """Get health status of active workers."""
        try:
            result = self.supabase.table('active_workers_health').select('*').execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to get active workers health: {e}")
            return [] 