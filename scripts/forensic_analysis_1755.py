#!/usr/bin/env python3
"""
Deep Forensic Analysis: 17:55 Scale-Up Event
=============================================

Reconstruct exactly what happened when the orchestrator scaled to 2 workers at 17:55.
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
    
    print("="*100)
    print("🔬 FORENSIC ANALYSIS: 17:55 SCALE-UP EVENT")
    print("="*100)
    print()
    
    # Focus on 17:54-17:57 timeframe
    start_time = datetime(2025, 10, 16, 17, 54, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 10, 16, 17, 57, 0, tzinfo=timezone.utc)
    
    print(f"⏰ Analysis Window: {start_time.strftime('%H:%M:%S')} to {end_time.strftime('%H:%M:%S')}")
    print()
    
    # 1. Get ALL orchestrator logs in this timeframe
    print("="*100)
    print("📋 COMPLETE ORCHESTRATOR LOG TIMELINE (17:54-17:57)")
    print("="*100)
    
    try:
        logs_result = supabase.table('system_logs') \
            .select('*') \
            .eq('source_type', 'orchestrator_gpu') \
            .gte('timestamp', start_time.isoformat()) \
            .lte('timestamp', end_time.isoformat()) \
            .order('timestamp', desc=False) \
            .execute()
        
        logs = logs_result.data or []
        
        if not logs:
            print("⚠️  No orchestrator logs found in this timeframe!")
        else:
            print(f"Found {len(logs)} orchestrator log entries")
            print()
            
            # Group by cycle
            cycles = {}
            for log in logs:
                cycle = log.get('cycle_number', 'unknown')
                if cycle not in cycles:
                    cycles[cycle] = []
                cycles[cycle].append(log)
            
            print(f"Covering {len(cycles)} orchestrator cycles")
            print()
            
            # Display each cycle in detail
            for cycle_num in sorted(cycles.keys()):
                cycle_logs = cycles[cycle_num]
                
                print("─" * 100)
                print(f"🔄 CYCLE #{cycle_num}")
                print("─" * 100)
                
                for log in cycle_logs:
                    timestamp = log['timestamp'][11:19]  # Just the time
                    level = log['log_level']
                    message = log['message']
                    
                    # Color code by level
                    if level == 'ERROR':
                        prefix = "❌"
                    elif level == 'WARNING':
                        prefix = "⚠️ "
                    elif 'SCALING' in message or 'desired' in message.lower():
                        prefix = "🎯"
                    elif 'spawn' in message.lower():
                        prefix = "🚀"
                    elif 'task' in message.lower():
                        prefix = "📦"
                    elif 'worker' in message.lower():
                        prefix = "👷"
                    else:
                        prefix = "  "
                    
                    print(f"{prefix} [{timestamp}] [{level:8}] {message}")
                
                print()
    
    except Exception as e:
        print(f"❌ Error querying orchestrator logs: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # 2. Get worker state changes during this time
    print("="*100)
    print("👷 WORKER STATE CHANGES (17:54-17:57)")
    print("="*100)
    
    try:
        # Get workers created in this timeframe
        workers_result = supabase.table('workers').select('*') \
            .gte('created_at', start_time.isoformat()) \
            .lte('created_at', end_time.isoformat()) \
            .order('created_at', desc=False) \
            .execute()
        
        workers = workers_result.data or []
        
        if not workers:
            print("⚠️  No workers created in this timeframe")
        else:
            print(f"Found {len(workers)} workers created:")
            print()
            
            for worker in workers:
                created = worker.get('created_at', 'unknown')[11:19]
                worker_id = worker.get('id', 'unknown')
                status = worker.get('status', 'unknown')
                metadata = worker.get('metadata', {})
                runpod_id = metadata.get('runpod_id', 'N/A')
                
                print(f"🆕 [{created}] Worker created: {worker_id}")
                print(f"   Status: {status}")
                print(f"   RunPod: {runpod_id}")
                print()
    
    except Exception as e:
        print(f"❌ Error querying workers: {e}")
    
    print()
    
    # 3. Get task activity during this time
    print("="*100)
    print("📦 TASK ACTIVITY (17:54-17:57)")
    print("="*100)
    
    try:
        # Get tasks that were updated in this timeframe
        tasks_result = supabase.table('tasks') \
            .select('*') \
            .or_(
                f'created_at.gte.{start_time.isoformat()},'
                f'generation_started_at.gte.{start_time.isoformat()},'
                f'generation_processed_at.gte.{start_time.isoformat()}'
            ) \
            .or_(
                f'created_at.lte.{end_time.isoformat()},'
                f'generation_started_at.lte.{end_time.isoformat()},'
                f'generation_processed_at.lte.{end_time.isoformat()}'
            ) \
            .order('created_at', desc=False) \
            .limit(50) \
            .execute()
        
        tasks = tasks_result.data or []
        
        if not tasks:
            print("⚠️  No task activity in this timeframe")
        else:
            print(f"Found {len(tasks)} tasks with activity:")
            print()
            
            # Group by type of activity
            created_tasks = []
            started_tasks = []
            completed_tasks = []
            
            for task in tasks:
                created_at = task.get('created_at', '')
                started_at = task.get('generation_started_at', '')
                completed_at = task.get('generation_processed_at', '')
                
                if created_at and start_time.isoformat() <= created_at <= end_time.isoformat():
                    created_tasks.append(task)
                if started_at and start_time.isoformat() <= started_at <= end_time.isoformat():
                    started_tasks.append(task)
                if completed_at and start_time.isoformat() <= completed_at <= end_time.isoformat():
                    completed_tasks.append(task)
            
            if created_tasks:
                print(f"📝 {len(created_tasks)} tasks CREATED:")
                for task in created_tasks[:10]:
                    created = task.get('created_at', 'unknown')[11:19]
                    task_id = str(task.get('id', 'unknown'))[:8]
                    task_type = task.get('task_type', 'unknown')
                    status = task.get('status', 'unknown')
                    user_id = str(task.get('user_id', 'unknown'))[:8]
                    print(f"   [{created}] {task_type:20} | {status:12} | Task {task_id}... | User {user_id}...")
                print()
            
            if started_tasks:
                print(f"▶️  {len(started_tasks)} tasks STARTED:")
                for task in started_tasks[:10]:
                    started = task.get('generation_started_at', 'unknown')[11:19]
                    task_id = str(task.get('id', 'unknown'))[:8]
                    task_type = task.get('task_type', 'unknown')
                    worker_id = task.get('worker_id', 'N/A')
                    print(f"   [{started}] {task_type:20} | Task {task_id}... | Worker: {worker_id}")
                print()
            
            if completed_tasks:
                print(f"✅ {len(completed_tasks)} tasks COMPLETED:")
                for task in completed_tasks[:10]:
                    completed = task.get('generation_processed_at', 'unknown')[11:19]
                    task_id = str(task.get('id', 'unknown'))[:8]
                    task_type = task.get('task_type', 'unknown')
                    status = task.get('status', 'unknown')
                    print(f"   [{completed}] {task_type:20} | {status:12} | Task {task_id}...")
                print()
    
    except Exception as e:
        print(f"❌ Error querying tasks: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # 4. Look at the cycles just BEFORE this to understand what changed
    print("="*100)
    print("📊 CONTEXT: CYCLES BEFORE THE SCALE-UP (17:50-17:54)")
    print("="*100)
    
    try:
        before_start = datetime(2025, 10, 16, 17, 50, 0, tzinfo=timezone.utc)
        before_end = start_time
        
        before_logs = supabase.table('system_logs') \
            .select('*') \
            .eq('source_type', 'orchestrator_gpu') \
            .gte('timestamp', before_start.isoformat()) \
            .lt('timestamp', before_end.isoformat()) \
            .like('message', '%FINAL DESIRED%') \
            .order('timestamp', desc=False) \
            .execute()
        
        logs = before_logs.data or []
        
        if logs:
            print("Recent scaling decisions before the scale-up:")
            for log in logs:
                timestamp = log['timestamp'][11:19]
                cycle = log.get('cycle_number', '?')
                message = log['message']
                print(f"  [{timestamp}] Cycle #{cycle}: {message}")
        else:
            print("No scaling decisions found in the 5 minutes before")
        
        print()
    
    except Exception as e:
        print(f"❌ Error querying before context: {e}")
    
    print()
    
    # 5. Summary analysis
    print("="*100)
    print("🎯 ANALYSIS SUMMARY")
    print("="*100)
    print()
    
    print("The forensic timeline above shows:")
    print()
    print("1. What orchestrator cycles ran during 17:54-17:57")
    print("2. What scaling decisions were made (desired worker counts)")
    print("3. What task counts the orchestrator observed")
    print("4. Which workers were spawned and when")
    print("5. What tasks were created, started, or completed")
    print("6. What the system state was just before the scale-up")
    print()
    print("Look for patterns like:")
    print("  - Sudden increase in queued tasks")
    print("  - Tasks becoming available (users dropping below concurrency limit)")
    print("  - Workers completing tasks (freeing capacity)")
    print("  - Failure rate dropping below threshold")
    print()
    print("="*100)


if __name__ == "__main__":
    main()





