#!/usr/bin/env python3
"""
Investigate 18:27 Scale-Up Event
=================================

Multiple workers just created around 18:27. Why?
"""

import os
import sys
from datetime import datetime, timezone, timedelta
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
print("🔍 INVESTIGATING 18:27 SCALE-UP EVENT")
print("="*100)
print()

now = datetime.now(timezone.utc)
print(f"Current time: {now.strftime('%H:%M:%S UTC')}")
print()

# Get all non-terminated workers
print("📊 CURRENT WORKERS (Non-Terminated)")
print("-"*100)

result = supabase.table('workers').select('*') \
    .neq('status', 'terminated') \
    .order('created_at', desc=False) \
    .execute()

workers = result.data or []

if not workers:
    print("No active workers!")
else:
    print(f"Found {len(workers)} non-terminated workers:")
    print()
    
    for i, worker in enumerate(workers, 1):
        created = worker.get('created_at', 'unknown')
        created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
        age_seconds = (now - created_dt).total_seconds()
        age_minutes = age_seconds / 60
        
        worker_id = worker.get('id', 'unknown')
        status = worker.get('status', 'unknown')
        last_hb = worker.get('last_heartbeat', 'never')
        if last_hb != 'never':
            last_hb = last_hb[11:19]
        
        metadata = worker.get('metadata', {})
        runpod_id = metadata.get('runpod_id', 'N/A')
        
        print(f"{i:2}. {worker_id}")
        print(f"    Created: {created[11:19]} ({age_minutes:.1f} min ago)")
        print(f"    Status: {status}")
        print(f"    Last HB: {last_hb}")
        print(f"    RunPod: {runpod_id}")
        print()

print()

# Get task counts
print("📦 TASK QUEUE STATE")
print("-"*100)

# Get all tasks by status
tasks_result = supabase.table('tasks').select('status').execute()
tasks = tasks_result.data or []

status_counts = {}
for task in tasks:
    status = task.get('status', 'unknown')
    status_counts[status] = status_counts.get(status, 0) + 1

print(f"Total tasks: {len(tasks)}")
print()
for status, count in sorted(status_counts.items()):
    print(f"  {status:15} : {count}")

print()

# Get recent task activity
print("📦 RECENT TASK ACTIVITY (Last 10 Minutes)")
print("-"*100)

recent_time = now - timedelta(minutes=10)

recent_tasks = supabase.table('tasks').select('*') \
    .or_(
        f'created_at.gte.{recent_time.isoformat()},'
        f'generation_started_at.gte.{recent_time.isoformat()},'
        f'generation_processed_at.gte.{recent_time.isoformat()}'
    ) \
    .order('created_at', desc=True) \
    .limit(50) \
    .execute()

tasks = recent_tasks.data or []

if not tasks:
    print("No recent task activity")
else:
    print(f"Found {len(tasks)} tasks with recent activity:")
    print()
    
    # Categorize
    created = []
    started = []
    completed = []
    
    for task in tasks:
        created_at = task.get('created_at', '')
        started_at = task.get('generation_started_at', '')
        completed_at = task.get('generation_processed_at', '')
        
        if created_at and created_at >= recent_time.isoformat():
            created.append(task)
        if started_at and started_at >= recent_time.isoformat():
            started.append(task)
        if completed_at and completed_at >= recent_time.isoformat():
            completed.append(task)
    
    if created:
        print(f"📝 {len(created)} tasks CREATED in last 10 min")
    if started:
        print(f"▶️  {len(started)} tasks STARTED in last 10 min")
    if completed:
        print(f"✅ {len(completed)} tasks COMPLETED in last 10 min")

print()

# Check what workers are doing
print("👷 WORKER TASK ASSIGNMENTS")
print("-"*100)

for worker in workers:
    worker_id = worker.get('id')
    
    # Get tasks assigned to this worker
    worker_tasks = supabase.table('tasks').select('*') \
        .eq('worker_id', worker_id) \
        .eq('status', 'In Progress') \
        .execute()
    
    tasks = worker_tasks.data or []
    
    if tasks:
        print(f"{worker_id}:")
        for task in tasks:
            task_id = str(task.get('id', 'unknown'))[:8]
            task_type = task.get('task_type', 'unknown')
            started = task.get('generation_started_at', 'unknown')[11:19]
            print(f"  - Task {task_id}... | {task_type:20} | Started: {started}")
    else:
        print(f"{worker_id}: IDLE (no tasks)")

print()

# Reconstruct what happened by looking at worker creation times
print("⏱️  TIMELINE RECONSTRUCTION")
print("-"*100)

# Get workers created in last 15 minutes
timeline_start = now - timedelta(minutes=15)

recent_workers = supabase.table('workers').select('*') \
    .gte('created_at', timeline_start.isoformat()) \
    .order('created_at', desc=False) \
    .execute()

workers_timeline = recent_workers.data or []

if not workers_timeline:
    print("No workers created in last 15 minutes")
else:
    print(f"Workers created in last 15 minutes ({len(workers_timeline)}):")
    print()
    
    for worker in workers_timeline:
        created = worker.get('created_at')[11:19]
        worker_id = worker.get('id')
        status = worker.get('status')
        metadata = worker.get('metadata', {})
        
        promoted_at = metadata.get('promoted_to_active_at')
        if promoted_at:
            promoted_at = promoted_at[11:19]
        
        terminated_at = metadata.get('terminated_at')
        if terminated_at:
            terminated_at = terminated_at[11:19]
        
        print(f"  [{created}] Created: {worker_id}")
        print(f"            Status: {status}")
        if promoted_at:
            print(f"            Promoted: {promoted_at}")
        if terminated_at:
            print(f"            Terminated: {terminated_at}")
        print()

print()

# Try to infer why orchestrator scaled up
print("🎯 SCALE-UP TRIGGER ANALYSIS")
print("-"*100)

# Count truly available workers (active and not busy)
idle_workers = 0
busy_workers = 0

for worker in workers:
    if worker.get('status') == 'active':
        worker_id = worker.get('id')
        
        # Check if has tasks
        tasks_result = supabase.table('tasks').select('id') \
            .eq('worker_id', worker_id) \
            .eq('status', 'In Progress') \
            .execute()
        
        if tasks_result.data:
            busy_workers += 1
        else:
            idle_workers += 1

print(f"Worker capacity:")
print(f"  - Active workers: {len([w for w in workers if w.get('status') == 'active'])}")
print(f"  - Spawning workers: {len([w for w in workers if w.get('status') == 'spawning'])}")
print(f"  - Busy (with tasks): {busy_workers}")
print(f"  - Idle (no tasks): {idle_workers}")
print()

# Get queued tasks
queued_result = supabase.table('tasks').select('id') \
    .eq('status', 'Queued') \
    .execute()

queued_count = len(queued_result.data or [])

print(f"Task demand:")
print(f"  - Queued tasks: {queued_count}")
print()

# Calculate what orchestrator likely thinks
print("🤔 LIKELY ORCHESTRATOR LOGIC:")
print()

if queued_count > 0:
    print(f"  ✅ {queued_count} tasks queued (workload exists)")
else:
    print(f"  ⚠️  0 tasks queued (but orchestrator may see claimable tasks)")

total_capacity = len([w for w in workers if w.get('status') in ['active', 'spawning']])
print(f"  Current capacity: {total_capacity} workers")

# Estimate desired workers
# Orchestrator uses: max(MIN_ACTIVE_GPUS, task_count, busy_workers + idle_buffer)
min_gpus = 1  # From env
desired_from_tasks = max(min_gpus, queued_count)
desired_from_buffer = busy_workers + 0  # Assuming idle_buffer = 0

desired = max(desired_from_tasks, desired_from_buffer)

print(f"  Estimated desired: ~{desired} workers (based on visible tasks)")
print()

if total_capacity > desired:
    print(f"  ⚠️  OVER-CAPACITY: {total_capacity} > {desired}")
    print(f"     Orchestrator should scale DOWN soon")
elif total_capacity < desired:
    print(f"  📈 UNDER-CAPACITY: {total_capacity} < {desired}")
    print(f"     This would explain the scale-up")
else:
    print(f"  ✅ AT CAPACITY: {total_capacity} = {desired}")

print()
print("="*100)





