# Logging Tools

Utilities for querying and viewing centralized system logs.

## Tools

### query_logs.py

**Command-line tool for querying logs from the database.**

Features:
- Query by worker, task, time, level, source, cycle
- Get complete timelines for workers or tasks
- Error summaries and statistics
- Export to JSON
- Table or JSON output

Examples:
```bash
# Recent errors
python query_logs.py --level ERROR --hours 24

# Worker timeline
python query_logs.py --worker-timeline gpu-20250115-abc123

# Task timeline
python query_logs.py --task-timeline abc-123-def-456

# Orchestrator cycle
python query_logs.py --cycle 42 --source-type orchestrator_gpu

# Export to JSON
python query_logs.py --source-type orchestrator_gpu --export logs.json

# Error summary
python query_logs.py --errors-summary

# Statistics
python query_logs.py --stats
```

Full help: `python query_logs.py --help`

### view_logs_dashboard.py

**Real-time terminal dashboard for viewing logs.**

Features:
- Auto-refreshing display (default: 5s)
- Color-coded by log level
- Statistics display
- Filter by source, worker, level
- Shows context (worker ID, task ID, cycle number)

Examples:
```bash
# View all logs
python view_logs_dashboard.py

# View orchestrator logs only
python view_logs_dashboard.py --source-type orchestrator_gpu

# View errors only
python view_logs_dashboard.py --level ERROR

# View specific worker
python view_logs_dashboard.py --worker gpu-20250115-abc123

# Faster refresh
python view_logs_dashboard.py --refresh 2
```

Full help: `python view_logs_dashboard.py --help`

## Setup

Make sure you have:
1. Applied the SQL migration (`sql/20250115000000_create_system_logs.sql`)
2. Set environment variables in `.env`:
   ```bash
   SUPABASE_URL=your-url
   SUPABASE_SERVICE_ROLE_KEY=your-key
   ```

## Documentation

- **Complete Setup Guide**: `../ORCHESTRATOR_LOGGING_SETUP.md`
- **Worker Implementation**: `../WORKER_LOGGING_IMPLEMENTATION.md`
- **Summary**: `../LOGGING_IMPLEMENTATION_SUMMARY.md`





