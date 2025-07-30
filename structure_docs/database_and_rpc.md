# Database Schema & RPC Functions

This document covers the Supabase database schema, RPC functions, and views used by the Headless-WGP-Orchestrator system.

## Core Tables

### `tasks` Table
The main task queue where video generation jobs are stored and processed.

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `id` | `uuid` | Primary key | Auto-generated |
| `status` | `text` | Task state | `Queued`, `In Progress`, `Complete`, `Failed`, `Cancelled` |
| `task_type` | `text` | Type of task | Video generation, etc. |
| `params` | `jsonb` | Task parameters | Maps to `task_data` in RPC functions |
| `attempts` | `int` | Retry counter | Max 3 attempts before `Failed` |
| `worker_id` | `text` | Assigned worker | NULL when queued |
| `generation_started_at` | `timestamptz` | Processing start time | Set when claimed |
| `generation_processed_at` | `timestamptz` | Processing end time | Set when complete/failed |
| `error_message` | `text` | Error details | Only for failed tasks |
| `result_data` | `jsonb` | Output data | Video URLs, metadata |
| `created_at` | `timestamptz` | Task creation time | |
| `updated_at` | `timestamptz` | Last modification | |

### `workers` Table
Registry of GPU workers managed by the orchestrator.

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| `id` | `text` | Worker identifier | Primary key, matches Runpod pod name |
| `instance_type` | `text` | GPU type or `external` | |
| `status` | `text` | Worker state | `inactive`, `active`, `terminated` |
| `last_heartbeat` | `timestamptz` | Last health check | Updated by workers every 20s |
| `metadata` | `jsonb` | Worker details | Runpod ID, VRAM usage, orchestrator status |
| `created_at` | `timestamptz` | Worker spawn time | |

#### Worker Metadata Structure
```json
{
  "runpod_id": "xyz123",
  "orchestrator_status": "spawning|active|terminating|error",
  "vram_total_mb": 24576,
  "vram_used_mb": 12288,
  "vram_timestamp": 1640995200.0,
  "auto_promoted": true
}
```

## RPC Functions

### Task Management

#### `func_claim_available_task(worker_id_param text)`
Atomically claims the next available task for a worker.

**Returns:** Task record with `task_data` mapped from `params`
**Logic:** 
- Checks if worker is marked for termination (if so, returns empty)
- Uses `FOR UPDATE SKIP LOCKED` to prevent race conditions
- Updates task status to `In Progress` and sets `generation_started_at`

#### `func_mark_task_complete(task_id_param uuid, result_data_param jsonb)`
Marks a task as completed with optional result data.

**Updates:**
- `status` → `Complete`
- `generation_processed_at` → NOW()
- `result_data` → provided data (video URLs, etc.)

#### `func_mark_task_failed(task_id_param uuid, error_message_param text)`
Marks a task as failed and handles retry logic.

**Logic:**
- Increments `attempts` counter
- If `attempts >= 3`: status → `Failed` (dead letter)
- If `attempts < 3`: status → `Queued`, `worker_id` → NULL (retry)
- Stores error message and clears worker assignment

#### `func_reset_orphaned_tasks(failed_worker_ids text[])`
Resets tasks from failed workers back to queue.

**Returns:** Count of reset tasks
**Logic:** Only resets tasks with `attempts < 3` to avoid infinite retries

### Worker Management

#### `func_update_worker_heartbeat(worker_id_param, vram_total_mb_param, vram_used_mb_param)`
Updates worker heartbeat with optional VRAM metrics.

**Features:**
- Creates worker record if it doesn't exist (for external workers)
- Merges VRAM data into existing metadata
- Updates `last_heartbeat` timestamp

### Legacy Compatibility

#### `func_claim_task(p_table_name text, p_worker_id text)`
Wrapper around `func_claim_available_task` for backward compatibility with Headless-Wan2GP workers.

## Monitoring Views

### `orchestrator_status`
Real-time system overview for dashboards.

**Metrics:**
- Task counts by status (`queued_tasks`, `running_tasks`, `completed_tasks`, etc.)
- Worker counts by status (`active_workers`, `terminated_workers`, etc.)
- Health indicators (`stale_workers`, `stuck_tasks`)

### `active_workers_health`
Detailed health status of all workers.

**Includes:**
- Heartbeat age in seconds
- VRAM usage percentage
- Current task information
- Health status: `HEALTHY`, `STALE_HEARTBEAT`, `STUCK_TASK`, `NO_HEARTBEAT`

### `recent_task_activity`
Last 24 hours of task activity with performance metrics.

**Features:**
- Processing duration calculations
- Worker assignment history
- Error message details

### `worker_performance`
7-day performance analysis per worker.

**Metrics:**
- Success rate percentage
- Average processing time
- Total tasks processed
- Uptime hours

### `task_queue_analysis`
Queue depth and processing time analysis by task type.

**Analytics:**
- Average/max queue time for pending tasks
- Processing time statistics
- Error rates by task type

## Database Indexes

Performance-critical indexes created by migrations:

```sql
-- Task processing optimization
CREATE INDEX idx_tasks_status_worker ON tasks(status, worker_id);
CREATE INDEX idx_tasks_queued_created ON tasks(created_at) WHERE status = 'Queued';
CREATE INDEX idx_tasks_running_started ON tasks(generation_started_at) WHERE status = 'In Progress';

-- Worker health monitoring
CREATE INDEX idx_workers_status_heartbeat ON workers(status, last_heartbeat);

-- Task claiming optimization
CREATE INDEX idx_tasks_claim_optimization ON tasks (status, created_at) WHERE status = 'Queued';
```

## Migration Files

| File | Purpose |
|------|---------|
| `20250202000000_add_missing_columns.sql` | Adds orchestrator columns to existing schema |
| `20250202000001_create_rpc_functions_existing.sql` | Core RPC functions |
| `20250202000002_create_monitoring_views_existing.sql` | Dashboard views |
| `20250202000003_add_legacy_functions.sql` | Backward compatibility |

All migrations are **idempotent** and safe to re-run. 