#!/usr/bin/env python3
"""
Monitor a worker until it starts logging or fails.
Polls every 30 seconds and shows progress.
Usage: python3 scripts/monitor_worker.py WORKER_ID [--timeout MINUTES]
"""

import sys
import os
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gpu_orchestrator.database import DatabaseClient

def monitor_worker(worker_id: str, timeout_minutes: int = 15):
    load_dotenv()
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    db = DatabaseClient()
    
    print('='*80)
    print(f'MONITORING WORKER: {worker_id}')
    print(f'Timeout: {timeout_minutes} minutes')
    print('='*80)
    
    start_time = time.time()
    iteration = 0
    
    while True:
        iteration += 1
        elapsed_min = (time.time() - start_time) / 60
        
        if elapsed_min > timeout_minutes:
            print(f'\n⏱️  Monitoring timeout reached ({timeout_minutes} min)')
            break
        
        print(f'\n[Check #{iteration}] Elapsed: {elapsed_min:.1f} min')
        print('-'*80)
        
        # Check worker status
        worker = db.supabase.table('workers').select('status, last_heartbeat, created_at').eq('id', worker_id).execute()
        
        if not worker.data:
            print(f'❌ Worker not found - may have been deleted')
            break
        
        w = worker.data[0]
        print(f'Status: {w["status"]}')
        
        if w.get('last_heartbeat'):
            hb = datetime.fromisoformat(w['last_heartbeat'].replace('Z', '+00:00'))
            hb_age = (datetime.now(timezone.utc) - hb).total_seconds() / 60
            print(f'Heartbeat: {hb_age:.1f} min ago')
        
        # Check if logging
        logs = supabase.table('system_logs').select('timestamp').eq('worker_id', worker_id).limit(1).execute()
        
        if logs.data:
            print(f'\n🎉 SUCCESS! Worker is logging!')
            print(f'   Worker started after {elapsed_min:.1f} minutes')
            
            # Show first few logs
            recent = supabase.table('system_logs').select('timestamp, message').eq('worker_id', worker_id).order('timestamp').limit(3).execute()
            print(f'\nFirst logs:')
            for log in recent.data:
                print(f'  {log["timestamp"][-12:-4]} | {log["message"][:70]}')
            break
        
        # Check for termination
        if w['status'] in ['terminated', 'error']:
            print(f'\n❌ Worker terminated with status: {w["status"]}')
            print(f'   Checking startup log for errors...')
            
            startup = supabase.table('system_logs').select('message').ilike('message', f'%{worker_id}%').ilike('message', '%startup log%').execute()
            
            if startup.data:
                log_content = startup.data[0]['message']
                if 'ModuleNotFoundError' in log_content or 'died immediately' in log_content:
                    print(f'\n   📋 Error found in startup log:')
                    # Extract the error
                    lines = log_content.split('\n')
                    for i, line in enumerate(lines):
                        if 'Traceback' in line or 'Error' in line:
                            print('   ' + '\n   '.join(lines[i:min(i+10, len(lines))]))
                            break
            break
        
        print(f'⏳ Still initializing... (waiting 30s)')
        time.sleep(30)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 scripts/monitor_worker.py WORKER_ID [--timeout MINUTES]')
        sys.exit(1)
    
    worker_id = sys.argv[1]
    timeout = 15
    
    if '--timeout' in sys.argv:
        timeout_idx = sys.argv.index('--timeout')
        if timeout_idx + 1 < len(sys.argv):
            timeout = int(sys.argv[timeout_idx + 1])
    
    monitor_worker(worker_id, timeout)

