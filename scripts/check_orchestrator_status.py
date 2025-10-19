#!/usr/bin/env python3
"""
Check Orchestrator Status
==========================

Verify if the orchestrator is still running and when the last activity was.
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
print("🔍 ORCHESTRATOR STATUS CHECK")
print("="*100)
print()

now = datetime.now(timezone.utc)
print(f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Get the most recent orchestrator log
print("📋 MOST RECENT ORCHESTRATOR ACTIVITY")
print("-"*100)

try:
    recent_logs = supabase.table('system_logs') \
        .select('*') \
        .eq('source_type', 'orchestrator_gpu') \
        .order('timestamp', desc=True) \
        .limit(10) \
        .execute()
    
    logs = recent_logs.data or []
    
    if not logs:
        print("❌ NO ORCHESTRATOR LOGS FOUND AT ALL!")
        print("   The orchestrator may not be running or database logging is not enabled.")
    else:
        most_recent = logs[0]
        most_recent_time = datetime.fromisoformat(most_recent['timestamp'].replace('Z', '+00:00'))
        age_seconds = (now - most_recent_time).total_seconds()
        age_minutes = age_seconds / 60
        
        print(f"Most recent log: {most_recent['timestamp']}")
        print(f"Age: {age_minutes:.1f} minutes ago ({age_seconds:.0f} seconds)")
        print(f"Cycle: #{most_recent.get('cycle_number', 'N/A')}")
        print(f"Message: {most_recent['message'][:100]}")
        print()
        
        if age_minutes > 5:
            print("⚠️  WARNING: Last orchestrator activity was more than 5 minutes ago!")
            print("   The orchestrator may have stopped or crashed.")
        else:
            print("✅ Orchestrator appears to be running (recent activity)")
        
        print()
        print("Last 10 log entries:")
        for i, log in enumerate(logs, 1):
            timestamp = log['timestamp'][11:19]
            cycle = log.get('cycle_number', '?')
            message = log['message'][:80]
            print(f"  {i:2}. [{timestamp}] Cycle #{cycle:4}: {message}")

except Exception as e:
    print(f"❌ Error: {e}")

print()
print()

# Check the most recent worker creation with full details
print("👷 MOST RECENT WORKER CREATION")
print("-"*100)

try:
    recent_workers = supabase.table('workers').select('*') \
        .order('created_at', desc=True) \
        .limit(5) \
        .execute()
    
    workers = recent_workers.data or []
    
    if workers:
        print("Last 5 workers created:")
        print()
        for worker in workers:
            created = worker.get('created_at', 'unknown')
            created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            age_minutes = (now - created_dt).total_seconds() / 60
            
            worker_id = worker.get('id', 'unknown')
            status = worker.get('status', 'unknown')
            metadata = worker.get('metadata', {})
            runpod_id = metadata.get('runpod_id', 'N/A')
            
            print(f"  {worker_id}")
            print(f"    Created: {created} ({age_minutes:.1f} min ago)")
            print(f"    Status: {status}")
            print(f"    RunPod: {runpod_id}")
            print()

except Exception as e:
    print(f"❌ Error: {e}")

print()
print()

# Get cycle history for the last 30 minutes
print("🔄 CYCLE HISTORY (Last 30 Minutes)")
print("-"*100)

try:
    from datetime import timedelta
    thirty_min_ago = now - timedelta(minutes=30)
    
    cycle_logs = supabase.table('system_logs') \
        .select('timestamp, cycle_number, message') \
        .eq('source_type', 'orchestrator_gpu') \
        .like('message', '%Starting orchestrator cycle%') \
        .gte('timestamp', thirty_min_ago.isoformat()) \
        .order('timestamp', desc=False) \
        .execute()
    
    logs = cycle_logs.data or []
    
    if not logs:
        print("⚠️  No cycle starts found in last 30 minutes")
    else:
        print(f"Found {len(logs)} orchestrator cycles in the last 30 minutes")
        print()
        
        # Group by minute to see cycle frequency
        from collections import defaultdict
        cycles_per_minute = defaultdict(int)
        
        for log in logs:
            minute = log['timestamp'][:16]  # YYYY-MM-DDTHH:MM
            cycles_per_minute[minute] += 1
        
        print("Cycles per minute:")
        for minute in sorted(cycles_per_minute.keys(), reverse=True)[:10]:
            count = cycles_per_minute[minute]
            cycle_time = minute[11:]  # Just HH:MM
            print(f"  {cycle_time}: {count} cycle(s)")

except Exception as e:
    print(f"❌ Error: {e}")

print()
print("="*100)





