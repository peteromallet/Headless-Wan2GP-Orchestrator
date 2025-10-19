#!/usr/bin/env python3
"""
Check for Scale-Up Events
==========================

Search for recent scale-up events in orchestrator logs.
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
    print("🔍 SEARCHING FOR SCALE-UP EVENTS")
    print("="*80)
    print()
    
    # Search for the last 6 hours
    start_time = datetime.now(timezone.utc) - timedelta(hours=6)
    
    # 1. Look for "desired workers: 2" or higher in scaling decisions
    print("📈 SCALING DECISIONS (Last 6 Hours)")
    print("-"*80)
    try:
        logs_result = supabase.table('system_logs') \
            .select('*') \
            .eq('source_type', 'orchestrator_gpu') \
            .gte('timestamp', start_time.isoformat()) \
            .like('message', '%FINAL DESIRED%') \
            .order('timestamp', desc=True) \
            .limit(100) \
            .execute()
        
        logs = logs_result.data or []
        
        if not logs:
            print("⚠️  No scaling decision logs found")
        else:
            print(f"Found {len(logs)} scaling decision log entries")
            print()
            
            # Parse desired workers from messages
            for log in logs:
                timestamp = log['timestamp'][:19].replace('T', ' ')
                message = log['message']
                cycle = log.get('cycle_number', '?')
                
                # Extract the number from "→ FINAL DESIRED: X workers"
                if 'FINAL DESIRED:' in message:
                    try:
                        parts = message.split('FINAL DESIRED:')[1].strip()
                        desired = int(parts.split()[0])
                        
                        # Highlight if desired >= 2
                        if desired >= 2:
                            print(f"  🔥 [{timestamp}] Cycle #{cycle}: DESIRED {desired} WORKERS")
                        else:
                            print(f"  [{timestamp}] Cycle #{cycle}: Desired {desired} workers")
                    except:
                        print(f"  [{timestamp}] Cycle #{cycle}: {message}")
    
    except Exception as e:
        print(f"❌ Error querying scaling decisions: {e}")
    
    print()
    
    # 2. Look for worker spawn events
    print("🚀 WORKER SPAWN EVENTS (Last 6 Hours)")
    print("-"*80)
    try:
        spawn_logs = supabase.table('system_logs') \
            .select('*') \
            .eq('source_type', 'orchestrator_gpu') \
            .gte('timestamp', start_time.isoformat()) \
            .or_('message.ilike.%spawning worker%,message.ilike.%workers_spawned%,message.ilike.%Scaling up%') \
            .order('timestamp', desc=True) \
            .limit(50) \
            .execute()
        
        logs = spawn_logs.data or []
        
        if not logs:
            print("⚠️  No worker spawn events found")
        else:
            print(f"Found {len(logs)} spawn-related log entries")
            print()
            
            for log in logs:
                timestamp = log['timestamp'][:19].replace('T', ' ')
                message = log['message']
                cycle = log.get('cycle_number', '?')
                level = log['log_level']
                
                # Highlight actual spawns
                if 'workers_spawned' in message and 'workers_spawned": 0' not in message and "'workers_spawned': 0" not in message:
                    print(f"  🔥 [{timestamp}] Cycle #{cycle} [{level}] {message}")
                elif 'Scaling up' in message:
                    print(f"  🔥 [{timestamp}] Cycle #{cycle} [{level}] {message}")
                else:
                    print(f"  [{timestamp}] Cycle #{cycle} [{level}] {message}")
    
    except Exception as e:
        print(f"❌ Error querying spawn events: {e}")
    
    print()
    
    # 3. Look for cycles where capacity changed
    print("📊 CAPACITY CHANGES (Last 6 Hours)")
    print("-"*80)
    try:
        capacity_logs = supabase.table('system_logs') \
            .select('*') \
            .eq('source_type', 'orchestrator_gpu') \
            .gte('timestamp', start_time.isoformat()) \
            .like('message', '%Current state:%') \
            .order('timestamp', desc=True) \
            .limit(50) \
            .execute()
        
        logs = capacity_logs.data or []
        
        if not logs:
            print("⚠️  No capacity logs found")
        else:
            print(f"Found {len(logs)} capacity log entries")
            print()
            print("Recent capacity states:")
            
            for log in logs[:20]:
                timestamp = log['timestamp'][:19].replace('T', ' ')
                message = log['message']
                cycle = log.get('cycle_number', '?')
                
                # Extract numbers from "Current state: X spawning, Y active, Z terminating"
                if 'spawning,' in message and 'active,' in message:
                    try:
                        parts = message.split('Current state:')[1].strip()
                        spawning = int(parts.split('spawning,')[0].strip())
                        active_part = parts.split('spawning,')[1].split('active,')[0].strip()
                        active = int(active_part)
                        total_workers = spawning + active
                        
                        if total_workers >= 2:
                            print(f"  🔥 [{timestamp}] Cycle #{cycle}: {spawning} spawning + {active} active = {total_workers} TOTAL")
                        else:
                            print(f"  [{timestamp}] Cycle #{cycle}: {spawning} spawning + {active} active = {total_workers} total")
                    except:
                        print(f"  [{timestamp}] Cycle #{cycle}: {message}")
    
    except Exception as e:
        print(f"❌ Error querying capacity changes: {e}")
    
    print()
    
    # 4. Check worker creation events in database
    print("👷 WORKER CREATION HISTORY (Last 6 Hours)")
    print("-"*80)
    try:
        workers_result = supabase.table('workers').select('*') \
            .gte('created_at', start_time.isoformat()) \
            .order('created_at', desc=True) \
            .execute()
        
        workers = workers_result.data or []
        
        if not workers:
            print("⚠️  No workers created in the last 6 hours")
        else:
            print(f"Found {len(workers)} workers created in the last 6 hours")
            print()
            
            # Group by time buckets to see when multiple workers were created
            from collections import defaultdict
            workers_by_minute = defaultdict(list)
            
            for worker in workers:
                created = worker.get('created_at', '')[:16]  # Group by minute
                workers_by_minute[created].append(worker)
            
            print("Workers created per minute:")
            for minute in sorted(workers_by_minute.keys(), reverse=True):
                worker_list = workers_by_minute[minute]
                count = len(worker_list)
                
                if count >= 2:
                    print(f"\n  🔥 {minute}: {count} WORKERS CREATED")
                    for worker in worker_list:
                        worker_id = worker.get('id', 'unknown')
                        status = worker.get('status', 'unknown')
                        print(f"     - {worker_id} ({status})")
                else:
                    worker = worker_list[0]
                    worker_id = worker.get('id', 'unknown')
                    status = worker.get('status', 'unknown')
                    print(f"  {minute}: 1 worker - {worker_id} ({status})")
    
    except Exception as e:
        print(f"❌ Error querying worker creation: {e}")
    
    print()
    print("="*80)
    print("✅ Scale-up analysis complete")
    print()
    print("Legend:")
    print("  🔥 = 2+ workers active/desired/spawned")
    print("  Regular = 1 worker or less")
    print("="*80)


if __name__ == "__main__":
    main()





