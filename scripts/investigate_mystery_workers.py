#!/usr/bin/env python3
"""
Investigate Mystery Workers Created at 17:55
=============================================

The orchestrator stopped at 17:35, but workers were created at 17:55.
Who or what created them?
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(supabase_url, supabase_key)

print("="*100)
print("🕵️  INVESTIGATING MYSTERY WORKERS")
print("="*100)
print()

# Get detailed info about the two workers
worker_ids = [
    'gpu-20251016_175506-a6a03b7b',
    'gpu-20251016_175532-78a04c2b'
]

for worker_id in worker_ids:
    print("─"*100)
    print(f"🔬 WORKER: {worker_id}")
    print("─"*100)
    
    try:
        result = supabase.table('workers').select('*').eq('id', worker_id).execute()
        
        if not result.data:
            print(f"❌ Worker not found!")
            continue
        
        worker = result.data[0]
        
        print(f"Created: {worker.get('created_at')}")
        print(f"Status: {worker.get('status')}")
        print(f"Instance type: {worker.get('instance_type')}")
        print()
        
        metadata = worker.get('metadata', {})
        print("📦 Metadata:")
        for key, value in metadata.items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for k, v in value.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {key}: {value}")
        
        print()
        
        # Check for any logs from this worker
        print("📋 Logs from this worker:")
        logs_result = supabase.table('system_logs') \
            .select('*') \
            .eq('worker_id', worker_id) \
            .order('timestamp', desc=False) \
            .limit(20) \
            .execute()
        
        logs = logs_result.data or []
        
        if not logs:
            print("  No logs found for this worker")
        else:
            print(f"  Found {len(logs)} log entries:")
            for log in logs:
                timestamp = log['timestamp'][11:19]
                source = log['source_type']
                level = log['log_level']
                message = log['message'][:60]
                print(f"    [{timestamp}] [{source}] [{level}] {message}")
        
        print()
        
        # Check for tasks assigned to this worker
        print("📦 Tasks assigned to this worker:")
        tasks_result = supabase.table('tasks') \
            .select('*') \
            .eq('worker_id', worker_id) \
            .limit(10) \
            .execute()
        
        tasks = tasks_result.data or []
        
        if not tasks:
            print("  No tasks assigned")
        else:
            print(f"  Found {len(tasks)} tasks:")
            for task in tasks:
                task_id = str(task.get('id', 'unknown'))[:8]
                status = task.get('status', 'unknown')
                task_type = task.get('task_type', 'unknown')
                started = task.get('generation_started_at', 'N/A')
                if started != 'N/A':
                    started = started[11:19]
                print(f"    Task {task_id}... | {task_type:20} | {status:12} | Started: {started}")
        
        print()
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print()

print()
print("="*100)
print("🔍 HYPOTHESIS TESTING")
print("="*100)
print()

# Check if there might be another orchestrator instance
print("1️⃣  Checking for multiple orchestrator instances...")
print()

try:
    # Look for orchestrator logs from different source_ids
    recent_logs = supabase.table('system_logs') \
        .select('source_id, source_type, timestamp') \
        .eq('source_type', 'orchestrator_gpu') \
        .gte('timestamp', '2025-10-16T17:30:00+00:00') \
        .order('timestamp', desc=True) \
        .limit(100) \
        .execute()
    
    logs = recent_logs.data or []
    
    source_ids = set()
    for log in logs:
        source_ids.add(log['source_id'])
    
    if len(source_ids) > 1:
        print(f"  ⚠️  Found {len(source_ids)} different orchestrator source IDs:")
        for source_id in source_ids:
            print(f"     - {source_id}")
    else:
        print(f"  ✅ Only one orchestrator source ID: {list(source_ids)[0] if source_ids else 'none'}")

except Exception as e:
    print(f"  ❌ Error: {e}")

print()

# Check if workers might have been manually created
print("2️⃣  Checking worker creation pattern...")
print()

try:
    # Get all workers created in the last hour
    from datetime import timedelta
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    
    recent_workers = supabase.table('workers').select('created_at, id, status, metadata') \
        .gte('created_at', one_hour_ago.isoformat()) \
        .order('created_at', desc=False) \
        .execute()
    
    workers = recent_workers.data or []
    
    print(f"  Workers created in last hour: {len(workers)}")
    print()
    
    # Look for patterns - are they all from one orchestrator instance?
    # Or are there gaps suggesting manual creation?
    
    for i, worker in enumerate(workers):
        created = worker['created_at'][11:19]
        worker_id = worker['id']
        status = worker['status']
        
        # Check metadata for clues
        metadata = worker.get('metadata', {})
        orch_status = metadata.get('orchestrator_status', 'N/A')
        
        print(f"    {i+1:2}. [{created}] {worker_id[:30]:30} | {status:12} | OrchestratorStatus: {orch_status}")

except Exception as e:
    print(f"  ❌ Error: {e}")

print()

# Check RunPod API directly
print("3️⃣  Checking if pods exist in RunPod...")
print()

try:
    import runpod
    
    runpod_api_key = os.getenv('RUNPOD_API_KEY')
    if not runpod_api_key:
        print("  ⚠️  RUNPOD_API_KEY not set, cannot check RunPod directly")
    else:
        runpod.api_key = runpod_api_key
        
        pods = runpod.get_pods()
        
        # Check if our mystery workers' pods exist
        for worker_id in worker_ids:
            result = supabase.table('workers').select('metadata').eq('id', worker_id).execute()
            if result.data:
                runpod_id = result.data[0].get('metadata', {}).get('runpod_id')
                if runpod_id:
                    pod = next((p for p in pods if p.get('id') == runpod_id), None)
                    if pod:
                        print(f"  ✅ Pod {runpod_id} exists in RunPod")
                        print(f"     Status: {pod.get('desiredStatus')}")
                        print(f"     Created: {pod.get('createdAt', 'unknown')}")
                    else:
                        print(f"  ❌ Pod {runpod_id} NOT found in RunPod!")

except ImportError:
    print("  ⚠️  runpod module not available")
except Exception as e:
    print(f"  ❌ Error: {e}")

print()
print("="*100)





