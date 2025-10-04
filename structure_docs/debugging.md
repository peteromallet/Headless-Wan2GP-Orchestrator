# Debugging Guide

Quick reference for accessing logs and diagnosing issues in the GPU orchestrator system.

## 🔍 Getting Worker Logs

### Individual Worker Analysis
```bash
# Analyze a specific worker (includes S3 logs, SSH tests, database state)
python scripts/comprehensive_diagnostics.py gpu-20250928_033832-4bc1e282

# Get recent terminated workers
python scripts/fetch_worker_logs.py --recent-terminated
```

### Worker S3 Logs (Archived)
Worker logs are automatically uploaded to S3 when workers terminate:
- **Location**: `s3://m6ccu1lodp/Headless-Wan2GP/logs/{worker_id}.log`
- **Contains**: Task processing, model loading, video generation progress
- **Access**: Via comprehensive diagnostics script (handles AWS auth)

### Live Worker Logs (SSH)
For active workers only:
```bash
# SSH into active worker (if SSH auth is working)
python scripts/fetch_worker_logs.py gpu-20250928_033832-4bc1e282 --live
```

## 📋 Getting Orchestrator Logs

### Railway Deployment Logs
```bash
# View live orchestrator logs from Railway
railway logs

# Follow logs in real-time
railway logs --follow
```

### Local Orchestrator Logs
```bash
# If running locally (file not created in Railway deployment)
tail -f orchestrator.log
```

## 🎯 Getting Task Logs

### Comprehensive Task Analysis
```bash
# Search for task across ALL worker machines (smart search)
python scripts/fetch_task_logs.py e5b419e9-3546-4899-9175-7e9b5dc35209 --worker-logs

# Get task timeline and status changes
python scripts/fetch_task_logs.py e5b419e9-3546-4899-9175-7e9b5dc35209 --timeline --worker-logs

# Save comprehensive analysis to file
python scripts/fetch_task_logs.py [task_id] --worker-logs --output task_analysis
```

**Multi-Machine Search Strategy:**
1. **Database lookup**: Finds assigned worker (if any)
2. **Targeted search**: Searches specific worker first (SSH + S3)  
3. **Comprehensive fallback**: If not found, searches ALL workers
4. **Hybrid access**: Live workers via SSH, terminated workers via S3

### Database Task Status
```python
# Query task directly from database
from gpu_orchestrator.database import DatabaseClient
db = DatabaseClient()
result = db.supabase.table('tasks').select('*').eq('id', 'task-id').execute()
```

## 🚨 Common Debugging Scenarios

### Worker Keeps Getting Terminated
```bash
# 1. Check recent terminated workers
python -c "
from gpu_orchestrator.database import DatabaseClient
import asyncio
db = DatabaseClient()
result = db.supabase.table('workers').select('id, created_at, metadata').eq('status', 'terminated').order('created_at', desc=True).limit(5).execute()
for w in result.data:
    print(f'{w[\"id\"]}: {w[\"metadata\"].get(\"error_reason\", \"Unknown\")}')
"

# 2. Analyze the most recent failure
python scripts/comprehensive_diagnostics.py [worker_id_from_above]
```

### Tasks Not Being Processed
```bash
# Check current system state
python scripts/comprehensive_diagnostics.py  # No worker ID = system overview

# Check specific worker processing
python scripts/comprehensive_diagnostics.py [active_worker_id]
```

### SSH Authentication Issues
```bash
# Test SSH connectivity to all pods
python scripts/comprehensive_diagnostics.py --save-report
# Check the "ssh_connectivity_tests" section in the report
```

## 🔧 Log Locations Summary

| Log Type | Location | Access Method |
|----------|----------|---------------|
| **Orchestrator** | Railway deployment | `railway logs` |
| **Worker (Live)** | RunPod container | SSH (if auth works) |
| **Worker (Archived)** | S3 bucket | `comprehensive_diagnostics.py` |
| **Task Processing** | Worker S3 logs | `fetch_task_logs.py --worker-logs` |
| **Database State** | Supabase | Direct SQL or `comprehensive_diagnostics.py` |

## ⚡ Quick Diagnosis Commands

```bash
# System health overview
python scripts/comprehensive_diagnostics.py

# Specific worker deep dive  
python scripts/comprehensive_diagnostics.py [worker_id]

# Task investigation
python scripts/fetch_task_logs.py [task_id] --worker-logs --timeline

# Recent failures
railway logs | grep -E "(ERROR|Failed|terminated)"
```

## 🎯 Key Timeout Parameters

Current timeout settings (in `.env` or Railway environment):
- `GPU_IDLE_TIMEOUT_SEC=600` - Workers terminated after 10 min without heartbeat
- `TASK_STUCK_TIMEOUT_SEC=700` - Tasks marked stuck after 11.7 min  
- `SPAWNING_TIMEOUT_SEC=1000` - Worker spawn timeout (16.7 min)

**Common Issue**: Workers get terminated mid-task due to missing heartbeats. Increase `GPU_IDLE_TIMEOUT_SEC` to 1800 (30 min) for video generation workloads.
