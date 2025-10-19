#!/usr/bin/env python3
"""
List all recent workers with their status.
Usage: python3 scripts/list_recent_workers.py [--hours HOURS]
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpu_orchestrator.database import DatabaseClient

def list_recent_workers(hours: int = 2):
    db = DatabaseClient()
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    result = db.supabase.table('workers').select('id, status, created_at, last_heartbeat, metadata').gte('created_at', cutoff_time.isoformat()).order('created_at', desc=True).execute()
    
    now = datetime.now(timezone.utc)
    
    print('='*80)
    print(f'RECENT WORKERS (last {hours} hours)')
    print('='*80)
    print(f'Total: {len(result.data)}\n')
    
    if not result.data:
        print('No workers found')
        return
    
    for w in result.data:
        worker_id = w['id']
        created = datetime.fromisoformat(w['created_at'].replace('Z', '+00:00'))
        age_min = (now - created).total_seconds() / 60
        
        # Heartbeat status
        last_hb = w.get('last_heartbeat')
        hb_status = '❓'
        hb_info = 'no HB'
        
        if last_hb:
            last_hb_time = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
            hb_age_min = (now - last_hb_time).total_seconds() / 60
            
            if hb_age_min < 1:
                hb_status = '✅'
            elif hb_age_min < 5:
                hb_status = '⚠️'
            elif hb_age_min < 10:
                hb_status = '🔴'
            else:
                hb_status = '❌'
            
            hb_info = f'HB {hb_age_min:.1f}m ago'
        
        metadata = w.get('metadata', {})
        ram_tier = metadata.get('ram_tier', '?')
        
        print(f'{hb_status} {worker_id}')
        print(f'   Status: {w["status"]:10} | Age: {age_min:.1f}m | {hb_info} | RAM: {ram_tier}GB')
        print()

if __name__ == '__main__':
    hours = 2
    
    if '--hours' in sys.argv:
        hours_idx = sys.argv.index('--hours')
        if hours_idx + 1 < len(sys.argv):
            hours = int(sys.argv[hours_idx + 1])
    
    list_recent_workers(hours)

