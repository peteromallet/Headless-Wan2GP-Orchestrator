# Spot Instance Lifetime Testing

## Overview

The `spot_instance_lifetime_test.py` script launches multiple RTX 4090 spot instances across different storage configurations and tracks how long each survives before being terminated by RunPod.

## Purpose

- **Compare storage configurations**: Test how different storage setups affect spot instance lifetime
- **Measure spot stability**: Track actual termination patterns vs. pricing
- **Cost optimization**: Identify most cost-effective configurations
- **Production planning**: Understand spot instance reliability for workloads

## Storage Configurations Tested

1. **No Storage** - Container disk only (50GB)
2. **Peter Storage** - Network storage volume attached
3. **Large Disk** - Large container disk (200GB)
4. **Storage + Large Disk** - Network storage + large container disk (150GB)

## Features

### Automated Launching
- Creates 4 spot instances simultaneously
- Uses `cloud_type: COMMUNITY` for spot pricing
- Configures each with different storage setups
- Records launch time and configuration

### Real-time Monitoring
- Checks instance status every 60 seconds
- Tracks runtime for each instance
- Detects termination events and reasons
- Updates progress display

### Comprehensive Reporting
- Generates detailed lifetime statistics
- Compares performance across configurations
- Shows termination reasons and patterns
- Saves results to JSON for analysis

### Safety Features
- Automatic cleanup of remaining instances
- Interrupt handling (Ctrl+C)
- Error handling for API failures
- User confirmation for cleanup

## Usage

### Basic Run
```bash
python3 scripts/spot_instance_lifetime_test.py
```

### Environment Requirements
```bash
# Required environment variables
RUNPOD_API_KEY=your_api_key
RUNPOD_WORKER_IMAGE=your_worker_image
RUNPOD_SSH_PUBLIC_KEY=your_ssh_key

# Optional (will use defaults)
RUNPOD_VOLUME_MOUNT_PATH=/workspace
```

### Sample Output
```
🚀 Launching 4 RTX 4090 spot instances for lifetime testing...
================================================================================

📦 Instance 1: No Storage
   Container disk only
   Storage: None
   Disk: 50GB
   ✅ Launched: a1b2c3d4e5f6

📦 Instance 2: Peter Storage
   Network storage volume
   Storage: Peter
   Disk: 50GB
   ✅ Launched: f6e5d4c3b2a1

👀 Monitoring 4 instances for up to 24 hours...
   ID               | Config              | Status    | Runtime
   ----------------------------------------------------------------------
   a1b2c3d4e5f6     | No Storage         | RUNNING   |     15m 23s
   f6e5d4c3b2a1     | Peter Storage      | TERMINATED| 2h  45m 12s
      💀 Reason: terminated

📈 SPOT INSTANCE LIFETIME REPORT
================================================================================
🏆 RESULTS SUMMARY:
   Total instances: 4
   Terminated: 3
   Still active: 1

⏱️ TERMINATION STATS:
   Average lifetime: 3h 22m 15s
   Shortest lived: 1h 15m 30s (Large Disk)
   Longest lived: 6h 45m 20s (Storage + Large Disk)
```

## Understanding Results

### Lifetime Metrics
- **Average lifetime**: Mean survival time for terminated instances
- **Shortest/Longest lived**: Range of lifetimes observed
- **Configuration comparison**: Which setups lasted longest

### Termination Reasons
- **terminated**: Normal spot termination (capacity needed elsewhere)
- **error**: Instance failed due to technical issues
- **stopping**: Instance in shutdown process

### Storage Impact
- **Network storage**: May provide better persistence/recovery
- **Large disk**: More local storage for caching
- **Hybrid approach**: Balance of network + local storage

## Cost Analysis

### Pricing Considerations
- Spot instances ~80% cheaper than on-demand
- Network storage adds ~$0.15/GB/month
- Container disk included in instance pricing
- Data transfer costs for network storage

### ROI Calculation
```
Savings = (On-demand price - Spot price) × Runtime hours
Storage cost = Volume size GB × $0.15 × (Runtime hours / 720)
Net savings = Savings - Storage cost - Interruption overhead
```

## Production Recommendations

### For Long-running Tasks (>4 hours)
- Use **Storage + Large Disk** configuration
- Implement checkpointing every 30 minutes
- Budget for 2-3 restarts per day

### For Short Tasks (<2 hours)
- Use **No Storage** for maximum cost savings
- Design for single-run completion
- Implement rapid startup (< 5 minutes)

### For Batch Processing
- Use **Peter Storage** for data persistence
- Implement queue-based task distribution
- Design for graceful interruption handling

## Advanced Usage

### Custom Configurations
Modify the `storage_configs` array in the script to test different setups:

```python
storage_configs = [
    {
        "name": "Custom Config",
        "storage_name": "MyStorage",
        "disk_gb": 100,
        "description": "Custom test configuration"
    }
]
```

### Extended Monitoring
Change monitoring duration:
```python
instances = tracker.monitor_instances(instances, max_hours=48)  # 48 hour test
```

### Different GPU Types
Modify GPU selection:
```python
if "A100" in gpu.get("displayName", ""):  # Test A100 spot instances
```

## Data Export

Results are automatically saved to timestamped JSON files:
- `spot_lifetime_report_YYYYMMDD_HHMMSS.json`
- Contains detailed instance data, timings, configurations
- Import into analysis tools (Excel, Python, R)

## Troubleshooting

### No Instances Launched
- Check RunPod API key validity
- Verify RTX 4090 availability in your regions
- Ensure sufficient account credits

### API Errors
- Network connectivity to RunPod API
- Rate limiting (wait and retry)
- Account permissions for spot instances

### Monitoring Issues
- Instance status polling failures
- Network interruptions during monitoring
- RunPod API maintenance windows

## Safety Notes

⚠️ **Cost Warning**: This script launches 4 GPU instances simultaneously. Monitor your RunPod credits and set appropriate limits.

⚠️ **Resource Usage**: Spot instances consume credits even when idle. The script includes automatic cleanup, but manual monitoring is recommended.

⚠️ **Data Loss**: Spot instances can be terminated without warning. Never store critical data only on instance storage.

## Contributing

To extend the script:
1. Add new storage configurations to test
2. Implement additional metrics collection
3. Add support for different GPU types
4. Enhance reporting and visualization

## Related Tools

- `check_current_workers.py` - Monitor active workers
- `terminate_single_worker.py` - Manual instance cleanup
- `view_logs_dashboard.py` - Instance logging analysis