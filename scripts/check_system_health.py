#!/usr/bin/env python3
"""
Quick system health check script.
Run this anytime to see current worker status and failure rate.
"""

import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient


async def check_system_health():
    """Check overall system health."""
    db = DatabaseClient()
    
    print("=" * 80)
    print("🔍 SYSTEM HEALTH CHECK")
    print("=" * 80)
    print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    # 1. Get current workers
    print("📊 WORKER STATUS")
    print("-" * 80)
    workers = await db.get_workers(['active', 'spawning', 'terminating'])
    
    if not workers:
        print("⚠️  No active workers found!")
    else:
        print(f"Total active/spawning workers: {len(workers)}")
        print()
        
        for w in workers:
            worker_id = w['id']
            status = w['status']
            created = w.get('created_at', 'N/A')
            last_hb = w.get('last_heartbeat')
            
            print(f"  Worker: {worker_id}")
            print(f"    Status: {status}")
            
            if last_hb:
                try:
                    hb_dt = datetime.fromisoformat(last_hb.replace('Z', '+00:00'))
                    age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
                    
                    if age < 60:
                        health = "✅ HEALTHY"
                    elif age < 300:
                        health = "⚠️  WARNING"
                    else:
                        health = "❌ STALE"
                    
                    print(f"    Last heartbeat: {age:.0f}s ago {health}")
                except Exception as e:
                    print(f"    Last heartbeat: Error parsing ({e})")
            else:
                try:
                    created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    age = (datetime.now(timezone.utc) - created_dt).total_seconds()
                    
                    if age < 300:
                        print(f"    Last heartbeat: None (still initializing, {age:.0f}s old)")
                    else:
                        print(f"    Last heartbeat: ❌ None after {age:.0f}s - likely failed")
                except:
                    print(f"    Last heartbeat: None")
            print()
    
    # 2. Check failure rate
    print("📈 FAILURE RATE ANALYSIS")
    print("-" * 80)
    
    failure_window_minutes = int(os.getenv("FAILURE_WINDOW_MINUTES", "30"))
    max_failure_rate = float(os.getenv("MAX_WORKER_FAILURE_RATE", "0.8"))
    min_workers_for_check = int(os.getenv("MIN_WORKERS_FOR_RATE_CHECK", "5"))
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=failure_window_minutes)
    
    recent_workers = []
    all_workers = await db.get_workers(['spawning', 'active', 'terminating', 'error', 'terminated'])
    
    for worker in all_workers:
        worker_time = worker.get('updated_at', worker.get('created_at'))
        if worker_time:
            try:
                worker_dt = datetime.fromisoformat(worker_time.replace('Z', '+00:00'))
                if worker_dt > cutoff_time:
                    recent_workers.append(worker)
            except:
                pass
    
    print(f"Window: Last {failure_window_minutes} minutes")
    print(f"Workers in window: {len(recent_workers)}")
    
    if len(recent_workers) < min_workers_for_check:
        print(f"✅ Not enough workers ({len(recent_workers)} < {min_workers_for_check}) to calculate rate")
        print(f"   Spawning: ALLOWED")
    else:
        # Count by status
        status_counts = {}
        for w in recent_workers:
            status = w['status']
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print("\nBreakdown by status:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")
        
        failed_workers = [w for w in recent_workers if w['status'] in ['error', 'terminated']]
        failure_rate = len(failed_workers) / len(recent_workers)
        
        print(f"\nFailure rate: {len(failed_workers)}/{len(recent_workers)} = {failure_rate:.1%}")
        print(f"Threshold: {max_failure_rate:.0%}")
        
        if failure_rate > max_failure_rate:
            print(f"❌ BLOCKING: Failure rate ({failure_rate:.1%}) > threshold ({max_failure_rate:.0%})")
            print(f"   Spawning: BLOCKED")
        else:
            print(f"✅ OK: Failure rate ({failure_rate:.1%}) <= threshold ({max_failure_rate:.0%})")
            print(f"   Spawning: ALLOWED")
    
    print()
    
    # 3. Check tasks
    print("📝 TASK STATUS")
    print("-" * 80)
    
    try:
        result = db.supabase.table('tasks').select('id, status').order('created_at', desc=True).limit(100).execute()
        
        status_counts = {}
        for task in result.data:
            status = task['status']
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print("Recent tasks (last 100):")
        for status, count in sorted(status_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {status}: {count}")
        
        # Highlight important statuses
        queued = status_counts.get('Queued', 0)
        in_progress = status_counts.get('In Progress', 0)
        
        print()
        if queued > 0:
            print(f"⚠️  {queued} tasks queued - need workers!")
        if in_progress > 0:
            print(f"✅ {in_progress} tasks in progress")
        
    except Exception as e:
        print(f"❌ Error checking tasks: {e}")
    
    print()
    print("=" * 80)
    
    # 4. Summary
    active_count = len([w for w in workers if w['status'] == 'active'])
    spawning_count = len([w for w in workers if w['status'] == 'spawning'])
    
    if active_count == 0 and spawning_count == 0:
        print("⚠️  WARNING: No active or spawning workers!")
        if len(recent_workers) >= min_workers_for_check:
            failed_workers = [w for w in recent_workers if w['status'] in ['error', 'terminated']]
            failure_rate = len(failed_workers) / len(recent_workers)
            if failure_rate > max_failure_rate:
                print("   Reason: High failure rate blocking spawns")
                print("   Action: Wait for failed workers to age out of the 30-min window,")
                print("           or investigate root cause of failures")
    elif active_count > 0:
        healthy = len([w for w in workers if w.get('last_heartbeat') and 
                      (datetime.now(timezone.utc) - datetime.fromisoformat(w['last_heartbeat'].replace('Z', '+00:00'))).total_seconds() < 60])
        print(f"✅ SYSTEM HEALTHY: {healthy} healthy workers, {active_count} active, {spawning_count} spawning")
    
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(check_system_health())

