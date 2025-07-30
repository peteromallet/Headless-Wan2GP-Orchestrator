#!/usr/bin/env python3
"""
Check existing tasks in the database.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from orchestrator.database import DatabaseClient

def check_tasks():
    """Check existing tasks and their structure."""
    db = DatabaseClient()
    
    print("📋 Checking existing tasks...")
    
    try:
        # Get a sample task to see the structure
        result = db.supabase.table('tasks').select('*').limit(1).execute()
        
        if result.data and len(result.data) > 0:
            task = result.data[0]
            print("\nSample task structure:")
            for key, value in task.items():
                print(f"  {key}: {value} ({type(value).__name__})")
            
            # Get project_id from the sample
            project_id = task.get('project_id')
            if project_id:
                print(f"\n✅ Found project_id: {project_id}")
                print("   You can use this project_id for creating test tasks")
            else:
                print("\n⚠️  No project_id found in sample task")
        else:
            print("❌ No tasks found in database")
            
    except Exception as e:
        print(f"❌ Error checking tasks: {e}")

if __name__ == "__main__":
    check_tasks() 