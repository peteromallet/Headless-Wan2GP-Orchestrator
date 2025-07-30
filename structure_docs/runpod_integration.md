# Runpod API Integration

This document covers how the orchestrator integrates with Runpod's GPU cloud platform through `runpod_client.py`.

## RunpodClient Class

The main interface for Runpod operations, configured via environment variables.

### Configuration Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUNPOD_API_KEY` | - | **Required** Personal API key |
| `RUNPOD_GPU_TYPE` | `"NVIDIA GeForce RTX 4090"` | GPU type to spawn |
| `RUNPOD_WORKER_IMAGE` | `"runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"` | Container image |
| `RUNPOD_STORAGE_NAME` | - | Network volume name (e.g., "Peter") |
| `RUNPOD_VOLUME_MOUNT_PATH` | `"/workspace"` | Where to mount storage |
| `RUNPOD_DISK_SIZE_GB` | `20` | Temporary pod storage |
| `RUNPOD_CONTAINER_DISK_GB` | `10` | Container disk space |
| `RUNPOD_SSH_PUBLIC_KEY_PATH` | - | SSH public key file path |
| `RUNPOD_SSH_PRIVATE_KEY_PATH` | - | SSH private key file path |

## Core Methods

### Worker Lifecycle

#### `spawn_worker(worker_id: str, worker_env: Dict[str, str]) -> Dict[str, Any]`
Creates a new GPU pod and returns immediately for tracking.

**Process:**
1. Looks up GPU type by display name
2. Finds network storage volume by name
3. Injects environment variables (Supabase credentials)
4. Creates pod with SSH key injection
5. Returns pod details for orchestrator tracking

**Environment Variables Injected:**
```python
{
    "WORKER_ID": worker_id,
    "SUPABASE_URL": os.getenv("SUPABASE_URL"),
    "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
    "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY"),
    # Plus any custom worker_env
}
```

#### `check_and_initialize_worker(worker_id: str, runpod_id: str) -> Dict[str, Any]`
Monitors spawning worker and initializes when ready.

**Status Flow:**
- `{"status": "spawning"}` - Pod is still provisioning
- `{"status": "active", "ssh_details": {...}}` - Ready and initialized
- `{"status": "error", "error": "..."}` - Failed to start or initialize

**Initialization Steps:**
1. Verify storage mount (`ls -la /workspace`)
2. Check Headless-Wan2GP directory exists
3. Test GPU availability (`nvidia-smi`)
4. Verify Python installation

#### `start_worker_process(runpod_id: str, worker_id: str) -> bool`
Starts the Headless-Wan2GP worker process in background.

**Command Executed:**
```bash
cd /workspace/reigh/Headless-Wan2GP/ && \
(timeout 30 git pull origin main || echo "Git pull failed, continuing") && \
source venv/bin/activate && \
(apt-get update && apt-get install -y python3.10-venv ffmpeg || true) && \
nohup python headless.py --db-type supabase \
  --supabase-url {supabase_url} \
  --supabase-anon-key {supabase_anon_key} \
  --supabase-access-token {supabase_service_key} \
  --worker {worker_id} >/dev/null 2>&1 &
```

#### `terminate_worker(runpod_id: str) -> bool`
Terminates a pod to stop billing.

**API Call:** `runpod.terminate_pod(runpod_id)`

### SSH Management

#### `get_ssh_client(runpod_id: str) -> SSHClient`
Creates authenticated SSH connection to worker pod.

**Authentication Priority:**
1. Private key (if `RUNPOD_SSH_PRIVATE_KEY_PATH` exists)
2. Password (from pod SSH details, default "runpod")

#### `execute_command_on_worker(runpod_id: str, command: str, timeout: int) -> tuple`
Executes shell commands on worker via SSH.

**Returns:** `(exit_code, stdout, stderr)`

### Pod Management

#### `get_pod_status(runpod_id: str) -> Dict[str, Any]`
Gets current pod state from Runpod API.

**Returns:**
```python
{
    "runpod_id": "xyz123",
    "desired_status": "RUNNING|PROVISIONING|FAILED|TERMINATED",
    "actual_status": "RUNNING|STARTING|...",
    "ip": "1.2.3.4",
    "ports": [{"privatePort": 22, "publicPort": 12345, "ip": "1.2.3.4"}],
    "ssh_password": "runpod",
    "created_at": "2024-01-01T00:00:00Z",
    "uptime_seconds": 3600,
    "cost_per_hr": 0.50
}
```

## Helper Functions

### Storage & GPU Discovery

#### `get_network_volumes(api_key: str) -> List[Dict]`
Retrieves network storage volumes via REST API or GraphQL.

**GraphQL Query Used:**
```graphql
query {
    myself {
        networkVolumes {
            id
            name
            size
            dataCenterId
        }
    }
}
```

#### `find_gpu_type(gpu_display_name: str, api_key: str) -> Dict`
Finds GPU type by display name and checks availability.

**API Call:** `runpod.get_gpus()`

### Pod Creation

#### `create_pod_and_wait(...) -> Dict`
Low-level pod creation using Runpod SDK.

**Parameters:**
- `name` - Pod identifier (matches worker_id)
- `image_name` - Container image URL
- `gpu_type_id` - GPU type from discovery
- `gpu_count` - Always 1
- `cloud_type` - Always "SECURE"
- `volume_in_gb` - Temporary storage size
- `container_disk_in_gb` - Container storage
- `ports` - Always "22/tcp" for SSH
- `network_volume_id` - Storage volume (optional)
- `volume_mount_path` - Mount point (default "/workspace")
- `env` - Environment variables dict

**Returns:** Pod details with ID for tracking

## SSH Connection Class

### `SSHClient`
Paramiko wrapper for executing commands on pods.

**Features:**
- Supports both password and key authentication
- Auto-accepts host keys (pods are ephemeral)
- Configurable timeouts
- Automatic connection management

**Usage Pattern:**
```python
ssh_client = self.get_ssh_client(runpod_id)
ssh_client.connect()
exit_code, stdout, stderr = ssh_client.execute_command("nvidia-smi")
ssh_client.disconnect()
```

## Convenience Functions

For use in orchestrator control loop:

#### `create_runpod_client() -> RunpodClient`
Factory function using `RUNPOD_API_KEY` from environment.

#### `spawn_runpod_gpu(worker_id: str) -> str`
Async wrapper returning just the pod ID.

#### `terminate_runpod_gpu(runpod_id: str) -> bool`
Async wrapper for pod termination.

#### `get_runpod_status(runpod_id: str) -> Dict`
Async wrapper for pod status checks.

## Error Handling

### Common Failure Modes

1. **GPU Type Not Found**
   - Check `RUNPOD_GPU_TYPE` matches available GPU display names
   - Use `find_gpu_type()` to debug

2. **Storage Volume Missing**
   - Verify `RUNPOD_STORAGE_NAME` exists in account
   - Check network volume is in same datacenter as GPU

3. **SSH Connection Failures**
   - Pod may still be starting (check `desired_status`)
   - Verify SSH keys are correctly configured
   - Check firewall/network restrictions

4. **Worker Initialization Timeout**
   - Storage mount issues
   - Missing dependencies in container image
   - Network connectivity problems

### Logging

All operations logged at INFO level with structured data:
- Pod creation/termination events
- SSH connection attempts
- Command execution results
- Error details with full stack traces

## Integration Points

### Orchestrator Control Loop
The control loop calls:
- `spawn_worker()` during scale-up
- `check_and_initialize_worker()` for spawning workers
- `start_worker_process()` when auto-start enabled
- `terminate_worker()` during scale-down

### Database Integration
Worker metadata stored in `workers.metadata`:
```json
{
    "runpod_id": "xyz123",
    "ssh_details": {"ip": "1.2.3.4", "port": 12345}
}
```

### Environment Variable Flow
Orchestrator → RunpodClient → Pod Environment → Headless-Wan2GP 