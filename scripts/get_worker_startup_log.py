#!/usr/bin/env python3
"""
Get the startup log for a worker (shows installation process).
Usage: python3 scripts/get_worker_startup_log.py WORKER_ID
"""

import sys
import os
from dotenv import load_dotenv
from supabase import create_client

def get_startup_log(worker_id: str):
    load_dotenv()
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Find startup log
    result = supabase.table('system_logs').select('timestamp, message').ilike('message', f'%{worker_id}%').ilike('message', '%startup log%').order('timestamp', desc=True).limit(1).execute()
    
    if not result.data:
        print(f'❌ No startup log found for worker {worker_id}')
        print(f'   This means either:')
        print(f'   1. Worker was created before log retrieval feature was added')
        print(f'   2. Worker is still being provisioned (SSH not available yet)')
        print(f'   3. Startup script has not completed yet')
        return
    
    log = result.data[0]
    print('='*80)
    print(f'STARTUP LOG FOR: {worker_id}')
    print(f'Retrieved at: {log["timestamp"]}')
    print('='*80)
    print(log['message'])
    print('='*80)
    
    # Check for common issues
    content = log['message']
    
    if 'ModuleNotFoundError' in content:
        print('\n⚠️  ISSUE DETECTED: Missing Python module')
        print('   Worker crashed due to missing dependencies')
    elif 'died immediately' in content:
        print('\n❌ ISSUE DETECTED: Worker process died immediately')
        print('   Check the traceback above for the error')
    elif 'still running after 2 seconds' in content:
        print('\n✅ Worker process started successfully')
    elif 'Installing PyTorch' in content:
        print('\n⏳ Worker is/was installing dependencies')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python3 scripts/get_worker_startup_log.py WORKER_ID')
        sys.exit(1)
    
    get_startup_log(sys.argv[1])

