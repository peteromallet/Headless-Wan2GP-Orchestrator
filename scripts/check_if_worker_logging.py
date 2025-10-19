#!/usr/bin/env python3
"""
Check if a worker has started logging (i.e., worker.py is running).
Usage: python3 scripts/check_if_worker_logging.py WORKER_ID
"""

import sys
import os
from dotenv import load_dotenv
from supabase import create_client

def check_worker_logging(worker_id: str):
    load_dotenv()
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Check for logs from worker.py (these have worker_id set, not just mentioned in message)
    result = supabase.table('system_logs').select('timestamp, message, log_level').eq('worker_id', worker_id).order('timestamp', desc=True).limit(10).execute()
    
    print('='*80)
    print(f'WORKER LOGGING CHECK: {worker_id}')
    print('='*80)
    
    if not result.data:
        print('❌ Worker is NOT logging yet')
        print('   This means worker.py has not started or crashed during initialization')
        print('\nNext steps:')
        print('  1. Check worker status: python3 scripts/check_worker_status.py', worker_id)
        print('  2. Check startup log: python3 scripts/get_worker_startup_log.py', worker_id)
        print('  3. Wait if worker is < 10 minutes old (might be installing dependencies)')
        return False
    
    print(f'✅ Worker IS logging! Total logs: {len(result.data)}')
    print(f'\nMost recent logs:')
    print('-'*80)
    
    for log in result.data[:5]:
        time = log['timestamp'][-12:-4]
        level = log['log_level']
        msg = log['message'][:70]
        print(f'[{level:7}] {time} | {msg}')
    
    return True

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python3 scripts/check_if_worker_logging.py WORKER_ID')
        sys.exit(1)
    
    is_logging = check_worker_logging(sys.argv[1])
    sys.exit(0 if is_logging else 1)

