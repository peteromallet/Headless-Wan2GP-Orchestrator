#!/usr/bin/env python3
"""
Verify Edge Function Bug
=========================

Test if the edge function is actually returning the wrong count.
"""

import os
import sys
import requests
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
print("🧪 TESTING EDGE FUNCTION vs DIRECT SQL")
print("="*100)
print()

# 1. Call the edge function like the orchestrator does
print("1️⃣  EDGE FUNCTION RESPONSE (What orchestrator sees)")
print("-"*100)

try:
    task_counts_url = f"{supabase_url}/functions/v1/task-counts"
    
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "run_type": "gpu",
        "include_active": False  # Only queued tasks
    }
    
    response = requests.post(task_counts_url, headers=headers, json=payload, timeout=10)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        data = response.json()
        edge_function_count = data.get('count', 'N/A')
        print()
        print(f"✅ Edge function returned: {edge_function_count} tasks")
    else:
        print(f"❌ Edge function failed: {response.text}")
        edge_function_count = None

except Exception as e:
    print(f"❌ Error calling edge function: {e}")
    edge_function_count = None

print()

# 2. Query database directly for queued tasks
print("2️⃣  DIRECT SQL QUERY (Ground truth)")
print("-"*100)

try:
    # Get ALL queued tasks
    all_queued = supabase.table('tasks').select('id, created_at').eq('status', 'Queued').execute()
    total_queued = len(all_queued.data or [])
    
    print(f"Total queued tasks in database: {total_queued}")
    
    # Get queued tasks from last 7 days (should be the "real" work)
    from datetime import timedelta
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    
    recent_queued = [
        t for t in (all_queued.data or [])
        if datetime.fromisoformat(t['created_at'].replace('Z', '+00:00')) >= recent_cutoff
    ]
    
    print(f"Recent queued tasks (last 7 days): {len(recent_queued)}")
    
    # Get ancient queued tasks
    ancient_queued = total_queued - len(recent_queued)
    print(f"Ancient queued tasks (>7 days old): {ancient_queued}")
    
except Exception as e:
    print(f"❌ Error querying database: {e}")
    total_queued = None

print()

# 3. Compare the numbers
print("3️⃣  COMPARISON")
print("-"*100)

if edge_function_count is not None and total_queued is not None:
    print(f"Edge function:  {edge_function_count} tasks")
    print(f"Database total: {total_queued} tasks")
    print(f"Recent tasks:   {len(recent_queued)} tasks")
    print(f"Ancient tasks:  {ancient_queued} tasks")
    print()
    
    if edge_function_count == total_queued:
        print("⚠️  EDGE FUNCTION INCLUDES ALL TASKS (including ancient ones)")
        print("   This is the BUG - it should filter out old tasks!")
    elif edge_function_count == len(recent_queued):
        print("✅ Edge function correctly filters to recent tasks only")
    else:
        print(f"❓ Edge function count doesn't match either number")
        print(f"   Difference from total: {edge_function_count - total_queued}")
        print(f"   Difference from recent: {edge_function_count - len(recent_queued)}")

print()

# 4. Check what the orchestrator would have seen at 18:25
print("4️⃣  RECONSTRUCTING 18:25 SCALE-UP TRIGGER")
print("-"*100)

# Look at worker creation pattern
workers_result = supabase.table('workers').select('*') \
    .gte('created_at', '2025-10-16T18:20:00+00:00') \
    .lte('created_at', '2025-10-16T18:30:00+00:00') \
    .order('created_at', desc=False) \
    .execute()

workers = workers_result.data or []

if workers:
    print(f"Workers created 18:20-18:30: {len(workers)}")
    print()
    
    # If 4 workers were created quickly, orchestrator saw high task count
    if len(workers) >= 4:
        print("✅ CONFIRMED: 4 workers created in quick succession")
        print("   This indicates orchestrator saw a high task count")
        print()
        
        for worker in workers:
            created = worker['created_at'][11:19]
            worker_id = worker['id'][:30]
            print(f"  [{created}] {worker_id}")
        
        print()
        print("🎯 CONCLUSION:")
        print("   Orchestrator saw enough tasks to justify 4 workers")
        print("   With MIN_ACTIVE_GPUS=1, this suggests it saw 4+ tasks")
        print(f"   Current edge function returns: {edge_function_count}")
        print(f"   But only {len(recent_queued)} are recent/valid work")
        print()
        
        if edge_function_count and edge_function_count > len(recent_queued):
            print("   ✅ VERIFIED: Edge function IS returning inflated count")
            print(f"   Inflation: {edge_function_count - len(recent_queued)} extra tasks")
            print("   These are the ancient orphaned tasks!")

print()

# 5. Test if the edge function filters by user_id
print("5️⃣  TESTING USER_ID FILTERING")
print("-"*100)

# Get a sample of the queued tasks to see if they have user_id
sample_tasks = supabase.table('tasks').select('*').eq('status', 'Queued').limit(5).execute()

if sample_tasks.data:
    print("Sample queued tasks:")
    for task in sample_tasks.data:
        task_id = str(task['id'])[:8]
        created = task['created_at'][:10]
        
        # Check if task has user_id field
        has_user_id = 'user_id' in task and task.get('user_id') is not None
        has_run_type = 'run_type' in task and task.get('run_type') is not None
        
        print(f"  Task {task_id}... (created {created})")
        print(f"    Has user_id: {has_user_id}")
        print(f"    Has run_type: {has_run_type}")
        
        if not has_user_id or not has_run_type:
            print(f"    ⚠️  OLD SCHEMA TASK - should be filtered out!")
        print()

print()
print("="*100)





