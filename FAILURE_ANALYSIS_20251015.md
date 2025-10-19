# Worker Failure Analysis - October 15, 2025

## Current State
- **Failure Rate**: 100% (6 out of 6 recent workers failed)
- **Scaling Status**: BLOCKED - Orchestrator refusing to spawn new workers
- **Active Workers**: 0
- **Queued Tasks**: 3

## Root Cause Analysis

### Primary Issue: Stale Heartbeat Failures
The majority of failures (60%+) are due to **"Stale heartbeat with active tasks (~330s old)"**

This indicates:
1. ✅ Workers are spawning successfully (pods created)
2. ✅ SSH authentication is working (based on logs showing successful SSH connections)
3. ✅ Tasks are being assigned to workers
4. ❌ **Workers are NOT sending heartbeats back to the database**

### Failure Breakdown (Last 2 Hours)
```
10 workers - No error specified
 8 workers - Stale heartbeat with active tasks (various ages ~330-350s)
 1 worker  - Exception in worker check: 'data'
 1 worker  - Failed to spawn Runpod instance
```

### Failure Timeline Pattern
Workers are failing every ~10 minutes in a consistent pattern:
- 18:26:03 - Stale heartbeat (330s)
- 18:36:34 - Stale heartbeat (327s)
- 18:47:06 - Stale heartbeat (349s)
- 18:57:35 - Stale heartbeat (331s)

This suggests:
1. Orchestrator tries to spawn a worker
2. Worker spawns and claims a task
3. Worker fails to start properly or crashes
4. After ~5-6 minutes (300-350s), orchestrator marks it as failed due to no heartbeat
5. Orchestrator tries again, but hits the same issue

## Potential Root Causes

### 1. Worker Process Not Starting (Most Likely)
The worker process may not be starting after SSH initialization:
- Script execution failure
- Missing dependencies in the Docker image
- Environment variable issues on the worker
- Worker code crashed immediately on startup

### 2. Database Connection Issues
Workers may not be able to connect to Supabase:
- Missing/incorrect SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY
- Network issues from Runpod to Supabase
- Firewall blocking connections

### 3. Worker Code Crash
The worker process starts but crashes before sending first heartbeat:
- Python errors in worker code
- Import failures
- CUDA/GPU initialization issues

## Diagnostic Steps

### Check Worker Logs
SSH into one of the failed workers (if still running) and check:
```bash
# Check if worker process is running
ps aux | grep python

# Check worker logs
tail -100 /workspace/Headless-Wan2GP/logs/worker_*.log

# Check if startup script executed
cat /workspace/Headless-Wan2GP/logs/gpu-*_startup.log
```

### Check Recent Worker Status in Runpod
Some workers may still be running on Runpod but not responding:
- Check Runpod console for active pods
- Terminate any stuck pods
- Check if pods are actually starting the worker process

### Check Database Configuration
Verify the environment variables are being passed correctly:
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY  
- WORKER_ID

### Check Worker Startup Script
The orchestrator generates a startup script that:
1. Sets up environment
2. Clones/updates the repo
3. Installs dependencies
4. Starts the worker process

If this script has errors, workers won't start.

## Immediate Fixes

### 1. Reset Failure Rate Counter
The failure rate mechanism is protecting against infinite spawn loops.
To reset it temporarily, you can either:
- Wait 30 minutes (the failure window)
- Manually terminate all failed workers from the database to reset the count
- Temporarily increase MAX_WORKER_FAILURE_RATE environment variable

### 2. Manual Worker Test
Spawn a worker manually and SSH in to check logs:
```bash
python3 scripts/spawn_gpu.py
# Then SSH into the spawned worker and check logs
```

### 3. Check Worker Heartbeat Code
Verify the worker heartbeat logic is working:
- Check if workers are calling the heartbeat endpoint
- Verify database connectivity from worker environment
- Check if heartbeat is being called frequently enough

## Recommended Actions

1. **Immediate**: SSH into a recently failed worker (if still running) to check logs
2. **Short-term**: Add more detailed logging to worker startup script
3. **Medium-term**: Implement health check endpoint that orchestrator can call
4. **Long-term**: Add worker telemetry and crash reporting

## Status Summary
The orchestrator's failure rate protection is **working as designed** - it's preventing
an infinite spawn loop when there's a systemic issue. The real problem is that workers
are not successfully starting their processes or connecting to the database to send heartbeats.

**Next Step**: Manually inspect a failed worker's logs to determine why the worker process isn't starting or sending heartbeats.

