#!/usr/bin/env python3
"""
Comprehensive utility to fetch task logs from both orchestrator and worker machines.
Searches orchestrator.log for task lifecycle events, then queries actual worker machines
that may have processed the task for detailed execution logs.

Usage: python fetch_task_logs.py [task_id] [--lines N] [--context C] [--output file] [--format json|text] [--worker-logs]
"""

import os
import sys
import argparse
import json
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import subprocess

# Load environment variables
load_dotenv()

# Add project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

# Import worker log functionality
from orchestrator.database import DatabaseClient
from orchestrator.runpod_client import RunpodClient


class TaskLogParser:
    """Parser for extracting task-specific logs from orchestrator.log"""
    
    def __init__(self, log_file_path: str):
        self.log_file_path = log_file_path
        self.task_entries = []
    
    def parse_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single log line and extract structured information"""
        # Try to parse JSON log entries
        try:
            if line.strip().startswith('{') and line.strip().endswith('}'):
                return json.loads(line.strip())
        except json.JSONDecodeError:
            pass
        
        # Parse non-JSON log entries with common patterns
        timestamp_patterns = [
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})',  # 2025-07-25 11:11:22,772
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})',         # 2025-07-25T11:11:22
        ]
        
        for pattern in timestamp_patterns:
            match = re.search(pattern, line)
            if match:
                timestamp = match.group(1)
                message = line[match.end():].strip()
                return {
                    'timestamp': timestamp,
                    'message': message,
                    'raw_line': line.strip()
                }
        
        # Return raw line if no pattern matches
        return {
            'timestamp': None,
            'message': line.strip(),
            'raw_line': line.strip()
        }
    
    def find_task_logs(self, task_id: str, context_lines: int = 0) -> List[Dict[str, Any]]:
        """Find all log entries related to a specific task ID"""
        task_entries = []
        all_lines = []
        
        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
        except Exception as e:
            print(f"❌ Error reading log file: {e}")
            return []
        
        # Find lines containing the task ID
        matching_indices = []
        for i, line in enumerate(all_lines):
            if task_id in line:
                matching_indices.append(i)
        
        # Collect matching lines with context
        collected_indices = set()
        for idx in matching_indices:
            start_idx = max(0, idx - context_lines)
            end_idx = min(len(all_lines), idx + context_lines + 1)
            for i in range(start_idx, end_idx):
                collected_indices.add(i)
        
        # Parse collected lines
        for idx in sorted(collected_indices):
            line = all_lines[idx]
            parsed = self.parse_log_line(line)
            if parsed:
                parsed['line_number'] = idx + 1
                parsed['is_match'] = task_id in line
                task_entries.append(parsed)
        
        return task_entries
    
    def get_task_timeline(self, task_id: str) -> Dict[str, Any]:
        """Get a timeline summary of task events"""
        entries = self.find_task_logs(task_id, context_lines=2)
        
        timeline = {
            'task_id': task_id,
            'total_entries': len(entries),
            'first_seen': None,
            'last_seen': None,
            'status_changes': [],
            'errors': [],
            'key_events': []
        }
        
        for entry in entries:
            if not entry['is_match']:
                continue
                
            timestamp = entry.get('timestamp')
            message = entry.get('message', '')
            
            # Track first and last seen
            if timestamp:
                if not timeline['first_seen']:
                    timeline['first_seen'] = timestamp
                timeline['last_seen'] = timestamp
            
            # Detect status changes
            status_keywords = ['queued', 'processing', 'completed', 'failed', 'error', 'success']
            for keyword in status_keywords:
                if keyword.lower() in message.lower():
                    timeline['status_changes'].append({
                        'timestamp': timestamp,
                        'status': keyword,
                        'message': message
                    })
                    break
            
            # Detect errors
            error_keywords = ['error', 'failed', 'exception', 'traceback']
            if any(keyword.lower() in message.lower() for keyword in error_keywords):
                timeline['errors'].append({
                    'timestamp': timestamp,
                    'message': message,
                    'line_number': entry['line_number']
                })
            
            # Key events
            key_phrases = [
                'queued', 'processing', 'completed', 'failed', 'started', 'finished',
                'enqueued', 'assigned', 'downloaded', 'uploaded', 'generated'
            ]
            if any(phrase.lower() in message.lower() for phrase in key_phrases):
                timeline['key_events'].append({
                    'timestamp': timestamp,
                    'message': message,
                    'line_number': entry['line_number']
                })
        
        return timeline


def search_s3_logs_for_task(worker_id: str, task_id: str, lines: int = 100) -> Dict[str, Any]:
    """Search S3 archived logs for task-related entries"""
    print(f"      📦 Searching S3 logs for task {task_id} in worker {worker_id}...")
    
    # Load AWS credentials from environment
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    if not aws_access_key or not aws_secret_key:
        print(f"      ❌ AWS credentials not found")
        return {'logs_found': False, 'task_entries': [], 'error': 'No AWS credentials'}
    
    # Set up AWS environment for subprocess calls
    env = os.environ.copy()
    env.update({
        'AWS_ACCESS_KEY_ID': aws_access_key,
        'AWS_SECRET_ACCESS_KEY': aws_secret_key,
        'AWS_DEFAULT_REGION': 'EU-RO-1'
    })
    
    try:
        # Download the worker log from S3
        local_log_path = f"./{worker_id}_task_search.log"
        s3_path = f"s3://m6ccu1lodp/reigh/Headless-Wan2GP/logs/{worker_id}.log"
        
        cmd = f"aws s3 cp --endpoint-url https://s3api-eu-ro-1.runpod.io {s3_path} {local_log_path}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, env=env)
        
        if result.returncode != 0:
            print(f"      ⚠️  S3 download failed: {result.stderr.strip() if result.stderr else 'Unknown error'}")
            return {'logs_found': False, 'task_entries': [], 'error': f'S3 download failed: {result.stderr}'}
        
        # Check if file was actually created
        if not os.path.exists(local_log_path):
            print(f"      ❌ S3 download succeeded but file not found")
            return {'logs_found': False, 'task_entries': [], 'error': 'File not created after download'}
        
        # Search for task ID in the downloaded log
        task_entries = []
        try:
            with open(local_log_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    if task_id in line:
                        task_entries.append({
                            'line_number': str(line_num),
                            'content': line.strip(),
                            'source': f'{worker_id}.log (S3)'
                        })
            
            if task_entries:
                print(f"      ✅ Found {len(task_entries)} task entries in S3 log")
                # Show first few entries for confirmation
                for entry in task_entries[:3]:
                    print(f"         [{entry['line_number']}] {entry['content'][:100]}{'...' if len(entry['content']) > 100 else ''}")
                if len(task_entries) > 3:
                    print(f"         ... and {len(task_entries) - 3} more entries")
            else:
                print(f"      ❌ No task entries found in S3 log")
            
            return {
                'logs_found': len(task_entries) > 0,
                'task_entries': task_entries[-lines:] if lines > 0 else task_entries,  # Limit entries
                'total_entries': len(task_entries)
            }
            
        except Exception as e:
            print(f"      ❌ Error reading downloaded log: {e}")
            return {'logs_found': False, 'task_entries': [], 'error': f'Error reading log: {e}'}
        
        finally:
            # Clean up downloaded file
            if os.path.exists(local_log_path):
                os.remove(local_log_path)
    
    except Exception as e:
        print(f"      ❌ S3 search error: {e}")
        return {'logs_found': False, 'task_entries': [], 'error': f'S3 error: {e}'}


def find_worker_for_task(task_id: str) -> Optional[str]:
    """Find which worker was assigned to process a specific task"""
    print(f"🔍 Finding worker assigned to task {task_id}...")
    
    try:
        db = DatabaseClient()
        
        # Query the tasks table to find the worker_id for this task
        # Using the supabase client directly to get more detailed info
        response = db.supabase.table('tasks').select('worker_id, status, created_at, updated_at').eq('id', task_id).execute()
        
        if response.data and len(response.data) > 0:
            task_info = response.data[0]
            worker_id = task_info.get('worker_id')
            status = task_info.get('status')
            created_at = task_info.get('created_at')
            updated_at = task_info.get('updated_at')
            
            print(f"   ✅ Found task in database:")
            print(f"      Task ID: {task_id}")
            print(f"      Worker ID: {worker_id}")
            print(f"      Status: {status}")
            print(f"      Created: {created_at}")
            print(f"      Updated: {updated_at}")
            
            return worker_id
        else:
            print(f"   ❌ Task {task_id} not found in database")
            return None
            
    except Exception as e:
        print(f"   ❌ Database query failed: {e}")
        return None


async def search_specific_worker_logs_for_task(worker_id: str, task_id: str, lines: int = 100) -> Dict[str, Any]:
    """Search logs for a specific worker that processed the task"""
    print(f"\n🎯 Searching logs for worker {worker_id} that processed task {task_id}...")
    
    # Initialize clients
    db = DatabaseClient()
    runpod_client = RunpodClient(os.getenv('RUNPOD_API_KEY'))
    
    # Get the specific worker info
    workers = await db.get_workers(['spawning', 'active', 'terminating', 'error', 'terminated'])
    worker = next((w for w in workers if w['id'] == worker_id), None)
    
    task_worker_logs = {
        'task_id': task_id,
        'target_worker_id': worker_id,
        'worker_found': False,
        'worker_accessible': False,
        'logs_found': False,
        'task_entries': [],
        'total_task_entries': 0,
        'search_method': None,
        'worker_status': None
    }
    
    if not worker:
        print(f"   ❌ Worker {worker_id} not found in database")
        task_worker_logs['error'] = f'Worker {worker_id} not found'
        return task_worker_logs
    
    task_worker_logs['worker_found'] = True
    status = worker.get('status', 'unknown')
    task_worker_logs['worker_status'] = status
    metadata = worker.get('metadata') or {}
    runpod_id = metadata.get('runpod_id')
    
    print(f"   📊 Worker {worker_id} status: {status}")
    
    # Try SSH if worker is active/terminating
    if runpod_id and status in ['active', 'terminating']:
        print(f"   🔗 Attempting SSH connection to active worker...")
        try:
            ssh_client = runpod_client.get_ssh_client(runpod_id)
            if ssh_client:
                ssh_client.connect()
                task_worker_logs['worker_accessible'] = True
                task_worker_logs['search_method'] = 'SSH'
                
                # Search worker-specific log file first
                log_path = f'/workspace/reigh/Headless-Wan2GP/logs/{worker_id}.log'
                exit_code, out, err = ssh_client.execute_command(f'grep -n "{task_id}" {log_path}', timeout=30)
                
                task_entries = []
                if exit_code == 0 and out.strip():
                    for line in out.strip().split('\n'):
                        if ':' in line:
                            line_num, content = line.split(':', 1)
                            task_entries.append({
                                'line_number': line_num,
                                'content': content.strip(),
                                'source': f'{worker_id}.log (SSH)'
                            })
                    print(f"   ✅ Found {len(task_entries)} task entries in worker-specific log")
                
                # Also try general worker.log
                if not task_entries:
                    exit_code, out, err = ssh_client.execute_command(f'grep -n "{task_id}" /workspace/reigh/Headless-Wan2GP/worker.log', timeout=30)
                    if exit_code == 0 and out.strip():
                        for line in out.strip().split('\n'):
                            if ':' in line:
                                line_num, content = line.split(':', 1)
                                task_entries.append({
                                    'line_number': line_num,
                                    'content': content.strip(),
                                    'source': 'worker.log (SSH)'
                                })
                        print(f"   ✅ Found {len(task_entries)} task entries in general worker log")
                
                if task_entries:
                    task_worker_logs['logs_found'] = True
                    task_worker_logs['task_entries'] = task_entries[-lines:] if lines > 0 else task_entries
                    task_worker_logs['total_task_entries'] = len(task_entries)
                
                ssh_client.disconnect()
            else:
                print(f"   ❌ Could not get SSH client")
        except Exception as e:
            print(f"   ❌ SSH error: {e}")
    
    # Try S3 if SSH failed or worker is terminated
    if not task_worker_logs['logs_found']:
        print(f"   📦 Attempting S3 log search...")
        task_worker_logs['search_method'] = 'S3'
        s3_result = search_s3_logs_for_task(worker_id, task_id, lines)
        
        if s3_result['logs_found']:
            task_worker_logs['logs_found'] = True
            task_worker_logs['task_entries'] = s3_result['task_entries']
            task_worker_logs['total_task_entries'] = len(s3_result['task_entries'])
            print(f"   ✅ Found {len(s3_result['task_entries'])} task entries in S3 logs")
        else:
            print(f"   ❌ No task entries found in S3 logs")
            task_worker_logs['s3_error'] = s3_result.get('error', 'Unknown S3 error')
    
    return task_worker_logs


async def search_worker_logs_for_task(task_id: str, lines: int = 100) -> Dict[str, Any]:
    """Search worker logs for task-related entries"""
    print(f"\n🔍 Searching worker logs for task {task_id}...")
    
    # Initialize clients
    db = DatabaseClient()
    runpod_client = RunpodClient(os.getenv('RUNPOD_API_KEY'))
    
    # Get recent workers that might have processed this task
    workers = await db.get_workers(['active', 'terminating', 'error', 'terminated'])
    
    task_worker_logs = {
        'task_id': task_id,
        'workers_searched': 0,
        'workers_with_task_logs': 0,
        'worker_results': [],
        'total_task_entries': 0
    }
    
    print(f"   📊 Found {len(workers)} workers to search")
    
    for worker in workers:
        worker_id = worker['id']
        status = worker.get('status', 'unknown')
        metadata = worker.get('metadata') or {}
        runpod_id = metadata.get('runpod_id')
        
        task_worker_logs['workers_searched'] += 1
        
        print(f"   🤖 Searching worker {worker_id} (status: {status})")
        
        worker_result = {
            'worker_id': worker_id,
            'status': status,
            'runpod_id': runpod_id,
            'task_entries': [],
            'ssh_available': False,
            'logs_found': False
        }
        
        # Try SSH-based log search if worker is accessible
        if runpod_id and status in ['active', 'terminating']:
            try:
                ssh_client = runpod_client.get_ssh_client(runpod_id)
                if ssh_client:
                    ssh_client.connect()
                    worker_result['ssh_available'] = True
                    
                    # Search worker-specific log file
                    log_path = f'/workspace/reigh/Headless-Wan2GP/logs/{worker_id}.log'
                    exit_code, out, err = ssh_client.execute_command(f'grep -n "{task_id}" {log_path} | tail -n {lines}', timeout=30)
                    
                    if exit_code == 0 and out.strip():
                        worker_result['logs_found'] = True
                        task_entries = []
                        for line in out.strip().split('\n'):
                            if ':' in line:
                                line_num, content = line.split(':', 1)
                                task_entries.append({
                                    'line_number': line_num,
                                    'content': content.strip(),
                                    'source': f'{worker_id}.log'
                                })
                        worker_result['task_entries'] = task_entries
                        task_worker_logs['total_task_entries'] += len(task_entries)
                        print(f"      ✅ Found {len(task_entries)} task entries in worker log")
                    else:
                        # Try general worker.log
                        exit_code, out, err = ssh_client.execute_command(f'grep -n "{task_id}" /workspace/reigh/Headless-Wan2GP/worker.log | tail -n {lines}', timeout=30)
                        if exit_code == 0 and out.strip():
                            worker_result['logs_found'] = True
                            task_entries = []
                            for line in out.strip().split('\n'):
                                if ':' in line:
                                    line_num, content = line.split(':', 1)
                                    task_entries.append({
                                        'line_number': line_num,
                                        'content': content.strip(),
                                        'source': 'worker.log'
                                    })
                            worker_result['task_entries'] = task_entries
                            task_worker_logs['total_task_entries'] += len(task_entries)
                            print(f"      ✅ Found {len(task_entries)} task entries in general worker log")
                        else:
                            print(f"      ❌ No task entries found in worker logs")
                    
                    ssh_client.disconnect()
                else:
                    print(f"      ❌ Could not get SSH client")
            except Exception as e:
                print(f"      ❌ SSH error: {e}")
        elif status in ['terminated', 'error']:
            # Try S3 log search for terminated/error workers
            print(f"      🔍 Worker not accessible via SSH, trying S3 archive search...")
            s3_result = search_s3_logs_for_task(worker_id, task_id, lines)
            
            if s3_result['logs_found']:
                worker_result['logs_found'] = True
                worker_result['task_entries'] = s3_result['task_entries']
                task_worker_logs['total_task_entries'] += len(s3_result['task_entries'])
            else:
                worker_result['s3_error'] = s3_result.get('error', 'Unknown S3 error')
        else:
            print(f"      ⚠️  Worker not accessible (status: {status}, runpod_id: {bool(runpod_id)})")
        
        # Count workers that had task logs
        if worker_result['logs_found']:
            task_worker_logs['workers_with_task_logs'] += 1
        
        task_worker_logs['worker_results'].append(worker_result)
        
        # Continue searching more workers since we can now search terminated ones too
        # Only limit if we've found multiple workers with the task (not just one)
        if worker_result['logs_found'] and task_worker_logs['workers_with_task_logs'] >= 2:
            print(f"   💡 Found task logs in {task_worker_logs['workers_with_task_logs']} workers, limiting search for performance")
            break
    
    return task_worker_logs


def format_worker_task_results(worker_results: Dict[str, Any], output_format: str = 'text') -> str:
    """Format worker task search results"""
    if output_format == 'json':
        return json.dumps(worker_results, indent=2, default=str)
    
    # Text format
    output = []
    output.append(f"\n🤖 Worker Log Analysis for Task {worker_results['task_id']}")
    output.append("=" * 80)
    
    if worker_results.get('target_worker_approach'):
        output.append(f"🎯 Targeted Search (found worker from database):")
        output.append(f"   Target worker: {worker_results.get('target_worker_id')}")
    else:
        output.append(f"🔍 Comprehensive Search (searched all workers):")
    
    output.append(f"📊 Summary:")
    output.append(f"   Workers searched: {worker_results['workers_searched']}")
    output.append(f"   Workers with task logs: {worker_results['workers_with_task_logs']}")
    output.append(f"   Total task entries found: {worker_results['total_task_entries']}")
    
    for worker_result in worker_results['worker_results']:
        if worker_result.get('logs_found'):
            search_method = worker_result.get('search_method', 'Unknown')
            worker_status = worker_result.get('worker_status', 'Unknown')
            output.append(f"\n🔍 Worker: {worker_result.get('target_worker_id', worker_result.get('worker_id'))} (status: {worker_status})")
            output.append(f"   Search method: {search_method}")
            output.append(f"   Found {len(worker_result.get('task_entries', []))} task-related log entries:")
            
            for entry in worker_result.get('task_entries', []):
                output.append(f"   [{entry['line_number']:>6}] {entry['source']} | {entry['content']}")
        elif worker_result.get('s3_error'):
            output.append(f"\n🔍 Worker: {worker_result.get('target_worker_id', worker_result.get('worker_id'))} (status: {worker_result.get('worker_status', 'Unknown')})")
            output.append(f"   S3 log search failed: {worker_result['s3_error']}")
        elif worker_result.get('error'):
            output.append(f"\n🔍 Worker: {worker_result.get('target_worker_id')} - {worker_result['error']}")
    
    return '\n'.join(output)


def format_output(entries: List[Dict[str, Any]], output_format: str = 'text') -> str:
    """Format log entries for output"""
    if output_format == 'json':
        return json.dumps(entries, indent=2, default=str)
    
    # Text format
    output = []
    for entry in entries:
        line_marker = "➤" if entry.get('is_match') else " "
        timestamp = entry.get('timestamp', 'N/A')
        line_num = entry.get('line_number', 'N/A')
        message = entry.get('message', entry.get('raw_line', ''))
        
        output.append(f"{line_marker} [{line_num:>6}] {timestamp} | {message}")
    
    return '\n'.join(output)


def print_timeline(timeline: Dict[str, Any]):
    """Print a formatted timeline summary"""
    print(f"\n📋 Task Timeline: {timeline['task_id']}")
    print("=" * 80)
    
    print(f"📊 Summary:")
    print(f"   Total log entries: {timeline['total_entries']}")
    print(f"   First seen: {timeline['first_seen'] or 'N/A'}")
    print(f"   Last seen: {timeline['last_seen'] or 'N/A'}")
    
    if timeline['status_changes']:
        print(f"\n📈 Status Changes:")
        for change in timeline['status_changes']:
            print(f"   {change['timestamp']} | {change['status'].upper()} | {change['message']}")
    
    if timeline['errors']:
        print(f"\n❌ Errors ({len(timeline['errors'])}):")
        for error in timeline['errors']:
            print(f"   [{error.get('line_number', 'N/A')}] {error['timestamp']} | {error['message']}")
    
    if timeline['key_events']:
        print(f"\n🔑 Key Events:")
        for event in timeline['key_events'][-10:]:  # Show last 10 events
            print(f"   [{event.get('line_number', 'N/A')}] {event['timestamp']} | {event['message']}")


def main():
    parser = argparse.ArgumentParser(description='Fetch comprehensive task logs from orchestrator and worker machines')
    parser.add_argument('task_id', help='Task ID to search for')
    parser.add_argument('--lines', '-n', type=int, default=50, help='Maximum number of lines to show (default: 50, 0 for all)')
    parser.add_argument('--context', '-c', type=int, default=2, help='Number of context lines around matches (default: 2)')
    parser.add_argument('--output', '-o', help='Save output to file')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text', help='Output format (default: text)')
    parser.add_argument('--timeline', '-t', action='store_true', help='Show timeline summary')
    parser.add_argument('--log-file', '-l', default='orchestrator.log', help='Path to orchestrator log file (default: orchestrator.log)')
    parser.add_argument('--worker-logs', action='store_true', help='Fetch detailed worker logs for the task')
    
    args = parser.parse_args()
    
    # Run async main
    asyncio.run(main_async(args))


async def main_async(args):
    """Async main function to handle worker log searching"""
    
    # Check if log file exists
    if not os.path.exists(args.log_file):
        print(f"❌ Log file not found: {args.log_file}")
        print("💡 Make sure you're running from the project root directory")
        return
    
    # Check required environment variables for worker logs
    if args.worker_logs:
        if not os.getenv('RUNPOD_API_KEY'):
            print("❌ RUNPOD_API_KEY environment variable is required for worker log search")
            return
        if not os.getenv('SUPABASE_URL'):
            print("❌ SUPABASE_URL environment variable is required for worker log search")
            return
    
    # Parse orchestrator logs
    parser_obj = TaskLogParser(args.log_file)
    
    print(f"🔍 Comprehensive task analysis for: {args.task_id}")
    print(f"📁 Orchestrator log: {args.log_file}")
    print(f"📝 Context lines: {args.context}")
    if args.worker_logs:
        print(f"🤖 Worker logs: enabled")
    print()
    
    # Get orchestrator task entries
    entries = parser_obj.find_task_logs(args.task_id, context_lines=args.context)
    
    # Limit lines if specified
    if args.lines > 0:
        entries = entries[-args.lines:]
    
    # Show timeline if requested
    timeline = None
    if args.timeline:
        timeline = parser_obj.get_task_timeline(args.task_id)
        print_timeline(timeline)
        print()
    
    # Search worker logs if requested
    worker_results = None
    if args.worker_logs:
        try:
            # First, try to find the specific worker assigned to this task
            target_worker_id = find_worker_for_task(args.task_id)
            
            if target_worker_id:
                # Search only the specific worker that processed this task
                worker_results = await search_specific_worker_logs_for_task(target_worker_id, args.task_id, args.lines)
                # Convert to the expected format for compatibility with existing display code
                worker_results = {
                    'task_id': args.task_id,
                    'workers_searched': 1,
                    'workers_with_task_logs': 1 if worker_results['logs_found'] else 0,
                    'total_task_entries': worker_results['total_task_entries'],
                    'worker_results': [worker_results] if worker_results['logs_found'] else [],
                    'target_worker_approach': True,
                    'target_worker_id': target_worker_id
                }
            else:
                # Fallback: search all workers (old approach)
                print("   💡 Task not found in database or no worker assigned, falling back to comprehensive search...")
                worker_results = await search_worker_logs_for_task(args.task_id, args.lines)
                worker_results['target_worker_approach'] = False
                
        except Exception as e:
            print(f"❌ Error searching worker logs: {e}")
            worker_results = None
    
    # Combine and display results
    orchestrator_found = len(entries) > 0
    worker_found = worker_results and worker_results['total_task_entries'] > 0
    
    if not orchestrator_found and not worker_found:
        print(f"❌ No log entries found for task ID: {args.task_id}")
        if not args.worker_logs:
            print("💡 Try using --worker-logs to search worker machines")
        return
    
    # Format and display output
    all_output = []
    
    # Orchestrator logs section
    if orchestrator_found:
        formatted_output = format_output(entries, args.format)
        all_output.append(f"📋 Orchestrator Log entries for task {args.task_id} ({len(entries)} entries):")
        all_output.append("=" * 80)
        all_output.append(formatted_output)
        all_output.append("=" * 80)
    else:
        all_output.append(f"📋 No orchestrator log entries found for task {args.task_id}")
    
    # Worker logs section
    if worker_results:
        worker_output = format_worker_task_results(worker_results, args.format)
        all_output.append(worker_output)
    
    combined_output = '\n'.join(all_output)
    
    if args.output:
        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{args.output}_{args.task_id}_{timestamp}.log"
        with open(filename, 'w') as f:
            f.write(f"# Comprehensive Task Logs: {args.task_id}\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write(f"# Orchestrator entries: {len(entries) if orchestrator_found else 0}\n")
            f.write(f"# Worker entries: {worker_results['total_task_entries'] if worker_results else 0}\n")
            f.write(f"# Context lines: {args.context}\n\n")
            f.write(combined_output)
        print(f"💾 Saved to {filename}")
    else:
        # Print to console
        print(combined_output)
    
    # Summary
    print(f"\n✅ Task Analysis Summary:")
    if orchestrator_found:
        print(f"   📋 Orchestrator: {len([e for e in entries if e.get('is_match')])} direct matches, {len(entries)} total entries")
    else:
        print(f"   📋 Orchestrator: No entries found")
    
    if worker_results:
        search_type = "Targeted" if worker_results.get('target_worker_approach') else "Comprehensive"
        print(f"   🤖 Workers ({search_type}): {worker_results['workers_with_task_logs']} workers with logs, {worker_results['total_task_entries']} total entries")
        if worker_results.get('target_worker_id'):
            print(f"   🎯 Target worker: {worker_results['target_worker_id']}")
    elif args.worker_logs:
        print(f"   🤖 Workers: No task entries found")
    else:
        print(f"   🤖 Workers: Not searched (use --worker-logs)")


if __name__ == '__main__':
    main() 