# Centralized Logging Implementation - Summary

## 📋 Overview

A complete centralized logging system has been implemented for the orchestrator. All logs from orchestrators and workers are now stored in a queryable Supabase database with 24-hour history and comprehensive filtering capabilities.

---

## ✅ What Was Implemented

### 1. Database Infrastructure

**File:** `sql/20250115000000_create_system_logs.sql`

- ✅ `system_logs` table with optimized indexes
- ✅ RPC function for batch log insertion
- ✅ Enhanced worker heartbeat RPC function (includes logs)
- ✅ Automatic cleanup function (48-hour retention)
- ✅ Helper views for error analysis and worker activity
- ✅ Proper permissions and constraints

**Key Features:**
- Stores logs from orchestrators and workers
- Indexed by timestamp, source, worker, task, level, cycle
- Automatic cleanup prevents unbounded growth
- Batch insertion for efficiency

### 2. Orchestrator Integration

**Files Modified:**
- `gpu_orchestrator/database_log_handler.py` (NEW)
- `gpu_orchestrator/logging_config.py` (MODIFIED)
- `gpu_orchestrator/main.py` (MODIFIED)
- `gpu_orchestrator/control_loop.py` (MODIFIED)

**Key Features:**
- Background thread for non-blocking log submission
- Automatic batching (50 logs per batch, 5s intervals)
- Cycle number tracking for timeline reconstruction
- Graceful shutdown with log flush
- Statistics tracking (logs sent, dropped, errors)
- Environment variable configuration

**How It Works:**
1. Logs are queued in memory
2. Background thread batches and sends every 5 seconds
3. Cycle number is automatically tracked
4. All logs are sent to database via RPC function
5. No impact on orchestrator performance

### 3. Query & Analysis Tools

**Files Created:**
- `scripts/query_logs.py` (NEW)
- `scripts/view_logs_dashboard.py` (NEW)

**Key Features:**

**query_logs.py:**
- Query logs by worker, task, time, level, source, cycle
- Get worker timeline (complete log history)
- Get task timeline (complete task log history)
- Error summary and statistics
- Export to JSON for offline analysis
- Table and JSON output formats

**view_logs_dashboard.py:**
- Real-time terminal dashboard
- Auto-refreshing every 5 seconds
- Color-coded by log level
- Statistics display
- Filter by source, worker, level
- Shows context (worker, task, cycle)

### 4. Worker Implementation Guide

**File:** `WORKER_LOGGING_IMPLEMENTATION.md` (NEW)

Complete guide for implementing logging in GPU workers:
- LogBuffer class implementation
- WorkerDatabaseLogHandler implementation
- Integration with heartbeat mechanism
- Testing procedures
- Configuration options
- Best practices and troubleshooting

---

## 📁 Complete File List

### New Files
```
sql/20250115000000_create_system_logs.sql
gpu_orchestrator/database_log_handler.py
scripts/query_logs.py
scripts/view_logs_dashboard.py
WORKER_LOGGING_IMPLEMENTATION.md
ORCHESTRATOR_LOGGING_SETUP.md
LOGGING_IMPLEMENTATION_SUMMARY.md
```

### Modified Files
```
gpu_orchestrator/logging_config.py
gpu_orchestrator/main.py
gpu_orchestrator/control_loop.py
```

---

## 🚀 Quick Start

### For Orchestrator (Already Implemented)

1. **Apply database migration:**
   ```bash
   # Use Supabase SQL Editor to run:
   sql/20250115000000_create_system_logs.sql
   ```

2. **Enable logging in `.env`:**
   ```bash
   ENABLE_DB_LOGGING=true
   ```

3. **Restart orchestrator:**
   ```bash
   cd gpu_orchestrator
   python main.py continuous
   ```

4. **Verify logs are being sent:**
   ```bash
   cd scripts
   python query_logs.py --source-type orchestrator_gpu --hours 1
   ```

### For Workers (Needs Implementation in Headless-Wan2GP)

See `WORKER_LOGGING_IMPLEMENTATION.md` for complete guide.

Summary:
1. Add `LogBuffer` and `WorkerDatabaseLogHandler` classes
2. Update heartbeat function to include logs
3. Initialize in worker main loop
4. Set/clear task context when processing

---

## 📊 Usage Examples

### Query Recent Logs
```bash
# All logs from last hour
python scripts/query_logs.py --hours 1

# Only errors
python scripts/query_logs.py --level ERROR --hours 24

# Orchestrator logs only
python scripts/query_logs.py --source-type orchestrator_gpu

# Specific worker
python scripts/query_logs.py --worker gpu-20250115-abc123
```

### View Real-Time Dashboard
```bash
# All logs
python scripts/view_logs_dashboard.py

# Only errors
python scripts/view_logs_dashboard.py --level ERROR

# Specific worker
python scripts/view_logs_dashboard.py --worker gpu-20250115-abc123
```

### Timeline Reconstruction
```bash
# Complete worker history
python scripts/query_logs.py --worker-timeline gpu-20250115-abc123

# Complete task history
python scripts/query_logs.py --task-timeline abc-123-def-456

# Specific orchestrator cycle
python scripts/query_logs.py --cycle 42 --source-type orchestrator_gpu
```

### Export & Analysis
```bash
# Export orchestrator logs
python scripts/query_logs.py --source-type orchestrator_gpu --hours 48 --export logs.json

# Get error summary
python scripts/query_logs.py --errors-summary

# Get statistics
python scripts/query_logs.py --stats
```

---

## ⚙️ Configuration

### Environment Variables

Add to `.env`:

```bash
# Enable database logging
ENABLE_DB_LOGGING=true

# Optional: Configure behavior
DB_LOG_LEVEL=INFO                    # Minimum level (DEBUG/INFO/WARNING/ERROR)
DB_LOG_BATCH_SIZE=50                 # Logs per batch
DB_LOG_FLUSH_INTERVAL=5.0            # Seconds between flushes
ORCHESTRATOR_INSTANCE_ID=orch-main   # Unique identifier
```

### Recommended Settings

**Production:**
```bash
ENABLE_DB_LOGGING=true
DB_LOG_LEVEL=INFO
DB_LOG_BATCH_SIZE=50
DB_LOG_FLUSH_INTERVAL=5.0
```

**Development/Debug:**
```bash
ENABLE_DB_LOGGING=true
DB_LOG_LEVEL=DEBUG
DB_LOG_BATCH_SIZE=25
DB_LOG_FLUSH_INTERVAL=2.0
```

**High Volume (many workers):**
```bash
ENABLE_DB_LOGGING=true
DB_LOG_LEVEL=WARNING
DB_LOG_BATCH_SIZE=100
DB_LOG_FLUSH_INTERVAL=10.0
```

---

## 🎯 Key Benefits

### 1. Complete Visibility
- ✅ All orchestrator logs in database
- ✅ 24+ hours of searchable history
- ✅ Timeline reconstruction for any worker or task
- ✅ Cycle-level tracking for orchestrator

### 2. Powerful Filtering
- ✅ Filter by worker, task, time, level, source, cycle
- ✅ Search message content
- ✅ Combine multiple filters
- ✅ Export results to JSON

### 3. Real-Time Monitoring
- ✅ Live dashboard with auto-refresh
- ✅ Color-coded by severity
- ✅ Statistics display
- ✅ Context information (worker, task, cycle)

### 4. Non-Blocking Performance
- ✅ Background thread processing
- ✅ Automatic batching
- ✅ No impact on main orchestrator loop
- ✅ Graceful error handling

### 5. Easy Integration
- ✅ Single environment variable to enable
- ✅ Automatic cycle tracking
- ✅ Worker logs piggyback on heartbeat (zero extra network calls)
- ✅ No code changes needed for basic usage

---

## 📈 Database Schema

### system_logs Table

| Column        | Type         | Nullable | Indexed | Description                |
|---------------|--------------|----------|---------|----------------------------|
| id            | uuid         | No       | Primary | Unique log ID              |
| timestamp     | timestamptz  | No       | Yes     | Log creation time          |
| source_type   | text         | No       | Yes     | orchestrator_gpu/api/worker|
| source_id     | text         | No       | Yes     | Instance identifier        |
| log_level     | text         | No       | Yes     | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| message       | text         | No       | No      | Log message                |
| task_id       | uuid         | Yes      | Yes     | Task context               |
| worker_id     | text         | Yes      | Yes     | Worker context             |
| cycle_number  | int          | Yes      | Yes     | Orchestrator cycle         |
| metadata      | jsonb        | Yes      | No      | Additional data            |

---

## 🔍 Common Use Cases

### 1. Debugging Failed Tasks

```bash
# Get task timeline
python scripts/query_logs.py --task-timeline <task-id>

# Get worker logs for task time period
python scripts/query_logs.py --worker <worker-id> --hours 2

# Look for errors
python scripts/query_logs.py --level ERROR --search "<task-id>"
```

### 2. Investigating Worker Issues

```bash
# Complete worker history
python scripts/query_logs.py --worker-timeline <worker-id>

# Worker errors only
python scripts/query_logs.py --worker <worker-id> --level ERROR

# Export for detailed analysis
python scripts/query_logs.py --worker <worker-id> --export debug.json
```

### 3. Monitoring Orchestrator Health

```bash
# View recent orchestrator logs
python scripts/query_logs.py --source-type orchestrator_gpu --hours 2

# Check for errors in recent cycles
python scripts/query_logs.py --source-type orchestrator_gpu --level ERROR

# View specific cycle
python scripts/query_logs.py --cycle 42 --source-type orchestrator_gpu
```

### 4. Real-Time Monitoring

```bash
# Watch all logs live
python scripts/view_logs_dashboard.py

# Watch errors only
python scripts/view_logs_dashboard.py --level ERROR

# Watch specific worker
python scripts/view_logs_dashboard.py --worker <worker-id>
```

---

## 🔧 Maintenance

### Automatic Cleanup

Logs are automatically cleaned up after 48 hours. To adjust:

```sql
-- Cleanup logs older than 24 hours
SELECT func_cleanup_old_logs(24);

-- Cleanup logs older than 7 days  
SELECT func_cleanup_old_logs(168);
```

### Monitor Database Size

```sql
-- Check table size
SELECT pg_size_pretty(pg_total_relation_size('system_logs'));

-- Count logs
SELECT COUNT(*) FROM system_logs;

-- Count by age
SELECT 
  date_trunc('hour', timestamp) as hour,
  COUNT(*) as count
FROM system_logs
GROUP BY hour
ORDER BY hour DESC
LIMIT 48;
```

---

## 🆘 Troubleshooting

### Logs Not Appearing

1. **Check migration applied:**
   ```sql
   SELECT * FROM system_logs LIMIT 1;
   ```

2. **Check environment variable:**
   ```bash
   echo $ENABLE_DB_LOGGING  # Should be 'true'
   ```

3. **Check orchestrator logs:**
   ```
   Look for: ✅ Database logging enabled: orchestrator-main -> Supabase
   ```

4. **Test query:**
   ```bash
   python scripts/query_logs.py --hours 1
   ```

### High Database Usage

```bash
# Increase batch size and interval
export DB_LOG_BATCH_SIZE=100
export DB_LOG_FLUSH_INTERVAL=10

# Reduce log level
export DB_LOG_LEVEL=WARNING
```

---

## 📚 Documentation

- **Orchestrator Setup**: `ORCHESTRATOR_LOGGING_SETUP.md`
- **Worker Implementation**: `WORKER_LOGGING_IMPLEMENTATION.md`
- **This Summary**: `LOGGING_IMPLEMENTATION_SUMMARY.md`
- **SQL Schema**: `sql/20250115000000_create_system_logs.sql`

---

## ✅ Implementation Checklist

### Orchestrator (✅ Complete)
- [x] Database schema created
- [x] DatabaseLogHandler implemented
- [x] logging_config.py updated
- [x] main.py updated with cycle tracking
- [x] control_loop.py updated
- [x] Query tools created
- [x] Dashboard created
- [x] Documentation written

### Workers (📝 Pending - See WORKER_LOGGING_IMPLEMENTATION.md)
- [ ] Add LogBuffer class
- [ ] Add WorkerDatabaseLogHandler class
- [ ] Update heartbeat function
- [ ] Initialize in worker main
- [ ] Set/clear task context
- [ ] Test with sample worker

---

## 🎉 Summary

The orchestrator side is **fully implemented and ready to use**. Simply:

1. Apply the SQL migration
2. Set `ENABLE_DB_LOGGING=true`
3. Restart the orchestrator
4. Start querying logs!

For workers, follow the comprehensive guide in `WORKER_LOGGING_IMPLEMENTATION.md`.

All logs are centralized, searchable, and stored with complete context for easy debugging and analysis.





