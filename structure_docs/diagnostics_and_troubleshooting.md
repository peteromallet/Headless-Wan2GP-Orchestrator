# Diagnostics and Troubleshooting

> **⚠️ This document has been superseded by the unified debug tool.**

## 🎯 Use the Unified Debug Tool

All debugging and diagnostics are now handled through one unified tool:

```bash
python scripts/debug.py <subcommand>
```

**Complete documentation:** [`scripts/debug/README.md`](../scripts/debug/README.md)

## Quick Commands

```bash
# Check system health
python scripts/debug.py health

# Investigate a failed task
python scripts/debug.py task <task_id>

# Check worker status
python scripts/debug.py worker <worker_id>
python scripts/debug.py worker <worker_id> --check-logging  # Is it running?
python scripts/debug.py worker <worker_id> --startup        # View startup logs

# Recent failures
python scripts/debug.py workers --hours 6

# View configuration
python scripts/debug.py config --explain

# Find orphaned pods
python scripts/debug.py runpod
```

## Common Issues

| Problem | Solution |
|---------|----------|
| "System seems down" | `debug.py health` |
| "Task failed" | `debug.py task <task_id>` |
| "Worker not responding" | `debug.py worker <id> --check-logging` |
| "High costs" | `debug.py runpod` |
| "Unclear timeouts" | `debug.py config --explain` |

## Emergency Procedures

### Shutdown all workers
```bash
python scripts/shutdown_all_workers.py
```

### Spawn a worker manually
```bash
python scripts/spawn_gpu.py
```

### Check Railway logs
```bash
cd gpu_orchestrator && railway logs
cd api_orchestrator && railway logs
```

## Legacy Documentation

This file previously contained 600+ lines of manual debugging procedures. 

All that functionality is now consolidated in the unified debug tool, which provides:
- Automated data collection from `system_logs` table
- Consistent formatting across all commands
- Better error detection and suggestions
- JSON output for automation

See [`debugging.md`](debugging.md) for the complete guide.
