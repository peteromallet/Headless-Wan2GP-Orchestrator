#!/usr/bin/env python3
"""
Check detailed status of a specific worker.
Usage: python3 scripts/check_worker_status.py WORKER_ID
"""

import sys
import os
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpu_orchestrator.database import DatabaseClient

def check_worker_status(worker_id: str):
    db = DatabaseClient()
    
    result = db.supabase.table('workers').select('*').eq('id', worker_id).execute()
    
    if not result.data:
        print(f'❌ Worker {worker_id} not found')
        return
    
    w = result.data[0]
    created = datetime.fromisoformat(w['created_at'].replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    age_min = (now - created).total_seconds() / 60
    
    print('='*80)
    print(f'WORKER: {worker_id}')
    print('='*80)
    print(f'Status: {w["status"]}')
    print(f'Created: {w["created_at"]}')
    print(f'Age: {age_min:.1f} minutes')
    
    # Heartbeat analysis
    last_hb = w.get('last_heartbeat')
    if last_hb:
        last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
        hb_age_sec = (now - last_hb_time).total_seconds()
        hb_age_min = hb_age_sec / 60
        
        # Determine status
        if hb_age_sec < 60:
            status = '✅ ALIVE'
        elif hb_age_sec < 300:
            status = '⚠️  AGING'
        elif hb_age_sec < 600:
            status = '🔴 STALE'
        else:
            status = '❌ DEAD'
        
        print(f'\nLast heartbeat: {last_hb}')
        print(f'Heartbeat age: {hb_age_sec:.1f}s ({hb_age_min:.1f} min) {status}')
        print(f'Timeout threshold: 600s (10 min)')
        
        time_until_timeout = 600 - hb_age_sec
        if time_until_timeout > 0:
            print(f'Time until timeout: {time_until_timeout/60:.1f} minutes')
        else:
            print(f'⚠️  OVERDUE for termination by {abs(time_until_timeout)/60:.1f} minutes')
    else:
        print('\nLast heartbeat: None')
    
    # Metadata
    metadata = w.get('metadata', {})
    print(f'\nRAM Tier: {metadata.get("ram_tier", "Unknown")} GB')
    print(f'RunPod ID: {metadata.get("runpod_id", "Unknown")}')
    
    pod_details = metadata.get('pod_details', {})
    if pod_details:
        print(f'Pod Status: {pod_details.get("desiredStatus", "Unknown")}')
        print(f'GPU: {pod_details.get("gpu_type_id", "Unknown")}')
    
    promoted_at = metadata.get('promoted_to_active_at')
    if promoted_at:
        print(f'Promoted to active: {promoted_at}')
    
    # Check for tasks
    print('\n' + '='*80)
    print('TASKS')
    print('='*80)
    tasks = db.supabase.table('tasks').select('id, task_type, status').eq('worker_id', worker_id).execute()
    
    if tasks.data:
        print(f'Total tasks assigned: {len(tasks.data)}')
        for task in tasks.data[:5]:
            print(f'  {task["task_type"]:20} | {task["status"]:15} | {task["id"][:8]}...')
        if len(tasks.data) > 5:
            print(f'  ... and {len(tasks.data) - 5} more')
    else:
        print('No tasks assigned')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python3 scripts/check_worker_status.py WORKER_ID')
        sys.exit(1)
    
    check_worker_status(sys.argv[1])

