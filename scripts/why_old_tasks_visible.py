#!/usr/bin/env python3
"""
Why Are 2-Month-Old Tasks Suddenly Visible?
============================================

51 tasks from AUGUST are suddenly being counted as "available" at 18:25.
What changed?
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
print("🔍 WHY ARE ANCIENT TASKS SUDDENLY VISIBLE?")
print("="*100)
print()

# Get those queued tasks
queued_result = supabase.table('tasks').select('*') \
    .eq('status', 'Queued') \
    .limit(10) \
    .execute()

tasks = queued_result.data or []

if tasks:
    print("📦 SAMPLE ANCIENT TASKS:")
    print()
    
    for i, task in enumerate(tasks[:5], 1):
        task_id = str(task['id'])[:8]
        created_at = task.get('created_at', 'unknown')
        task_type = task.get('task_type', 'unknown')
        
        print(f"{i}. Task {task_id}...")
        print(f"   Created: {created_at}")
        print(f"   Type: {task_type}")
        print(f"   Status: {task.get('status')}")
        
        # Check for user_id or similar fields
        print(f"   Fields in task:")
        for key in ['user_id', 'params', 'metadata', 'attempts', 'run_type']:
            if key in task:
                value = task.get(key)
                if isinstance(value, dict):
                    print(f"     {key}: {list(value.keys())}")
                else:
                    print(f"     {key}: {value}")
        print()

print()

# Check the edge function logic
print("🔍 EDGE FUNCTION LOGIC")
print("-"*100)

try:
    # Call with detailed mode to see what it's doing
    result = supabase.rpc('func_get_task_counts', {
        'mode': 'detailed',
        'run_type_filter': 'cloud'
    }).execute()
    
    if result.data:
        data = result.data
        
        print("Edge function response:")
        print()
        
        # Check totals
        if 'totals' in data:
            totals = data['totals']
            print(f"Totals:")
            for key, value in totals.items():
                print(f"  {key}: {value}")
            print()
        
        # Check global breakdown
        if 'global_task_breakdown' in data:
            breakdown = data['global_task_breakdown']
            print(f"Global task breakdown:")
            for key, value in breakdown.items():
                print(f"  {key}: {value}")
            print()
        
        # Check users
        if 'users' in data:
            users = data['users']
            print(f"Users: {len(users)}")
            
            # Show users with most queued tasks
            sorted_users = sorted(users, key=lambda u: u.get('queued_tasks', 0), reverse=True)
            print()
            print("Top users by queued tasks:")
            for user in sorted_users[:10]:
                user_id = user.get('user_id', 'NULL')
                if user_id:
                    user_id_short = str(user_id)[:20]
                else:
                    user_id_short = "NULL"
                queued = user.get('queued_tasks', 0)
                in_prog = user.get('in_progress_tasks', 0)
                at_limit = user.get('at_limit', False)
                print(f"  {user_id_short}: {queued} queued, {in_prog} in progress {'(AT LIMIT)' if at_limit else ''}")
            print()
        
        # Check recent tasks sample
        if 'recent_tasks' in data:
            recent = data['recent_tasks']
            print(f"Recent tasks sample: {len(recent)}")
            for i, task in enumerate(recent[:5], 1):
                print(f"  {i}. Task {task.get('task_id', 'unknown')[:8]}... | Status: {task.get('status')} | Cloud: {task.get('is_cloud')}")
            print()
        
except Exception as e:
    print(f"Error calling edge function: {e}")
    import traceback
    traceback.print_exc()

print()

# Check if tasks have run_type field
print("🔍 TASK RUN_TYPE ANALYSIS")
print("-"*100)

# Count tasks by run_type
all_tasks_result = supabase.table('tasks').select('id, status, run_type').execute()
all_tasks = all_tasks_result.data or []

run_type_counts = {}
for task in all_tasks:
    run_type = task.get('run_type', 'NULL')
    status = task.get('status')
    
    key = f"{run_type} - {status}"
    run_type_counts[key] = run_type_counts.get(key, 0) + 1

print("Tasks by run_type and status:")
for key in sorted(run_type_counts.keys()):
    count = run_type_counts[key]
    print(f"  {key:40} : {count}")

print()

# Specifically check the queued tasks
print("🔍 QUEUED TASKS RUN_TYPE:")
print()

queued_run_types = {}
for task in tasks:
    run_type = task.get('run_type', 'NULL')
    queued_run_types[run_type] = queued_run_types.get(run_type, 0) + 1

for run_type, count in queued_run_types.items():
    print(f"  {run_type}: {count}")

print()

# Check if these tasks were EVER processed
print("🔍 TASK HISTORY CHECK")
print("-"*100)

for i, task in enumerate(tasks[:3], 1):
    task_id = str(task['id'])[:8]
    
    print(f"{i}. Task {task_id}...")
    print(f"   Created: {task.get('created_at')}")
    print(f"   Status: {task.get('status')}")
    print(f"   Attempts: {task.get('attempts', 0)}")
    print(f"   Worker ID: {task.get('worker_id', 'NULL')}")
    print(f"   Started at: {task.get('generation_started_at', 'NULL')}")
    print(f"   Processed at: {task.get('generation_processed_at', 'NULL')}")
    print(f"   Error: {task.get('error_message', 'NULL')}")
    print()

print()

# HYPOTHESIS: Check if there was a recent change to the edge function or orchestrator
print("💡 HYPOTHESIS TESTING")
print("-"*100)
print()

print("Hypothesis 1: Tasks have NULL user_id, bypassing concurrency limits")
print("  - These tasks show user_id: 'unknown' in queries")
print("  - Edge function may not filter NULL user_id properly")
print("  - Would explain why they suddenly became 'available'")
print()

print("Hypothesis 2: Tasks have run_type='local' being counted as 'cloud'")
print("  - Edge function filters by run_type_filter='cloud'")
print("  - If NULL or wrong value, might be included incorrectly")
print()

print("Hypothesis 3: Edge function code was deployed at ~18:25")
print("  - New logic started counting old tasks")
print("  - Or bug fix made them visible")
print()

print("Hypothesis 4: These tasks are stuck/orphaned")
print("  - Never completed despite being old")
print("  - Should be cleaned up or marked as failed")
print()

# Try to call the edge function with different filters
print("🧪 TESTING EDGE FUNCTION FILTERS")
print("-"*100)
print()

for run_type_filter in ['cloud', 'local', None]:
    try:
        params = {'mode': 'count'}
        if run_type_filter:
            params['run_type_filter'] = run_type_filter
        
        result = supabase.rpc('func_get_task_counts', params).execute()
        
        if result.data and 'totals' in result.data:
            totals = result.data['totals']
            queued = totals.get('queued_only', 0)
            print(f"run_type_filter='{run_type_filter}': {queued} queued tasks")
    except Exception as e:
        print(f"run_type_filter='{run_type_filter}': Error - {e}")

print()
print("="*100)





