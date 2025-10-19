# Worker Logging Implementation Guide

This guide explains how to implement centralized logging in GPU workers (Headless-Wan2GP) to integrate with the orchestrator's logging system.

## Overview

The orchestrator now has a centralized logging system that stores all logs in Supabase. Workers can send their logs via the existing heartbeat mechanism, requiring minimal changes to the worker codebase.

**Key Benefits:**
- ✅ **Zero Additional Network Calls** - Logs piggyback on existing heartbeats
- ✅ **Complete Timeline Reconstruction** - Query any worker or task history
- ✅ **Centralized Analysis** - All logs in one queryable database
- ✅ **Automatic Cleanup** - 48-hour retention prevents unbounded growth

---

## Architecture

### How It Works

1. **Worker buffers logs in memory** (LogBuffer class)
2. **Every heartbeat (20s), logs are flushed** to database
3. **Database stores logs** in `system_logs` table
4. **Orchestrator can query** complete worker history

```
┌─────────────┐                    ┌─────────────┐                 ┌─────────────┐
│   Worker    │                    │  Heartbeat  │                 │  Supabase   │
│             │                    │  (20s)      │                 │  Database   │
│ ┌─────────┐ │                    │             │                 │             │
│ │ Logger  │ │──> Buffer logs ──> │             │──> Batch logs ─>│ system_logs │
│ └─────────┘ │                    │             │                 │   table     │
└─────────────┘                    └─────────────┘                 └─────────────┘
```

---

## Implementation Steps

### Step 1: Create LogBuffer Class

Add this to your worker codebase (e.g., `logging_utils.py`):

```python
"""
Logging utilities for GPU workers.
Buffers logs in memory and sends them with heartbeat updates.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


class LogBuffer:
    """
    Thread-safe buffer for collecting logs.
    
    Logs are stored in memory and flushed periodically with heartbeat updates.
    This prevents excessive database calls while maintaining log history.
    """
    
    def __init__(self, max_size: int = 100):
        """
        Initialize log buffer.
        
        Args:
            max_size: Maximum logs to buffer before auto-flush (default: 100)
        """
        self.logs: List[Dict[str, Any]] = []
        self.max_size = max_size
        self.lock = threading.Lock()
        self.total_logs = 0
        self.total_flushes = 0
    
    def add(
        self,
        level: str,
        message: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Add a log entry to buffer.
        
        Args:
            level: Log level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
            message: Log message
            task_id: Optional task ID for context
            metadata: Optional additional metadata
        
        Returns:
            List of logs if buffer is full and auto-flushed, otherwise []
        """
        with self.lock:
            self.logs.append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'level': level,
                'message': message,
                'task_id': task_id,
                'metadata': metadata or {}
            })
            self.total_logs += 1
            
            # Auto-flush if buffer is full
            if len(self.logs) >= self.max_size:
                return self.flush()
        
        return []
    
    def flush(self) -> List[Dict[str, Any]]:
        """
        Get and clear all buffered logs.
        
        Returns:
            List of log entries
        """
        with self.lock:
            logs = self.logs.copy()
            self.logs = []
            if logs:
                self.total_flushes += 1
            return logs
    
    def get_stats(self) -> Dict[str, int]:
        """Get buffer statistics."""
        with self.lock:
            return {
                'current_buffer_size': len(self.logs),
                'total_logs_buffered': self.total_logs,
                'total_flushes': self.total_flushes
            }


class WorkerDatabaseLogHandler(logging.Handler):
    """
    Custom logging handler that buffers logs for database storage.
    
    Usage:
        log_buffer = LogBuffer()
        handler = WorkerDatabaseLogHandler('gpu-worker-123', log_buffer)
        logging.getLogger().addHandler(handler)
        
        # Set current task when processing
        handler.set_current_task('task-id-456')
    """
    
    def __init__(
        self,
        worker_id: str,
        log_buffer: LogBuffer,
        min_level: int = logging.INFO
    ):
        """
        Initialize handler.
        
        Args:
            worker_id: Worker's unique ID
            log_buffer: LogBuffer instance to collect logs
            min_level: Minimum log level to buffer (default: INFO)
        """
        super().__init__()
        self.worker_id = worker_id
        self.log_buffer = log_buffer
        self.current_task_id: Optional[str] = None
        self.setLevel(min_level)
    
    def set_current_task(self, task_id: Optional[str]):
        """Set current task ID for context."""
        self.current_task_id = task_id
    
    def emit(self, record: logging.LogRecord):
        """
        Capture log record to buffer.
        
        Called automatically by logging framework.
        """
        try:
            # Extract metadata from record
            metadata = {
                'module': record.module,
                'funcName': record.funcName,
                'lineno': record.lineno,
            }
            
            # Add exception info if present
            if record.exc_info:
                metadata['exception'] = self.format(record)
            
            # Add to buffer
            self.log_buffer.add(
                level=record.levelname,
                message=record.getMessage(),
                task_id=self.current_task_id,
                metadata=metadata
            )
        except Exception:
            self.handleError(record)
```

---

### Step 2: Update Heartbeat Function

Modify your heartbeat function to include logs:

```python
async def send_heartbeat_with_logs(
    worker_id: str,
    log_buffer: LogBuffer,
    supabase_client,
    current_task_id: Optional[str] = None
) -> bool:
    """
    Enhanced heartbeat that includes log batch.
    
    Args:
        worker_id: Worker's unique ID
        log_buffer: LogBuffer instance
        supabase_client: Supabase client instance
        current_task_id: Current task being processed (optional)
    
    Returns:
        True if heartbeat successful
    """
    try:
        # Get GPU metrics (if available)
        vram_total, vram_used = get_gpu_memory_usage()
        
        # Flush log buffer
        logs = log_buffer.flush()
        
        # Send to database via enhanced RPC function
        result = supabase_client.rpc('func_worker_heartbeat_with_logs', {
            'worker_id_param': worker_id,
            'vram_total_mb_param': vram_total,
            'vram_used_mb_param': vram_used,
            'logs_param': logs,  # ← NEW: Include logs
            'current_task_id_param': current_task_id
        }).execute()
        
        # Log success (to local file, not buffer to avoid recursion)
        if result.data and result.data.get('logs_inserted', 0) > 0:
            print(f"DEBUG: Sent {result.data['logs_inserted']} logs with heartbeat")
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to send heartbeat with logs: {e}")
        return False


def get_gpu_memory_usage():
    """
    Get GPU memory usage in MB.
    
    Returns:
        Tuple of (total_mb, used_mb) or (None, None) if unavailable
    """
    try:
        import torch
        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
            allocated = torch.cuda.memory_allocated(0) / (1024 * 1024)
            return int(total), int(allocated)
    except Exception:
        pass
    
    return None, None
```

---

### Step 3: Initialize in Worker Main Loop

Update your worker initialization:

```python
#!/usr/bin/env python3
"""
GPU Worker Main Loop (Headless-Wan2GP)
"""

import os
import sys
import logging
import asyncio
from supabase import create_client
from logging_utils import LogBuffer, WorkerDatabaseLogHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Worker configuration
WORKER_ID = os.getenv("WORKER_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
HEARTBEAT_INTERVAL = 20  # seconds

# Initialize log buffer and handler
log_buffer = LogBuffer(max_size=100)
log_handler = WorkerDatabaseLogHandler(
    worker_id=WORKER_ID,
    log_buffer=log_buffer,
    min_level=logging.INFO  # Only send INFO+ to database
)
logging.getLogger().addHandler(log_handler)

logger.info(f"Worker {WORKER_ID} starting with centralized logging enabled")


async def worker_main_loop():
    """Main worker loop."""
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    last_heartbeat = 0
    current_task_id = None
    
    while True:
        try:
            # Send heartbeat with logs every 20 seconds
            current_time = time.time()
            if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                await send_heartbeat_with_logs(
                    worker_id=WORKER_ID,
                    log_buffer=log_buffer,
                    supabase_client=supabase,
                    current_task_id=current_task_id
                )
                last_heartbeat = current_time
            
            # Try to claim a task
            task = await claim_next_task(supabase, WORKER_ID)
            
            if task:
                current_task_id = task['id']
                
                # Set current task in log handler for context
                log_handler.set_current_task(current_task_id)
                
                logger.info(f"Processing task {current_task_id}")
                
                try:
                    # Process task
                    result = await process_task(task)
                    
                    # Mark complete
                    await mark_task_complete(supabase, current_task_id, result)
                    logger.info(f"Completed task {current_task_id}")
                    
                except Exception as e:
                    logger.error(f"Task {current_task_id} failed: {e}", exc_info=True)
                    await mark_task_failed(supabase, current_task_id, str(e))
                
                finally:
                    # Clear task context
                    log_handler.set_current_task(None)
                    current_task_id = None
            
            else:
                # No tasks available
                await asyncio.sleep(5)
        
        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            await asyncio.sleep(10)
    
    # Final heartbeat flush before exit
    logger.info("Worker shutting down, flushing remaining logs...")
    await send_heartbeat_with_logs(
        worker_id=WORKER_ID,
        log_buffer=log_buffer,
        supabase_client=supabase,
        current_task_id=current_task_id
    )


if __name__ == "__main__":
    asyncio.run(worker_main_loop())
```

---

## Testing the Implementation

### 1. Verify Database Schema

Make sure the `system_logs` table and RPC functions exist:

```bash
# Run the migration on orchestrator side
psql $DATABASE_URL < sql/20250115000000_create_system_logs.sql
```

### 2. Test Worker Logging

Start a worker and verify logs are being sent:

```python
# In worker code, add test logs
logger.info("Worker started successfully")
logger.warning("This is a test warning")
logger.error("This is a test error")

# Wait 20 seconds for heartbeat
time.sleep(21)

# Logs should now be in database
```

### 3. Query Logs from Orchestrator

```bash
# View worker logs
python scripts/query_logs.py --worker your-worker-id --hours 1

# View errors only
python scripts/query_logs.py --worker your-worker-id --level ERROR

# View complete timeline
python scripts/query_logs.py --worker-timeline your-worker-id
```

---

## Configuration Options

### Environment Variables (Optional)

These can be set in the worker's environment:

```bash
# Enable verbose logging to database
export DB_LOG_LEVEL=DEBUG  # Default: INFO

# Adjust buffer size (logs before auto-flush)
export LOG_BUFFER_SIZE=100  # Default: 100

# Heartbeat interval (seconds)
export HEARTBEAT_INTERVAL=20  # Default: 20
```

### Tuning Parameters

**Buffer Size:**
- **Small (50)**: More frequent database writes, lower memory usage
- **Medium (100)**: Default, good balance
- **Large (200)**: Fewer database writes, higher memory usage

**Log Level:**
- **INFO**: Recommended for production (default)
- **DEBUG**: More verbose, useful for troubleshooting
- **WARNING**: Only warnings and errors

---

## Best Practices

### 1. Set Task Context

Always set the current task ID when processing:

```python
log_handler.set_current_task(task_id)
try:
    # Process task
    result = process_task(task)
finally:
    log_handler.set_current_task(None)
```

This allows filtering logs by task ID.

### 2. Structured Logging

Use structured logging for better queryability:

```python
# Good: Include context in message
logger.info(f"Downloaded video: {video_url}, size: {size_mb}MB, duration: {duration}s")

# Even better: Use metadata
logger.info("Downloaded video", extra={
    'extra_data': {
        'video_url': video_url,
        'size_mb': size_mb,
        'duration_seconds': duration
    }
})
```

### 3. Error Handling

Always log errors with full context:

```python
try:
    result = risky_operation()
except Exception as e:
    # exc_info=True includes full stack trace
    logger.error(f"Failed to process video: {e}", exc_info=True)
    raise
```

### 4. Performance Considerations

- **Buffer size**: Keep at 100 unless you have specific needs
- **Heartbeat interval**: 20s is optimal (matches existing heartbeat)
- **Log level**: INFO or higher for production (DEBUG generates too many logs)
- **Message length**: Keep messages concise (database stores full message)

---

## Monitoring Log Health

### Check Buffer Stats

```python
# In worker code
stats = log_buffer.get_stats()
logger.info(f"Log buffer stats: {stats}")
# Output: {'current_buffer_size': 15, 'total_logs_buffered': 1250, 'total_flushes': 12}
```

### Query from Orchestrator

```bash
# View recent worker logs
python scripts/query_logs.py --source-type worker --hours 1

# View log statistics
python scripts/query_logs.py --stats

# View error summary
python scripts/query_logs.py --errors-summary
```

### Real-time Dashboard

```bash
# View live logs for all workers
python scripts/view_logs_dashboard.py

# View live logs for specific worker
python scripts/view_logs_dashboard.py --worker gpu-20250115-abc123

# View only errors
python scripts/view_logs_dashboard.py --level ERROR
```

---

## Troubleshooting

### Logs Not Appearing in Database

**Check 1: Database function exists**
```sql
-- Run this in Supabase SQL editor
SELECT func_worker_heartbeat_with_logs('test-worker', NULL, NULL, '[]'::jsonb, NULL);
```

**Check 2: Worker is sending heartbeats**
```python
# Add debug logging before heartbeat call
print(f"Sending heartbeat with {len(logs)} logs")
result = supabase.rpc('func_worker_heartbeat_with_logs', {...})
print(f"Heartbeat result: {result.data}")
```

**Check 3: Logs are being buffered**
```python
# Add periodic stats logging
if loop_count % 10 == 0:
    stats = log_buffer.get_stats()
    print(f"Buffer stats: {stats}")
```

### Buffer Filling Up Too Fast

If auto-flush triggers frequently:

```python
# Increase buffer size
log_buffer = LogBuffer(max_size=200)

# Or reduce log verbosity
log_handler.setLevel(logging.WARNING)  # Only warnings and errors
```

### Logs Taking Too Long to Appear

Logs are sent with heartbeat (every 20s by default). To see logs faster:

```python
# Reduce heartbeat interval (not recommended below 10s)
HEARTBEAT_INTERVAL = 10

# Or manually flush buffer for critical logs
if critical_error:
    logger.error("Critical error occurred")
    await send_heartbeat_with_logs(...)  # Force immediate flush
```

---

## Migration Checklist

- [ ] Add `logging_utils.py` with `LogBuffer` and `WorkerDatabaseLogHandler`
- [ ] Update heartbeat function to include logs parameter
- [ ] Initialize log buffer and handler in worker main
- [ ] Set/clear task context when processing tasks
- [ ] Test logging with sample worker
- [ ] Query logs from orchestrator to verify
- [ ] Monitor buffer stats for first few hours
- [ ] Adjust buffer size and log level if needed

---

## Example: Complete Worker Integration

Here's a complete minimal example:

```python
#!/usr/bin/env python3
"""Minimal worker with centralized logging."""

import os
import time
import logging
from supabase import create_client
from logging_utils import LogBuffer, WorkerDatabaseLogHandler

# Setup
WORKER_ID = os.getenv("WORKER_ID", "test-worker")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize logging
log_buffer = LogBuffer(max_size=100)
log_handler = WorkerDatabaseLogHandler(WORKER_ID, log_buffer)
logging.getLogger().addHandler(log_handler)

# Supabase client
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

def send_heartbeat():
    """Send heartbeat with logs."""
    logs = log_buffer.flush()
    try:
        supabase.rpc('func_worker_heartbeat_with_logs', {
            'worker_id_param': WORKER_ID,
            'vram_total_mb_param': None,
            'vram_used_mb_param': None,
            'logs_param': logs,
            'current_task_id_param': None
        }).execute()
        print(f"Sent {len(logs)} logs")
    except Exception as e:
        print(f"Heartbeat failed: {e}")

# Main loop
logger.info("Worker starting")
last_heartbeat = 0

while True:
    # Send heartbeat every 20s
    if time.time() - last_heartbeat >= 20:
        send_heartbeat()
        last_heartbeat = time.time()
    
    # Simulate work
    logger.info("Processing task...")
    time.sleep(5)
```

---

## Additional Resources

- **Query Logs**: `scripts/query_logs.py --help`
- **View Dashboard**: `scripts/view_logs_dashboard.py --help`
- **SQL Schema**: `sql/20250115000000_create_system_logs.sql`
- **Orchestrator Implementation**: `gpu_orchestrator/database_log_handler.py`

---

## Support

If you encounter issues:

1. Check logs are being buffered: `log_buffer.get_stats()`
2. Verify heartbeat is being sent: Add debug prints
3. Check database function exists: Query Supabase SQL editor
4. View logs in dashboard: `python scripts/view_logs_dashboard.py`

For questions or issues, refer to the main orchestrator repository.

