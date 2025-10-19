# Orchestrator Centralized Logging System

Complete implementation of database-backed centralized logging for the GPU orchestrator and workers.

## 🎯 What's Implemented

### ✅ Database Schema
- **System Logs Table** - Stores all logs with full context (worker, task, cycle, etc.)
- **RPC Functions** - Batch log insertion and enhanced heartbeat with logs
- **Indexes** - Optimized for common query patterns
- **Automatic Cleanup** - 48-hour retention to prevent unbounded growth
- **Helper Views** - For error analysis and worker activity

### ✅ Orchestrator Integration
- **DatabaseLogHandler** - Background thread for non-blocking log submission
- **Cycle Tracking** - Automatic cycle number context for timeline reconstruction
- **Batch Processing** - Efficient batching of logs (50 logs per batch, 5s intervals)
- **Statistics** - Track logs sent, dropped, errors
- **Graceful Shutdown** - Flushes remaining logs before exit

### ✅ Query & Analysis Tools
- **query_logs.py** - Powerful CLI for querying and exporting logs
- **view_logs_dashboard.py** - Real-time terminal dashboard for live log viewing
- **Flexible Filtering** - By worker, task, level, time, source, cycle
- **Export Capability** - JSON export for offline analysis

---

## 📁 Files Created/Modified

### New Files
```
sql/20250115000000_create_system_logs.sql     # Database schema
gpu_orchestrator/database_log_handler.py      # Database logging handler
scripts/query_logs.py                         # Log query tool
scripts/view_logs_dashboard.py                # Real-time log viewer
WORKER_LOGGING_IMPLEMENTATION.md              # Worker implementation guide
ORCHESTRATOR_LOGGING_SETUP.md                 # This file
```

### Modified Files
```
gpu_orchestrator/logging_config.py            # Added database logging support
gpu_orchestrator/main.py                      # Cycle tracking and stats
gpu_orchestrator/control_loop.py              # Cycle context setting
```

---

## 🚀 Setup Instructions

### Step 1: Apply Database Migration

Run the SQL migration to create the necessary tables and functions:

```bash
# Option 1: Using Supabase SQL Editor
# Copy contents of sql/20250115000000_create_system_logs.sql
# Paste and execute in Supabase SQL Editor

# Option 2: Using psql (if you have direct database access)
psql $DATABASE_URL -f sql/20250115000000_create_system_logs.sql

# Option 3: Using the apply_sql_migrations.py script
cd scripts
python apply_sql_migrations.py
```

**Verify Installation:**
```sql
-- Run in Supabase SQL Editor
SELECT * FROM system_logs LIMIT 1;  -- Should work (may be empty)
SELECT func_insert_logs_batch('[]'::jsonb);  -- Should return success
```

### Step 2: Enable Database Logging

Add to your `.env` file:

```bash
# Enable centralized logging
ENABLE_DB_LOGGING=true

# Optional: Adjust settings
DB_LOG_LEVEL=INFO                    # Minimum level to send (DEBUG/INFO/WARNING/ERROR)
DB_LOG_BATCH_SIZE=50                 # Logs per batch
DB_LOG_FLUSH_INTERVAL=5.0            # Seconds between flushes
ORCHESTRATOR_INSTANCE_ID=orchestrator-main  # Unique instance identifier
```

### Step 3: Test Orchestrator Logging

Start the orchestrator and verify logs are being sent:

```bash
# Start orchestrator
cd gpu_orchestrator
python main.py continuous

# In another terminal, query recent logs
cd scripts
python query_logs.py --source-type orchestrator_gpu --hours 1
```

You should see orchestrator logs appearing in the database!

---

## 📊 Using the Query Tools

### Basic Queries

```bash
# View all recent logs
python scripts/query_logs.py --hours 24

# View only errors
python scripts/query_logs.py --level ERROR --hours 48

# View orchestrator logs
python scripts/query_logs.py --source-type orchestrator_gpu

# View specific cycle
python scripts/query_logs.py --cycle 42 --source-type orchestrator_gpu

# Search for specific content
python scripts/query_logs.py --search "CUDA" --level ERROR
```

### Timeline Queries

```bash
# Get complete worker timeline
python scripts/query_logs.py --worker-timeline gpu-20250115-abc123

# Get complete task timeline
python scripts/query_logs.py --task-timeline 8755aa83-a502-4089-990d-df4414f90d58
```

### Statistics & Summaries

```bash
# View error summary
python scripts/query_logs.py --errors-summary

# View overall statistics
python scripts/query_logs.py --stats
```

### Export Logs

```bash
# Export to JSON file
python scripts/query_logs.py --source-type orchestrator_gpu --hours 48 --export orchestrator_logs.json

# Export specific worker logs
python scripts/query_logs.py --worker gpu-20250115-abc123 --export worker_logs.json
```

---

## 📺 Real-Time Log Dashboard

View live logs in a terminal dashboard:

```bash
# View all logs
python scripts/view_logs_dashboard.py

# View only orchestrator logs
python scripts/view_logs_dashboard.py --source-type orchestrator_gpu

# View only errors
python scripts/view_logs_dashboard.py --level ERROR

# View specific worker
python scripts/view_logs_dashboard.py --worker gpu-20250115-abc123

# Faster refresh (default is 5 seconds)
python scripts/view_logs_dashboard.py --refresh 2
```

The dashboard shows:
- **Real-time log stream** (auto-refreshing)
- **Statistics** (total logs, by level, by source)
- **Colored output** (errors in red, warnings in yellow, etc.)
- **Context information** (worker ID, task ID, cycle number)

---

## 🔍 Query Examples

### Debugging a Failed Task

```bash
# 1. Get task timeline
python scripts/query_logs.py --task-timeline abc-123-def-456

# 2. Check worker that processed it
python scripts/query_logs.py --worker gpu-20250115-xyz789 --hours 2

# 3. Look for errors around task time
python scripts/query_logs.py --level ERROR --hours 1 --search "abc-123"
```

### Investigating Worker Issues

```bash
# 1. View worker's complete history
python scripts/query_logs.py --worker-timeline gpu-20250115-abc123

# 2. Check for errors
python scripts/query_logs.py --worker gpu-20250115-abc123 --level ERROR

# 3. Export for detailed analysis
python scripts/query_logs.py --worker gpu-20250115-abc123 --export worker_debug.json
```

### Monitoring Orchestrator Cycles

```bash
# View specific cycle
python scripts/query_logs.py --cycle 42 --source-type orchestrator_gpu

# Check recent cycles for errors
python scripts/query_logs.py --source-type orchestrator_gpu --level ERROR --hours 2

# Export cycle for analysis
python scripts/query_logs.py --cycle 42 --export cycle_42.json
```

---

## 📈 Database Schema

### system_logs Table

| Column        | Type         | Description                              |
|---------------|--------------|------------------------------------------|
| id            | uuid         | Primary key                              |
| timestamp     | timestamptz  | When log was created                     |
| source_type   | text         | 'orchestrator_gpu', 'orchestrator_api', 'worker' |
| source_id     | text         | Instance identifier                      |
| log_level     | text         | 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL' |
| message       | text         | Log message                              |
| task_id       | uuid         | Task context (nullable)                  |
| worker_id     | text         | Worker context (nullable)                |
| cycle_number  | int          | Orchestrator cycle (nullable)            |
| metadata      | jsonb        | Additional structured data               |

### Indexes

- **timestamp** - Fast time-range queries
- **source_type + source_id** - Fast per-source queries
- **task_id** - Fast task timeline reconstruction
- **worker_id** - Fast worker timeline reconstruction
- **log_level** - Fast error filtering
- **cycle_number** - Fast cycle-specific queries

### RPC Functions

**func_insert_logs_batch(logs jsonb)**
- Batch insert logs from orchestrator
- Returns count of inserted logs

**func_worker_heartbeat_with_logs(worker_id, vram_total, vram_used, logs, task_id)**
- Enhanced heartbeat that includes log batch
- Updates worker heartbeat AND inserts logs atomically

**func_cleanup_old_logs(retention_hours int)**
- Cleanup logs older than retention period
- Default: 48 hours

---

## ⚙️ Configuration

### Environment Variables

| Variable                   | Default              | Description                          |
|----------------------------|----------------------|--------------------------------------|
| ENABLE_DB_LOGGING          | false                | Enable database logging              |
| DB_LOG_LEVEL               | INFO                 | Minimum log level to send            |
| DB_LOG_BATCH_SIZE          | 50                   | Logs per batch                       |
| DB_LOG_FLUSH_INTERVAL      | 5.0                  | Seconds between flushes              |
| ORCHESTRATOR_INSTANCE_ID   | orchestrator-{hostname} | Unique instance identifier    |

### Performance Tuning

**Batch Size:**
- **Small (25)**: Lower latency, more database calls
- **Medium (50)**: Default, good balance
- **Large (100)**: Higher latency, fewer database calls

**Flush Interval:**
- **Fast (2s)**: Lower latency, more frequent writes
- **Medium (5s)**: Default, good balance
- **Slow (10s)**: Higher latency, less frequent writes

**Log Level:**
- **DEBUG**: Very verbose, use only for troubleshooting
- **INFO**: Recommended for production
- **WARNING**: Only warnings and errors
- **ERROR**: Only errors

---

## 🔧 Troubleshooting

### Logs Not Appearing

**Check 1: Database function exists**
```sql
SELECT func_insert_logs_batch('[]'::jsonb);
-- Should return: {"success": true, "inserted": 0, "errors": 0}
```

**Check 2: Environment variable is set**
```bash
echo $ENABLE_DB_LOGGING  # Should print 'true'
```

**Check 3: Check orchestrator startup logs**
```bash
# Look for this line in orchestrator output:
# ✅ Database logging enabled: orchestrator-main -> Supabase
```

**Check 4: Query for any logs**
```bash
python scripts/query_logs.py --hours 1 --limit 10
```

### High Database Usage

If you see too many database calls:

```bash
# Increase batch size
export DB_LOG_BATCH_SIZE=100

# Increase flush interval
export DB_LOG_FLUSH_INTERVAL=10

# Reduce log level
export DB_LOG_LEVEL=WARNING
```

### Missing Logs

If some logs are missing:

1. **Check buffer isn't full** - Increase `DB_LOG_BATCH_SIZE`
2. **Check log level** - Lower `DB_LOG_LEVEL` if needed
3. **Check for errors** - Look for database connection issues in orchestrator logs

---

## 📊 Monitoring

### Database Stats Query

```sql
-- Count logs by source type
SELECT source_type, COUNT(*) as count
FROM system_logs
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY source_type;

-- Count logs by level
SELECT log_level, COUNT(*) as count
FROM system_logs
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY log_level
ORDER BY count DESC;

-- Recent errors
SELECT * FROM v_recent_errors LIMIT 10;

-- Worker activity
SELECT * FROM v_worker_log_activity;
```

### Orchestrator Stats

Check DatabaseLogHandler statistics periodically:

```python
from gpu_orchestrator.logging_config import get_db_logging_stats

stats = get_db_logging_stats()
print(stats)
# Output: {
#   'total_logs_queued': 1250,
#   'total_logs_sent': 1245,
#   'total_logs_dropped': 0,
#   'total_batches_sent': 25,
#   'total_errors': 0,
#   'queue_size': 5
# }
```

---

## 🧹 Maintenance

### Cleanup Old Logs

Logs are automatically cleaned up after 48 hours. To adjust or manually clean:

```sql
-- Cleanup logs older than 24 hours
SELECT func_cleanup_old_logs(24);

-- Cleanup logs older than 7 days
SELECT func_cleanup_old_logs(168);
```

### Database Size Monitoring

```sql
-- Check system_logs table size
SELECT pg_size_pretty(pg_total_relation_size('system_logs'));

-- Count logs by age
SELECT 
  CASE 
    WHEN age_hours < 1 THEN '< 1 hour'
    WHEN age_hours < 24 THEN '< 24 hours'
    WHEN age_hours < 48 THEN '< 48 hours'
    ELSE '> 48 hours'
  END as age_range,
  COUNT(*) as count
FROM (
  SELECT EXTRACT(EPOCH FROM (NOW() - timestamp))/3600 as age_hours
  FROM system_logs
) sub
GROUP BY age_range
ORDER BY age_range;
```

---

## 🔮 Future Enhancements

Potential improvements for the logging system:

1. **Log Aggregation** - Pre-aggregate common queries for faster dashboards
2. **Alerting** - Trigger alerts based on error patterns
3. **Log Sampling** - Sample high-volume logs to reduce storage
4. **Retention Tiers** - Keep summary stats longer than detailed logs
5. **Distributed Tracing** - Add correlation IDs for request tracing
6. **Metrics Extraction** - Extract performance metrics from logs

---

## 📚 Additional Resources

- **Worker Implementation Guide**: `WORKER_LOGGING_IMPLEMENTATION.md`
- **SQL Schema**: `sql/20250115000000_create_system_logs.sql`
- **Query Tool Help**: `python scripts/query_logs.py --help`
- **Dashboard Help**: `python scripts/view_logs_dashboard.py --help`
- **DatabaseLogHandler Source**: `gpu_orchestrator/database_log_handler.py`

---

## ✅ Quick Start Checklist

- [ ] Applied SQL migration (`sql/20250115000000_create_system_logs.sql`)
- [ ] Added `ENABLE_DB_LOGGING=true` to `.env`
- [ ] Restarted orchestrator
- [ ] Verified logs with `python scripts/query_logs.py --hours 1`
- [ ] Tested real-time dashboard with `python scripts/view_logs_dashboard.py`
- [ ] Read worker implementation guide (`WORKER_LOGGING_IMPLEMENTATION.md`)

---

## 🆘 Support

If you encounter issues:

1. Check database migration was applied correctly
2. Verify `ENABLE_DB_LOGGING=true` in environment
3. Check orchestrator startup logs for database logging confirmation
4. Test with `python scripts/query_logs.py --stats`
5. Review troubleshooting section above

For worker implementation, see `WORKER_LOGGING_IMPLEMENTATION.md`.





