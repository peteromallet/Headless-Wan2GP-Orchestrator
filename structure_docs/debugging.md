# Debugging Guide

## 🎯 Quick Start: Use the Unified Debug Tool

All debugging functionality is consolidated into **one tool**: `scripts/debug.py`

**📖 Full documentation: [`scripts/debug/README.md`](../scripts/debug/README.md)**

## Essential Commands

```bash
# Investigate a failed task
python scripts/debug.py task <task_id>

# Check worker health
python scripts/debug.py worker <worker_id>
python scripts/debug.py worker <worker_id> --check-logging  # Is it running?
python scripts/debug.py worker <worker_id> --startup        # View initialization

# System overview
python scripts/debug.py health          # Overall health
python scripts/debug.py workers         # Recent worker failures
python scripts/debug.py tasks           # Recent task statistics
python scripts/debug.py orchestrator    # Is orchestrator alive?

# Configuration & Cost Management
python scripts/debug.py config --explain    # View all settings
python scripts/debug.py runpod              # Find orphaned pods ($$$ waste!)
```

## Common Scenarios

| Problem | Command |
|---------|---------|
| "Why did this task fail?" | `debug.py task <task_id>` |
| "Worker isn't doing anything" | `debug.py worker <id> --check-logging` |
| "System seems broken" | `debug.py health` |
| "Are we wasting money?" | `debug.py runpod` |
| "What are my timeout settings?" | `debug.py config --explain` |

## Architecture

The unified debug tool uses a **logs-first approach**:
- Primary data source: `system_logs` table (complete event timeline)
- Augmented with current state from `tasks` and `workers` tables
- Consistent formatting across all commands
- Single unified data access layer (`DebugClient`)

See [`scripts/debug/README.md`](../scripts/debug/README.md) for complete documentation.

---

## Other Tools (Specialized Use)

### Management Scripts
- `spawn_gpu.py` - Manually spawn a worker
- `shutdown_all_workers.py` - Emergency shutdown
- `terminate_single_worker.py` - Terminate specific worker

### Forensic Investigation (One-off Analysis)
- `investigate_*.py` - Specific incident investigations
- `forensic_analysis_*.py` - Historical failure analysis
- `reconstruct_from_worker_metadata.py` - Timeline reconstruction

### Testing & Setup
- `test_*.py` - Component testing
- `setup_database.py` - Database initialization
- `apply_sql_migrations.py` - Schema updates

### Monitoring
- `dashboard.py` - Real-time monitoring dashboard
- `monitor_worker.py` - Continuous worker monitoring

---

## Troubleshooting: Worker Health Checks

### How Health Checks Work

The orchestrator performs health checks on **idle workers** (workers with no active tasks and no queued work):

1. **Heartbeat Check** (Primary): Workers send heartbeats every 20 seconds via the guardian process
   - ✅ Heartbeat < 60s old → Worker is healthy
   - ❌ Heartbeat > 60s old or missing → Worker is unhealthy

2. **Failsafe Check**: Catches very stale workers (>idle timeout) regardless of status

**Important:** The system relies entirely on heartbeat for health detection. If a worker is heartbeating, it's alive and working - no SSH or network checks are performed to avoid false positives.

### Common False Positive (Fixed Nov 2025)

**Issue:** Workers were being terminated despite being healthy and actively processing tasks.

**Root Cause:** The old health check used SSH connectivity tests which failed due to temporary network issues (EAGAIN errors), even though the worker was still heartbeating.

**Fix:** Health checks now rely solely on heartbeat. If a worker is sending heartbeats (updated < 60s ago), it passes the health check. This eliminates false positives from network hiccups while still detecting truly dead workers.

---

## Troubleshooting: Tasks Not Creating Generations

### Symptom
Tasks show `generation_created: false` even though they have:
- ✅ Status = "Complete"
- ✅ Valid `output_location` URL
- ✅ No error messages

### Root Cause (Fixed Nov 2025)
Both the API orchestrator and GPU workers were calling the wrong edge function endpoint when marking tasks complete:
- **Old (broken):** `update-task-status` or `mark-task-complete` - Only sets status to "Complete"
- **New (fixed):** `complete-task` - Sets status AND creates generation records

### Impact
**API Orchestrator tasks:**
- `qwen_image_edit`
- `video_upscale`
- Other API-based tasks
- **Fix:** `api_orchestrator/task_utils.py` now uses `complete-task` endpoint

**GPU Worker tasks (Headless-Wan2GP):**
- `travel_orchestrator`
- `travel_segment`
- `travel_stitch`
- `video_generation`
- Other GPU-based tasks
- **Fix:** `gpu_orchestrator/runpod_client.py` now passes `SUPABASE_EDGE_COMPLETE_TASK_URL` to workers

### Fix Locations
1. **API Orchestrator:** `api_orchestrator/task_utils.py` - `_get_supabase_edge_urls()` function
2. **GPU Workers:** `gpu_orchestrator/runpod_client.py` - `spawn_worker()` method now passes correct edge function URLs to workers

**Note:** The GPU worker fix requires redeploying workers. Existing workers spawned before this fix will still use the wrong endpoint.

---

**💡 Pro Tip:** Start with `debug.py health` for a quick system overview, then drill down into specific tasks or workers as needed.
