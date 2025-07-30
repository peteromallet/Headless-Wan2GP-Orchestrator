#!/usr/bin/env python3
"""
Database setup script for Runpod GPU Worker Orchestrator.
Runs all SQL files to create tables, functions, and views.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

def setup_database():
    """Set up the database schema by running SQL files in order."""
    
    # Load environment variables
    load_dotenv()
    
    # Get Supabase credentials
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env file")
        sys.exit(1)
    
    # Create Supabase client
    supabase: Client = create_client(supabase_url, supabase_key)
    
    # Get SQL files directory
    sql_dir = Path(__file__).parent.parent / "sql"
    
    # SQL files in execution order
    sql_files = [
        "01_create_enums.sql",
        "02_create_workers_table.sql", 
        "03_create_or_update_tasks_table.sql",
        "04_create_rpc_functions.sql",
        "05_create_monitoring_views.sql"
    ]
    
    print("Setting up database schema...")
    
    for sql_file in sql_files:
        file_path = sql_dir / sql_file
        
        if not file_path.exists():
            print(f"Warning: {sql_file} not found, skipping...")
            continue
            
        print(f"Executing {sql_file}...")
        
        # Read and print SQL file content for manual execution
        with open(file_path, 'r') as f:
            sql_content = f.read()
        
        print(f"\n--- Copy and paste this into your Supabase SQL Editor ---")
        print(f"-- File: {sql_file}")
        print(sql_content)
        print(f"-- End of {sql_file}")
        print("-" * 60)
    
    # Test the setup by querying the monitoring view
    try:
        result = supabase.table('orchestrator_status').select('*').execute()
        print("✅ Database setup completed successfully!")
        print("📊 Current status:", result.data[0] if result.data else "No data yet")
        
    except Exception as e:
        print(f"⚠️  Setup may be incomplete. Error testing monitoring view: {e}")
        print("Please run the SQL files manually in your Supabase SQL editor if needed.")

if __name__ == "__main__":
    setup_database() 