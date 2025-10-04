# GPU Orchestrator Diagnostics and Troubleshooting

This guide provides systematic approaches to diagnose and troubleshoot issues with the GPU orchestrator system, based on real-world debugging scenarios and comprehensive diagnostic tools.

## Table of Contents

1. [Quick Health Check](#quick-health-check)
2. [Comprehensive Diagnostics](#comprehensive-diagnostics)
3. [Common Issues and Solutions](#common-issues-and-solutions)
4. [Worker-Specific Debugging](#worker-specific-debugging)
5. [Environment and Configuration Issues](#environment-and-configuration-issues)
6. [SSH Authentication Problems](#ssh-authentication-problems)
7. [Task Processing Issues](#task-processing-issues)
8. [Performance and Scaling Analysis](#performance-and-scaling-analysis)
9. [Log Analysis](#log-analysis)
10. [Emergency Procedures](#emergency-procedures)

## Quick Health Check

### 1. Check System Overview
```bash
# Check active workers
cd scripts && python spawn_gpu.py list

# Check Railway logs (if deployed)
cd gpu_orchestrator && railway logs

# Check current tasks
python -c "
from gpu_orchestrator.database import DatabaseClient
import asyncio
async def check():
    db = DatabaseClient()
    result = db.supabase.table('tasks').select('*').eq('status', 'In Progress').execute()
    print(f'Tasks in progress: {len(result.data or [])}')
    result = db.supabase.table('tasks').select('*').eq('status', 'Queued').execute()
    print(f'Tasks queued: {len(result.data or [])}')
asyncio.run(check())
"
```

### 2. Quick Status Indicators
Look for these key signs of system health:

**✅ Healthy System:**
- Workers in `active` status with recent heartbeats
- Tasks moving from `Queued` → `In Progress` → `Complete`
- Railway logs showing successful worker promotions
- SSH connections working (in Railway environment)

**❌ Unhealthy System:**
- Workers stuck in `spawning` status
- No recent heartbeats (>10 minutes old)
- Tasks stuck in `Queued` status
- SSH authentication failures
- No worker processes starting

## Comprehensive Diagnostics

### The Comprehensive Diagnostics Script

We've built a powerful diagnostic tool that analyzes the entire system:

```bash
cd scripts

# Analyze all active workers
python comprehensive_diagnostics.py --save-report

# Analyze specific worker
python comprehensive_diagnostics.py <worker_id> --save-report

# Include sensitive data (use carefully)
python comprehensive_diagnostics.py --include-sensitive --save-report
```

### What the Comprehensive Diagnostics Checks

1. **Environment Configuration**
   - Critical environment variables (API keys, SSH keys)
   - Important configuration variables
   - AWS/S3 credentials

2. **Database State**
   - Worker counts by status
   - Task counts and breakdowns
   - RPC function availability

3. **RunPod State**
   - Pod status and costs
   - SSH connectivity tests
   - Resource utilization

4. **Worker Analysis**
   - Database records vs RunPod status
   - SSH connection testing
   - Process status on workers
   - Log analysis (S3 and orchestrator)

5. **Network Connectivity**
   - Supabase connectivity
   - RunPod API access
   - S3 storage access
   - External service connectivity

6. **Deployment Verification**
   - Git status and commits
   - Railway deployment status
   - Code consistency

## Common Issues and Solutions

### Issue 1: Workers Stuck in "Spawning" Status

**Symptoms:**
- Workers show `spawning` status for >5 minutes
- No SSH details available
- Workers never promoted to `active`

**Diagnosis:**
```bash
# Check specific worker
python spawn_gpu.py status <worker_id>

# Check SSH details
python comprehensive_diagnostics.py <worker_id>
```

**Solutions:**
1. **SSH Key Issues:** Ensure `RUNPOD_SSH_PRIVATE_KEY` is set on Railway
2. **RunPod API Issues:** Check `get_pod_ssh_details()` function
3. **Network Issues:** Verify RunPod API connectivity

### Issue 2: SSH Authentication Failures

**Symptoms:**
- "Authentication failed" in logs
- Workers can't start processes
- SSH details available but connection fails

**Root Cause Analysis:**
This was the main issue we solved. The problem occurs when:
- Railway has the public key but missing private key
- Key format mismatches (RSA vs Ed25519)
- Environment variables not properly deployed

**Solution Steps:**
1. **Verify SSH keys on Railway:**
   ```bash
   cd gpu_orchestrator && railway variables | grep SSH
   ```

2. **Add missing private key:**
   ```bash
   # Extract your Ed25519 private key
   cat ~/.ssh/id_ed25519

   # Set on Railway
   railway variables --set "RUNPOD_SSH_PRIVATE_KEY=$(cat ~/.ssh/id_ed25519)"
   ```

3. **Verify key format consistency:**
   - Ensure both public and private keys are Ed25519
   - Check that public key matches private key

### Issue 3: Tasks Not Processing

**Symptoms:**
- Tasks stuck in `Queued` status
- Workers active but not claiming tasks
- Zero task throughput

**Diagnosis:**
```bash
# Check task claiming
python comprehensive_diagnostics.py --save-report

# Check specific task
python -c "
from gpu_orchestrator.database import DatabaseClient
import asyncio
async def check():
    db = DatabaseClient()
    result = db.supabase.table('tasks').select('*').limit(5).execute()
    for task in result.data or []:
        print(f'{task[\"id\"][:8]}... {task[\"status\"]} {task.get(\"task_type\", \"unknown\")}')
asyncio.run(check())
"
```

**Common Causes:**
1. **Worker processes not starting:** Check `start_worker_process()` execution
2. **Database connectivity issues:** Verify Supabase connection
3. **Edge function problems:** Check Supabase edge function deployment
4. **Task claiming logic errors:** Review RPC functions

### Issue 4: Stitch Tasks Failing

**Symptoms:**
- Individual segments complete successfully
- Stitch task fails with "No valid segment videos found"
- Database shows completed segments but stitch can't find them

**Root Cause:**
Missing or broken `get-completed-segments` Supabase Edge Function.

**Investigation:**
```bash
# Check segment completion
python -c "
import sys
sys.path.append('..')
from gpu_orchestrator.database import DatabaseClient
import asyncio

async def check_segments():
    db = DatabaseClient()
    # Check for completed travel_segment tasks
    result = db.supabase.table('tasks').select('*').eq('task_type', 'travel_segment').eq('status', 'Complete').execute()
    print(f'Completed segments: {len(result.data or [])}')
    for task in (result.data or [])[:5]:
        print(f'  {task[\"id\"][:8]}... {task.get(\"output_location\", \"no output\")[:50]}...')

asyncio.run(check_segments())
"
```

**Solution:**
Deploy missing Supabase Edge Functions or fix the segment querying logic in the worker code.

## Worker-Specific Debugging

### Deep Worker Analysis

For detailed worker investigation:

```bash
# Get comprehensive worker info
python comprehensive_diagnostics.py <worker_id> --save-report

# Check worker logs from S3
python fetch_worker_logs.py <worker_id> --lines 200

# Check worker status
python spawn_gpu.py status <worker_id>
```

### Worker Log Analysis

The comprehensive diagnostics automatically fetches and analyzes:

1. **S3 Worker Logs:** Complete worker execution logs
2. **Orchestrator Logs:** Worker lifecycle events
3. **SSH Process Status:** What's running on the worker
4. **Workspace Status:** Code deployment and file access

### Worker Lifecycle States

Understanding worker progression:
```
spawning → active → (processing tasks) → terminated
     ↓         ↓
  (stuck)   (idle)
```

**Key Transition Points:**
- `spawning` → `active`: SSH details available and `start_worker_process()` succeeds
- `active` → processing: Worker claims tasks and starts processing
- Processing → `idle`: Tasks complete, worker waits for more
- `idle` → `terminated`: Timeout reached or manual termination

## Environment and Configuration Issues

### Critical Environment Variables

**Railway Deployment Must Have:**
```bash
RUNPOD_API_KEY=rpa_...
SUPABASE_URL=https://...supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...
RUNPOD_SSH_PUBLIC_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5...
RUNPOD_SSH_PRIVATE_KEY=-----BEGIN OPENSSH PRIVATE KEY-----...
```

**Important Configuration:**
```bash
RUNPOD_STORAGE_NAME=Your_Storage_Name
RUNPOD_GPU_TYPE=NVIDIA GeForce RTX 4090
RUNPOD_WORKER_IMAGE=runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
MAX_ACTIVE_GPUS=2
MIN_ACTIVE_GPUS=0
GPU_IDLE_TIMEOUT_SEC=600
TASKS_PER_GPU_THRESHOLD=3
```

### Environment Validation

The comprehensive diagnostics script automatically validates:
- Presence of critical variables
- Format validation for SSH keys
- Database connectivity
- API key validity

## SSH Authentication Problems

### SSH Key Setup for Railway

**Step 1: Generate Ed25519 Keys (if needed)**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''
```

**Step 2: Extract Keys for Railway**
```bash
# Public key
cat ~/.ssh/id_ed25519.pub

# Private key (handle securely)
cat ~/.ssh/id_ed25519
```

**Step 3: Set on Railway**
```bash
cd gpu_orchestrator
railway variables --set "RUNPOD_SSH_PUBLIC_KEY=$(cat ~/.ssh/id_ed25519.pub)"
railway variables --set "RUNPOD_SSH_PRIVATE_KEY=$(cat ~/.ssh/id_ed25519)"
```

### SSH Troubleshooting

**Test SSH connectivity:**
```bash
# Check if SSH details are available
python -c "
from gpu_orchestrator.runpod_client import get_pod_ssh_details
import os
ssh_details = get_pod_ssh_details('<pod_id>', os.getenv('RUNPOD_API_KEY'))
print('SSH Details:', ssh_details)
"
```

**Common SSH Issues:**
1. **Key format mismatch:** RSA vs Ed25519
2. **Missing private key on Railway**
3. **Corrupted key during environment variable setting**
4. **RunPod API not returning SSH details**

## Task Processing Issues

### Task Flow Analysis

**Normal Task Flow:**
```
Queued → In Progress → Complete
   ↑         ↑           ↑
Created   Claimed    Processed
```

**Failure Points:**
1. **Claiming:** RPC functions not working
2. **Processing:** Worker code errors
3. **Completion:** Update functions failing

### Task Debugging Commands

```bash
# Check task status distribution
python -c "
from gpu_orchestrator.database import DatabaseClient
import asyncio
async def check():
    db = DatabaseClient()
    for status in ['Queued', 'In Progress', 'Complete', 'Failed']:
        result = db.supabase.table('tasks').select('id', count='exact').eq('status', status).execute()
        print(f'{status}: {result.count or 0}')
asyncio.run(check())
"

# Check recent task activity
python -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timedelta
import asyncio
async def check():
    db = DatabaseClient()
    cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
    result = db.supabase.table('tasks').select('*').gte('updated_at', cutoff).order('updated_at', desc=True).limit(10).execute()
    print('Recent task activity:')
    for task in result.data or []:
        print(f'  {task[\"id\"][:8]}... {task[\"status\"]} {task.get(\"task_type\", \"unknown\")} {task[\"updated_at\"]}')
asyncio.run(check())
"
```

## Performance and Scaling Analysis

### Scaling Metrics

**Key Metrics to Monitor:**
- Task throughput (tasks/hour)
- Worker utilization (busy vs idle time)
- Queue depth (queued tasks)
- Cost efficiency ($/task)

**Scaling Analysis:**
```bash
# Check current scaling state
python comprehensive_diagnostics.py --save-report

# Analyze worker efficiency
python -c "
from gpu_orchestrator.database import DatabaseClient
from datetime import datetime, timedelta
import asyncio
async def check():
    db = DatabaseClient()
    # Check recent completions
    cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
    result = db.supabase.table('tasks').select('*').eq('status', 'Complete').gte('generation_processed_at', cutoff).execute()
    print(f'Tasks completed in last hour: {len(result.data or [])}')
    
    # Check current queue
    result = db.supabase.table('tasks').select('id', count='exact').eq('status', 'Queued').execute()
    print(f'Current queue depth: {result.count or 0}')
asyncio.run(check())
"
```

## Log Analysis

### Log Sources

1. **Railway Logs:** Orchestrator behavior and scaling decisions
2. **S3 Worker Logs:** Individual worker task processing
3. **Orchestrator Local Logs:** Development and debugging
4. **Supabase Logs:** Database and edge function issues

### Log Analysis Tools

**Fetch Worker Logs:**
```bash
# Get logs for specific worker
python fetch_worker_logs.py <worker_id> --lines 500

# Get logs for all active workers
python fetch_worker_logs.py --lines 200
```

**Orchestrator Log Analysis:**
```bash
# Check orchestrator patterns (if running locally)
python comprehensive_diagnostics.py --save-report
# Look for error_patterns in the report
```

### Log Patterns to Watch

**Healthy Patterns:**
- Regular "ORCHESTRATOR CYCLE" entries
- "Worker startup completed successfully"
- "workers_promoted": 1 (when scaling up)
- Task status transitions: Queued → In Progress → Complete

**Problem Patterns:**
- "Authentication failed"
- "Failed to reset orphaned tasks"
- "SSH connection failed"
- "No valid segment videos found"
- Workers stuck in same status for >10 minutes

## Emergency Procedures

### System Recovery

**If System is Completely Down:**
1. Check Railway deployment status
2. Verify environment variables
3. Restart Railway service if needed
4. Check Supabase connectivity

**If Workers are Stuck:**
```bash
# Terminate all workers
python scripts/shutdown_all_workers.py

# Wait 2-3 minutes, then check status
python spawn_gpu.py list

# System should auto-scale based on queued tasks
```

**If Tasks are Backed Up:**
```bash
# Check queue depth
python comprehensive_diagnostics.py --save-report

# Consider manual scaling
# (System should auto-scale, but you can spawn additional workers if needed)
```

### Data Recovery

**If Worker Logs are Missing:**
- Check S3 storage: logs are automatically uploaded
- Use comprehensive diagnostics to fetch from multiple sources
- Check Railway logs for orchestrator-level information

**If Database is Inconsistent:**
- Use `scripts/sync_runpod_database.py` to sync RunPod state with database
- Check for orphaned pods or stale database entries

## Diagnostic Report Interpretation

### Understanding Comprehensive Diagnostic Reports

The `comprehensive_diagnostics.py` script generates detailed JSON reports. Key sections:

**Environment Issues:**
```json
{
  "missing_critical": ["RUNPOD_SSH_PRIVATE_KEY"],
  "recommendations": [
    {
      "priority": "HIGH",
      "category": "Environment",
      "issue": "Missing critical environment variables",
      "action": "Add missing environment variables to Railway deployment"
    }
  ]
}
```

**Worker Analysis:**
```json
{
  "workers": {
    "gpu-20250912_203750-18865e9b": {
      "database_record": {"status": "active"},
      "ssh_analysis": {"connection_status": "✅ Connected"},
      "log_analysis": {"s3_logs_available": true}
    }
  }
}
```

**System Health:**
```json
{
  "runpod_state": {
    "total_pods": 3,
    "total_hourly_cost": 1.770,
    "ssh_connectivity_tests": {...}
  }
}
```

## Best Practices

### Regular Monitoring

1. **Daily:** Check system health with quick commands
2. **Weekly:** Run comprehensive diagnostics and save reports
3. **Monthly:** Analyze cost efficiency and scaling patterns

### Proactive Maintenance

1. **Monitor costs:** Keep track of hourly spending
2. **Check logs regularly:** Look for recurring error patterns
3. **Update dependencies:** Keep RunPod images and packages current
4. **Test SSH keys:** Ensure authentication remains working

### Documentation

1. **Save diagnostic reports:** Keep historical data for trend analysis
2. **Document issues:** Record solutions for common problems
3. **Update configurations:** Keep environment variables current

---

## Quick Reference Commands

```bash
# System health check
python spawn_gpu.py list
python comprehensive_diagnostics.py --save-report

# Worker debugging
python comprehensive_diagnostics.py <worker_id>
python fetch_worker_logs.py <worker_id>

# Task analysis
python -c "from gpu_orchestrator.database import DatabaseClient; import asyncio; db = DatabaseClient(); asyncio.run(db.get_workers())"

# Emergency shutdown
python scripts/shutdown_all_workers.py

# Railway management
cd gpu_orchestrator && railway logs
railway variables
railway up --detach
```

This diagnostic guide provides systematic approaches to identify, analyze, and resolve issues with the GPU orchestrator system. Use the comprehensive diagnostics script as your primary tool, and refer to this guide for interpreting results and implementing solutions.





