#!/usr/bin/env python3
"""
Create test tasks in Supabase for testing the orchestrator.
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient

async def create_test_tasks(count: int = 1, task_type: str = "test", project_id: str = None):
    """Create test tasks in the database."""
    db = DatabaseClient()
    
    # If no project_id provided, try to get one from existing tasks
    if not project_id:
        try:
            result = db.supabase.table('tasks').select('project_id').limit(1).execute()
            if result.data and len(result.data) > 0:
                project_id = result.data[0]['project_id']
                print(f"📝 Using project_id from existing task: {project_id}")
            else:
                print("❌ No project_id provided and no existing tasks found")
                print("   Please provide a project_id using --project-id flag")
                return []
        except Exception as e:
            print(f"❌ Error getting project_id: {e}")
            return []
    
    print(f"🚀 Creating {count} test task(s) of type '{task_type}'...")
    
    created_tasks = []
    for i in range(count):
        try:
            task_data = {
                'task_type': task_type,
                'project_id': project_id,
                'params': {
                    'test_number': i + 1,
                    'processing_time': 30,  # seconds
                    'description': f'Test task {i + 1} created at {datetime.now(timezone.utc).isoformat()}'
                },
                'status': 'Queued',
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            
            result = db.supabase.table('tasks').insert(task_data).execute()
            
            if result.data:
                task_id = result.data[0]['id']
                created_tasks.append(task_id)
                print(f"✅ Created task {task_id}")
            else:
                print(f"❌ Failed to create task {i + 1}")
                
        except Exception as e:
            print(f"❌ Error creating task {i + 1}: {e}")
    
    if created_tasks:
        print(f"\n🎉 Successfully created {len(created_tasks)} task(s)")
        print("\nCreated task IDs:")
        for task_id in created_tasks:
            print(f"  - {task_id}")
    else:
        print("\n❌ No tasks were created")
    
    return created_tasks

async def main():
    parser = argparse.ArgumentParser(description="Create test tasks for the orchestrator")
    parser.add_argument('--count', '-n', type=int, default=1, help='Number of tasks to create (default: 1)')
    parser.add_argument('--type', '-t', default='test', help='Task type (default: test)')
    parser.add_argument('--project-id', '-p', help='Project ID to associate tasks with (optional)')
    
    args = parser.parse_args()
    
    await create_test_tasks(args.count, args.type, args.project_id)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 