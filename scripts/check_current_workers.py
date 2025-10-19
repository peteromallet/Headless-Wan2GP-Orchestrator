#!/usr/bin/env python3
"""Quick check of current non-terminated workers"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(supabase_url, supabase_key)

print("🔍 CURRENT NON-TERMINATED WORKERS")
print("="*80)

# Get all non-terminated workers
result = supabase.table('workers').select('*') \
    .neq('status', 'terminated') \
    .order('created_at', desc=True) \
    .execute()

workers = result.data or []

if not workers:
    print("No active workers found!")
else:
    print(f"Found {len(workers)} non-terminated workers:")
    print()
    
    for worker in workers:
        created = worker.get('created_at', 'unknown')[:19]
        status = worker.get('status', 'unknown')
        worker_id = worker.get('id', 'unknown')
        last_hb = worker.get('last_heartbeat', 'never')
        if last_hb != 'never':
            last_hb = last_hb[:19]
        
        metadata = worker.get('metadata', {})
        runpod_id = metadata.get('runpod_id', 'N/A')
        
        print(f"Worker: {worker_id}")
        print(f"  Status: {status}")
        print(f"  Created: {created}")
        print(f"  Last heartbeat: {last_hb}")
        print(f"  RunPod ID: {runpod_id}")
        print()





