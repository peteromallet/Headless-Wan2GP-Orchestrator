#!/usr/bin/env python3
"""
Test the claim_next_task edge function to see what it returns.
This script will call the edge function in both dry_run mode (to check available tasks)
and actual claim mode (to see what task gets returned).
"""

import os
import sys
import json
import argparse
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient
from dotenv import load_dotenv

load_dotenv()

async def test_claim_next_task(worker_id: str = "test-worker-001", dry_run: bool = False):
    """
    Test the claim_next_task edge function.
    
    Args:
        worker_id: Worker ID to use for claiming tasks
        dry_run: If True, only check available tasks without claiming
    """
    
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ Missing Supabase credentials")
        print("   Make sure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set")
        return None
    
    edge_function_url = f"{supabase_url}/functions/v1/claim-next-task"
    
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "worker_id": worker_id,
        "dry_run": dry_run
    }
    
    print(f"🚀 Testing claim_next_task edge function...")
    print(f"   URL: {edge_function_url}")
    print(f"   Worker ID: {worker_id}")
    print(f"   Dry run: {dry_run}")
    print()
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(edge_function_url, headers=headers, json=payload) as response:
                print(f"📊 Response status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Response data:")
                    print(json.dumps(data, indent=2))
                    
                    # Extract key information
                    if dry_run:
                        available_tasks = data.get("available_tasks", 0)
                        print(f"\n📈 Available tasks: {available_tasks}")
                        return available_tasks
                    else:
                        # For actual claiming, the edge function returns the task data directly
                        if data.get("task_id"):
                            task_id = data.get("task_id")
                            task_type = data.get("task_type")
                            print(f"\n🎯 Claimed task: {task_id}")
                            print(f"   Type: {task_type}")
                            return data
                        else:
                            print(f"\n❌ No task was claimed (no available tasks)")
                            return None
                else:
                    error_text = await response.text()
                    print(f"❌ Error response: {error_text}")
                    return None
                    
    except Exception as e:
        print(f"❌ Exception calling edge function: {e}")
        return None

async def test_available_tasks_count():
    """Test the existing count_available_tasks_via_edge_function method."""
    print("🔍 Testing available tasks count via DatabaseClient...")
    
    try:
        db = DatabaseClient()
        
        # Test with include_active=True (default)
        count_with_active = await db.count_available_tasks_via_edge_function(include_active=True)
        print(f"📊 Available tasks (including active): {count_with_active}")
        
        # Test with include_active=False (only queued)
        count_queued_only = await db.count_available_tasks_via_edge_function(include_active=False)
        print(f"📊 Available tasks (queued only): {count_queued_only}")
        
        return count_with_active, count_queued_only
        
    except Exception as e:
        print(f"❌ Error testing DatabaseClient method: {e}")
        return None, None

async def show_task_queue_status():
    """Show current task queue status from database."""
    print("📋 Current task queue status...")
    
    try:
        db = DatabaseClient()
        
        # Get task counts by status
        result = db.supabase.table('tasks').select('status').execute()
        
        if result.data:
            status_counts = {}
            for task in result.data:
                status = task['status']
                status_counts[status] = status_counts.get(status, 0) + 1
            
            print("   Task counts by status:")
            for status, count in sorted(status_counts.items()):
                print(f"     {status}: {count}")
        else:
            print("   No tasks found in database")
            
        # Get recent tasks
        recent_result = db.supabase.table('tasks').select('id, task_type, status, created_at, worker_id').order('created_at', desc=True).limit(5).execute()
        
        if recent_result.data:
            print(f"\n   Recent tasks (last 5):")
            for task in recent_result.data:
                created_at = task.get('created_at', 'unknown')
                worker_id = task.get('worker_id', 'none')
                print(f"     {task['id'][:8]}... | {task['status']} | {task.get('task_type', 'unknown')} | worker: {worker_id} | {created_at}")
        
    except Exception as e:
        print(f"❌ Error getting task queue status: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Test the claim_next_task edge function")
    parser.add_argument('--worker-id', '-w', default='test-worker-001', help='Worker ID to use (default: test-worker-001)')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Only check available tasks without claiming')
    parser.add_argument('--claim', '-c', action='store_true', help='Actually claim a task (default behavior)')
    parser.add_argument('--status-only', '-s', action='store_true', help='Only show task queue status')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🧪 CLAIM_NEXT_TASK EDGE FUNCTION TEST")
    print("=" * 60)
    print()
    
    # Show current queue status
    await show_task_queue_status()
    print()
    
    if args.status_only:
        return
    
    # Test the DatabaseClient method first
    await test_available_tasks_count()
    print()
    
    # Test the edge function directly
    if args.dry_run:
        print("🔍 Testing dry run (check available tasks)...")
        result = await test_claim_next_task(args.worker_id, dry_run=True)
    else:
        print("🎯 Testing actual task claiming...")
        result = await test_claim_next_task(args.worker_id, dry_run=False)
    
    print()
    print("=" * 60)
    print("✅ Test completed!")
    
    if result is not None:
        if isinstance(result, int):
            print(f"🔢 Number returned: {result}")
        else:
            print(f"📦 Object returned: {type(result).__name__}")
    else:
        print("❌ No result returned")

if __name__ == "__main__":
    asyncio.run(main())
