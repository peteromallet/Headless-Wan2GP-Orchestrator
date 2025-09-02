#!/usr/bin/env python3
"""
Intelligent utility to fetch worker logs from GPU pods for analysis.
Automatically adapts based on worker state and method success:

Always runs:
- Orchestrator log analysis (worker lifecycle)
- S3 storage log fetching (works for terminated workers)

Conditionally runs (when SSH is available):
- Direct SSH log retrieval (fastest method)
- Git status and commit history 
- Machine-level system logs (boot, syslog, journal)
- Comprehensive file search (only if direct logs fail)

Smart decisions:
- Skips SSH methods if pod is terminated/inaccessible
- Skips comprehensive search if direct SSH gets logs
- Only shows process debugging if no logs found anywhere

Usage: python fetch_worker_logs.py [worker_id] [--lines N] [--follow] [--output file]
"""

import os
import sys
import argparse
import asyncio
import subprocess
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient
from gpu_orchestrator.runpod_client import RunpodClient


async def check_orchestrator_logs(worker_id: str, lines: int = 100):
    """Check orchestrator.log for entries related to this worker."""
    print(f"   📋 Checking orchestrator.log for worker {worker_id}:")
    
    orchestrator_log = Path(__file__).parent.parent / "orchestrator.log"
    if not orchestrator_log.exists():
        print("   ❌ orchestrator.log not found")
        return
    
    try:
        # Get file size
        file_size = orchestrator_log.stat().st_size
        print(f"   📊 Log file size: {file_size / 1024 / 1024:.2f} MB")
        
        # Events to track
        events = {
            'spawning': [],
            'active': [],
            'errors': [],
            'terminating': [],
            'tasks': [],
            'health_checks': [],
            'other': []
        }
        
        # Read and parse log file
        line_count = 0
        matches = 0
        
        with open(orchestrator_log, 'r') as f:
            for line in f:
                line_count += 1
                if worker_id in line:
                    matches += 1
                    
                    # Try to parse JSON log format
                    try:
                        if line.strip().startswith('{'):
                            log_entry = json.loads(line.strip())
                            # Handle both "timestamp" and "asctime" fields
                            timestamp = log_entry.get('timestamp') or log_entry.get('asctime', 'Unknown time')
                            message = log_entry.get('message', '')
                            level = log_entry.get('level') or log_entry.get('levelname', 'INFO')
                            
                            # Categorize the event
                            if 'spawning' in message.lower() or 'spawn' in message.lower():
                                events['spawning'].append((timestamp, level, message))
                            elif 'active' in message.lower() and 'status' in message.lower():
                                events['active'].append((timestamp, level, message))
                            elif level in ['ERROR', 'CRITICAL'] or 'error' in message.lower():
                                events['errors'].append((timestamp, level, message))
                            elif 'terminating' in message.lower() or 'terminated' in message.lower():
                                events['terminating'].append((timestamp, level, message))
                            elif 'task' in message.lower():
                                events['tasks'].append((timestamp, level, message))
                            elif 'health' in message.lower() or 'heartbeat' in message.lower():
                                events['health_checks'].append((timestamp, level, message))
                            else:
                                events['other'].append((timestamp, level, message))
                    except:
                        # Plain text format
                        if 'spawning' in line.lower() or 'spawn' in line.lower():
                            events['spawning'].append(('', 'INFO', line.strip()))
                        elif 'active' in line.lower() and 'status' in line.lower():
                            events['active'].append(('', 'INFO', line.strip()))
                        elif 'error' in line.lower():
                            events['errors'].append(('', 'ERROR', line.strip()))
                        elif 'terminating' in line.lower() or 'terminated' in line.lower():
                            events['terminating'].append(('', 'INFO', line.strip()))
                        elif 'task' in line.lower():
                            events['tasks'].append(('', 'INFO', line.strip()))
                        elif 'health' in line.lower() or 'heartbeat' in line.lower():
                            events['health_checks'].append(('', 'INFO', line.strip()))
                        else:
                            events['other'].append(('', 'INFO', line.strip()))
        
        print(f"   📊 Scanned {line_count:,} lines, found {matches} matches")
        
        # Display categorized events
        if events['spawning']:
            print(f"\n   🚀 Spawning Events ({len(events['spawning'])}):")
            for timestamp, level, msg in events['spawning'][-5:]:  # Show last 5
                print(f"      [{timestamp}] {msg[:150]}{'...' if len(msg) > 150 else ''}")
        
        if events['active']:
            print(f"\n   ✅ Active Status Changes ({len(events['active'])}):")
            for timestamp, level, msg in events['active'][-5:]:
                print(f"      [{timestamp}] {msg[:150]}{'...' if len(msg) > 150 else ''}")
        
        if events['errors']:
            print(f"\n   ❌ Errors ({len(events['errors'])}):")
            for timestamp, level, msg in events['errors'][-10:]:  # Show more errors
                print(f"      [{timestamp}] {msg[:150]}{'...' if len(msg) > 150 else ''}")
        
        if events['terminating']:
            print(f"\n   🛑 Termination Events ({len(events['terminating'])}):")
            for timestamp, level, msg in events['terminating'][-5:]:
                print(f"      [{timestamp}] {msg[:150]}{'...' if len(msg) > 150 else ''}")
        
        if events['tasks']:
            print(f"\n   📦 Task Events ({len(events['tasks'])}):")
            # Show task summary
            task_counts = {}
            for _, _, msg in events['tasks']:
                if 'assigned' in msg.lower():
                    task_counts['assigned'] = task_counts.get('assigned', 0) + 1
                elif 'completed' in msg.lower():
                    task_counts['completed'] = task_counts.get('completed', 0) + 1
                elif 'failed' in msg.lower():
                    task_counts['failed'] = task_counts.get('failed', 0) + 1
            
            for status, count in task_counts.items():
                print(f"      {status.capitalize()}: {count}")
            
            # Show last few task events
            print("      Recent task events:")
            for timestamp, level, msg in events['tasks'][-5:]:
                print(f"        [{timestamp}] {msg[:120]}{'...' if len(msg) > 120 else ''}")
        
        if events['health_checks'] and len(events['health_checks']) > 10:
            print(f"\n   💓 Health Checks: {len(events['health_checks'])} (last check: {events['health_checks'][-1][0]})")
        
        if events['other'] and lines > 50:  # Only show if user wants more lines
            print(f"\n   📝 Other Events ({len(events['other'])}):")
            for timestamp, level, msg in events['other'][-5:]:
                print(f"      [{timestamp}] {msg[:150]}{'...' if len(msg) > 150 else ''}")
        
        # Show timeline summary
        all_events = []
        for category, items in events.items():
            for timestamp, level, msg in items:
                if timestamp:  # Only include events with timestamps
                    all_events.append((timestamp, category, level, msg))
        
        if all_events:
            all_events.sort(key=lambda x: x[0])
            print(f"\n   ⏱️  Worker Timeline (showing key events):")
            
            # Show first event
            if all_events:
                t, cat, lvl, msg = all_events[0]
                print(f"      First seen: [{t}] {cat.upper()} - {msg[:100]}{'...' if len(msg) > 100 else ''}")
            
            # Show last event
            if len(all_events) > 1:
                t, cat, lvl, msg = all_events[-1]
                print(f"      Last seen:  [{t}] {cat.upper()} - {msg[:100]}{'...' if len(msg) > 100 else ''}")
            
            # Calculate worker lifetime if we have spawn and termination events
            spawn_times = [e[0] for e in events['spawning'] if e[0]]
            term_times = [e[0] for e in events['terminating'] if e[0]]
            
            if spawn_times and term_times:
                try:
                    # Parse timestamps
                    spawn_dt = datetime.fromisoformat(spawn_times[0].replace('Z', '+00:00'))
                    term_dt = datetime.fromisoformat(term_times[-1].replace('Z', '+00:00'))
                    lifetime = term_dt - spawn_dt
                    print(f"      Lifetime: {lifetime}")
                except:
                    pass
        
    except Exception as e:
        print(f"   ❌ Error reading orchestrator.log: {e}")


async def check_git_status(ssh_client, worker_id):
    """Check git status and recent commits on the worker."""
    print(f"   🔍 Checking git status for {worker_id}:")
    
    git_commands = [
        # Check current branch and status
        "cd /workspace/Headless-Wan2GP && git branch -v",
        # Check last few commits
        "cd /workspace/Headless-Wan2GP && git log --oneline -5",
        # Check if there are uncommitted changes
        "cd /workspace/Headless-Wan2GP && git status --porcelain",
        # Check when last git pull happened (from reflog)
        "cd /workspace/Headless-Wan2GP && git reflog --grep=pull -5",
        # Check if remote origin is set correctly
        "cd /workspace/Headless-Wan2GP && git remote -v",
        # Manual git pull test
        "cd /workspace/Headless-Wan2GP && timeout 30 git pull origin main 2>&1"
    ]
    
    for cmd in git_commands:
        try:
            exit_code, stdout, stderr = ssh_client.execute_command(cmd, timeout=30)
            cmd_name = cmd.split('&&')[-1].strip().split()[-2:]  # Extract the main git command
            print(f"      {' '.join(cmd_name)}: ", end="")
            
            if exit_code == 0:
                if stdout.strip():
                    print(f"✅ {stdout.strip()}")
                else:
                    print("✅ (no output)")
            else:
                print(f"❌ Exit {exit_code}: {stderr.strip() if stderr else 'No error output'}")
                
        except Exception as e:
            print(f"      {cmd}: ❌ Error: {e}")


async def fetch_machine_logs(ssh_client, worker_id, lines=50):
    """Fetch actual system/machine logs including initialization and pre-worker logs."""
    print(f"   🖥️  Fetching machine-level logs for {worker_id}:")
    
    # System log commands to check initialization, boot, and pre-worker activity
    log_commands = [
        # System logs
        ("System Log (syslog)", f"tail -n {lines} /var/log/syslog 2>/dev/null || echo 'No syslog access'"),
        
        # Systemd journal logs
        ("System Journal", f"journalctl --no-pager -n {lines} 2>/dev/null || echo 'No journalctl access'"),
        
        # Boot log
        ("Boot Log", f"dmesg | tail -n {lines} 2>/dev/null || echo 'No dmesg access'"),
        
        # Docker logs if running in container
        ("Docker Container Log", "timeout 10 docker logs $(hostname) 2>/dev/null | tail -n 20 || echo 'Not in docker or no access'"),
        
        # Check for any startup/init scripts
        ("Startup Scripts", "ls -la /etc/init.d/ /etc/systemd/system/ 2>/dev/null | head -10 || echo 'No startup script access'"),
        
        # Check for any container initialization logs
        ("Container Init", "ls -la /var/log/ | grep -E '(init|start|setup)' | head -10 || echo 'No container init logs'"),
        
        # Check for any RunPod specific logs
        ("RunPod Logs", "find /var/log /tmp /root -name '*runpod*' -o -name '*pod*' 2>/dev/null | head -10 || echo 'No RunPod logs found'"),
        
        # Check for any recent files that might be logs
        ("Recent Log Files", f"find /var/log /tmp -type f -mtime -1 -name '*.log' 2>/dev/null | head -10 || echo 'No recent log files'"),
        
        # Check process tree and uptime
        ("System Info", "uptime && ps axf | head -20"),
        
        # Check environment and mounted filesystems
        ("Mount Info", "df -h && mount | grep -E '(workspace|tmp|var)' || echo 'Basic mount info'"),
        
        # Check for any Python/worker related logs in standard locations
        ("Python Logs", f"find /var/log /tmp /root -name '*.log' -exec grep -l -i 'python\\|worker' {{}} \\; 2>/dev/null | head -5 || echo 'No Python-related logs'"),
        
        # Check system messages
        ("System Messages", f"tail -n {lines//2} /var/log/messages 2>/dev/null || echo 'No messages log'"),
        
        # Check auth logs for SSH connections
        ("Auth Log", f"tail -n {lines//4} /var/log/auth.log 2>/dev/null || echo 'No auth log'"),
        
        # Check if there are any crash dumps or core files
        ("Crash/Core Files", "find /var/crash /tmp /core* -type f 2>/dev/null | head -5 || echo 'No crash files'"),
    ]
    
    for log_name, cmd in log_commands:
        try:
            print(f"      📋 {log_name}:")
            exit_code, stdout, stderr = ssh_client.execute_command(cmd, timeout=30)
            
            if exit_code == 0 and stdout.strip():
                # Show first few and last few lines if output is long
                lines_output = stdout.strip().split('\n')
                if len(lines_output) > 10:
                    print(f"         (showing first 5 and last 5 of {len(lines_output)} lines)")
                    for line in lines_output[:5]:
                        print(f"         {line}")
                    print(f"         ... ({len(lines_output) - 10} lines skipped) ...")
                    for line in lines_output[-5:]:
                        print(f"         {line}")
                else:
                    for line in lines_output:
                        print(f"         {line}")
            else:
                print(f"         ⚠️  {stdout.strip() if stdout else 'No output'}")
                if stderr and stderr.strip():
                    print(f"         Error: {stderr.strip()}")
                    
        except Exception as e:
            print(f"         ❌ Error executing {log_name}: {e}")
        
        print()  # Add space between log sections


def check_s3_storage():
    """Check RunPod storage using S3-compatible API."""
    print("   🗄️  Checking RunPod storage via S3 API:")
    
    # Load AWS credentials from environment
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    # Try to use s3cmd if available (more commonly installed than aws cli)
    s3_commands = []
    
    # Add s3cmd command if available
    s3_commands.append("s3cmd ls --host=s3api-eu-ro-1.runpod.io --host-bucket=s3api-eu-ro-1.runpod.io s3://m6ccu1lodp/")
    
    # Add aws cli command if credentials are available
    if aws_access_key and aws_secret_key:
        s3_commands.append(f"AWS_ACCESS_KEY_ID={aws_access_key} AWS_SECRET_ACCESS_KEY={aws_secret_key} aws s3 ls --endpoint-url https://s3api-eu-ro-1.runpod.io s3://m6ccu1lodp/")
    
    # Add curl command as fallback
    s3_commands.append("curl -s 'https://s3api-eu-ro-1.runpod.io/m6ccu1lodp/' | head -20")
    
    for cmd in s3_commands:
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                print(f"      ✅ {cmd.split()[0]} succeeded:")
                for line in result.stdout.strip().split('\n')[:10]:  # Show first 10 lines
                    print(f"         {line}")
                return True
            else:
                print(f"      ⚠️  {cmd.split()[0]} failed: {result.stderr.strip() if result.stderr else 'No output'}")
        except Exception as e:
            print(f"      ❌ {cmd.split()[0]} error: {e}")
    
    print("      💡 To check storage manually, try:")
    if aws_access_key and aws_secret_key:
        print("         aws s3 ls --endpoint-url https://s3api-eu-ro-1.runpod.io s3://m6ccu1lodp/")
    print("         curl 'https://s3api-eu-ro-1.runpod.io/m6ccu1lodp/' | head -20")
    return False


async def fetch_direct_ssh_logs(ssh_client, worker_id: str, lines: int = 100) -> bool:
    """Direct SSH log fetching - simple and reliable approach."""
    print(f"   🔗 Fetching logs directly via SSH for worker {worker_id}...")
    
    try:
        # Find all log files in workspace
        exit_code, out, err = ssh_client.execute_command('find /workspace -name "*.log" 2>/dev/null | head -10', timeout=10)
        if exit_code == 0 and out.strip():
            print(f"   📁 Found log files:")
            log_files = out.strip().split('\n')
            for line in log_files:
                print(f"      {line}")
            
            # Try to get the specific worker log
            worker_log_path = f'/workspace/Headless-Wan2GP/logs/{worker_id}.log'
            if worker_log_path in log_files or any(worker_id in log_file for log_file in log_files):
                print(f"   📄 Reading worker-specific log: {worker_log_path}")
                exit_code, out, err = ssh_client.execute_command(f'tail -n {lines} {worker_log_path}', timeout=30)
                if exit_code == 0 and out.strip():
                    print("   " + "="*80)
                    print(f"   📄 Worker Log (last {lines} lines):")
                    print("   " + "="*80)
                    for line in out.strip().split('\n'):
                        print(f"   {line}")
                    print("   " + "="*80)
                    return True
                else:
                    print(f"   ⚠️  Could not read worker log: {err.strip() if err else 'Unknown error'}")
            
            # Fallback: try general worker.log
            general_log_path = '/workspace/Headless-Wan2GP/worker.log'
            if general_log_path in log_files:
                print(f"   📄 Checking general worker.log for relevant entries...")
                exit_code, out, err = ssh_client.execute_command(f'tail -n {lines * 2} {general_log_path} | grep -A 10 -B 10 "{worker_id}" | tail -n {lines}', timeout=30)
                if exit_code == 0 and out.strip():
                    print("   " + "="*80)
                    print(f"   📄 Worker Log (filtered, last {lines} lines):")
                    print("   " + "="*80)
                    for line in out.strip().split('\n'):
                        print(f"   {line}")
                    print("   " + "="*80)
                    return True
        
        print(f"   ❌ No suitable log files found for worker {worker_id}")
        return False
        
    except Exception as e:
        print(f"   ❌ Error in direct SSH log fetch: {e}")
        return False


async def fetch_s3_worker_logs(worker_id: str, lines: int = 100) -> bool:
    """Fetch worker logs from S3 storage."""
    print(f"   📦 Fetching logs from S3 storage for worker {worker_id}...")
    
    # Load AWS credentials from environment
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    if not aws_access_key or not aws_secret_key:
        print("   ❌ AWS credentials not found in environment")
        return False
    
    # Set up AWS environment for subprocess calls
    env = os.environ.copy()
    region = os.getenv('AWS_DEFAULT_REGION', 'eu-ro-1')
    env.update({
        'AWS_ACCESS_KEY_ID': aws_access_key,
        'AWS_SECRET_ACCESS_KEY': aws_secret_key,
        'AWS_DEFAULT_REGION': region
    })

    def _download_and_print(s3_path: str) -> bool:
        """Helper to fetch, tail and print a log file from S3."""
        local_log_path = f"./{worker_id}_s3.log"
        
        # Try aws s3 cp first with explicit region
        cmd = (
            f"aws s3 cp --endpoint-url https://s3api-eu-ro-1.runpod.io --region {region} "
            f"{s3_path} {local_log_path}"
        )
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, env=env)
        
        # If cp succeeded but file missing, fall back to s3api get-object
        if res.returncode == 0 and not os.path.exists(local_log_path):
            print(f"   🔄 s3 cp succeeded but file missing, trying s3api get-object...")
            # Extract bucket and key from s3 path
            s3_parts = s3_path.replace('s3://', '').split('/', 1)
            bucket = s3_parts[0]
            key = s3_parts[1] if len(s3_parts) > 1 else ''
            
            fallback_cmd = (
                f"aws s3api get-object "
                f"--endpoint-url https://s3api-eu-ro-1.runpod.io "
                f"--bucket {bucket} --key {key} {local_log_path} "
                f"--region {region}"
            )
            fallback_res = subprocess.run(fallback_cmd, shell=True, capture_output=True, text=True, timeout=60, env=env)
            if fallback_res.returncode != 0:
                print(f"   ⚠️  Fallback get-object failed: {fallback_res.stderr.strip() if fallback_res.stderr else 'Unknown error'}")
                return False
            else:
                print(f"   🔄 Fallback get-object succeeded")
        
        elif res.returncode != 0:
            print(f"   ⚠️  S3 download failed: {res.stderr.strip() if res.stderr else 'Unknown error'}")
            return False
        
        # Check if file was actually created and is readable
        if not os.path.exists(local_log_path):
            print(f"   ❌ S3 download succeeded but file not found: {local_log_path}")
            return False
            
        try:
            with open(local_log_path, 'r') as f:
                log_content = f.read()
            print("   " + "="*60)
            print(f"   📄 S3 Worker Log ({os.path.basename(s3_path)}) – last {lines} lines:")
            print("   " + "="*60)
            for line in log_content.strip().split('\n')[-lines:]:
                print(f"   {line}")
            print("   " + "="*60)
            return True
        except Exception as e:
            print(f"   ❌ Error reading S3 log file: {e}")
            return False
        finally:
            if os.path.exists(local_log_path):
                os.remove(local_log_path)

    # 1) try exact path first
    exact_path = f"s3://m6ccu1lodp/Headless-Wan2GP/logs/{worker_id}.log"
    if _download_and_print(exact_path):
        print("   ✅ Exact worker log fetched from S3")
        return True

    # 2) wildcard search: any log that contains the worker_id (handles sub-dirs or suffixes)
    search_cmd = f"aws s3 ls --recursive --endpoint-url https://s3api-eu-ro-1.runpod.io --region {region} s3://m6ccu1lodp | grep {worker_id} | head -1"
    search = subprocess.run(search_cmd, shell=True, capture_output=True, text=True, timeout=30, env=env)
    if search.returncode == 0 and search.stdout.strip():
        parts = search.stdout.split()
        key = parts[-1] if parts else ''
        if key:
            if _download_and_print(f"s3://m6ccu1lodp/{key}"):
                print("   ✅ Found and fetched matching S3 log by wildcard")
                return True

    # 3) fallback list by date prefix
    date_prefix = worker_id.split('_')[1][:8] if '_' in worker_id else ''
    if date_prefix:
        list_cmd = f"aws s3 ls --endpoint-url https://s3api-eu-ro-1.runpod.io --region {region} s3://m6ccu1lodp/Headless-Wan2GP/logs/ | grep {date_prefix} | head -5"
        list_res = subprocess.run(list_cmd, shell=True, capture_output=True, text=True, timeout=30, env=env)
        if list_res.returncode == 0 and list_res.stdout.strip():
            print(f"   💡 Other logs from same date ({date_prefix}) that you might inspect:")
            for line in list_res.stdout.strip().split('\n'):
                print(f"      {line}")

    print("   ❌ No S3 log found for this worker")
    return False


async def fetch_worker_logs(worker_id=None, lines=100, follow=False, output_file=None):
    """Fetch logs from a worker pod using all available methods."""
    
    # Initialize clients
    db = DatabaseClient()
    runpod_client = RunpodClient(os.getenv('RUNPOD_API_KEY'))
    
    # Get worker info
    if worker_id:
        # Include terminated workers when a specific worker_id is requested so we can fetch logs
        workers = await db.get_workers(['spawning', 'active', 'terminating', 'error', 'terminated'])
        worker = next((w for w in workers if w['id'] == worker_id), None)
        if not worker:
            print(f"❌ Worker {worker_id} not found")
            return
        workers = [worker]
    else:
        # Get all non-terminated workers
        workers = await db.get_workers(['spawning', 'active', 'terminating'])
        if not workers:
            print("❌ No active workers found")
            return
    
    # Check S3 storage by default (not just when requested)
    await fetch_s3_storage_overview()
    print()
    
    print(f"🔍 Intelligent log analysis will include:")
    print(f"   📋 Orchestrator logs (always - fast and local)")
    print(f"   📦 S3 storage logs (always - works for terminated workers)")
    print(f"   🔗 SSH-based methods (if pod is accessible):")
    print(f"     • Direct log retrieval")
    print(f"     • Git status and commit history")
    print(f"     • Machine-level system logs")
    print(f"     • Comprehensive file search (if direct logs fail)")
    print(f"   🧠 Smart decisions: skips redundant or impossible operations")
    print()
    
    for worker in workers:
        worker_id = worker['id']
        status = worker.get('status', 'unknown')
        metadata = worker.get('metadata') or {}
        runpod_id = metadata.get('runpod_id')
        
        print(f"\n🤖 Worker: {worker_id}")
        print(f"   Status: {status}")
        print(f"   Pod ID: {runpod_id}")
        
        # Check orchestrator logs (always run - fast and local)
        await check_orchestrator_logs(worker_id, lines)
        print()
        
        # Always try to fetch S3 logs first (works even for terminated workers)
        s3_logs_found = await fetch_s3_worker_logs(worker_id, lines)
        
        if not runpod_id:
            print("   ❌ No RunPod ID found")
            if not s3_logs_found:
                print("   💡 Try checking S3 storage for logs from this timeframe")
            else:
                print("   ✅ S3 logs available - worker analysis complete")
            continue
        
        # Check if worker is likely terminated
        is_likely_terminated = status in ['terminated', 'error'] and not s3_logs_found
        
        # Get SSH client
        ssh_available = False
        ssh_client = None
        try:
            ssh_client = runpod_client.get_ssh_client(runpod_id)
            if not ssh_client:
                print("   ❌ Could not get SSH access")
                if not s3_logs_found:
                    print("   💡 Pod may be terminated - only S3 logs are available")
                else:
                    print("   ✅ S3 logs available - SSH not needed")
                continue
        except Exception as e:
            print(f"   ❌ Could not get SSH client: {e}")
            if not s3_logs_found:
                print("   💡 Pod may be terminated - only S3 logs are available") 
            else:
                print("   ✅ S3 logs available - SSH not accessible")
            continue
        
        # Try SSH connection
        try:
            ssh_client.connect()
            print(f"   ✅ Connected to pod")
            ssh_available = True
            
            # Try direct SSH log fetching first (simple and reliable)
            direct_ssh_success = await fetch_direct_ssh_logs(ssh_client, worker_id, lines)
            if direct_ssh_success:
                print(f"   ✅ Successfully fetched logs via direct SSH")
            
            # Always check git status when SSH is available (quick and valuable)
            await check_git_status(ssh_client, worker_id)
            print()
            
            # Always fetch machine-level logs when SSH available (different info than worker logs)
            await fetch_machine_logs(ssh_client, worker_id, lines)
            print()
            
            # Only do comprehensive log search if direct SSH didn't get the worker logs
            if not direct_ssh_success:
                print(f"   🔍 Direct SSH didn't get worker logs, trying comprehensive search...")
                
                # Check for logs in multiple locations including /root/logs/
                log_locations = [
                    f"/workspace/Headless-Wan2GP/logs/{worker_id}.log",
                    f"/workspace/Headless-Wan2GP/logs/{worker_id}/",
                    "/workspace/Headless-Wan2GP/worker.log",
                    f"/root/logs/{worker_id}.log",  # Add /root/logs/ location
                    "/root/logs/",  # Check /root/logs/ directory
                ]
                
                logs_found = False
                
                for log_path in log_locations:
                    try:
                        if log_path.endswith('/'):
                            # Directory - list files
                            exit_code, out, err = ssh_client.execute_command(f'ls -la {log_path}', timeout=10)
                            if exit_code == 0 and out.strip():
                                print(f"   📁 Found logs in {log_path}:")
                                print(f"      {out.strip()}")
                                
                                # Get the latest log file
                                exit_code, out, err = ssh_client.execute_command(f'find {log_path} -type f -name "*.log" | head -5', timeout=10)
                                if exit_code == 0 and out.strip():
                                    for log_file in out.strip().split('\n'):
                                        if log_file.strip():
                                            print(f"   📄 Reading {log_file}:")
                                            
                                            # Fetch log content
                                            follow_flag = "-f" if follow else ""
                                            cmd = f'tail {follow_flag} -n {lines} {log_file}'
                                            exit_code, out, err = ssh_client.execute_command(cmd, timeout=30 if not follow else 3600)
                                            
                                            if exit_code == 0:
                                                logs_found = True
                                                log_content = out.strip()
                                                
                                                if output_file:
                                                    # Save to file
                                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                                    filename = f"{output_file}_{worker_id}_{timestamp}.log"
                                                    with open(filename, 'w') as f:
                                                        f.write(f"# Worker: {worker_id}\n")
                                                        f.write(f"# Status: {status}\n")
                                                        f.write(f"# Pod ID: {runpod_id}\n")
                                                        f.write(f"# Log file: {log_file}\n")
                                                        f.write(f"# Fetched: {datetime.now().isoformat()}\n")
                                                        f.write(f"# Lines: {lines}\n\n")
                                                        f.write(log_content)
                                                    print(f"   💾 Saved to {filename}")
                                                else:
                                                    # Print to console
                                                    print("   " + "="*60)
                                                    for line in log_content.split('\n'):
                                                        print(f"   {line}")
                                                    print("   " + "="*60)
                                                    
                                                    break  # Found logs, stop checking other locations
                                        else:
                                            # File - check if exists and verify it belongs to this worker
                                            exit_code, out, err = ssh_client.execute_command(f'test -f {log_path} && echo "exists"', timeout=10)
                                            if exit_code == 0 and "exists" in out:
                                                # For worker.log, verify it contains this worker's ID before reading
                                                if log_path.endswith("worker.log") and "/workspace/" in log_path:
                                                    exit_code, out, err = ssh_client.execute_command(f'head -20 {log_path} | grep -q "{worker_id}" && echo "matches"', timeout=10)
                                                    if exit_code != 0 or "matches" not in out:
                                                        print(f"   ⚠️  {log_path} exists but doesn't belong to worker {worker_id}, skipping")
                                                        continue
                                                
                                                print(f"   📄 Found log file: {log_path}")
                                                
                                                # Fetch log content
                                                follow_flag = "-f" if follow else ""
                                                cmd = f'tail {follow_flag} -n {lines} {log_path}'
                                                exit_code, out, err = ssh_client.execute_command(cmd, timeout=30 if not follow else 3600)
                                                
                                                if exit_code == 0:
                                                    logs_found = True
                                                    log_content = out.strip()
                                                    
                                                    if output_file:
                                                        # Save to file
                                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                                        filename = f"{output_file}_{worker_id}_{timestamp}.log"
                                                        with open(filename, 'w') as f:
                                                            f.write(f"# Worker: {worker_id}\n")
                                                            f.write(f"# Status: {status}\n")
                                                            f.write(f"# Pod ID: {runpod_id}\n")
                                                            f.write(f"# Log file: {log_path}\n")
                                                            f.write(f"# Fetched: {datetime.now().isoformat()}\n")
                                                            f.write(f"# Lines: {lines}\n\n")
                                                            f.write(log_content)
                                                        print(f"   💾 Saved to {filename}")
                                                    else:
                                                        # Print to console
                                                        print("   " + "="*60)
                                                        for line in log_content.split('\n'):
                                                            print(f"   {line}")
                                                        print("   " + "="*60)
                                                    
                                                    break  # Found logs, stop checking other locations
                                                    
                        break  # Found logs, stop checking other locations
                    except Exception as e:
                        # Silent fail for log location checks
                        pass
            
                if not logs_found:
                    print("   ❌ No log files found in comprehensive search")
                    
                    # Only show process debugging if we have no logs from any source
                    if not s3_logs_found:
                        print("   🔍 No logs from any source - checking running processes for debugging:")
                        exit_code, out, err = ssh_client.execute_command('ps aux | grep -E "(python|worker)" | grep -v grep', timeout=10)
                        if exit_code == 0 and out.strip():
                            for line in out.strip().split('\n'):
                                print(f"      {line}")
                        else:
                            print("      No python/worker processes running")
                    else:
                        print("   💡 S3 logs are available above for this worker")
                else:
                    print("   ✅ Found logs via comprehensive search")
            else:
                # Determine what information we successfully gathered
                info_sources = []
                if s3_logs_found:
                    info_sources.append("S3 logs")
                if direct_ssh_success:
                    info_sources.append("direct SSH logs")
                info_sources.extend(["git status", "machine logs"])
                
                print(f"   ✅ Worker analysis complete - gathered: {', '.join(info_sources)}")
                
        except Exception as e:
            print(f"   ❌ SSH Error: {e}")
            if s3_logs_found:
                print("   💡 S3 logs are available above")
            else:
                print("   💡 No logs available from any source")
        finally:
            if ssh_client:
                ssh_client.disconnect()


async def fetch_s3_storage_overview():
    """Check S3 storage overview."""
    print("   🗄️  Checking RunPod S3 storage:")
    
    # Load AWS credentials from environment
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    if not aws_access_key or not aws_secret_key:
        print("   ❌ AWS credentials not found in environment")
        return False
    
    # Set up AWS environment for subprocess calls
    env = os.environ.copy()
    region = os.getenv('AWS_DEFAULT_REGION', 'eu-ro-1')
    env.update({
        'AWS_ACCESS_KEY_ID': aws_access_key,
        'AWS_SECRET_ACCESS_KEY': aws_secret_key,
        'AWS_DEFAULT_REGION': region
    })
    
    try:
        # List recent logs in the logs directory
        cmd = f"aws s3 ls --endpoint-url https://s3api-eu-ro-1.runpod.io --region {region} s3://m6ccu1lodp/Headless-Wan2GP/logs/ | tail -10"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, env=env)
        
        if result.returncode == 0 and result.stdout.strip():
            print(f"   ✅ Recent logs in S3:")
            for line in result.stdout.strip().split('\n'):
                print(f"      {line}")
            return True
        else:
            print(f"   ⚠️  Could not list S3 logs: {result.stderr.strip() if result.stderr else 'No output'}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error checking S3: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Intelligently fetch worker logs from GPU pods, adapting based on worker state and method success')
    parser.add_argument('worker_id', nargs='?', help='Specific worker ID to fetch logs for (default: all workers)')
    parser.add_argument('--lines', '-n', type=int, default=100, help='Number of lines to fetch (default: 100)')
    parser.add_argument('--follow', '-f', action='store_true', help='Follow log output (like tail -f)')
    parser.add_argument('--output', '-o', help='Save logs to file (will append worker_id and timestamp)')
    # Removed --check-git, --check-s3, --machine-logs, --check-orchestrator, --direct-ssh flags
    
    args = parser.parse_args()
    
    # Check required environment variables
    if not os.getenv('RUNPOD_API_KEY'):
        print("❌ RUNPOD_API_KEY environment variable is required")
        sys.exit(1)
    
    if not os.getenv('SUPABASE_URL'):
        print("❌ SUPABASE_URL environment variable is required")
        sys.exit(1)
    
    try:
        asyncio.run(fetch_worker_logs(
            worker_id=args.worker_id,
            lines=args.lines,
            follow=args.follow,
            output_file=args.output,
            # Removed all boolean flags
        ))
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main() 