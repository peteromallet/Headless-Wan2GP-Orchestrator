#!/usr/bin/env python3
"""
Worker Diagnostics Viewer
=========================

View diagnostic data collected from failed workers before termination.

Usage:
    # View diagnostics for a specific worker
    python view_worker_diagnostics.py --worker gpu-20251015_150851-0d58d2c4
    
    # View diagnostics for all recently failed workers
    python view_worker_diagnostics.py --recent-failures --hours 24
    
    # Export diagnostics to JSON
    python view_worker_diagnostics.py --worker gpu-20251015_150851-0d58d2c4 --export diagnostics.json
"""

import argparse
import os
import sys
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

load_dotenv()

from supabase import create_client


class WorkerDiagnosticsViewer:
    """View diagnostics data from failed workers."""
    
    def __init__(self):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
        
        self.supabase = create_client(supabase_url, supabase_key)
    
    def get_worker_diagnostics(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Get diagnostic data for a specific worker."""
        try:
            result = self.supabase.table('workers').select('*').eq('id', worker_id).single().execute()
            if result.data:
                return result.data
            return None
        except Exception as e:
            print(f"Error fetching worker {worker_id}: {e}")
            return None
    
    def get_recent_failed_workers(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get all workers that failed in the last N hours."""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            result = self.supabase.table('workers').select('*').eq('status', 'error').gte('created_at', cutoff_time.isoformat()).order('created_at', desc=True).execute()
            return result.data or []
        except Exception as e:
            print(f"Error fetching failed workers: {e}")
            return []
    
    def print_diagnostics(self, worker_data: Dict[str, Any]):
        """Print formatted diagnostics for a worker."""
        worker_id = worker_data['id']
        metadata = worker_data.get('metadata', {})
        diagnostics = metadata.get('diagnostics', {})
        
        print("\n" + "="*100)
        print(f"WORKER DIAGNOSTICS: {worker_id}")
        print("="*100 + "\n")
        
        # Basic info
        print(f"Worker ID:       {worker_id}")
        print(f"Status:          {worker_data.get('status')}")
        print(f"Created:         {worker_data.get('created_at')}")
        print(f"Last Heartbeat:  {worker_data.get('last_heartbeat')}")
        print(f"RunPod ID:       {metadata.get('runpod_id')}")
        
        # Error info
        error_reason = metadata.get('error_reason', 'N/A')
        error_time = metadata.get('error_time', 'N/A')
        print(f"\nError Reason:    {error_reason}")
        print(f"Error Time:      {error_time}")
        
        if not diagnostics:
            print("\n⚠️  No diagnostic data collected (worker may have failed before diagnostic collection was implemented)")
            return
        
        print(f"\n{'─'*100}")
        print("DIAGNOSTIC DATA")
        print(f"{'─'*100}\n")
        
        # VRAM info
        if 'vram_total_mb' in diagnostics:
            vram_used = diagnostics.get('vram_used_mb', 0)
            vram_total = diagnostics.get('vram_total_mb', 0)
            vram_percent = diagnostics.get('vram_usage_percent', 0)
            print(f"🖥️  VRAM Usage:    {vram_used}/{vram_total} MB ({vram_percent:.1f}%)")
            print(f"   VRAM Timestamp: {diagnostics.get('vram_timestamp', 'N/A')}")
        else:
            print("🖥️  VRAM Usage:    No data available")
        
        # Running tasks
        running_tasks = diagnostics.get('running_tasks', [])
        running_tasks_count = diagnostics.get('running_tasks_count', 0)
        print(f"\n📋 Running Tasks: {running_tasks_count}")
        if running_tasks:
            for i, task in enumerate(running_tasks, 1):
                age = task.get('age_seconds', 0)
                print(f"   {i}. Task {task['id'][:8]}... ({task.get('task_type', 'unknown')})")
                print(f"      Started: {task.get('started_at', 'unknown')}")
                print(f"      Age: {age:.1f}s")
        
        # Pod status
        pod_status = diagnostics.get('pod_status', {})
        if pod_status:
            print(f"\n☁️  Pod Status:")
            print(f"   Desired:  {pod_status.get('desired_status', 'N/A')}")
            print(f"   Actual:   {pod_status.get('actual_status', 'N/A')}")
            print(f"   Uptime:   {pod_status.get('uptime_seconds', 0)}s")
            print(f"   Cost:     ${pod_status.get('cost_per_hr', 0)}/hr")
        elif 'pod_status_error' in diagnostics:
            print(f"\n☁️  Pod Status:   ❌ {diagnostics['pod_status_error']}")
        
        # Logs - reference to system_logs table
        if diagnostics.get('logs_available_in_system_logs'):
            print(f"\n📄 Worker Logs: ✅ Available in system_logs table")
            print(f"   {diagnostics.get('logs_note', 'Use query_logs.py --worker-timeline to view')}")
            print(f"\n   💡 To view logs:")
            print(f"      python scripts/query_logs.py --worker-timeline {worker_id}")
            print(f"      python scripts/query_logs.py --worker {worker_id} --level ERROR")
        elif 'container_logs_error' in diagnostics:
            print(f"\n📄 Worker Logs: ❌ {diagnostics['container_logs_error']}")
        
        # Collection status
        collection_success = diagnostics.get('collection_success', False)
        print(f"\n{'✅' if collection_success else '❌'} Diagnostic Collection: {'Successful' if collection_success else 'Failed'}")
        if 'collection_error' in diagnostics:
            print(f"   Error: {diagnostics['collection_error']}")
        
        print("\n" + "="*100 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="View diagnostic data from failed workers",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--worker', help='Specific worker ID to view')
    parser.add_argument('--recent-failures', action='store_true', help='View all recent failures')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back for recent failures (default: 24)')
    parser.add_argument('--export', help='Export diagnostics to JSON file')
    parser.add_argument('--format', choices=['text', 'json'], default='text', help='Output format')
    
    args = parser.parse_args()
    
    if not args.worker and not args.recent_failures:
        parser.error("Must specify either --worker or --recent-failures")
    
    try:
        viewer = WorkerDiagnosticsViewer()
        
        if args.worker:
            # View specific worker
            worker_data = viewer.get_worker_diagnostics(args.worker)
            if not worker_data:
                print(f"❌ Worker {args.worker} not found")
                sys.exit(1)
            
            if args.format == 'json':
                print(json.dumps(worker_data, indent=2, default=str))
            else:
                viewer.print_diagnostics(worker_data)
            
            if args.export:
                with open(args.export, 'w') as f:
                    json.dump(worker_data, f, indent=2, default=str)
                print(f"✅ Exported to {args.export}")
        
        elif args.recent_failures:
            # View recent failures
            workers = viewer.get_recent_failed_workers(args.hours)
            
            if not workers:
                print(f"No failed workers found in the last {args.hours} hours")
                sys.exit(0)
            
            print(f"\n{'='*100}")
            print(f"RECENT WORKER FAILURES (last {args.hours} hours): {len(workers)} workers")
            print(f"{'='*100}\n")
            
            for worker in workers:
                metadata = worker.get('metadata', {})
                error_reason = metadata.get('error_reason', 'Unknown')
                has_diagnostics = 'diagnostics' in metadata
                
                print(f"Worker: {worker['id']}")
                print(f"  Created:  {worker.get('created_at')}")
                print(f"  Error:    {error_reason}")
                print(f"  Diagnostics: {'✅ Available' if has_diagnostics else '❌ Not collected'}")
                print()
            
            print(f"\nUse --worker <worker_id> to view detailed diagnostics for a specific worker")
            
            if args.export:
                with open(args.export, 'w') as f:
                    json.dump(workers, f, indent=2, default=str)
                print(f"✅ Exported {len(workers)} workers to {args.export}")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

