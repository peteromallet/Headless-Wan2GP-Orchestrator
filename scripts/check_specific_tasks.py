#!/usr/bin/env python3
"""
Check specific tasks by ID to see what happened to them.
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient

def check_specific_task(db, task_id, description=""):
    """Check a specific task by ID."""
    print(f"\n{'='*80}")
    print(f"🔍 Checking task: {task_id}")
    if description:
        print(f"   Description: {description}")
    print('='*80)
    
    try:
        # Get the specific task
        result = db.supabase.table('tasks').select('*').eq('id', task_id).execute()
        
        if result.data and len(result.data) > 0:
            task = result.data[0]
            
            print("\n📋 Task Details:")
            print("-" * 40)
            
            # Key fields
            key_fields = [
                'id', 'task_type', 'status', 'worker_id', 'attempts',
                'created_at', 'updated_at', 'generation_started_at', 
                'generation_processed_at', 'error_message', 'output_location'
            ]
            
            for field in key_fields:
                value = task.get(field)
                if value is not None:
                    print(f"  {field}: {value}")
                else:
                    print(f"  {field}: None")
            
            # Calculate durations
            print("\n⏱️  Timing Analysis:")
            print("-" * 40)
            
            created_at = task.get('created_at')
            started_at = task.get('generation_started_at')
            processed_at = task.get('generation_processed_at')
            
            if created_at:
                created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                print(f"  Created: {created_time}")
                
                if started_at:
                    started_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    queue_duration = (started_time - created_time).total_seconds()
                    print(f"  Started: {started_time}")
                    print(f"  Queue Duration: {queue_duration:.1f} seconds")
                    
                    if processed_at:
                        processed_time = datetime.fromisoformat(processed_at.replace('Z', '+00:00'))
                        processing_duration = (processed_time - started_time).total_seconds()
                        total_duration = (processed_time - created_time).total_seconds()
                        print(f"  Processed: {processed_time}")
                        print(f"  Processing Duration: {processing_duration:.1f} seconds")
                        print(f"  Total Duration: {total_duration:.1f} seconds")
                    else:
                        print("  ⚠️  Never processed (no generation_processed_at)")
                        now = datetime.now()
                        if started_time.tzinfo:
                            now = now.replace(tzinfo=started_time.tzinfo)
                        running_duration = (now - started_time).total_seconds()
                        print(f"  Running Duration: {running_duration:.1f} seconds")
                else:
                    print("  ⚠️  Never started (no generation_started_at)")
                    now = datetime.now()
                    if created_time.tzinfo:
                        now = now.replace(tzinfo=created_time.tzinfo)
                    waiting_duration = (now - created_time).total_seconds()
                    print(f"  Waiting Duration: {waiting_duration:.1f} seconds")
            
            # Show params if available
            params = task.get('params')
            if params:
                print("\n📝 Task Parameters:")
                print("-" * 40)
                if isinstance(params, dict):
                    for key, value in params.items():
                        if len(str(value)) > 100:
                            print(f"  {key}: {str(value)[:100]}...")
                        else:
                            print(f"  {key}: {value}")
                else:
                    print(f"  {params}")
            
            # Show result data if available
            result_data = task.get('result_data')
            if result_data and result_data != {}:
                print("\n📊 Result Data:")
                print("-" * 40)
                if isinstance(result_data, dict):
                    for key, value in result_data.items():
                        if len(str(value)) > 100:
                            print(f"  {key}: {str(value)[:100]}...")
                        else:
                            print(f"  {key}: {value}")
                else:
                    print(f"  {result_data}")
            
            # Status analysis
            print(f"\n📈 Status Analysis:")
            print("-" * 40)
            status = task.get('status', '').lower()
            
            if status == 'complete':
                print("  ✅ Task completed successfully")
                if task.get('output_location'):
                    print(f"  📁 Output available at: {task.get('output_location')}")
                else:
                    print("  ⚠️  No output location recorded")
                    
            elif status == 'failed':
                print("  ❌ Task failed")
                error = task.get('error_message')
                if error:
                    print(f"  💥 Error: {error}")
                else:
                    print("  ⚠️  No error message recorded")
                    
            elif status == 'in progress':
                print("  🔄 Task is currently in progress")
                worker = task.get('worker_id')
                if worker:
                    print(f"  👷 Worker: {worker}")
                else:
                    print("  ⚠️  No worker assigned")
                    
            elif status == 'queued':
                print("  ⏳ Task is waiting in queue")
                
            else:
                print(f"  ❓ Unknown status: {status}")
                
        else:
            print(f"❌ Task {task_id} not found in database")
            
    except Exception as e:
        print(f"❌ Error checking task {task_id}: {e}")
        import traceback
        print(f"Full error: {traceback.format_exc()}")

def main():
    """Check the specific tasks mentioned."""
    db = DatabaseClient()
    
    print("🔍 Checking specific tasks...")
    
    # The tasks to check
    tasks_to_check = [
        ("da2cebe6-e8ab-4580-9a61-06ee7b78b72c", "orchestrator task"),
        ("1360a8f3-447b-4fd2-ae4f-8eedf3259361", "processed successfully + never processed (duplicate ID?)"),
    ]
    
    for task_id, description in tasks_to_check:
        check_specific_task(db, task_id, description)
    
    print(f"\n{'='*80}")
    print("✅ Task analysis complete")

if __name__ == "__main__":
    main()
