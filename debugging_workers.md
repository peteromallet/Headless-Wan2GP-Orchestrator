# Debugging Workers Guide

Quick reference for investigating worker issues and crashes.

---

## 1. Check Worker Status & Heartbeat

### Get Worker Details
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone

db = DatabaseClient()
worker_id = 'YOUR_WORKER_ID'

result = db.supabase.table('workers').select('*').eq('id', worker_id).execute()

if result.data:
    w = result.data[0]
    print(f'Status: {w[\"status\"]}')
    print(f'Created: {w[\"created_at\"]}')
    
    # Check heartbeat freshness
    last_hb = w.get('last_heartbeat')
    if last_hb:
        last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        age_sec = (now - last_hb_time).total_seconds()
        
        status = '✅' if age_sec < 60 else ('⚠️' if age_sec < 300 else '❌')
        print(f'Last heartbeat: {age_sec:.1f}s ago ({age_sec/60:.1f} min) {status}')
    
    # Check metadata
    metadata = w.get('metadata', {})
    print(f'RAM Tier: {metadata.get(\"ram_tier\", \"Unknown\")} GB')
    print(f'GPU: {metadata.get(\"pod_details\", {}).get(\"gpu_type_id\", \"Unknown\")}')
"
```

**Heartbeat Status:**
- ✅ < 60s = Alive
- ⚠️ 60s-5min = Aging
- ❌ > 5min = Dead/Crashed

---

## 2. Get Worker Logs

### Recent Logs (Simple)
```bash
python3 scripts/query_logs.py --worker WORKER_ID --limit 20
```

### All Logs (Comprehensive)
```python
python3 -c "
from supabase import create_client
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

worker_id = 'YOUR_WORKER_ID'

result = supabase.table('system_logs').select('timestamp, task_id, message, log_level').eq('worker_id', worker_id).order('timestamp').execute()

if result.data:
    print(f'Total logs: {len(result.data)}\\n')
    
    for i, log in enumerate(result.data, 1):
        task_short = log.get('task_id', 'no-task')[:8] if log.get('task_id') else 'no-task'
        print(f'{i:3}. {log[\"timestamp\"]} | {task_short}... | {log[\"message\"][:80]}')
    
    # Show last log
    last = result.data[-1]
    last_time = datetime.fromisoformat(last['timestamp'].replace('Z', '+00:00'))
    silence = (datetime.now(timezone.utc) - last_time).total_seconds() / 60
    
    print(f'\\n🔴 Last log: {last[\"message\"]}')
    print(f'Silence: {silence:.1f} minutes')
"
```

### Find Last Log Before Crash
Look for the absolute last message - often:
- `✅ [HEARTBEAT] Worker ... active`
- `🔄 MODEL SWITCH: ...`
- Or task-specific messages

---

## 3. Find Tasks Assigned to Worker

```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient

db = DatabaseClient()
worker_id = 'YOUR_WORKER_ID'

result = db.supabase.table('tasks').select('id, task_type, status, created_at, generation_started_at').eq('worker_id', worker_id).execute()

if result.data:
    print(f'Total tasks: {len(result.data)}\\n')
    for task in result.data:
        print(f'{task[\"task_type\"]:20} {task[\"id\"]}')
        print(f'  Status: {task[\"status\"]}')
        print(f'  Started: {task.get(\"generation_started_at\", \"None\")}')
        print()
"
```

---

## 4. Check for Crash Patterns

### A. Heartbeat Analysis
```python
python3 -c "
from supabase import create_client
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

worker_id = 'YOUR_WORKER_ID'

# Get all heartbeat logs
result = supabase.table('system_logs').select('timestamp').eq('worker_id', worker_id).ilike('message', '%HEARTBEAT%').order('timestamp').execute()

if result.data:
    print(f'Total heartbeat logs: {len(result.data)}')
    
    # Check gaps between heartbeats
    prev_time = None
    for log in result.data:
        timestamp = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
        
        if prev_time:
            gap_sec = (timestamp - prev_time).total_seconds()
            if gap_sec > 40:
                print(f'⚠️  Long gap: {gap_sec:.1f}s at {timestamp}')
        
        prev_time = timestamp
    
    # Check database heartbeats vs logged heartbeats
    print(f'\\nNote: Database heartbeats (workers.last_heartbeat) update every ~20s')
    print(f'Logged heartbeats are less frequent (informational only)')
"
```

### B. Model Switch Crash Pattern
```python
python3 -c "
from supabase import create_client
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

worker_id = 'YOUR_WORKER_ID'

# Find MODEL SWITCH log
switch_result = supabase.table('system_logs').select('timestamp').eq('worker_id', worker_id).ilike('message', '%MODEL SWITCH%').order('timestamp', desc=True).limit(1).execute()

if switch_result.data:
    switch_time = datetime.fromisoformat(switch_result.data[0]['timestamp'].replace('Z', '+00:00'))
    print(f'MODEL SWITCH at: {switch_time}')
    
    # Get all logs AFTER model switch
    logs_after = supabase.table('system_logs').select('timestamp, message').eq('worker_id', worker_id).gte('timestamp', switch_result.data[0]['timestamp']).order('timestamp').execute()
    
    print(f'\\nLogs after MODEL SWITCH:')
    for i, log in enumerate(logs_after.data, 1):
        log_time = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
        time_after = (log_time - switch_time).total_seconds()
        print(f'{i}. +{time_after:.1f}s: {log[\"message\"][:80]}')
    
    # Check if worker crashed during model loading
    last_log_time = datetime.fromisoformat(logs_after.data[-1]['timestamp'].replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    silence = (now - last_log_time).total_seconds()
    
    if silence > 120:
        print(f'\\n❌ Worker crashed {silence/60:.1f} minutes after MODEL SWITCH')
        print(f'Crash time: ~{(last_log_time - switch_time).total_seconds()/60:.1f} min after switch')
"
```

---

## 5. Common Crash Patterns

### Pattern 1: OOM During Model Loading
```
✅ MODEL SWITCH logged
✅ One or two heartbeats after (5-90 seconds)
❌ Worker dies silently
❌ No error logs
❌ Task left "In Progress" (orphaned)
```

**Timing:** Usually 1.5-5 minutes after MODEL SWITCH

**Cause:** Out of memory during model loading into VRAM

### Pattern 2: Initialization Failure
```
✅ Worker created
✅ One heartbeat sent (immediately)
❌ Never logs anything else
❌ Never picks up tasks
```

**Timing:** Within first 10 seconds

**Cause:** Worker process crashes before logging setup completes

### Pattern 3: VLM Loading Hang
```
✅ "Before VLM loading" logged
⏳ Long silence (5+ minutes)
❌ May or may not crash
```

**Timing:** 3-6 minutes during orchestrator phase

---

## 6. Quick Status Check Script

Save this as `check_worker.sh`:
```bash
#!/bin/bash

WORKER_ID=$1

if [ -z "$WORKER_ID" ]; then
    echo "Usage: ./check_worker.sh WORKER_ID"
    exit 1
fi

echo "=== Worker Status ==="
python3 scripts/query_logs.py --worker "$WORKER_ID" --limit 5

echo ""
echo "=== Tasks ==="
python3 -c "
from gpu_orchestrator.database import DatabaseClient
db = DatabaseClient()
result = db.supabase.table('tasks').select('id, task_type, status').eq('worker_id', '$WORKER_ID').execute()
for t in result.data:
    print(f'{t[\"task_type\"]}: {t[\"status\"]} - {t[\"id\"][:8]}')
"
```

Usage:
```bash
chmod +x check_worker.sh
./check_worker.sh gpu-20251017_130952-95cd7f4c
```

---

## 7. Find Active Workers

```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone

db = DatabaseClient()

result = db.supabase.table('workers').select('id, status, last_heartbeat').eq('status', 'active').execute()

now = datetime.now(timezone.utc)

print('ACTIVE WORKERS:')
for w in result.data:
    worker_id = w['id']
    last_hb = w.get('last_heartbeat')
    
    if last_hb:
        last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
        age_min = (now - last_hb_time).total_seconds() / 60
        
        status = '✅' if age_min < 1 else ('⚠️' if age_min < 5 else '❌')
        print(f'{status} {worker_id} | HB: {age_min:.1f}m ago')
"
```

---

## 8. Find All Recent Workers

### All Workers Created in Last N Hours
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone, timedelta

db = DatabaseClient()

# Get workers from last 6 hours
hours_ago = 6
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

result = db.supabase.table('workers').select('id, status, created_at, last_heartbeat, metadata').gte('created_at', cutoff_time.isoformat()).order('created_at', desc=True).execute()

now = datetime.now(timezone.utc)

print(f'WORKERS FROM LAST {hours_ago} HOURS:')
print('='*100)
print(f'Total: {len(result.data)}\\n')

for w in result.data:
    worker_id = w['id']
    created = datetime.fromisoformat(w['created_at'].replace('Z', '+00:00'))
    age_min = (now - created).total_seconds() / 60
    
    # Heartbeat status
    last_hb = w.get('last_heartbeat')
    hb_status = '❓'
    if last_hb:
        last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
        hb_age_min = (now - last_hb_time).total_seconds() / 60
        hb_status = '✅' if hb_age_min < 1 else ('⚠️' if hb_age_min < 5 else '❌')
    
    metadata = w.get('metadata', {})
    ram_tier = metadata.get('ram_tier', '?')
    
    print(f'{hb_status} {worker_id[:30]}')
    print(f'   Status: {w[\"status\"]:10} | Age: {age_min:.0f}m | RAM: {ram_tier}GB | Created: {created.strftime(\"%H:%M:%S\")}')
    print()
"
```

### Workers by Date Range
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone

db = DatabaseClient()

# Specify date range
start_date = '2025-10-17T12:00:00'
end_date = '2025-10-17T14:00:00'

result = db.supabase.table('workers').select('id, status, created_at').gte('created_at', start_date).lte('created_at', end_date).order('created_at').execute()

print(f'Workers between {start_date} and {end_date}:')
print(f'Total: {len(result.data)}\\n')

for w in result.data:
    print(f'{w[\"id\"]} | {w[\"status\"]:10} | {w[\"created_at\"]}')
"
```

---

## 9. Find Workers with Stale Heartbeats

### All Workers with Dead Heartbeats
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone, timedelta

db = DatabaseClient()

result = db.supabase.table('workers').select('id, status, last_heartbeat, created_at').eq('status', 'active').execute()

now = datetime.now(timezone.utc)
stale_threshold_min = 5

print('WORKERS WITH STALE HEARTBEATS (>5 min):')
print('='*100)

stale_workers = []

for w in result.data:
    last_hb = w.get('last_heartbeat')
    
    if last_hb:
        last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
        age_min = (now - last_hb_time).total_seconds() / 60
        
        if age_min > stale_threshold_min:
            created = datetime.fromisoformat(w['created_at'].replace('Z', '+00:00'))
            lifetime_min = (now - created).total_seconds() / 60
            
            stale_workers.append({
                'id': w['id'],
                'hb_age': age_min,
                'lifetime': lifetime_min
            })

if stale_workers:
    print(f'Found {len(stale_workers)} stale workers:\\n')
    
    for sw in sorted(stale_workers, key=lambda x: x['hb_age'], reverse=True):
        print(f'❌ {sw[\"id\"]}')
        print(f'   Last heartbeat: {sw[\"hb_age\"]:.1f} min ago')
        print(f'   Worker age: {sw[\"lifetime\"]:.1f} min')
        print()
else:
    print('✅ No stale workers found')
"
```

### Quick Stale Workers Check
```bash
# One-liner to find stale workers
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone

db = DatabaseClient()
result = db.supabase.table('workers').select('id, last_heartbeat').eq('status', 'active').execute()
now = datetime.now(timezone.utc)

for w in result.data:
    if w.get('last_heartbeat'):
        age = (now - datetime.fromisoformat(w['last_heartbeat'].replace('Z', '+00:00'))).total_seconds() / 60
        if age > 5:
            print(f'❌ {w[\"id\"]} - {age:.1f}m stale')
"
```

---

## 10. Find Workers with Failed Tasks

### Workers with Any Failed Tasks
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient

db = DatabaseClient()

# Get all failed tasks
result = db.supabase.table('tasks').select('worker_id, id, task_type, error_message, created_at').eq('status', 'Failed').order('created_at', desc=True).limit(50).execute()

print('WORKERS WITH FAILED TASKS:')
print('='*100)

if result.data:
    print(f'Total failed tasks: {len(result.data)}\\n')
    
    # Group by worker
    workers_with_failures = {}
    for task in result.data:
        worker_id = task.get('worker_id', 'unknown')
        if worker_id not in workers_with_failures:
            workers_with_failures[worker_id] = []
        workers_with_failures[worker_id].append(task)
    
    for worker_id, tasks in workers_with_failures.items():
        print(f'Worker: {worker_id}')
        print(f'Failed tasks: {len(tasks)}')
        
        for task in tasks[:3]:  # Show first 3
            print(f'  - {task[\"task_type\"]:20} {task[\"id\"][:8]}... | {task.get(\"error_message\", \"No error\")[:50]}')
        
        if len(tasks) > 3:
            print(f'  ... and {len(tasks) - 3} more')
        print()
else:
    print('✅ No failed tasks found')
"
```

### Failed Tasks by Worker ID
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient

db = DatabaseClient()
worker_id = 'YOUR_WORKER_ID'

result = db.supabase.table('tasks').select('id, task_type, status, error_message, created_at').eq('worker_id', worker_id).eq('status', 'Failed').execute()

print(f'FAILED TASKS FOR WORKER: {worker_id}')
print('='*100)

if result.data:
    print(f'Total: {len(result.data)}\\n')
    
    for task in result.data:
        print(f'{task[\"task_type\"]:20} {task[\"id\"]}')
        print(f'  Created: {task[\"created_at\"]}')
        print(f'  Error: {task.get(\"error_message\", \"None\")}')
        print()
else:
    print('✅ No failed tasks')
"
```

---

## 11. Find Orphaned Tasks

### Tasks "In Progress" with No Active Worker
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone

db = DatabaseClient()

# Get all 'In Progress' tasks
result = db.supabase.table('tasks').select('id, task_type, worker_id, generation_started_at, created_at').eq('status', 'In Progress').execute()

now = datetime.now(timezone.utc)

print('ORPHANED TASKS (In Progress with dead/missing worker):')
print('='*100)

orphaned = []

for task in result.data:
    worker_id = task.get('worker_id')
    
    if not worker_id:
        print(f'⚠️  Task {task[\"id\"][:8]}... has no worker assigned')
        continue
    
    # Check worker status
    worker_result = db.supabase.table('workers').select('status, last_heartbeat').eq('id', worker_id).execute()
    
    if not worker_result.data:
        orphaned.append({
            'task_id': task['id'],
            'task_type': task['task_type'],
            'worker_id': worker_id,
            'reason': 'Worker deleted'
        })
        continue
    
    worker = worker_result.data[0]
    last_hb = worker.get('last_heartbeat')
    
    if last_hb:
        last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
        hb_age_min = (now - last_hb_time).total_seconds() / 60
        
        if hb_age_min > 5:
            started = task.get('generation_started_at')
            runtime = '?'
            if started:
                started_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
                runtime = f'{(now - started_time).total_seconds() / 60:.1f}'
            
            orphaned.append({
                'task_id': task['id'],
                'task_type': task['task_type'],
                'worker_id': worker_id,
                'reason': f'Worker heartbeat stale ({hb_age_min:.1f}m)',
                'runtime': runtime
            })

if orphaned:
    print(f'Found {len(orphaned)} orphaned tasks:\\n')
    
    for o in orphaned:
        print(f'❌ {o[\"task_type\"]:20} {o[\"task_id\"][:8]}...')
        print(f'   Worker: {o[\"worker_id\"][:30]}')
        print(f'   Reason: {o[\"reason\"]}')
        if 'runtime' in o:
            print(f'   Runtime: {o[\"runtime\"]}m')
        print()
else:
    print('✅ No orphaned tasks found')
"
```

---

## 12. Find Workers by Crash Pattern

### Workers That Crashed During Model Loading
```python
python3 -c "
from supabase import create_client
from gpu_orchestrator.database import DatabaseClient
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
db = DatabaseClient()

# Get workers from last 24 hours
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

# Find all workers that logged MODEL SWITCH
switch_logs = supabase.table('system_logs').select('worker_id, timestamp').ilike('message', '%MODEL SWITCH%').gte('timestamp', cutoff.isoformat()).execute()

print('WORKERS THAT HIT MODEL SWITCH:')
print('='*100)

crashed_during_model_loading = []

for log in switch_logs.data:
    worker_id = log['worker_id']
    switch_time = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
    
    # Get all logs after MODEL SWITCH
    logs_after = supabase.table('system_logs').select('timestamp').eq('worker_id', worker_id).gt('timestamp', log['timestamp']).execute()
    
    # Check worker current status
    worker_result = db.supabase.table('workers').select('status, last_heartbeat').eq('id', worker_id).execute()
    
    if worker_result.data:
        worker = worker_result.data[0]
        last_hb = worker.get('last_heartbeat')
        
        if last_hb:
            last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
            
            # If last heartbeat is close to MODEL SWITCH and now stale = crashed during loading
            time_between = (last_hb_time - switch_time).total_seconds() / 60
            now = datetime.now(timezone.utc)
            hb_age = (now - last_hb_time).total_seconds() / 60
            
            if time_between < 10 and hb_age > 5:  # Died within 10 min of switch
                crashed_during_model_loading.append({
                    'worker_id': worker_id,
                    'switch_time': switch_time,
                    'crash_time': time_between,
                    'logs_after_switch': len(logs_after.data)
                })

if crashed_during_model_loading:
    print(f'Found {len(crashed_during_model_loading)} workers that crashed during model loading:\\n')
    
    for c in crashed_during_model_loading:
        print(f'❌ {c[\"worker_id\"]}')
        print(f'   MODEL SWITCH: {c[\"switch_time\"].strftime(\"%H:%M:%S\")}')
        print(f'   Crashed after: {c[\"crash_time\"]:.1f} minutes')
        print(f'   Logs after switch: {c[\"logs_after_switch\"]}')
        print()
else:
    print('✅ No crashed workers found')
"
```

---

## 13. Worker Summary Report

### Comprehensive System Status
```python
python3 -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timezone, timedelta

db = DatabaseClient()
now = datetime.now(timezone.utc)
hours_ago = 6
cutoff = now - timedelta(hours=hours_ago)

print('='*100)
print(f'WORKER SYSTEM REPORT - Last {hours_ago} Hours')
print('='*100)

# Get all workers
all_workers = db.supabase.table('workers').select('id, status, last_heartbeat, created_at').gte('created_at', cutoff.isoformat()).execute()

# Categorize
alive = []
stale = []
terminated = []

for w in all_workers.data:
    if w['status'] == 'terminated':
        terminated.append(w)
    elif w.get('last_heartbeat'):
        last_hb_time = datetime.fromisoformat(w['last_heartbeat'].replace('Z', '+00:00'))
        age_min = (now - last_hb_time).total_seconds() / 60
        
        if age_min < 5:
            alive.append(w)
        else:
            stale.append(w)

print(f'\\n📊 WORKER COUNTS:')
print(f'   Total created: {len(all_workers.data)}')
print(f'   ✅ Alive: {len(alive)}')
print(f'   ❌ Stale: {len(stale)}')
print(f'   🔴 Terminated: {len(terminated)}')

# Get task stats
tasks = db.supabase.table('tasks').select('status, task_type').gte('created_at', cutoff.isoformat()).execute()

in_progress = sum(1 for t in tasks.data if t['status'] == 'In Progress')
completed = sum(1 for t in tasks.data if t['status'] == 'Completed')
failed = sum(1 for t in tasks.data if t['status'] == 'Failed')
queued = sum(1 for t in tasks.data if t['status'] == 'Queued')

print(f'\\n📋 TASK COUNTS:')
print(f'   Total: {len(tasks.data)}')
print(f'   ⏳ In Progress: {in_progress}')
print(f'   ✅ Completed: {completed}')
print(f'   ❌ Failed: {failed}')
print(f'   📥 Queued: {queued}')

# Success rate
if len(tasks.data) > 0:
    success_rate = (completed / len(tasks.data)) * 100
    failure_rate = (failed / len(tasks.data)) * 100
    print(f'\\n📈 SUCCESS RATE: {success_rate:.1f}%')
    print(f'   Failure rate: {failure_rate:.1f}%')

# Average worker lifetime
if len(all_workers.data) > 0:
    total_lifetime = 0
    for w in all_workers.data:
        created = datetime.fromisoformat(w['created_at'].replace('Z', '+00:00'))
        if w.get('last_heartbeat'):
            last_hb = datetime.fromisoformat(w['last_heartbeat'].replace('Z', '+00:00'))
            lifetime = (last_hb - created).total_seconds() / 60
            total_lifetime += lifetime
    
    avg_lifetime = total_lifetime / len(all_workers.data)
    print(f'\\n⏱️  AVERAGE WORKER LIFETIME: {avg_lifetime:.1f} minutes')

print('\\n' + '='*100)
"
```

---

## 14. Memory Profile Check

```bash
# Check what memory profile a worker is using
python3 scripts/query_logs.py --worker WORKER_ID | grep -i "memory profile"
```

Or:
```python
python3 -c "
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

worker_id = 'YOUR_WORKER_ID'

result = supabase.table('system_logs').select('message').eq('worker_id', worker_id).ilike('message', '%Memory Profile%').limit(1).execute()

if result.data:
    msg = result.data[0]['message']
    if 'Profile 3' in msg:
        print('Memory Profile: 3')
    elif 'Profile 4' in msg:
        print('Memory Profile: 4')
    else:
        print(f'Found: {msg}')
else:
    print('No memory profile log found')
"
```

---

## 15. Investigation Checklist

When investigating a worker crash:

- [ ] Check last heartbeat age (workers table)
- [ ] Get all logs for the worker
- [ ] Identify the last log before silence
- [ ] Look for MODEL SWITCH log
- [ ] Calculate time between MODEL SWITCH and crash
- [ ] Check for heartbeat gaps
- [ ] Find any error messages
- [ ] Check tasks assigned to worker
- [ ] Verify memory profile being used
- [ ] Compare crash timing with other failed workers

---

## 16. Key Insights

**Two Types of Heartbeats:**
1. **Database heartbeats** (`workers.last_heartbeat`): Updated every ~20s, this is what the orchestrator monitors
2. **Logged heartbeats** (`system_logs`): Occasional informational messages, not sent every time

**Critical Crash Window:**
- Most workers crash 1.5-5 minutes after MODEL SWITCH
- The crash happens during silent model loading (no logs during this phase)
- No error is logged because the process is killed by OOM or hangs

**What "In Progress" Task + Stale Heartbeat Means:**
- Worker crashed without completing the task
- Task is "orphaned" and needs cleanup/retry
- Orchestrator will detect stale heartbeat after 5 minutes and terminate the worker record

