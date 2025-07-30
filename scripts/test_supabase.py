#!/usr/bin/env python3
"""
Test script for Supabase connection and basic database operations.
"""

import os
import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from supabase import create_client, Client

async def test_supabase_connection():
    """Test basic Supabase connection and operations."""
    
    print("🧪 Testing Supabase Connection...")
    print("=" * 50)
    
    # Load environment
    load_dotenv()
    
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env file")
        return False
    
    try:
        # Create client
        supabase: Client = create_client(supabase_url, supabase_key)
        print(f"✅ Connected to Supabase at {supabase_url}")
        
        # Test 1: Check if orchestrator_status view exists
        print("\n📊 Testing orchestrator_status view...")
        try:
            result = supabase.table('orchestrator_status').select('*').execute()
            print(f"✅ orchestrator_status view accessible")
            print(f"   Current status: {json.dumps(result.data[0] if result.data else {}, indent=2)}")
        except Exception as e:
            print(f"❌ orchestrator_status view error: {e}")
            print("   💡 Run 'python scripts/setup_database.py' to create the schema")
        
        # Test 2: Check workers table
        print("\n👷 Testing workers table...")
        try:
            result = supabase.table('workers').select('*').limit(5).execute()
            print(f"✅ workers table accessible ({len(result.data or [])} records)")
            if result.data:
                for worker in result.data:
                    print(f"   Worker: {worker['id']} - {worker['status']}")
        except Exception as e:
            print(f"❌ workers table error: {e}")
        
        # Test 3: Check tasks table
        print("\n📋 Testing tasks table...")
        try:
            result = supabase.table('tasks').select('*').limit(5).execute()
            print(f"✅ tasks table accessible ({len(result.data or [])} records)")
            if result.data:
                task_counts = {}
                for task in result.data:
                    status = task['status']
                    task_counts[status] = task_counts.get(status, 0) + 1
                print(f"   Task status counts: {task_counts}")
        except Exception as e:
            print(f"❌ tasks table error: {e}")
        
        # Test RPC functions
        print("\n🔧 Testing RPC functions...")
        try:
            # Test heartbeat function
            result = supabase.rpc('func_update_worker_heartbeat', {
                'worker_id_param': f'test-worker-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                'vram_total_mb_param': 8192,
                'vram_used_mb_param': 4096
            }).execute()
            
            print("✅ RPC functions working correctly")
        except Exception as e:
            print(f"❌ RPC function error: {e}")
            if hasattr(e, 'message'):
                print(f"   💡 Run the SQL migrations to create RPC functions")
        
        # Test 5: Test active_workers_health view
        print("\n💚 Testing active_workers_health view...")
        try:
            result = supabase.table('active_workers_health').select('*').execute()
            print(f"✅ active_workers_health view accessible ({len(result.data or [])} workers)")
            for worker in (result.data or [])[:3]:  # Show first 3
                print(f"   {worker['id']}: {worker['health_status']} (heartbeat: {worker.get('heartbeat_age_seconds', 'N/A')}s ago)")
        except Exception as e:
            print(f"❌ active_workers_health view error: {e}")
        
        print("\n🎉 Supabase connection test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return False

async def create_test_task():
    """Create a test task for testing worker functionality."""
    
    print("\n🧪 Creating test task...")
    
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ Supabase credentials not configured")
        return
    
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        
        # Create a test task
        test_task = {
            'status': 'Queued',
            'task_data': {
                'type': 'test',
                'processing_time': 15,  # 15 seconds
                'description': 'Test task created by test_supabase.py'
            }
        }
        
        result = supabase.table('tasks').insert(test_task).execute()
        
        if result.data:
            task_id = result.data[0]['id']
            print(f"✅ Created test task: {task_id}")
            print(f"   Task data: {json.dumps(test_task['task_data'], indent=2)}")
        else:
            print("❌ Failed to create test task")
    
    except Exception as e:
        print(f"❌ Error creating test task: {e}")

def main():
    """Main function with command line options."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Supabase connection and database operations")
    parser.add_argument(
        "--create-task",
        action="store_true",
        help="Create a test task for worker testing"
    )
    
    args = parser.parse_args()
    
    # Run the main test
    success = asyncio.run(test_supabase_connection())
    
    # Create test task if requested
    if args.create_task:
        asyncio.run(create_test_task())
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 