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
                       public_key_string: str | None = None, env_vars: Dict[str, str] = None,
                       min_vcpu_count: int = 8, min_memory_in_gb: int = 32):
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
        "min_vcpu_count": min_vcpu_count,
        "min_memory_in_gb": min_memory_in_gb,
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
    
    # Try the RunPod SDK first
    try:
        status = runpod.get_pod(pod_id)
        if status and isinstance(status, dict):
            runtime = status.get("runtime", {})
            if runtime and isinstance(runtime, dict):
                for port_map in runtime.get("ports", []):
                    if port_map.get("privatePort") == 22:
                        return {
                            "ip": port_map.get("ip"),
                            "port": port_map.get("publicPort"),
                            "password": runtime.get("sshPassword", "runpod"),
                        }
    except Exception as e:
        logger.warning(f"RunPod SDK get_pod failed for {pod_id}: {e}")
    
    # Fallback to direct GraphQL API call
    try:
        import requests
        headers = {"Authorization": f"Bearer {api_key}"}
        query = f'''
        {{
          pod(input: {{podId: "{pod_id}"}}) {{
            id
            desiredStatus
            runtime {{
              ports {{
                ip
                publicPort
                privatePort
                type
              }}
            }}
          }}
        }}
        '''
        
        response = requests.post('https://api.runpod.io/graphql', 
                                json={'query': query}, 
                                headers=headers, 
                                timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            pod = data.get('data', {}).get('pod')
            if pod:
                runtime = pod.get('runtime', {})
                if runtime:
                    for port_map in runtime.get('ports', []):
                        if port_map.get('privatePort') == 22:
                            return {
                                "ip": port_map.get("ip"),
                                "port": port_map.get("publicPort"),
                                "password": "runpod",  # Default password
                            }
        else:
            logger.warning(f"GraphQL API failed for pod {pod_id}: {response.status_code}")
            
    except Exception as e:
        logger.warning(f"GraphQL fallback failed for pod {pod_id}: {e}")
    
    # If both methods fail, log the issue but don't error out completely
    logger.error(f"Could not get SSH details for pod {pod_id} via SDK or GraphQL API")
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
                 private_key_path: str | None = None, private_key_content: str | None = None, timeout: int = 10):
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.private_key_path = private_key_path
        self.private_key_content = private_key_content
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

        # Try private key from environment variable first (for Railway)
        if self.private_key_content:
            try:
                from io import StringIO
                # Try Ed25519 first (more common for new keys)
                try:
                    pkey = paramiko.Ed25519Key.from_private_key(StringIO(self.private_key_content))
                except Exception:
                    # Fallback to RSA
                    try:
                        pkey = paramiko.RSAKey.from_private_key(StringIO(self.private_key_content))
                    except Exception:
                        # Fallback to other key types
                        pkey = paramiko.ECDSAKey.from_private_key(StringIO(self.private_key_content))
                connect_kwargs["pkey"] = pkey
            except Exception as e:
                raise RuntimeError(f"Failed to load private key from environment variable: {e}") from e
        # Fallback to key file if path is provided and exists
        elif self.private_key_path and os.path.exists(os.path.expanduser(self.private_key_path)):
            expanded_key = os.path.expanduser(self.private_key_path)
            try:
                # Try different key types
                try:
                    pkey = paramiko.Ed25519Key.from_private_key_file(expanded_key)
                except Exception:
                    try:
                        pkey = paramiko.RSAKey.from_private_key_file(expanded_key)
                    except Exception:
                        pkey = paramiko.ECDSAKey.from_private_key_file(expanded_key)
                connect_kwargs["pkey"] = pkey
            except Exception as e:
                raise RuntimeError(f"Failed to load private key {expanded_key}: {e}") from e
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
        self.disk_size_gb = int(os.getenv("RUNPOD_DISK_SIZE_GB", "50"))
        self.container_disk_gb = int(os.getenv("RUNPOD_CONTAINER_DISK_GB", "50"))
        self.min_vcpu_count = int(os.getenv("RUNPOD_MIN_VCPU_COUNT", "8"))
        self.min_memory_gb = int(os.getenv("RUNPOD_MIN_MEMORY_GB", "32"))
        
        # Storage volume fallback: Try multiple storage volumes (may have different instance availability)
        # Hardcoded list of storage volumes to try in order
        self.storage_volumes = ["Peter", "EU-NO-1", "EU-CZ-1", "EUR-IS-1"]  # Add your storage volume names here
        
        # RAM tier fallback strategy: Try to get highest RAM instances, fall back if unavailable
        # Based on testing: 72GB is max available, then 60GB, 48GB, 32GB are common tiers
        self.ram_tiers_enabled = os.getenv("RUNPOD_RAM_TIER_FALLBACK", "true").lower() == "true"
        self.high_ram_tiers = [72, 60]  # Try high RAM (60+ GB) first across all storages
        self.low_ram_tiers = [48, 32, 16]  # Fallback to lower RAM if high RAM unavailable
        
        # SSH configuration for worker access (both keys like user's example)
        self.ssh_public_key_path = os.getenv("RUNPOD_SSH_PUBLIC_KEY_PATH")
        self.ssh_private_key_path = os.getenv("RUNPOD_SSH_PRIVATE_KEY_PATH")
        
        # Cache storage volume ID (looked up by name)
        self._storage_volume_id = None
        
        # Cache GPU type info
        self._gpu_type_info = None
    
    def _expand_network_volume(self, volume_id: str, new_size_gb: int) -> bool:
        """
        Expand a network volume to a new size using RunPod REST API.
        
        Args:
            volume_id: Network volume ID
            new_size_gb: New size in GB (must be larger than current)
        
        Returns:
            True if successful, False otherwise
        """
        import requests
        
        try:
            url = f"https://rest.runpod.io/v1/networkvolumes/{volume_id}"
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            data = {
                'size': new_size_gb
            }
            
            logger.info(f"📦 Expanding network volume {volume_id} to {new_size_gb} GB...")
            response = requests.patch(url, json=data, headers=headers)
            
            if response.status_code == 200:
                logger.info(f"✅ Successfully expanded volume to {new_size_gb} GB")
                return True
            else:
                logger.error(f"❌ Failed to expand volume: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error expanding volume: {e}")
            return False
    
    def _check_and_expand_storage(self, storage_name: str, volume_id: str, min_free_gb: int = 50) -> bool:
        """
        Check storage space and expand if needed.
        
        Args:
            storage_name: Name of the storage volume
            volume_id: Network volume ID
            min_free_gb: Minimum free space required in GB
        
        Returns:
            True if storage is adequate or was successfully expanded
        """
        try:
            # Get volume info
            volumes = get_network_volumes(self.api_key)
            volume_info = next((v for v in volumes if v.get('id') == volume_id), None)
            
            if not volume_info:
                logger.warning(f"⚠️  Could not find volume info for {volume_id}")
                return True  # Continue anyway
            
            current_size_gb = volume_info.get('size', 0)
            logger.info(f"📊 Storage '{storage_name}': {current_size_gb} GB total")
            
            # Try to check actual free space via a test pod's df command
            # For now, we'll use a heuristic: if total size < 100GB, expand it
            if current_size_gb < 100:
                new_size = current_size_gb + min_free_gb
                logger.warning(f"⚠️  Storage '{storage_name}' is only {current_size_gb} GB")
                logger.info(f"🔧 Expanding to {new_size} GB to ensure adequate space...")
                
                if self._expand_network_volume(volume_id, new_size):
                    logger.info(f"✅ Storage expansion successful")
                    return True
                else:
                    logger.warning(f"⚠️  Storage expansion failed, continuing anyway...")
                    return True  # Don't block worker spawn on expansion failure
            else:
                logger.info(f"✅ Storage '{storage_name}' has adequate capacity ({current_size_gb} GB)")
                return True
                
        except Exception as e:
            logger.warning(f"⚠️  Error checking storage space: {e}, continuing anyway...")
            return True  # Don't block worker spawn on storage check failure
    
    def _get_storage_volume_id(self, storage_name: Optional[str] = None) -> Optional[str]:
        """Get storage volume ID by name, optionally cached."""
        # If no storage name provided, use the configured default
        if storage_name is None:
            storage_name = self.storage_name
            # Return cached value for default storage
            if self._storage_volume_id is not None:
                return self._storage_volume_id
        
        if not storage_name:
            logger.info("No storage name configured")
            return None
        
        logger.info(f"Looking up storage volume: {storage_name}")
        volumes = get_network_volumes(self.api_key)
        
        for vol in volumes:
            if vol.get('name') == storage_name:
                volume_id = vol.get('id')
                dc_info = vol.get('dataCenter', {})
                logger.info(f"Found storage '{storage_name}' (ID: {volume_id})")
                logger.info(f"  Size: {vol.get('size')}GB")
                logger.info(f"  Location: {dc_info.get('name')} ({dc_info.get('location')})")
                
                # Cache only if this is the default storage
                if storage_name == self.storage_name:
                    self._storage_volume_id = volume_id
                
                return volume_id
        
        logger.warning(f"Storage '{storage_name}' not found. Available volumes:")
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
        Spawn a new GPU worker on Runpod using storage + RAM tiered fallback strategy.
        
        Strategy:
        1. Try all storage volumes with HIGH RAM (60+ GB) first
        2. If all fail, try all storage volumes with LOWER RAM tiers
        
        This maximizes chance of getting high-RAM instances across different datacenter locations.
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
        
        # Determine RAM tier strategy
        if self.ram_tiers_enabled:
            # Filter high/low RAM tiers based on configured minimum
            high_ram_tiers = [tier for tier in self.high_ram_tiers if tier >= self.min_memory_gb]
            low_ram_tiers = [tier for tier in self.low_ram_tiers if tier >= self.min_memory_gb]
            
            # If min is very high, might have no low tiers
            if not low_ram_tiers and not high_ram_tiers:
                low_ram_tiers = [self.min_memory_gb]
            
            logger.info(f"🎯 Storage + RAM tier fallback enabled")
            logger.info(f"   Phase 1 (High RAM): Try {high_ram_tiers} GB across storages: {self.storage_volumes}")
            logger.info(f"   Phase 2 (Low RAM): Try {low_ram_tiers} GB across storages if Phase 1 fails")
        else:
            # Simple mode: just try configured minimum
            high_ram_tiers = [self.min_memory_gb]
            low_ram_tiers = []
        
        # Phase 1: Try HIGH RAM across all storage volumes
        last_error = None
        for storage_name in self.storage_volumes:
            storage_volume_id = self._get_storage_volume_id(storage_name)
            if not storage_volume_id:
                logger.warning(f"⚠️  Storage '{storage_name}' not found, skipping...")
                continue
            
            # Check and expand storage if needed (adds +50GB if total < 100GB)
            self._check_and_expand_storage(storage_name, storage_volume_id, min_free_gb=50)
            
            for ram_tier in high_ram_tiers:
                try:
                    logger.info(f"🚀 Creating worker: {worker_id} (Storage: {storage_name}, RAM: {ram_tier} GB)")
                    
                    pod_details = create_pod_and_wait(
                        api_key=self.api_key,
                        gpu_type_id=gpu_info["id"],
                        image_name=self.worker_image,
                        name=worker_id,
                        network_volume_id=storage_volume_id,
                        volume_mount_path=self.volume_mount_path,
                        disk_in_gb=self.disk_size_gb,
                        container_disk_in_gb=self.container_disk_gb,
                        min_vcpu_count=self.min_vcpu_count,
                        min_memory_in_gb=ram_tier,
                        public_key_string=public_key_content,
                        env_vars=env_vars,
                    )
                    
                    if pod_details and 'id' in pod_details:
                        pod_id = pod_details['id']
                        logger.info(f"✅ SUCCESS: {worker_id} -> {pod_id} (Storage: {storage_name}, RAM: {ram_tier} GB)")
                        
                        return {
                            "worker_id": worker_id,
                            "runpod_id": pod_id,
                            "gpu_type": gpu_info["displayName"],
                            "status": "spawning",
                            "created_at": time.time(),
                            "pod_details": pod_details,
                            "ram_tier": ram_tier,
                            "storage_volume": storage_name,
                        }
                    else:
                        logger.warning(f"⚠️  Storage: {storage_name}, RAM: {ram_tier} GB - No ID returned")
                        last_error = "Pod creation returned no ID"
                        
                except Exception as e:
                    error_msg = str(e)
                    if "no longer any instances available" in error_msg.lower():
                        logger.warning(f"⚠️  Storage: {storage_name}, RAM: {ram_tier} GB - No instances available")
                        last_error = f"No instances available"
                    else:
                        logger.warning(f"⚠️  Storage: {storage_name}, RAM: {ram_tier} GB - {error_msg}")
                        last_error = error_msg
                    continue
        
        # Phase 2: If high RAM failed everywhere, try LOW RAM across all storage volumes
        if low_ram_tiers:
            logger.warning(f"⚠️  Phase 1 failed (high RAM not available). Trying Phase 2 (lower RAM tiers)...")
            
            for storage_name in self.storage_volumes:
                storage_volume_id = self._get_storage_volume_id(storage_name)
                if not storage_volume_id:
                    continue
                
                for ram_tier in low_ram_tiers:
                    try:
                        logger.info(f"🚀 Creating worker: {worker_id} (Storage: {storage_name}, RAM: {ram_tier} GB)")
                        
                        pod_details = create_pod_and_wait(
                            api_key=self.api_key,
                            gpu_type_id=gpu_info["id"],
                            image_name=self.worker_image,
                            name=worker_id,
                            network_volume_id=storage_volume_id,
                            volume_mount_path=self.volume_mount_path,
                            disk_in_gb=self.disk_size_gb,
                            container_disk_in_gb=self.container_disk_gb,
                            min_vcpu_count=self.min_vcpu_count,
                            min_memory_in_gb=ram_tier,
                            public_key_string=public_key_content,
                            env_vars=env_vars,
                        )
                        
                        if pod_details and 'id' in pod_details:
                            pod_id = pod_details['id']
                            logger.info(f"✅ SUCCESS: {worker_id} -> {pod_id} (Storage: {storage_name}, RAM: {ram_tier} GB)")
                            
                            return {
                                "worker_id": worker_id,
                                "runpod_id": pod_id,
                                "gpu_type": gpu_info["displayName"],
                                "status": "spawning",
                                "created_at": time.time(),
                                "pod_details": pod_details,
                                "ram_tier": ram_tier,
                                "storage_volume": storage_name,
                            }
                        else:
                            last_error = "Pod creation returned no ID"
                            
                    except Exception as e:
                        error_msg = str(e)
                        if "no longer any instances available" in error_msg.lower():
                            last_error = f"No instances available"
                        else:
                            last_error = error_msg
                        continue
        
        # All attempts failed
        logger.error(f"❌ Failed to create pod for worker {worker_id}")
        logger.error(f"   Tried storages: {self.storage_volumes}")
        logger.error(f"   Tried RAM tiers: {high_ram_tiers + low_ram_tiers}")
        logger.error(f"   Last error: {last_error}")
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
export SUPABASE_SERVICE_KEY="{supabase_service_key}"
export REPLICATE_API_TOKEN="{os.getenv('REPLICATE_API_TOKEN', '')}"

# Check if Headless-Wan2GP exists, install if not
if [ ! -d "/workspace/Headless-Wan2GP" ]; then
    echo "📦 Headless-Wan2GP not found, installing..."
    cd /workspace || exit 1
    
    echo "Step 1: Cloning repository..."
    git clone https://github.com/peteromallet/Headless-Wan2GP || exit 1
    
    cd Headless-Wan2GP || exit 1
    
    echo "Step 2: Installing system dependencies..."
    apt-get update && apt-get install -y python3.10-venv ffmpeg || exit 1
    
    echo "Step 3: Creating virtual environment..."
    python3.10 -m venv venv || exit 1
    
    echo "Step 4: Activating venv and installing PyTorch..."
    source venv/bin/activate || exit 1
    pip install --no-cache-dir torch==2.6.0 torchvision torchaudio -f https://download.pytorch.org/whl/cu124 || exit 1
    
    echo "Step 5: Installing Wan2GP requirements..."
    pip install --no-cache-dir -r Wan2GP/requirements.txt || exit 1
    
    echo "Step 6: Installing worker requirements..."
    pip install --no-cache-dir -r requirements.txt || exit 1
    
    echo "✅ Headless-Wan2GP installation complete"
else
    echo "✅ Headless-Wan2GP already exists at /workspace/Headless-Wan2GP"
    cd /workspace/Headless-Wan2GP || exit 1
    
    # Check if venv exists, if not create it and install dependencies
    if [ ! -d "venv" ] || [ ! -f "venv/bin/activate" ]; then
        echo "⚠️  Virtual environment missing or incomplete, rebuilding..."
        
        echo "Step 1: Installing system dependencies..."
        apt-get update && apt-get install -y python3.10-venv ffmpeg || exit 1
        
        echo "Step 2: Creating virtual environment..."
        python3.10 -m venv venv || exit 1
        
        echo "Step 3: Activating venv and installing PyTorch..."
        source venv/bin/activate || exit 1
        pip install --no-cache-dir torch==2.6.0 torchvision torchaudio -f https://download.pytorch.org/whl/cu124 || exit 1
        
        echo "Step 4: Installing Wan2GP requirements..."
        pip install --no-cache-dir -r Wan2GP/requirements.txt || exit 1
        
        echo "Step 5: Installing worker requirements..."
        pip install --no-cache-dir -r requirements.txt || exit 1
        
        echo "✅ Virtual environment rebuild complete"
    else
        echo "✅ Virtual environment exists and looks valid"
        echo "Activating existing virtual environment..."
        source venv/bin/activate || exit 1
        echo "✅ Virtual environment activated"
    fi
fi

# Create logs directory FIRST (critical for debugging)
mkdir -p /workspace/Headless-Wan2GP/logs

# Initialize comprehensive logging IMMEDIATELY with gpu_ prefix
LOG_FILE="/workspace/Headless-Wan2GP/logs/gpu_{worker_id}.log"
echo "=========================================" > "$LOG_FILE"
echo "🚀 WORKER STARTUP SCRIPT EXECUTION BEGIN" >> "$LOG_FILE"
echo "=========================================" >> "$LOG_FILE"
echo "Script PID: $$" >> "$LOG_FILE"
echo "Timestamp: $(date)" >> "$LOG_FILE"
echo "Initial PWD: $(pwd)" >> "$LOG_FILE"
echo "USER: $(whoami)" >> "$LOG_FILE"
echo "Shell: $0" >> "$LOG_FILE"
echo "Environment vars: $(env | wc -l) total" >> "$LOG_FILE"
echo "Log file: $LOG_FILE" >> "$LOG_FILE"

# Set up error handling with detailed error reporting
set -e  # Exit on any error
trap 'echo "❌ SCRIPT FAILED at line $LINENO with exit code $? at $(date)" >> "$LOG_FILE"; exit 1' ERR

echo "✅ Changing to workspace directory..." >> "$LOG_FILE"

# Change to workspace directory
cd /workspace/Headless-Wan2GP/

echo "✅ Now in directory: $(pwd)" >> "$LOG_FILE" 2>&1
echo "✅ Directory contents:" >> "$LOG_FILE" 2>&1
ls -la >> "$LOG_FILE" 2>&1

echo "Worker ID: $WORKER_ID" >> "$LOG_FILE" 2>&1

# Try git pull (but don't fail if it times out)
echo "=== GIT PULL ===" >> "$LOG_FILE" 2>&1

# Capture commit before pull
BEFORE_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
echo "Before commit: $BEFORE_COMMIT" >> "$LOG_FILE" 2>&1

# Perform pull with timeout and record exit status
timeout 30 git pull origin main >> "$LOG_FILE" 2>&1
GIT_PULL_EXIT=$?
if [ "$GIT_PULL_EXIT" -ne 0 ]; then
    echo "Git pull failed or timed out (exit $GIT_PULL_EXIT), continuing with existing code" >> "$LOG_FILE" 2>&1
fi

# Capture commit after pull to detect if code actually changed
AFTER_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
echo "After commit:  $AFTER_COMMIT" >> "$LOG_FILE" 2>&1

# Install essential dependencies if needed (quietly)
echo "=== INSTALLING DEPENDENCIES ===" >> $LOG_FILE 2>&1

# Update package list first
echo "Updating package list..." >> $LOG_FILE 2>&1
if apt-get update -qq >> $LOG_FILE 2>&1; then
    echo "Package list updated successfully" >> $LOG_FILE 2>&1
else
    echo "WARNING: Package list update failed" >> $LOG_FILE 2>&1
fi

# Install dependencies with proper error checking
echo "Installing python3.10-venv ffmpeg git curl wget..." >> $LOG_FILE 2>&1
if apt-get install -y -qq python3.10-venv ffmpeg git curl wget >> $LOG_FILE 2>&1; then
    echo "Dependencies installed successfully" >> $LOG_FILE 2>&1
else
    echo "ERROR: Dependency installation failed!" >> $LOG_FILE 2>&1
    echo "Attempting to continue, but worker may not function correctly" >> $LOG_FILE 2>&1
fi

# Verify critical dependencies
echo "=== VERIFYING DEPENDENCIES ===" >> $LOG_FILE 2>&1
if command -v ffmpeg >/dev/null 2>&1; then
    echo "✅ FFmpeg found: $(which ffmpeg)" >> $LOG_FILE 2>&1
    echo "✅ FFmpeg version: $(ffmpeg -version 2>&1 | head -1)" >> $LOG_FILE 2>&1
else
    echo "❌ ERROR: FFmpeg not found! Worker cannot process videos" >> $LOG_FILE 2>&1
fi

if command -v git >/dev/null 2>&1; then
    echo "✅ Git found: $(which git)" >> $LOG_FILE 2>&1
else
    echo "❌ WARNING: Git not found!" >> $LOG_FILE 2>&1
fi

if command -v python3.10 >/dev/null 2>&1; then
    echo "✅ Python 3.10 found: $(which python3.10)" >> $LOG_FILE 2>&1
else
    echo "❌ WARNING: Python 3.10 not found!" >> $LOG_FILE 2>&1
fi

# Activate virtual environment
echo "=== ACTIVATING VIRTUAL ENV ===" >> $LOG_FILE 2>&1
source venv/bin/activate
echo "Virtual env activated: $VIRTUAL_ENV" >> $LOG_FILE 2>&1
echo "Python path: $(which python)" >> $LOG_FILE 2>&1
echo "Python version: $(python --version)" >> $LOG_FILE 2>&1

# If repo updated successfully, update Python dependencies
echo "=== DEPENDENCY UPDATE (conditional) ===" >> $LOG_FILE 2>&1
if [ "${{GIT_PULL_EXIT:-1}}" -eq 0 ] && [ "$BEFORE_COMMIT" != "$AFTER_COMMIT" ]; then
    echo "Git updated code ($BEFORE_COMMIT -> $AFTER_COMMIT). Installing/upgrading Python deps..." >> $LOG_FILE 2>&1
    python -m pip install --upgrade -r requirements.txt >> $LOG_FILE 2>&1 || echo "WARNING: pip install failed" >> $LOG_FILE 2>&1
    # Also install subfolder requirements if present
    if [ -f Wan2GP/requirements.txt ]; then
        echo "Installing subfolder requirements from Wan2GP/requirements.txt" >> $LOG_FILE 2>&1
        python -m pip install --upgrade -r Wan2GP/requirements.txt >> $LOG_FILE 2>&1 || echo "WARNING: subfolder pip install failed" >> $LOG_FILE 2>&1
    else
        echo "No subfolder requirements found at Wan2GP/requirements.txt" >> $LOG_FILE 2>&1
    fi
else
    echo "No repo updates detected or git pull failed; skipping pip install" >> $LOG_FILE 2>&1
fi

# Verify worker.py exists
echo "=== CHECKING FILES ===" >> $LOG_FILE 2>&1
ls -la worker.py >> $LOG_FILE 2>&1

# Test Python import
echo "=== TESTING PYTHON ===" >> $LOG_FILE 2>&1
timeout 10 python -c "import sys; print('Python can start'); print('sys.path:', sys.path[:3])" >> $LOG_FILE 2>&1 || echo "Python import test failed" >> $LOG_FILE 2>&1

# Final pre-flight checks before starting worker
echo "=== PRE-FLIGHT CHECKS ===" >> $LOG_FILE 2>&1
echo "✅ Checking virtual environment..." >> $LOG_FILE 2>&1
echo "VIRTUAL_ENV: $VIRTUAL_ENV" >> $LOG_FILE 2>&1
echo "Python path: $(which python)" >> $LOG_FILE 2>&1
echo "Python version: $(python --version)" >> $LOG_FILE 2>&1

echo "✅ Checking worker.py..." >> $LOG_FILE 2>&1
if [ -f worker.py ]; then
    echo "worker.py exists ($(wc -l < worker.py) lines)" >> $LOG_FILE 2>&1
else
    echo "❌ ERROR: worker.py not found!" >> $LOG_FILE 2>&1
    exit 1
fi

echo "✅ Testing Python imports..." >> $LOG_FILE 2>&1
python -c "import sys, os; print('Python working, sys.path has', len(sys.path), 'entries')" >> $LOG_FILE 2>&1 || echo "❌ Python import test failed" >> $LOG_FILE 2>&1

echo "✅ Checking environment variables..." >> $LOG_FILE 2>&1
echo "WORKER_ID: $WORKER_ID" >> $LOG_FILE 2>&1
echo "SUPABASE_URL: ${{SUPABASE_URL:0:30}}..." >> $LOG_FILE 2>&1
echo "SUPABASE_ANON_KEY: ${{SUPABASE_ANON_KEY:0:20}}..." >> $LOG_FILE 2>&1
echo "SUPABASE_SERVICE_ROLE_KEY: ${{SUPABASE_SERVICE_ROLE_KEY:0:20}}..." >> $LOG_FILE 2>&1

# Start the actual worker process
echo "=== STARTING MAIN WORKER ===" >> $LOG_FILE 2>&1
WORKER_CMD="python worker.py --supabase-url $SUPABASE_URL --supabase-access-token $SUPABASE_SERVICE_ROLE_KEY --worker $WORKER_ID"
echo "Command: $WORKER_CMD" >> $LOG_FILE 2>&1
echo "Starting at: $(date)" >> $LOG_FILE 2>&1

# Start worker in background with comprehensive logging
nohup $WORKER_CMD >> $LOG_FILE 2>&1 &
WORKER_PID=$!

echo "✅ Worker process started with PID: $WORKER_PID at $(date)" >> $LOG_FILE 2>&1

# Give the worker a moment to start and check if it's still running
sleep 2
if kill -0 $WORKER_PID 2>/dev/null; then
    echo "✅ Worker process $WORKER_PID is still running after 2 seconds" >> $LOG_FILE 2>&1
else
    echo "❌ ERROR: Worker process $WORKER_PID died immediately!" >> $LOG_FILE 2>&1
    echo "Exit status was: $?" >> $LOG_FILE 2>&1
fi

echo "=========================================" >> $LOG_FILE 2>&1
echo "🏁 STARTUP SCRIPT COMPLETED SUCCESSFULLY" >> $LOG_FILE 2>&1
echo "=========================================" >> $LOG_FILE 2>&1
"""

        # Write the script to a temporary file and execute it
        script_path = f"/tmp/start_worker_{worker_id}.sh"
        
        logger.info(f"Creating startup script at {script_path} for worker {worker_id}")
        
        # First, create the script file
        create_script_command = f"cat > {script_path} << 'SCRIPT_EOF'\n{startup_script}\nSCRIPT_EOF"
        
        result = self.execute_command_on_worker(runpod_id, create_script_command, timeout=10)
        if not result or result[0] != 0:
            logger.error(f"Failed to create startup script for worker {worker_id}: {result}")
            return False
        
        logger.info(f"Startup script created successfully, verifying and executing...")
        
        # Verify the script was created and make it executable
        # First ensure logs directory exists (may not exist if Headless-Wan2GP was just cloned)
        verify_and_execute_command = f"""
        mkdir -p /workspace/Headless-Wan2GP/logs
        echo "=== SCRIPT EXECUTION DEBUG ===" > /workspace/Headless-Wan2GP/logs/{worker_id}_script.log
        echo "Script path: {script_path}" >> /workspace/Headless-Wan2GP/logs/{worker_id}_script.log
        echo "Script exists: $(ls -la {script_path})" >> /workspace/Headless-Wan2GP/logs/{worker_id}_script.log
        echo "Script size: $(wc -l < {script_path}) lines" >> /workspace/Headless-Wan2GP/logs/{worker_id}_script.log
        echo "Making executable and running at $(date)..." >> /workspace/Headless-Wan2GP/logs/{worker_id}_script.log
        chmod +x {script_path}
        {script_path} >> /workspace/Headless-Wan2GP/logs/{worker_id}_script.log 2>&1 || echo "Script failed with exit code $?" >> /workspace/Headless-Wan2GP/logs/{worker_id}_script.log
        echo "Script execution completed at $(date)" >> /workspace/Headless-Wan2GP/logs/{worker_id}_script.log
        """
        
        result = self.execute_command_on_worker(runpod_id, verify_and_execute_command, timeout=120)
        
        if result:
            exit_code, stdout, stderr = result
            logger.info(f"Worker startup script executed with exit code {exit_code}")
            if stdout and stdout.strip():
                logger.info(f"Script stdout: {stdout.strip()}")
            if stderr and stderr.strip():
                logger.warning(f"Script stderr: {stderr.strip()}")
            return exit_code == 0
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
        logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}] Getting SSH client - starting authentication flow")
        
        ssh_details = get_pod_ssh_details(runpod_id, self.api_key)
        if not ssh_details:
            logger.error(f"🔐 SSH_AUTH [Pod {runpod_id}] ❌ FAILED: Could not get SSH details from RunPod API")
            return None
        
        logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}] SSH details obtained - IP: {ssh_details['ip']}, Port: {ssh_details['port']}")
        
        # Check environment variables for SSH keys
        private_key_env = os.getenv("RUNPOD_SSH_PRIVATE_KEY")
        public_key_env = os.getenv("RUNPOD_SSH_PUBLIC_KEY")
        private_key_path_env = os.getenv("RUNPOD_SSH_PRIVATE_KEY_PATH")
        
        logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}] Environment check:")
        logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}]   - RUNPOD_SSH_PRIVATE_KEY: {'✅ SET' if private_key_env else '❌ MISSING'}")
        logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}]   - RUNPOD_SSH_PUBLIC_KEY: {'✅ SET' if public_key_env else '❌ MISSING'}")
        logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}]   - RUNPOD_SSH_PRIVATE_KEY_PATH: {'✅ SET' if private_key_path_env else '❌ MISSING'}")
        
        # Try private key from environment variable first (for Railway)
        if private_key_env:
            logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}] ✅ Using PRIVATE KEY from environment variable")
            logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}] Private key length: {len(private_key_env)} chars")
            logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}] Private key starts with: {private_key_env[:50]}...")
            return SSHClient(
                hostname=ssh_details['ip'],
                port=ssh_details['port'],
                username='root',
                private_key_content=private_key_env,
            )
        
        # Fallback to private key file path (for local development)
        if self.ssh_private_key_path and os.path.exists(os.path.expanduser(self.ssh_private_key_path)):
            logger.info(f"🔐 SSH_AUTH [Pod {runpod_id}] ✅ Using PRIVATE KEY from file path: {self.ssh_private_key_path}")
            return SSHClient(
                hostname=ssh_details['ip'],
                port=ssh_details['port'],
                username='root',
                private_key_path=self.ssh_private_key_path,
            )
        else:
            logger.warning(f"🔐 SSH_AUTH [Pod {runpod_id}] ⚠️  FALLING BACK to PASSWORD authentication")
            logger.warning(f"🔐 SSH_AUTH [Pod {runpod_id}] This will likely FAIL as RunPod requires key-based auth")
            logger.warning(f"🔐 SSH_AUTH [Pod {runpod_id}] Password from RunPod: {ssh_details.get('password', 'runpod')}")
            return SSHClient(
                hostname=ssh_details['ip'],
                port=ssh_details['port'],
                username='root',
                password=ssh_details.get('password', 'runpod'),
            )
    
    def execute_command_on_worker(self, runpod_id: str, command: str, timeout: int = 600) -> Optional[tuple]:
        """Execute a command on a worker via SSH."""
        logger.info(f"🔐 SSH_EXEC [Pod {runpod_id}] Executing command: {command[:100]}...")
        
        ssh_client = self.get_ssh_client(runpod_id)
        if not ssh_client:
            logger.error(f"🔐 SSH_EXEC [Pod {runpod_id}] ❌ FAILED: Could not get SSH client")
            return None
        
        try:
            logger.info(f"🔐 SSH_EXEC [Pod {runpod_id}] Attempting SSH connection...")
            ssh_client.connect()
            logger.info(f"🔐 SSH_EXEC [Pod {runpod_id}] ✅ SSH connection successful!")
            
            exit_code, stdout, stderr = ssh_client.execute_command(command, timeout)
            logger.info(f"🔐 SSH_EXEC [Pod {runpod_id}] Command completed - Exit code: {exit_code}")
            if stderr:
                logger.warning(f"🔐 SSH_EXEC [Pod {runpod_id}] Command stderr: {stderr[:200]}...")
            return exit_code, stdout, stderr
        except Exception as e:
            logger.error(f"🔐 SSH_EXEC [Pod {runpod_id}] ❌ SSH EXECUTION FAILED: {e}")
            logger.error(f"🔐 SSH_EXEC [Pod {runpod_id}] This indicates SSH authentication or connection issues")
            return None
        finally:
            if ssh_client:
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
                
                # Get SSH details with better error handling
                ssh_details = get_pod_ssh_details(runpod_id, self.api_key)
                
                if ssh_details and ssh_details.get('ip') and ssh_details.get('port'):
                    logger.info(f"SSH available for {worker_id}: {ssh_details['ip']}:{ssh_details['port']}")
                    
                    # Worker is ready for start_worker_process()
                    return {
                        "status": "active",
                        "ssh_details": ssh_details,
                        "ready": True
                    }
                else:
                    # Pod is running but SSH details are incomplete/missing
                    # Check if we have basic port info from runtime
                    ssh_port = None
                    ssh_ip = None
                    for port_map in runtime.get("ports", []):
                        if port_map.get("privatePort") == 22:
                            ssh_ip = port_map.get("ip")
                            ssh_port = port_map.get("publicPort")
                            break
                    
                    if ssh_ip and ssh_port:
                        logger.info(f"SSH details found in runtime for {worker_id}: {ssh_ip}:{ssh_port}")
                        # Use runtime details directly
                        return {
                            "status": "active",
                            "ssh_details": {
                                "ip": ssh_ip,
                                "port": ssh_port,
                                "password": "runpod"
                            },
                            "ready": True
                        }
                    else:
                        logger.warning(f"Pod {runpod_id} is running but SSH details incomplete - waiting...")
                        return {"status": "spawning", "message": "Waiting for complete SSH access"}
                    
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