# Debugging & Monitoring

This document covers debugging tools, monitoring scripts, and logging features available in the orchestrator.

## Monitoring Scripts

### Dashboard (`scripts/dashboard.py`)
Real-time monitoring dashboard with auto-refresh.

**Usage:**
```bash
# Interactive dashboard (refreshes every 10s)
python scripts/dashboard.py

# Custom refresh interval
python scripts/dashboard.py --refresh 5

# Export JSON for monitoring tools
python scripts/dashboard.py --export
```

**Features:**
- System status (queue depth, worker counts)
- Worker health with VRAM usage
- Recent performance metrics (last hour)
- Health alerts (stale workers, stuck tasks)
- Success rates and processing stats

**Sample Output:**
```
🤖 Runpod GPU Worker Orchestrator Dashboard
============================================================
📅 2024-01-01 12:00:00

📊 System Status
------------------------------
Queued Tasks:           15
Running Tasks:           3
Completed Tasks:       142
Error Tasks:             2
Failed Tasks:            0

👷 Worker Status
------------------------------
Spawning Workers:        1
Active Workers:          3
Terminating:             0
Error Workers:           0
Terminated:             12

🚨 Health Alerts
------------------------------
Stale Workers:           0
Stuck Tasks:             0

📈 Recent Performance (Last Hour)
------------------------------
Completed:              28
Failed:                  1
Success Rate:         96.6%
```

### Worker Status Check (`gpu_orchestrator.main status`)
Quick status check without dashboard interface.

```bash
python -m gpu_orchestrator.main status
```

**Returns:**
- Overall orchestrator status
- Worker health details
- Current task assignments
- VRAM usage per worker

## Worker Management Scripts

### Spawn GPU (`scripts/spawn_gpu.py`)
Manual worker management for testing and emergency scaling.

**Commands:**
```bash
# Spawn a new worker
python scripts/spawn_gpu.py spawn

# Spawn with specific ID
python scripts/spawn_gpu.py spawn --worker-id test-worker-123

# Skip database registration (Runpod only)
python scripts/spawn_gpu.py spawn --no-db

# List all workers
python scripts/spawn_gpu.py list

# Terminate specific worker
python scripts/spawn_gpu.py terminate --worker-id worker-xyz
python scripts/spawn_gpu.py terminate --pod-id runpod-abc123

# Check worker status
python scripts/spawn_gpu.py status worker-xyz
```

### Shutdown All Workers (`scripts/shutdown_all_workers.py`)
Emergency shutdown and cleanup tool.

**Features:**
- Terminates all active Runpod instances
- Marks workers as `terminated` in database
- Resets orphaned tasks back to `Queued`
- Provides detailed shutdown summary

**Commands:**
```bash
# Show current state without shutdown
python scripts/shutdown_all_workers.py --show-only

# Emergency shutdown with confirmation
python scripts/shutdown_all_workers.py

# Force shutdown without confirmation
python scripts/shutdown_all_workers.py --force

# Reset tasks only (don't terminate workers)
python scripts/shutdown_all_workers.py --reset-tasks-only
```

**Use Cases:**
- Emergency stop during issues
- Maintenance mode preparation
- System reset after errors
- Cost control during development

## Log Analysis Tools

### Fetch Worker Logs (`scripts/fetch_worker_logs.py`)
SSH into workers and retrieve logs for debugging.

**Usage:**
```bash
# Get logs from all workers
python scripts/fetch_worker_logs.py

# Specific worker logs
python scripts/fetch_worker_logs.py worker-xyz123

# Follow logs in real-time
python scripts/fetch_worker_logs.py --follow

# Get last 200 lines
python scripts/fetch_worker_logs.py --lines 200

# Save logs to file
python scripts/fetch_worker_logs.py --output worker_logs

# Check git status on workers
python scripts/fetch_worker_logs.py --check-git

# Check Runpod storage integration
python scripts/fetch_worker_logs.py --check-s3
```

**Features:**
- Automatic SSH connection to all active workers
- Multiple log location detection
- Git status and commit history checking
- Storage mount verification
- Real-time log following

**Log Locations Checked:**
- `/workspace/Headless-Wan2GP/logs/{worker_id}/`
- `/workspace/Headless-Wan2GP/logs/`
- `/workspace/Headless-Wan2GP/worker.log`
- `/workspace/Headless-Wan2GP/worker.log`

## Database Monitoring

### Direct SQL Queries
Access monitoring views for detailed analysis:

```sql
-- Overall system status
SELECT * FROM orchestrator_status;

-- Worker health details
SELECT * FROM active_workers_health;

-- Recent task performance
SELECT * FROM recent_task_activity LIMIT 20;

-- Worker performance metrics
SELECT * FROM worker_performance;

-- Queue analysis by task type
SELECT * FROM task_queue_analysis;
```

### CLI Database Tools

**Check Tasks:**
```bash
python scripts/check_tasks.py
```

**Create Test Task:**
```bash
python scripts/create_test_task.py
```

## Logging Configuration

### Structured Logging (`orchestrator/logging_config.py`)
The orchestrator uses structured JSON logging for better analysis.

**Log Levels:**
- `DEBUG` - Detailed operation traces
- `INFO` - Normal operations, status changes
- `WARNING` - Non-critical issues
- `ERROR` - Failures requiring attention

**Enable Debug Logging:**
```bash
# Environment variable
export LOG_LEVEL=DEBUG

# Command line
python -m gpu_orchestrator.main --verbose single
```

### Log Format
```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "level": "INFO",
  "logger": "gpu_orchestrator.control_loop",
  "message": "Promoted worker worker-xyz to active",
  "worker_id": "worker-xyz",
  "action": "promote_worker"
}
```

### Key Log Messages

**Scaling Events:**
```
INFO: Starting orchestrator cycle
INFO: Promoted worker {id} to active
INFO: Marked worker {id} for termination (idle)
INFO: Successfully spawned worker {id}
```

**Health Issues:**
```
ERROR: Marked worker {id} as error: Heartbeat expired with tasks queued
WARNING: Worker {id} has stale VRAM data (120.5s old)
ERROR: Stuck task {task_id} on worker {worker_id}
```

**API Operations:**
```
INFO: Creating worker pod: {worker_id}
INFO: Worker pod created successfully: {worker_id} -> {pod_id}
INFO: Pod terminated: {pod_id}
```

## Testing & Validation Scripts

### Supabase Connectivity (`scripts/test_supabase.py`)
Validates database connection and RPC functions.

```bash
# Basic connection test
python scripts/test_supabase.py

# Create test task
python scripts/test_supabase.py --create-task

# Test all RPC functions
python scripts/test_supabase.py --test-rpcs
```

### Runpod Integration (`scripts/test_runpod.py`)
Comprehensive Runpod API testing.

```bash
# Test all components
python scripts/test_runpod.py

# Quick test (no worker spawning)
python scripts/test_runpod.py --quick

# Specific tests
python scripts/test_runpod.py --test config
python scripts/test_runpod.py --test api
python scripts/test_runpod.py --test volumes
python scripts/test_runpod.py --test ssh
```

### Database Migration (`scripts/apply_sql_migrations.py`)
Apply schema updates and RPC functions.

```bash
# Apply all migrations
python scripts/apply_sql_migrations.py

# Show migration content for manual execution
python scripts/show_migrations.py
```

## Cost Monitoring

### Real-time Cost Estimates
The dashboard includes cost calculations based on:
- Worker count × hourly GPU rates
- Processing time per task
- Queue depth predictions

**Dashboard Metrics:**
```
💰 Cost Estimates
------------------------------
Active Workers:      5 workers
Hourly Rate:        $2.50/hour
Est. Daily Cost:    $60.00
Processing Rate:    120 videos/hour
Queue Backlog:      45 minutes
```

### Historical Cost Analysis
Query worker performance for cost optimization:

```sql
-- Daily cost breakdown
SELECT 
    DATE(created_at) as date,
    COUNT(*) as workers_spawned,
    AVG(uptime_hours) as avg_uptime,
    SUM(uptime_hours) * 0.50 as estimated_cost_usd
FROM worker_performance 
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY DATE(created_at)
ORDER BY date DESC;

-- Task processing efficiency
SELECT 
    task_type,
    COUNT(*) as total_tasks,
    AVG(processing_time_seconds) as avg_processing_time,
    (COUNT(*) * AVG(processing_time_seconds) / 3600) * 0.50 as estimated_gpu_cost
FROM recent_task_activity 
WHERE status = 'Complete'
GROUP BY task_type;
```

## Deployment Monitoring

### VM Deployment (`scripts/deploy_vm.sh`)
Automated deployment script with health checks.

**Features:**
- System dependency installation
- Environment configuration
- Connectivity testing
- Cron job setup
- Log monitoring setup

**Post-deployment Monitoring:**
```bash
# Check orchestrator logs
tail -f /var/log/orchestrator.log

# Verify cron jobs
crontab -l

# Test single run
cd ~/runpod-orchestrator && python -m gpu_orchestrator.main single
```

### Container Health Checks
For containerized deployments:

```bash
# Docker health check
docker run --env-file .env orchestrator:latest single

# Kubernetes pod logs
kubectl logs -f deployment/runpod-orchestrator

# ECS task monitoring
aws ecs describe-tasks --cluster runpod-orchestrator
```

## Troubleshooting Guides

### Common Issues

**1. Workers Not Spawning**
```bash
# Check Runpod configuration
python scripts/test_runpod.py --test config

# Verify GPU availability
python scripts/test_runpod.py --test api

# Check network volumes
python scripts/test_runpod.py --test volumes
```

**2. Workers Not Processing Tasks**
```bash
# Check worker SSH access
python scripts/fetch_worker_logs.py --check-git

# Verify Headless-Wan2GP status
python scripts/fetch_worker_logs.py worker-xyz

# Check task claiming RPC
python scripts/test_supabase.py --test-rpcs
```

**3. High Error Rates**
```bash
# Check worker health
python scripts/dashboard.py

# Analyze failed tasks
python scripts/check_tasks.py

# Review worker performance
SELECT * FROM worker_performance WHERE success_rate_percent < 90;
```

### Debug Commands Summary

| Purpose | Command |
|---------|---------|
| **Real-time Status** | `python scripts/dashboard.py` |
| **Quick Status** | `python -m gpu_orchestrator.main status` |
| **Worker Logs** | `python scripts/fetch_worker_logs.py` |
| **Manual Spawn** | `python scripts/spawn_gpu.py spawn` |
| **Emergency Stop** | `python scripts/shutdown_all_workers.py` |
| **Test DB** | `python scripts/test_supabase.py` |
| **Test Runpod** | `python scripts/test_runpod.py --quick` |
| **Single Cycle** | `python -m gpu_orchestrator.main single` | 