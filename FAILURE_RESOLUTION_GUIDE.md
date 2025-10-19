# Failure Rate Resolution Guide

## Current Situation (as of latest check)

**Status**: ⚠️ **PARTIALLY RECOVERED - Still Blocking**

- **Failure Rate**: 85.7% (6/7 workers in last 30 minutes)
- **Threshold**: 80%
- **Spawning**: BLOCKED (failure rate too high)
- **Healthy Workers**: 1 active worker (working normally!)
- **Queued Tasks**: 1 (waiting for capacity)

## Why Scaling is Still Blocked

Even though you have **1 healthy worker** processing tasks successfully, the orchestrator sees:
- 6 terminated/failed workers in the last 30 minutes
- 1 active worker
- **Failure rate: 6/7 = 85.7%** > 80% threshold

The system is preventing new spawns to avoid wasting money on potentially failing workers.

## What's Happening Right Now

### The Good 👍
- 1 worker is healthy and processing tasks
- Worker has recent heartbeat (13s ago)
- Worker completed multiple tasks successfully
- No systemic issue preventing workers from running

### The Bad 👎
- 6 failed workers from the past hour are still in the 30-minute rolling window
- This keeps the failure rate above 80%
- New workers cannot spawn until rate drops below 80%

### The Timeline ⏱️
```
Now:  19:22 UTC - 1 healthy worker, 6 failures in window → 85.7% → BLOCKING
+5min: 19:27 UTC - Some failures start aging out
+10min: 19:32 UTC - More failures age out, rate may drop below 80%
+15min: 19:37 UTC - Should have clean window if no new failures
```

## Resolution Options

### Option 1: Wait It Out (Recommended) ⏰
**Time**: 10-15 minutes  
**Risk**: None  
**Action**: Do nothing, let the system self-heal

The failed workers will age out of the 30-minute window automatically:
- At 19:32 UTC: Most failures will be > 30 minutes old
- Failure rate will drop below 80%
- Orchestrator will automatically resume spawning
- System returns to normal

**This is the safest approach** - the system is designed to self-recover.

### Option 2: Manual Intervention 🛠️
**Time**: Immediate  
**Risk**: Low (if done carefully)  
**Action**: Manually adjust the environment or clear old workers

#### 2a. Temporarily Increase Threshold
```bash
# In Railway dashboard, set environment variable:
MAX_WORKER_FAILURE_RATE=0.95  # Increase from 0.80 to 0.95 (95%)

# Redeploy orchestrator
# This will allow spawning even with current failure rate
```

**Pros**: Immediate relief  
**Cons**: Could mask real issues if they recur

#### 2b. Extend Failure Window
```bash
# In Railway dashboard, set environment variable:
FAILURE_WINDOW_MINUTES=15  # Reduce from 30 to 15 minutes

# Redeploy orchestrator
# Failures older than 15 minutes won't count
```

**Pros**: Faster recovery  
**Cons**: Less time to detect patterns

#### 2c. Clear Old Failed Workers from Database
```python
# Run this to manually mark old failed workers as "cleared"
# This removes them from the failure rate calculation

python3 -c "
from gpu_orchestrator.database import DatabaseClient
import asyncio
from datetime import datetime, timezone, timedelta

async def clear_old_failures():
    db = DatabaseClient()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    
    # Update old terminated workers to status 'cleared'
    # (This is a custom status that won't count in failure rate)
    # NOTE: This requires modifying the database schema
    pass

asyncio.run(clear_old_failures())
"
```

**Not recommended**: Requires schema changes

### Option 3: Force Spawn (Emergency Only) 🚨
**Time**: Immediate  
**Risk**: HIGH - could waste money  
**Action**: Temporarily disable failure rate check

```bash
# In Railway dashboard, set environment variable:
MIN_WORKERS_FOR_RATE_CHECK=999  # Set very high

# This makes the system think there aren't enough workers to calculate rate
# So it bypasses the check entirely
```

**⚠️ WARNING**: Only use if you urgently need capacity and have confirmed the underlying issue is resolved!

## Recommended Action Plan

### Step 1: Verify Current Health ✅
```bash
cd /Users/peteromalley/Headless_WGP_Orchestrator
python3 scripts/check_system_health.py
```

Check:
- Is the healthy worker still active?
- Is heartbeat recent (<60s)?
- Are tasks being completed?

### Step 2: Monitor for 10 Minutes 📊
Run the health check every few minutes:
```bash
# Run this in a loop
watch -n 60 'python3 scripts/check_system_health.py'
```

Watch for:
- Failure rate dropping as workers age out
- Should drop below 80% around 19:32-19:37 UTC

### Step 3: If Rate Drops Below 80% ✅
The system will automatically:
1. Resume spawning workers
2. Scale up to meet demand
3. Process queued tasks

**No action needed** - just monitor to ensure it stays healthy.

### Step 4: If Issues Persist 🔍
If the failure rate doesn't drop or healthy worker fails:

1. **Check Runpod Console**
   - Are there capacity issues?
   - Check pod status and logs
   - Verify SSH keys are working

2. **Check Worker Logs**
   ```bash
   # SSH into the healthy worker and check logs
   ssh -p <port> root@<ip>
   tail -100 /workspace/Headless-Wan2GP/logs/worker_*.log
   ```

3. **Review Recent Changes**
   - Did Docker image change?
   - Environment variables updated?
   - Network/firewall changes?

## Prevention for Future

### 1. Increase Heartbeat Timeout
If workers legitimately need >5 minutes to initialize:
```bash
GPU_IDLE_TIMEOUT_SEC=600  # Increase from 300 to 600 (10 minutes)
```

### 2. Add Health Check Endpoint
Implement a simple HTTP endpoint in workers that orchestrator can ping:
- Faster than heartbeat checking
- Can detect hung processes
- Better debugging

### 3. Add Worker Startup Logging
Enhance the startup script to log:
- Each initialization step
- Time taken for each step
- Any errors encountered
- Upload logs to centralized location

### 4. Implement Gradual Scaling
Instead of spawning multiple workers at once:
- Spawn one, wait for it to be healthy
- Then spawn next
- Reduces waste if there's an issue

### 5. Add Alerting
Set up alerts for:
- Failure rate >50%
- No workers for >5 minutes
- All workers without heartbeats
- Unusual task failure rates

## Summary

**Current Status**: System is healthy but blocked from scaling due to recent failures

**Root Cause**: 6 workers failed in the past hour, keeping failure rate at 85.7%

**Resolution**: Wait 10-15 minutes for failures to age out of the 30-minute window

**Expected Recovery**: ~19:32-19:37 UTC (automatic)

**Manual Intervention**: Only if you can't wait or issues persist

---

## Quick Reference

### Check Current Status
```bash
cd /Users/peteromalley/Headless_WGP_Orchestrator
python3 scripts/check_system_health.py
```

### Key Metrics to Watch
- **Failure Rate**: Should be <80%
- **Healthy Workers**: Should have heartbeat <60s old
- **Queued Tasks**: Should be processed within reasonable time

### Environment Variables
```bash
MAX_WORKER_FAILURE_RATE=0.8        # 80% threshold
FAILURE_WINDOW_MINUTES=30           # 30-minute rolling window
MIN_WORKERS_FOR_RATE_CHECK=5        # Need 5+ workers to calculate
GPU_IDLE_TIMEOUT_SEC=300            # 5-minute heartbeat timeout
```

### Decision Tree
```
Is failure rate <80%?
├─ YES → ✅ System operating normally
└─ NO  → Is there a healthy worker?
    ├─ YES → ⏰ Wait for failures to age out (10-15 min)
    └─ NO  → 🔍 Investigate root cause before spawning more
```

