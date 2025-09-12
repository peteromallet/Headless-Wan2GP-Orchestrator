#!/usr/bin/env python3
"""
Runpod client for the GPU worker orchestrator.
Handles spawning and terminating GPU workers on Runpod infrastructure.
Based on the runpod_repo_setup_agent codebase patterns.
"""
import os
import time
import json
import requests
import paramiko
from dotenv import load_dotenv
import runpod
import logging
from typing import Optional, Dict, Any
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------
# Helper Functions & Classes
# ---------------------------

def get_network_volumes(api_key: str):
    """Return a list of your RunPod network volumes."""
    runpod.api_key = api_key
    try:
        # Try using the SDK's get_network_volumes method if available
        if hasattr(runpod, 'get_network_volumes'):
            volumes = runpod.get_network_volumes()
            return volumes if isinstance(volumes, list) else []
        
        # Otherwise try the REST API with different endpoints
        endpoints = [
            "https://api.runpod.io/v1/networkvolumes",
            "https://api.runpod.io/graphql",  # GraphQL endpoint might be needed
        ]
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        for url in endpoints:
            try:
                if "graphql" in url:
                    # Try GraphQL query for network volumes
                    query = """
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
                    """
                    response = requests.post(url, json={"query": query}, headers=headers, timeout=30)
                else:
                    response = requests.get(url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Handle GraphQL response
                    if "data" in data and "myself" in data["data"]:
                        return data["data"]["myself"].get("networkVolumes", [])
                    
                    # Handle REST response
                    if isinstance(data, list):
                        return data
                        
            except Exception:
                continue
        
        logger.warning("Could not fetch network volumes from any endpoint")
        return []
        
    except Exception as e:
        logger.error(f"Error fetching network volumes: {e}")
        return []


def find_gpu_type(gpu_display_name: str, api_key: str):
    """Find a GPU type by its display name (or ID) and ensure it's available."""
    runpod.api_key = api_key
    try:
        gpus = runpod.get_gpus()
    except Exception as e:
        logger.error(f"Error retrieving GPU list from RunPod: {e}")
        return None

    for gpu in gpus:
        if gpu_display_name in (gpu.get("displayName"), gpu.get("id")):
            return gpu
    return None


def create_pod_and_wait(api_key: str, gpu_type_id: str, image_name: str, name: str = "worker-pod", 
                       network_volume_id: str | None = None, volume_mount_path: str = "/workspace", 
                       disk_in_gb: int = 20, container_disk_in_gb: int = 10, wait_timeout: int = 600, 
                       public_key_string: str | None = None, env_vars: Dict[str, str] = None):
    """Create a RunPod pod and wait until it is running."""
    runpod.api_key = api_key

    params = {
        "name": name,
        "image_name": image_name,
        "gpu_type_id": gpu_type_id,
        "gpu_count": 1,
        "cloud_type": "SECURE",
        "volume_in_gb": disk_in_gb,
        "container_disk_in_gb": container_disk_in_gb,
        "ports": "22/tcp",
    }

    if network_volume_id:
        params["network_volume_id"] = network_volume_id
        params["volume_mount_path"] = volume_mount_path

    # Environment variables for the worker
    pod_env = {}
    if env_vars:
        pod_env.update(env_vars)
    
    # Inject PUBLIC_KEY env var if provided so the pod image adds the key to ~/.ssh/authorized_keys
    if public_key_string:
        pod_env["PUBLIC_KEY"] = public_key_string

    if pod_env:
        params["env"] = pod_env

    try:
        pod = runpod.create_pod(**params)
    except Exception as e:
        logger.error(f"Error creating pod: {e}")
        return None

    # Handle nested response structure
    if isinstance(pod, dict) and 'data' in pod:
        pod_data = pod['data'].get('podFindAndDeployOnDemand', {})
        pod_id = pod_data.get('id')
    else:
        pod_id = pod.get("id")
    
    if not pod_id:
        logger.error("Pod creation failed (no pod ID returned)")
        return None

    logger.info(f"Pod created with ID: {pod_id}")
    
    # Return immediately with the pod ID so we can track it
    # The orchestrator will handle monitoring the pod status
    return {
        'id': pod_id,
        'desiredStatus': 'PROVISIONING',
        'name': name,
        'gpu_type_id': gpu_type_id,
        'created': True
    }


def get_pod_ssh_details(pod_id: str, api_key: str):
    """Return SSH connection details (ip, port, password) for a running pod."""
    runpod.api_key = api_key
    try:
        status = runpod.get_pod(pod_id)
    except Exception as e:
        logger.error(f"Error fetching pod details: {e}")
        return None

    # Handle None response (pod might be terminated)
    if status is None:
        logger.error(f"Pod {pod_id} not found or terminated")
        return None
    
    # Ensure status is a dict
    if not isinstance(status, dict):
        logger.error(f"Unexpected pod status type for {pod_id}: {type(status)}")
        return None

    runtime = status.get("runtime", {})
    if runtime is None:
        runtime = {}
    
    for port_map in runtime.get("ports", []):
        if port_map.get("privatePort") == 22:
            return {
                "ip": port_map.get("ip"),
                "port": port_map.get("publicPort"),
                "password": runtime.get("sshPassword", "runpod"),
            }
    return None


def terminate_pod(pod_id: str, api_key: str):
    """Terminate a RunPod pod to stop billing."""
    runpod.api_key = api_key
    try:
        runpod.terminate_pod(pod_id)
    except Exception as e:
        logger.error(f"Error terminating pod: {e}")


class SSHClient:
    """Minimal paramiko wrapper for executing commands over SSH."""

    def __init__(self, hostname: str, port: int, username: str, password: str | None = None, 
                 private_key_path: str | None = None, timeout: int = 10):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.private_key_path = private_key_path
        self.timeout = timeout
        self.client: paramiko.SSHClient | None = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }

        # Prefer key authentication if a key path is provided and exists
        if self.private_key_path and os.path.exists(os.path.expanduser(self.private_key_path)):
            expanded_key = os.path.expanduser(self.private_key_path)
            try:
                pkey = paramiko.RSAKey.from_private_key_file(expanded_key)
            except Exception as e:
                raise RuntimeError(f"Failed to load private key {expanded_key}: {e}") from e
            connect_kwargs["pkey"] = pkey
        else:
            connect_kwargs["password"] = self.password

        self.client.connect(**connect_kwargs)

    def execute_command(self, command: str, timeout: int = 600):
        if not self.client:
            raise RuntimeError("SSH client not connected. Call connect() first.")
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode()
        err = stderr.read().decode()
        return exit_status, out, err

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None

# ---------------------------
# End helper section
# ---------------------------


class RunpodClient:
    """Client for managing Runpod GPU instances using the exact patterns from the user's example."""
    
    def __init__(self, api_key: str):
        """Initialize Runpod client with API key."""
        self.api_key = api_key
        runpod.api_key = api_key
        
        # Configuration from environment (matching user's example)
        self.gpu_type = os.getenv("RUNPOD_GPU_TYPE", "NVIDIA GeForce RTX 4090")
        self.worker_image = os.getenv("RUNPOD_WORKER_IMAGE", "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04")
        self.storage_name = os.getenv("RUNPOD_STORAGE_NAME")  # Like "Peter" in your example
        self.volume_mount_path = os.getenv("RUNPOD_VOLUME_MOUNT_PATH", "/workspace")
        self.disk_size_gb = int(os.getenv("RUNPOD_DISK_SIZE_GB", "20"))
        self.container_disk_gb = int(os.getenv("RUNPOD_CONTAINER_DISK_GB", "10"))
        
        # SSH configuration for worker access (both keys like user's example)
        self.ssh_public_key_path = os.getenv("RUNPOD_SSH_PUBLIC_KEY_PATH")
        self.ssh_private_key_path = os.getenv("RUNPOD_SSH_PRIVATE_KEY_PATH")
        
        # Cache storage volume ID (looked up by name)
        self._storage_volume_id = None
        
        # Cache GPU type info
        self._gpu_type_info = None
    
    def _get_storage_volume_id(self) -> Optional[str]:
        """Get storage volume ID by name, cached."""
        if self._storage_volume_id is not None:
            return self._storage_volume_id
        
        if not self.storage_name:
            logger.info("No storage name configured")
            return None
        
        logger.info(f"Looking up storage volume: {self.storage_name}")
        volumes = get_network_volumes(self.api_key)
        
        for vol in volumes:
            if vol.get('name') == self.storage_name:
                self._storage_volume_id = vol.get('id')
                dc_info = vol.get('dataCenter', {})
                logger.info(f"Found storage '{self.storage_name}' (ID: {self._storage_volume_id})")
                logger.info(f"  Size: {vol.get('size')}GB")
                logger.info(f"  Location: {dc_info.get('name')} ({dc_info.get('location')})")
                return self._storage_volume_id
        
        logger.warning(f"Storage '{self.storage_name}' not found. Available volumes:")
        for vol in volumes:
            dc_info = vol.get('dataCenter', {})
            logger.warning(f"  • {vol.get('name')} (ID: {vol.get('id')}) - {vol.get('size')}GB")
            logger.warning(f"    Location: {dc_info.get('name')} ({dc_info.get('location')})")
        
        return None
    
    def _get_gpu_type_info(self) -> Optional[Dict[str, Any]]:
        """Get GPU type information, cached."""
        if self._gpu_type_info is not None:
            return self._gpu_type_info
            
        self._gpu_type_info = find_gpu_type(self.gpu_type, self.api_key)
        if self._gpu_type_info:
            logger.info(f"Found GPU type: {self._gpu_type_info.get('displayName')} (ID: {self._gpu_type_info.get('id')})")
        else:
            logger.error(f"GPU type '{self.gpu_type}' not found")
        
        return self._gpu_type_info
    
    def _get_public_key_content(self) -> Optional[str]:
        """Get SSH public key content from environment variable or file path."""
        # First try to get from environment variable (for Railway deployment)
        public_key_env = os.getenv("RUNPOD_SSH_PUBLIC_KEY")
        if public_key_env:
            logger.info(f"[SSH_DEBUG] Using SSH public key from RUNPOD_SSH_PUBLIC_KEY environment variable")
            logger.info(f"[SSH_DEBUG] Key preview: {public_key_env[:50]}...{public_key_env[-20:]}")
            return public_key_env.strip()
        
        # Fallback to file path (for local development)
        if not self.ssh_public_key_path:
            logger.warning("No SSH public key configured. Set RUNPOD_SSH_PUBLIC_KEY environment variable or RUNPOD_SSH_PUBLIC_KEY_PATH")
            return None
            
        pub_path = os.path.expanduser(self.ssh_public_key_path)
        if not os.path.exists(pub_path):
            logger.warning(f"SSH public key not found at {pub_path}")
            return None
            
        try:
            with open(pub_path, "r", encoding="utf-8") as f:
                logger.debug(f"Using SSH public key from file: {pub_path}")
                return f.read().strip()
        except Exception as e:
            logger.error(f"Error reading SSH public key: {e}")
            return None
    
    def spawn_worker(self, worker_id: str, worker_env: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """
        Spawn a new GPU worker on Runpod using the exact patterns from user's example.
        """
        gpu_info = self._get_gpu_type_info()
        if not gpu_info:
            logger.error("Cannot spawn worker: GPU type not available")
            return None
        
        # Prepare environment variables for the worker
        env_vars = {
            "WORKER_ID": worker_id,
            "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
            "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY", ""),
            "REPLICATE_API_TOKEN": os.getenv("REPLICATE_API_TOKEN", ""),
        }
        
        # Merge in any additional environment variables
        if worker_env:
            env_vars.update(worker_env)
        
        # Get public key content for injection (like user's example)
        public_key_content = self._get_public_key_content()
        if public_key_content:
            logger.info(f"[SSH_DEBUG] Will inject SSH public key into worker {worker_id}")
        else:
            logger.error(f"[SSH_DEBUG] No SSH public key available for worker {worker_id} - authentication will fail!")
        
        try:
            logger.info(f"Creating worker pod: {worker_id}")
            
            # Get storage volume ID by name lookup (like user's example)
            storage_volume_id = self._get_storage_volume_id()
            
            # Use the exact create_pod_and_wait pattern from user's example
            pod_details = create_pod_and_wait(
                api_key=self.api_key,
                gpu_type_id=gpu_info["id"],
                image_name=self.worker_image,
                name=worker_id,
                network_volume_id=storage_volume_id,
                volume_mount_path=self.volume_mount_path,  # Always provide mount path
                disk_in_gb=self.disk_size_gb,
                container_disk_in_gb=self.container_disk_gb,
                public_key_string=public_key_content,
                env_vars=env_vars,
            )
            
            if not pod_details or 'id' not in pod_details:
                logger.error(f"Failed to create pod for worker {worker_id}")
                return None
            
            pod_id = pod_details['id']
            logger.info(f"Worker pod created successfully: {worker_id} -> {pod_id}")
            
            # Return pod details immediately for tracking
            result = {
                "worker_id": worker_id,
                "runpod_id": pod_id,
                "gpu_type": gpu_info["displayName"],
                "status": "spawning",  # Worker is spawning, orchestrator will monitor it
                "created_at": time.time(),
                "pod_details": pod_details,
            }
            
            logger.info(f"Worker {worker_id} pod created, will be initialized once it's running")
            
            # Don't wait for SSH or initialization here - let the orchestrator handle that
            # This prevents timeouts and ensures we track all created pods
            
            return result
            
        except Exception as e:
            logger.error(f"Error creating pod for worker {worker_id}: {e}")
            return None
    

    
    def start_worker_process(self, runpod_id: str, worker_id: str) -> bool:
        """
        Start the actual worker process in the background.
        This runs the worker.py script with Supabase configuration.
        """
        # Ensure environment variables are loaded
        from dotenv import load_dotenv
        load_dotenv()
        
        # Get Supabase credentials from environment
        supabase_url = os.getenv("SUPABASE_URL", "")
        supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        
        logger.info(f"Starting worker process on {runpod_id} with worker_id: {worker_id}")
        logger.debug(f"Environment: SUPABASE_URL={supabase_url}, SERVICE_KEY={'***' if supabase_service_key else 'EMPTY'}")
        
        # Create a robust startup script that handles all the steps
        startup_script = f"""#!/bin/bash
set -e  # Exit on any error

# Set environment variables
export WORKER_ID="{worker_id}"
export SUPABASE_URL="{supabase_url}"
export SUPABASE_ANON_KEY="{supabase_anon_key}"
export SUPABASE_SERVICE_ROLE_KEY="{supabase_service_key}"
export REPLICATE_API_TOKEN="{os.getenv('REPLICATE_API_TOKEN', '')}"

# Change to workspace directory
cd /workspace/Headless-Wan2GP/

# Create logs directory
mkdir -p logs

# Start debug logging
echo "=== WORKER STARTUP DEBUG ===" > logs/{worker_id}.log 2>&1
echo "Timestamp: $(date)" >> logs/{worker_id}.log 2>&1
echo "Worker ID: $WORKER_ID" >> logs/{worker_id}.log 2>&1
echo "Working directory: $(pwd)" >> logs/{worker_id}.log 2>&1

# Try git pull (but don't fail if it times out)
echo "=== GIT PULL ===" >> logs/{worker_id}.log 2>&1
timeout 30 git pull origin main >> logs/{worker_id}.log 2>&1 || echo "Git pull failed or timed out, continuing with existing code" >> logs/{worker_id}.log 2>&1

# Install essential dependencies if needed (quietly)
echo "=== INSTALLING DEPENDENCIES ===" >> logs/{worker_id}.log 2>&1

# Update package list first
echo "Updating package list..." >> logs/{worker_id}.log 2>&1
if apt-get update -qq >> logs/{worker_id}.log 2>&1; then
    echo "Package list updated successfully" >> logs/{worker_id}.log 2>&1
else
    echo "WARNING: Package list update failed" >> logs/{worker_id}.log 2>&1
fi

# Install dependencies with proper error checking
echo "Installing python3.10-venv ffmpeg git curl wget..." >> logs/{worker_id}.log 2>&1
if apt-get install -y -qq python3.10-venv ffmpeg git curl wget >> logs/{worker_id}.log 2>&1; then
    echo "Dependencies installed successfully" >> logs/{worker_id}.log 2>&1
else
    echo "ERROR: Dependency installation failed!" >> logs/{worker_id}.log 2>&1
    echo "Attempting to continue, but worker may not function correctly" >> logs/{worker_id}.log 2>&1
fi

# Verify critical dependencies
echo "=== VERIFYING DEPENDENCIES ===" >> logs/{worker_id}.log 2>&1
if command -v ffmpeg >/dev/null 2>&1; then
    echo "✅ FFmpeg found: $(which ffmpeg)" >> logs/{worker_id}.log 2>&1
    echo "✅ FFmpeg version: $(ffmpeg -version 2>&1 | head -1)" >> logs/{worker_id}.log 2>&1
else
    echo "❌ ERROR: FFmpeg not found! Worker cannot process videos" >> logs/{worker_id}.log 2>&1
fi

if command -v git >/dev/null 2>&1; then
    echo "✅ Git found: $(which git)" >> logs/{worker_id}.log 2>&1
else
    echo "❌ WARNING: Git not found!" >> logs/{worker_id}.log 2>&1
fi

if command -v python3.10 >/dev/null 2>&1; then
    echo "✅ Python 3.10 found: $(which python3.10)" >> logs/{worker_id}.log 2>&1
else
    echo "❌ WARNING: Python 3.10 not found!" >> logs/{worker_id}.log 2>&1
fi

# Activate virtual environment
echo "=== ACTIVATING VIRTUAL ENV ===" >> logs/{worker_id}.log 2>&1
source venv/bin/activate
echo "Virtual env activated: $VIRTUAL_ENV" >> logs/{worker_id}.log 2>&1
echo "Python path: $(which python)" >> logs/{worker_id}.log 2>&1
echo "Python version: $(python --version)" >> logs/{worker_id}.log 2>&1

# Verify worker.py exists
echo "=== CHECKING FILES ===" >> logs/{worker_id}.log 2>&1
ls -la worker.py >> logs/{worker_id}.log 2>&1

# Test Python import
echo "=== TESTING PYTHON ===" >> logs/{worker_id}.log 2>&1
timeout 10 python -c "import sys; print('Python can start'); print('sys.path:', sys.path[:3])" >> logs/{worker_id}.log 2>&1 || echo "Python import test failed" >> logs/{worker_id}.log 2>&1

# Start the actual worker process
echo "=== STARTING MAIN WORKER ===" >> logs/{worker_id}.log 2>&1
echo "Command: python worker.py --db-type supabase --supabase-url $SUPABASE_URL --supabase-anon-key $SUPABASE_ANON_KEY --supabase-access-token $SUPABASE_SERVICE_ROLE_KEY --worker $WORKER_ID" >> logs/{worker_id}.log 2>&1

# Start worker in background
nohup python worker.py --db-type supabase \\
  --supabase-url "$SUPABASE_URL" \\
  --supabase-anon-key "$SUPABASE_ANON_KEY" \\
  --supabase-access-token "$SUPABASE_SERVICE_ROLE_KEY" \\
  --worker "$WORKER_ID" >> logs/{worker_id}.log 2>&1 &

echo "Worker process started with PID: $!" >> logs/{worker_id}.log 2>&1
echo "Worker startup completed successfully"
"""

        # Write the script to a temporary file and execute it
        script_path = f"/tmp/start_worker_{worker_id}.sh"
        
        # First, create the script file
        create_script_command = f"cat > {script_path} << 'SCRIPT_EOF'\n{startup_script}\nSCRIPT_EOF"
        
        result = self.execute_command_on_worker(runpod_id, create_script_command, timeout=10)
        if not result or result[0] != 0:
            logger.error(f"Failed to create startup script for worker {worker_id}")
            return False
        
        # Make the script executable and run it
        execute_script_command = f"chmod +x {script_path} && {script_path}"
        
        result = self.execute_command_on_worker(runpod_id, execute_script_command, timeout=60)
        
        if result:
            exit_code, stdout, stderr = result
            logger.info(f"Worker startup script executed: {stdout.strip() if stdout else 'script completed'}")
            if stderr.strip():
                logger.warning(f"Worker startup stderr: {stderr.strip()}")
            return True
        else:
            logger.error(f"Failed to execute worker startup script")
            return False
    
    def terminate_worker(self, runpod_id: str) -> bool:
        """Terminate a worker pod on Runpod."""
        try:
            logger.info(f"Terminating pod: {runpod_id}")
            terminate_pod(runpod_id, self.api_key)
            logger.info(f"Pod terminated: {runpod_id}")
            return True
        except Exception as e:
            logger.error(f"Error terminating pod {runpod_id}: {e}")
            return False
    
    def get_pod_status(self, runpod_id: str) -> Optional[Dict[str, Any]]:
        """Get the current status of a pod."""
        runpod.api_key = self.api_key
        try:
            status = runpod.get_pod(runpod_id)
            if not status:
                return None
            
            # Extract key status information
            runtime = status.get("runtime", {})
            return {
                "runpod_id": runpod_id,
                "desired_status": status.get("desiredStatus"),
                "actual_status": status.get("actualStatus"),
                "ip": runtime.get("ip"),
                "ports": runtime.get("ports", []),
                "ssh_password": runtime.get("sshPassword"),
                "created_at": status.get("createdAt"),
                "last_status_change": status.get("lastStatusChange"),
                "uptime_seconds": runtime.get("uptimeInSeconds", 0),
                "cost_per_hr": status.get("costPerHr"),
            }
        except Exception as e:
            logger.error(f"Error getting pod status for {runpod_id}: {e}")
            return None
    
    def get_ssh_client(self, runpod_id: str) -> Optional[SSHClient]:
        """Get an SSH client for connecting to a worker pod."""
        ssh_details = get_pod_ssh_details(runpod_id, self.api_key)
        if not ssh_details:
            logger.error(f"Could not get SSH details for pod {runpod_id}")
            return None
        
        # Prefer private key if available, fallback to password
        if self.ssh_private_key_path and os.path.exists(os.path.expanduser(self.ssh_private_key_path)):
            return SSHClient(
                hostname=ssh_details['ip'],
                port=ssh_details['port'],
                username='root',
                private_key_path=self.ssh_private_key_path,
            )
        else:
            return SSHClient(
                hostname=ssh_details['ip'],
                port=ssh_details['port'],
                username='root',
                password=ssh_details.get('password', 'runpod'),
            )
    
    def execute_command_on_worker(self, runpod_id: str, command: str, timeout: int = 600) -> Optional[tuple]:
        """Execute a command on a worker via SSH."""
        ssh_client = self.get_ssh_client(runpod_id)
        if not ssh_client:
            return None
        
        try:
            ssh_client.connect()
            exit_code, stdout, stderr = ssh_client.execute_command(command, timeout)
            return exit_code, stdout, stderr
        except Exception as e:
            logger.error(f"Error executing command on {runpod_id}: {e}")
            return None
        finally:
            ssh_client.disconnect()
    
    def get_network_volumes(self) -> list:
        """Get list of available network volumes."""
        return get_network_volumes(self.api_key)
    
    def generate_worker_id(self) -> str:
        """Generate a unique worker ID for Runpod."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"gpu-{timestamp}-{str(uuid.uuid4())[:8]}"

    def check_and_initialize_worker(self, worker_id: str, runpod_id: str) -> Dict[str, Any]:
        """
        Check if a spawning worker is ready for worker process startup.
        Returns status update for the worker.
        """
        try:
            # Check pod status
            runpod.api_key = self.api_key
            pod_status = runpod.get_pod(runpod_id)
            
            # More robust None checking
            if pod_status is None:
                logger.warning(f"Pod {runpod_id} status returned None (pod may be provisioning)")
                return {"status": "spawning", "message": "Pod status not available yet"}
            
            if not isinstance(pod_status, dict):
                logger.error(f"Pod {runpod_id} status returned unexpected type: {type(pod_status)}")
                return {"status": "error", "error": f"Invalid pod status response: {type(pod_status)}"}
            
            desired_status = pod_status.get("desiredStatus")
            runtime = pod_status.get("runtime", {})
            
            # Ensure runtime is a dict
            if runtime is None:
                runtime = {}
            elif not isinstance(runtime, dict):
                logger.warning(f"Pod {runpod_id} runtime is not a dict: {type(runtime)}")
                runtime = {}
            
            # Check if pod is running and has SSH access
            if desired_status == "RUNNING" and runtime.get("ports"):
                logger.info(f"Pod {runpod_id} is running, checking SSH access...")
                
                # Get SSH details
                ssh_details = get_pod_ssh_details(runpod_id, self.api_key)
                
                if ssh_details:
                    logger.info(f"SSH available for {worker_id}: {ssh_details['ip']}:{ssh_details['port']}")
                    
                    # Worker is ready for start_worker_process()
                    return {
                        "status": "active",
                        "ssh_details": ssh_details,
                        "ready": True
                    }
                else:
                    # Pod is running but no SSH yet
                    return {"status": "spawning", "message": "Waiting for SSH access"}
                    
            elif desired_status in ["FAILED", "TERMINATED"]:
                return {"status": "error", "error": f"Pod {desired_status.lower()}"}
            else:
                # Still provisioning
                return {"status": "spawning", "message": f"Pod status: {desired_status}"}
                
        except Exception as e:
            logger.error(f"Error checking worker {worker_id} (pod {runpod_id}): {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"status": "error", "error": f"Exception in worker check: {str(e)}"}


# Convenience functions for use in orchestrator
def create_runpod_client() -> RunpodClient:
    """Create a Runpod client using environment configuration."""
    api_key = os.getenv("RUNPOD_API_KEY")
    if not api_key:
        raise ValueError("RUNPOD_API_KEY environment variable is required")
    
    return RunpodClient(api_key)


async def spawn_runpod_gpu(worker_id: str) -> Optional[str]:
    """
    Spawn a GPU worker on Runpod.
    
    Args:
        worker_id: Unique identifier for the worker
        
    Returns:
        Runpod pod ID if successful, None otherwise
    """
    client = create_runpod_client()
    result = client.spawn_worker(worker_id)
    
    if result:
        return result["runpod_id"]
    return None


async def terminate_runpod_gpu(runpod_id: str) -> bool:
    """
    Terminate a GPU worker on Runpod.
    
    Args:
        runpod_id: Runpod pod ID to terminate
        
    Returns:
        True if successful, False otherwise
    """
    client = create_runpod_client()
    return client.terminate_worker(runpod_id)


async def get_runpod_status(runpod_id: str) -> Optional[Dict[str, Any]]:
    """
    Get status of a Runpod GPU worker.
    
    Args:
        runpod_id: Runpod pod ID to check
        
    Returns:
        Status information or None if error
    """
    client = create_runpod_client()
    return client.get_pod_status(runpod_id) 