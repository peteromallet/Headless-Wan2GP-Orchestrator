#!/usr/bin/env python3
"""
Reconstruct Orchestrator Activity from Worker Metadata
=======================================================

Since orchestrator logs stopped at 17:35, reconstruct what happened
by analyzing worker metadata timestamps.
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
print("🔬 RECONSTRUCTING ORCHESTRATOR ACTIVITY FROM WORKER METADATA")
print("="*100)
print()

# Get all workers from 17:30 onwards
start_time = datetime(2025, 10, 16, 17, 30, 0, tzinfo=timezone.utc)

result = supabase.table('workers').select('*') \
    .gte('created_at', start_time.isoformat()) \
    .order('created_at', desc=False) \
    .execute()

workers = result.data or []

print(f"Found {len(workers)} workers created since 17:30")
print()

# Build a timeline from worker metadata
timeline = []

for worker in workers:
    worker_id = worker.get('id', 'unknown')
    created_at = worker.get('created_at', 'unknown')
    status = worker.get('status', 'unknown')
    metadata = worker.get('metadata', {})
    
    # Add creation event
    timeline.append({
        'time': created_at,
        'event': 'worker_created',
        'worker_id': worker_id,
        'detail': f"Status: {status}"
    })
    
    # Add promotion event if exists
    promoted_at = metadata.get('promoted_to_active_at')
    if promoted_at:
        timeline.append({
            'time': promoted_at,
            'event': 'worker_promoted',
            'worker_id': worker_id,
            'detail': 'Promoted to active'
        })
    
    # Add termination event if exists
    terminated_at = metadata.get('terminated_at')
    if terminated_at:
        timeline.append({
            'time': terminated_at,
            'event': 'worker_terminated',
            'worker_id': worker_id,
            'detail': f"Reason: {metadata.get('error_reason', 'Normal termination')}"
        })

# Sort timeline
timeline.sort(key=lambda x: x['time'])

print("📅 COMPLETE TIMELINE OF ORCHESTRATOR ACTIONS")
print("-"*100)

last_time = None
for event in timeline:
    time_str = event['time'][11:19]  # Just HH:MM:SS
    worker_id = event['worker_id'][:30]
    event_type = event['event']
    detail = event['detail']
    
    # Add separator between different minutes
    current_minute = event['time'][:16]
    if last_time and last_time[:16] != current_minute:
        print()
    last_time = event['time']
    
    # Format event type
    if event_type == 'worker_created':
        icon = "🆕"
    elif event_type == 'worker_promoted':
        icon = "⬆️ "
    elif event_type == 'worker_terminated':
        icon = "🛑"
    else:
        icon = "  "
    
    print(f"{icon} [{time_str}] {worker_id:30} | {event_type:20} | {detail}")

print()
print()

# Analyze the gaps
print("="*100)
print("📊 ANALYSIS: ORCHESTRATOR ACTIVITY PATTERNS")
print("="*100)
print()

# Group events by 5-minute windows
from collections import defaultdict

windows = defaultdict(lambda: {'created': 0, 'promoted': 0, 'terminated': 0})

for event in timeline:
    # Round to 5-minute window
    dt = datetime.fromisoformat(event['time'].replace('Z', '+00:00'))
    minute = dt.minute
    window_minute = (minute // 5) * 5
    window = dt.replace(minute=window_minute, second=0, microsecond=0)
    window_key = window.strftime('%H:%M')
    
    event_type = event['event']
    if 'created' in event_type:
        windows[window_key]['created'] += 1
    elif 'promoted' in event_type:
        windows[window_key]['promoted'] += 1
    elif 'terminated' in event_type:
        windows[window_key]['terminated'] += 1

print("Activity in 5-minute windows:")
print()
print("  Time  | Created | Promoted | Terminated")
print("  ------+---------+----------+-----------")

for window in sorted(windows.keys()):
    counts = windows[window]
    print(f"  {window} |    {counts['created']:2}   |    {counts['promoted']:2}    |     {counts['terminated']:2}")

print()
print()

# Check if there's a specific pattern around 17:55
print("="*100)
print("🎯 DEEP DIVE: WHAT HAPPENED AT 17:55?")
print("="*100)
print()

window_1755_start = datetime(2025, 10, 16, 17, 54, 0, tzinfo=timezone.utc)
window_1755_end = datetime(2025, 10, 16, 17, 58, 0, tzinfo=timezone.utc)

events_1755 = [
    e for e in timeline 
    if window_1755_start.isoformat() <= e['time'] <= window_1755_end.isoformat()
]

if events_1755:
    print(f"Found {len(events_1755)} orchestrator actions between 17:54-17:58:")
    print()
    
    for event in events_1755:
        time_str = event['time'][11:19]
        worker_id = event['worker_id']
        event_type = event['event']
        detail = event['detail']
        
        print(f"  [{time_str}] {event_type:20} | {worker_id}")
        print(f"           {detail}")
        print()
    
    # Count workers in different states
    workers_1755 = {}
    for event in events_1755:
        worker_id = event['worker_id']
        if worker_id not in workers_1755:
            workers_1755[worker_id] = []
        workers_1755[worker_id].append(event)
    
    print(f"Workers involved: {len(workers_1755)}")
    print()
    
    for worker_id, events in workers_1755.items():
        print(f"  {worker_id}:")
        for e in events:
            time_str = e['time'][11:19]
            print(f"    - [{time_str}] {e['event']}: {e['detail']}")
        print()
else:
    print("No orchestrator actions found between 17:54-17:58")

print()

# Final summary
print("="*100)
print("💡 CONCLUSIONS")
print("="*100)
print()

last_event = timeline[-1] if timeline else None
if last_event:
    last_time = datetime.fromisoformat(last_event['time'].replace('Z', '+00:00'))
    age = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
    
    print(f"✅ Orchestrator IS ACTIVE")
    print(f"   - Last action: {last_event['event']} at {last_event['time'][11:19]}")
    print(f"   - {age:.1f} minutes ago")
    print(f"   - Worker: {last_event['worker_id']}")
    print()
    
    if age < 5:
        print("✅ Orchestrator is actively managing workers")
    else:
        print(f"⚠️  Last action was {age:.1f} minutes ago - may be idle")

print()
print("🐛 DATABASE LOGGING ISSUE:")
print("   - Orchestrator logs to database stopped at 17:35")
print("   - But orchestrator continues to manage workers")
print("   - Worker metadata updates are still working")
print("   - Possible causes:")
print("     • Database log handler crashed")
print("     • Log queue overflow")
print("     • Network issue with log submission")
print("     • Rate limiting on log insertion")
print()
print("="*100)





