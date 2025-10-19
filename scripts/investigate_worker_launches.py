#!/usr/bin/env python3
"""
Investigate Worker Launch Activity
===================================

Queries Supabase logs to understand why workers are being launched.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from supabase import create_client


def main():
    load_dotenv()
    
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    print("="*80)
    print("🔍 WORKER LAUNCH INVESTIGATION")
    print("="*80)
    print()
    
    # 1. Get current worker state from database
    print("📊 CURRENT WORKER STATE")
    print("-"*80)
    try:
        workers_result = supabase.table('workers').select('*').execute()
        workers = workers_result.data or []
        
        if not workers:
            print("⚠️  No workers found in database!")
        else:
            status_counts = {}
            for worker in workers:
                status = worker.get('status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            print(f"Total workers in database: {len(workers)}")
            print()
            for status, count in sorted(status_counts.items()):
                print(f"  {status:15} : {count}")
            
            # Show recent workers
            print()
            print("Recent workers (last 10):")
            workers_sorted = sorted(workers, key=lambda w: w.get('created_at', ''), reverse=True)
            for worker in workers_sorted[:10]:
                created = worker.get('created_at', 'unknown')[:19]
                status = worker.get('status', 'unknown')
                worker_id = worker.get('id', 'unknown')
                print(f"  {created} | {status:12} | {worker_id}")
    
    except Exception as e:
        print(f"❌ Error querying workers: {e}")
    
    print()
    
    # 2. Get recent orchestrator logs (last hour)
    print("📋 RECENT ORCHESTRATOR ACTIVITY (Last Hour)")
    print("-"*80)
    try:
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        # Get orchestrator logs
        logs_result = supabase.table('system_logs') \
            .select('*') \
            .eq('source_type', 'orchestrator_gpu') \
            .gte('timestamp', start_time.isoformat()) \
            .order('timestamp', desc=True) \
            .limit(200) \
            .execute()
        
        logs = logs_result.data or []
        
        if not logs:
            print("⚠️  No orchestrator logs found in the last hour!")
            print("   This might indicate the orchestrator is not running.")
        else:
            print(f"Found {len(logs)} orchestrator log entries")
            print()
            
            # Filter for interesting events
            scaling_logs = []
            spawn_logs = []
            error_logs = []
            
            for log in logs:
                message = log.get('message', '')
                level = log.get('log_level', '')
                
                if 'SCALING' in message or 'scaling' in message.lower() or 'desired' in message.lower():
                    scaling_logs.append(log)
                if 'spawn' in message.lower() or 'worker' in message.lower():
                    spawn_logs.append(log)
                if level in ['ERROR', 'CRITICAL']:
                    error_logs.append(log)
            
            # Show scaling decisions
            print("🎯 SCALING DECISIONS:")
            if scaling_logs:
                for log in scaling_logs[:10]:  # Last 10 scaling decisions
                    timestamp = log['timestamp'][:19].replace('T', ' ')
                    message = log['message']
                    cycle = log.get('cycle_number', '?')
                    print(f"  [{timestamp}] Cycle #{cycle}: {message}")
            else:
                print("  No scaling decision logs found")
            
            print()
            
            # Show worker spawn events
            print("🚀 WORKER SPAWN EVENTS:")
            if spawn_logs:
                for log in spawn_logs[:15]:  # Last 15 spawn events
                    timestamp = log['timestamp'][:19].replace('T', ' ')
                    message = log['message']
                    level = log['log_level']
                    if 'spawn' in message.lower():
                        print(f"  [{timestamp}] [{level}] {message}")
            else:
                print("  No spawn events found")
            
            print()
            
            # Show errors
            if error_logs:
                print("❌ RECENT ERRORS:")
                for log in error_logs[:10]:
                    timestamp = log['timestamp'][:19].replace('T', ' ')
                    message = log['message']
                    print(f"  [{timestamp}] {message}")
                print()
    
    except Exception as e:
        print(f"❌ Error querying orchestrator logs: {e}")
    
    # 3. Get task counts
    print("📦 CURRENT TASK STATE")
    print("-"*80)
    try:
        # Query tasks by status
        tasks_result = supabase.table('tasks') \
            .select('status') \
            .execute()
        
        tasks = tasks_result.data or []
        
        if not tasks:
            print("⚠️  No tasks found in database!")
        else:
            status_counts = {}
            for task in tasks:
                status = task.get('status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            print(f"Total tasks: {len(tasks)}")
            print()
            for status, count in sorted(status_counts.items()):
                print(f"  {status:15} : {count}")
        
        # Get queued tasks details
        queued_result = supabase.table('tasks') \
            .select('*') \
            .eq('status', 'Queued') \
            .limit(10) \
            .execute()
        
        queued_tasks = queued_result.data or []
        if queued_tasks:
            print()
            print(f"Recent queued tasks (showing {len(queued_tasks)}):")
            for task in queued_tasks:
                created = task.get('created_at', 'unknown')[:19]
                task_id = task.get('id', 'unknown')
                task_type = task.get('task_type', 'unknown')
                user_id = task.get('user_id', 'unknown')
                print(f"  {created} | {task_type:20} | User: {user_id}")
    
    except Exception as e:
        print(f"❌ Error querying tasks: {e}")
    
    print()
    
    # 4. Check for recent orchestrator cycles
    print("🔄 RECENT ORCHESTRATOR CYCLES")
    print("-"*80)
    try:
        # Get unique cycle numbers from logs
        cycles_result = supabase.table('system_logs') \
            .select('cycle_number, timestamp') \
            .eq('source_type', 'orchestrator_gpu') \
            .not_.is_('cycle_number', 'null') \
            .gte('timestamp', start_time.isoformat()) \
            .order('cycle_number', desc=True) \
            .limit(100) \
            .execute()
        
        cycle_logs = cycles_result.data or []
        
        if not cycle_logs:
            print("⚠️  No recent cycle logs found!")
            print("   The orchestrator may not be running or database logging is not enabled.")
        else:
            # Group by cycle number
            cycles = {}
            for log in cycle_logs:
                cycle_num = log.get('cycle_number')
                timestamp = log.get('timestamp')
                if cycle_num not in cycles:
                    cycles[cycle_num] = timestamp
            
            print(f"Found {len(cycles)} unique cycles in the last hour")
            print()
            print("Most recent cycles:")
            for cycle_num in sorted(cycles.keys(), reverse=True)[:10]:
                timestamp = cycles[cycle_num][:19].replace('T', ' ')
                print(f"  Cycle #{cycle_num}: {timestamp}")
    
    except Exception as e:
        print(f"❌ Error querying cycles: {e}")
    
    print()
    print("="*80)
    print("✅ Investigation complete")
    print()
    print("💡 NEXT STEPS:")
    print("   - If orchestrator is spawning workers, check the scaling decision logs above")
    print("   - If there are queued tasks, workers should be launched to process them")
    print("   - If there are errors, investigate the error messages above")
    print("   - Run: python scripts/view_logs_dashboard.py --source-type orchestrator_gpu")
    print("   - Run: python scripts/query_logs.py --source-type orchestrator_gpu --minutes 60")
    print("="*80)


if __name__ == "__main__":
    main()

