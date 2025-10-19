#!/usr/bin/env python3
"""
Deep Dive Worker Status Analysis
=================================

Investigates the worker failure rate and current worker state mismatch.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from supabase import create_client


def main():
    load_dotenv()
    
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    supabase = create_client(supabase_url, supabase_key)
    
    print("="*80)
    print("🔬 DEEP DIVE: WORKER STATUS ANALYSIS")
    print("="*80)
    print()
    
    # 1. Get workers from the last 30 minutes (window for failure rate calculation)
    print("📊 RECENT WORKERS (Last 30 Minutes)")
    print("-"*80)
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        # Get workers created in the last 30 minutes (no updated_at column)
        workers_result = supabase.table('workers').select('*') \
            .gte('created_at', cutoff_time.isoformat()) \
            .order('created_at', desc=True) \
            .execute()
        
        recent_workers = workers_result.data or []
        
        if not recent_workers:
            print("⚠️  No workers found in the last 30 minutes!")
            print("   This is the window used for failure rate calculation.")
        else:
            print(f"Found {len(recent_workers)} workers updated in the last 30 minutes")
        
        if recent_workers:
            print()
            status_counts = {}
            for worker in recent_workers:
                status = worker.get('status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            print("Status breakdown:")
            for status, count in sorted(status_counts.items()):
                print(f"  {status:15} : {count}")
            
            # Calculate failure rate like the orchestrator does
            failed_workers = [w for w in recent_workers if w['status'] in ['error', 'terminated']]
            if len(recent_workers) >= 5:  # MIN_WORKERS_FOR_RATE_CHECK
                failure_rate = len(failed_workers) / len(recent_workers)
                print()
                print(f"📈 FAILURE RATE CALCULATION:")
                print(f"   Total workers: {len(recent_workers)}")
                print(f"   Failed/Terminated: {len(failed_workers)}")
                print(f"   Failure rate: {failure_rate:.2%}")
                print(f"   Threshold: 80.00%")
                
                if failure_rate > 0.80:
                    print(f"   ❌ EXCEEDS THRESHOLD - Worker spawning is BLOCKED")
                else:
                    print(f"   ✅ Within threshold - Spawning allowed")
            else:
                print()
                print(f"⚠️  Not enough recent workers ({len(recent_workers)}) to calculate failure rate (need 5)")
            
            print()
            print("Recent worker details:")
            for i, worker in enumerate(recent_workers[:15]):
                created = worker.get('created_at', 'unknown')[:19]
                status = worker.get('status', 'unknown')
                worker_id = worker.get('id', 'unknown')
                metadata = worker.get('metadata', {})
                error_reason = metadata.get('error_reason', 'N/A')
                runpod_id = metadata.get('runpod_id', 'N/A')
                
                print(f"{i+1:2}. [{created}] {status:12} | {worker_id:30}")
                if status in ['error', 'terminated']:
                    print(f"    RunPod: {runpod_id}")
                    if error_reason != 'N/A':
                        print(f"    Error: {error_reason}")
    
    except Exception as e:
        print(f"❌ Error querying workers: {e}")
    
    print()
    
    # 2. Query the orchestrator logs for the failure rate check
    print("📋 ORCHESTRATOR FAILURE RATE CHECKS (Last Hour)")
    print("-"*80)
    try:
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        logs_result = supabase.table('system_logs') \
            .select('*') \
            .eq('source_type', 'orchestrator_gpu') \
            .gte('timestamp', start_time.isoformat()) \
            .like('message', '%FAILURE_RATE%') \
            .order('timestamp', desc=True) \
            .limit(20) \
            .execute()
        
        logs = logs_result.data or []
        
        if not logs:
            print("⚠️  No failure rate logs found")
        else:
            print(f"Found {len(logs)} failure rate log entries")
            print()
            
            for log in logs[:10]:
                timestamp = log['timestamp'][:19].replace('T', ' ')
                message = log['message']
                print(f"  [{timestamp}] {message}")
    
    except Exception as e:
        print(f"❌ Error querying failure rate logs: {e}")
    
    print()
    
    # 3. Check if there are actually any active workers
    print("🔍 NON-TERMINATED WORKERS")
    print("-"*80)
    try:
        active_result = supabase.table('workers').select('*') \
            .neq('status', 'terminated') \
            .order('created_at', desc=True) \
            .execute()
        
        active_workers = active_result.data or []
        
        if not active_workers:
            print("⚠️  No active/spawning/error workers found in database!")
            print("   The orchestrator thinks it has 1 active worker but database shows none.")
            print()
            print("   This suggests:")
            print("   - The orchestrator may be reading stale data")
            print("   - OR a worker was just terminated between checks")
            print("   - OR there's a sync issue between orchestrator and database")
        else:
            print(f"Found {len(active_workers)} non-terminated workers:")
            print()
            
            for worker in active_workers:
                created = worker.get('created_at', 'unknown')[:19]
                status = worker.get('status', 'unknown')
                worker_id = worker.get('id', 'unknown')
                last_hb = worker.get('last_heartbeat', 'never')
                if last_hb != 'never':
                    last_hb = last_hb[:19]
                
                metadata = worker.get('metadata', {})
                runpod_id = metadata.get('runpod_id', 'N/A')
                
                print(f"  [{created}] {status:12} | {worker_id:30}")
                print(f"    Last heartbeat: {last_hb}")
                print(f"    RunPod ID: {runpod_id}")
                print()
    
    except Exception as e:
        print(f"❌ Error querying active workers: {e}")
    
    print()
    
    # 4. Show the latest scaling decisions with full context
    print("🎯 LATEST SCALING DECISION (Full Context)")
    print("-"*80)
    try:
        # Get the most recent cycle number
        cycle_result = supabase.table('system_logs') \
            .select('cycle_number') \
            .eq('source_type', 'orchestrator_gpu') \
            .not_.is_('cycle_number', 'null') \
            .order('cycle_number', desc=True) \
            .limit(1) \
            .execute()
        
        if cycle_result.data:
            latest_cycle = cycle_result.data[0]['cycle_number']
            
            # Get all logs from this cycle
            cycle_logs = supabase.table('system_logs') \
                .select('*') \
                .eq('source_type', 'orchestrator_gpu') \
                .eq('cycle_number', latest_cycle) \
                .order('timestamp', desc=False) \
                .execute()
            
            logs = cycle_logs.data or []
            
            print(f"Cycle #{latest_cycle} ({len(logs)} log entries)")
            print()
            
            for log in logs:
                timestamp = log['timestamp'][:19].replace('T', ' ')
                level = log['log_level']
                message = log['message']
                print(f"  [{timestamp}] [{level:8}] {message}")
    
    except Exception as e:
        print(f"❌ Error querying latest cycle: {e}")
    
    print()
    print("="*80)
    print("✅ Analysis complete")
    print()
    print("💡 DIAGNOSIS:")
    print("   The orchestrator has a HIGH FAILURE RATE (>80%) for recent workers.")
    print("   This is a SAFETY MECHANISM to prevent endless worker spin-ups.")
    print()
    print("   Common causes:")
    print("   1. SSH authentication failures (missing/invalid SSH keys)")
    print("   2. Docker image issues (image not pulling correctly)")
    print("   3. Worker initialization failures (code bugs, missing dependencies)")
    print("   4. Network issues preventing worker startup")
    print()
    print("💡 NEXT STEPS:")
    print("   1. Check recent worker error reasons above")
    print("   2. Verify SSH keys are configured correctly in environment")
    print("   3. Check if RunPod pods are actually starting")
    print("   4. Review worker initialization logs")
    print("   5. Once root cause is fixed, old terminated workers will age out")
    print("      and failure rate will drop below 80%")
    print("="*80)


if __name__ == "__main__":
    main()

