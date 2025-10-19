#!/usr/bin/env python3
"""
Deep Dive: What Are These "Queued" Tasks?
==========================================

51 tasks queued but only 36 created in last 10 min. 
Where are the other tasks from? Why did they suddenly become "available"?
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
print("🔬 DEEP DIVE: QUEUED TASKS ANALYSIS")
print("="*100)
print()

now = datetime.now(timezone.utc)

# Get ALL queued tasks with full details
print("📦 ALL QUEUED TASKS (Full Details)")
print("-"*100)

queued_result = supabase.table('tasks').select('*') \
    .eq('status', 'Queued') \
    .order('created_at', desc=False) \
    .execute()

queued_tasks = queued_result.data or []

print(f"Total queued tasks: {len(queued_tasks)}")
print()

if queued_tasks:
    # Analyze by creation time
    print("📅 WHEN WERE THESE TASKS CREATED?")
    print()
    
    age_buckets = {
        'Last 10 min': 0,
        'Last hour': 0,
        'Last 24 hours': 0,
        'Older than 24h': 0
    }
    
    ten_min_ago = now - timedelta(minutes=10)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)
    
    for task in queued_tasks:
        created_at = datetime.fromisoformat(task['created_at'].replace('Z', '+00:00'))
        
        if created_at >= ten_min_ago:
            age_buckets['Last 10 min'] += 1
        elif created_at >= one_hour_ago:
            age_buckets['Last hour'] += 1
        elif created_at >= one_day_ago:
            age_buckets['Last 24 hours'] += 1
        else:
            age_buckets['Older than 24h'] += 1
    
    for bucket, count in age_buckets.items():
        print(f"  {bucket:20} : {count:3} tasks")
    
    print()
    
    # Show oldest queued tasks
    print("🕰️  OLDEST QUEUED TASKS (First 10):")
    print()
    
    for i, task in enumerate(queued_tasks[:10], 1):
        task_id = str(task['id'])[:8]
        created_at = task['created_at']
        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        age_hours = (now - created_dt).total_seconds() / 3600
        
        task_type = task.get('task_type', 'unknown')
        user_id = str(task.get('user_id', 'unknown'))[:8]
        
        print(f"  {i:2}. Task {task_id}... | {created_at[:19]} ({age_hours:.1f}h ago)")
        print(f"      Type: {task_type:20} | User: {user_id}...")
        print()
    
    # Analyze by user
    print("👥 TASKS BY USER:")
    print()
    
    user_counts = {}
    for task in queued_tasks:
        user_id = task.get('user_id', 'unknown')
        user_counts[user_id] = user_counts.get(user_id, 0) + 1
    
    sorted_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)
    
    for user_id, count in sorted_users[:10]:
        user_id_short = str(user_id)[:8]
        print(f"  User {user_id_short}...: {count:2} queued tasks")
    
    print()
    
    # Check user concurrency
    print("🔍 USER CONCURRENCY CHECK:")
    print("(Are these tasks blocked by user limits?)")
    print()
    
    # For each user with queued tasks, check how many they have in progress
    for user_id, queued_count in sorted_users[:5]:
        # Get in-progress tasks for this user
        in_progress_result = supabase.table('tasks').select('id') \
            .eq('user_id', user_id) \
            .eq('status', 'In Progress') \
            .execute()
        
        in_progress_count = len(in_progress_result.data or [])
        
        user_id_short = str(user_id)[:8]
        
        if in_progress_count >= 5:
            status = "AT LIMIT (≥5)"
        else:
            status = f"Under limit ({in_progress_count}/5)"
        
        print(f"  User {user_id_short}...: {queued_count} queued, {in_progress_count} in progress - {status}")
    
    print()

# Check what the edge function would return
print("🔍 EDGE FUNCTION TASK COUNT")
print("-"*100)

try:
    # Call the edge function to see what it returns
    result = supabase.rpc('func_get_task_counts', {
        'mode': 'count',
        'run_type_filter': 'cloud'
    }).execute()
    
    if result.data:
        data = result.data
        
        print("Edge function response:")
        print()
        
        if 'totals' in data:
            totals = data['totals']
            print(f"  Queued only: {totals.get('queued_only', 0)}")
            print(f"  Active only: {totals.get('active_only', 0)}")
            print(f"  Total (queued + active): {totals.get('queued_plus_active', 0)}")
        
        print()
        
        # Show why tasks might be excluded
        if 'users' in data:
            users = data['users']
            at_limit = [u for u in users if u.get('at_limit', False)]
            
            print(f"  Total users with tasks: {len(users)}")
            print(f"  Users at concurrency limit: {len(at_limit)}")
            print()
            
            if at_limit:
                print("  Users at limit (tasks blocked):")
                for user in at_limit[:5]:
                    user_id = str(user.get('user_id', 'unknown'))[:8]
                    queued = user.get('queued_tasks', 0)
                    in_prog = user.get('in_progress_tasks', 0)
                    print(f"    {user_id}...: {queued} queued, {in_prog} in progress")
        
except Exception as e:
    print(f"Error calling edge function: {e}")

print()

# Check task history around 18:25
print("📊 TASK ACTIVITY TIMELINE (18:20-18:30)")
print("-"*100)

start_time = datetime(2025, 10, 16, 18, 20, 0, tzinfo=timezone.utc)
end_time = datetime(2025, 10, 16, 18, 30, 0, tzinfo=timezone.utc)

# Get tasks created in this window
created_result = supabase.table('tasks').select('*') \
    .gte('created_at', start_time.isoformat()) \
    .lte('created_at', end_time.isoformat()) \
    .order('created_at', desc=False) \
    .execute()

created_tasks = created_result.data or []

print(f"Tasks created between 18:20-18:30: {len(created_tasks)}")
print()

if created_tasks:
    # Group by minute
    from collections import defaultdict
    tasks_per_minute = defaultdict(int)
    
    for task in created_tasks:
        created_at = task['created_at'][:16]  # YYYY-MM-DDTHH:MM
        minute = created_at[11:]  # HH:MM
        tasks_per_minute[minute] += 1
    
    print("Tasks created per minute:")
    for minute in sorted(tasks_per_minute.keys()):
        count = tasks_per_minute[minute]
        bar = "█" * min(count, 50)
        print(f"  {minute}: {bar} ({count})")
    
    print()
    
    # Show first few tasks
    print("First 10 tasks created:")
    for i, task in enumerate(created_tasks[:10], 1):
        created_at = task['created_at'][11:19]
        task_id = str(task['id'])[:8]
        task_type = task.get('task_type', 'unknown')
        status = task.get('status', 'unknown')
        user_id = str(task.get('user_id', 'unknown'))[:8]
        print(f"  {i:2}. [{created_at}] Task {task_id}... | {task_type:20} | {status:12} | User {user_id}...")

print()

# Check if there was an orchestrator restart
print("🔄 ORCHESTRATOR ACTIVITY CHECK")
print("-"*100)

# Look for orchestrator logs around 18:25
orch_logs = supabase.table('system_logs').select('*') \
    .eq('source_type', 'orchestrator_gpu') \
    .gte('timestamp', start_time.isoformat()) \
    .lte('timestamp', end_time.isoformat()) \
    .order('timestamp', desc=False) \
    .execute()

logs = orch_logs.data or []

if not logs:
    print("⚠️  NO ORCHESTRATOR LOGS FOUND 18:20-18:30")
    print("   (Remember: database logging stopped at 17:35)")
    print()
    print("   Using worker metadata to reconstruct orchestrator activity...")
    
    # Get worker creation events
    workers_result = supabase.table('workers').select('*') \
        .gte('created_at', start_time.isoformat()) \
        .lte('created_at', end_time.isoformat()) \
        .order('created_at', desc=False) \
        .execute()
    
    workers = workers_result.data or []
    
    if workers:
        print()
        print("   Worker creation events (orchestrator was active):")
        for worker in workers:
            created = worker['created_at'][11:19]
            worker_id = worker['id']
            print(f"     [{created}] Created worker: {worker_id}")
else:
    print(f"Found {len(logs)} orchestrator log entries")
    for log in logs[:10]:
        timestamp = log['timestamp'][11:19]
        message = log['message'][:80]
        print(f"  [{timestamp}] {message}")

print()
print("="*100)





