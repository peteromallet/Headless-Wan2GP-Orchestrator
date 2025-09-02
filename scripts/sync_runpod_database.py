#!/usr/bin/env python3
"""
Sync RunPod state with orchestrator database.
This script identifies orphaned pods and can either terminate them or update the database.
"""

import os
import sys
import asyncio
from dotenv import load_dotenv
import runpod
from datetime import datetime, timezone

# Add parent directory to path to import orchestrator modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpu_orchestrator.database import DatabaseClient
from gpu_orchestrator.runpod_client import create_runpod_client

async def sync_runpod_database(action="analyze"):
    """
    Sync RunPod pods with orchestrator database.
    
    Actions:
    - analyze: Show differences (default)
    - terminate_orphaned: Terminate pods not in database
    - update_database: Add missing workers to database
    """
    load_dotenv()
    
    # Initialize clients
    db = DatabaseClient()
    runpod_client = create_runpod_client()
    
    print("🔍 Analyzing RunPod vs Database state...")
    
    # Get RunPod pods
    runpod.api_key = os.getenv('RUNPOD_API_KEY')
    runpod_pods = runpod.get_pods()
    
    # Filter for running/active pods
    active_runpod_pods = [
        pod for pod in runpod_pods 
        if pod.get('desiredStatus') in ['RUNNING', 'PROVISIONING']
    ]
    
    # Get database workers
    db_workers = await db.get_workers()
    
    # Create lookup for database workers by runpod_id
    db_runpod_ids = set()
    active_db_workers = []
    
    for worker in db_workers:
        if worker['status'] in ['active', 'spawning']:
            active_db_workers.append(worker)
            runpod_id = worker.get('metadata', {}).get('runpod_id')
            if runpod_id:
                db_runpod_ids.add(runpod_id)
    
    # Find orphaned pods (in RunPod but not in database)
    orphaned_pods = []
    runpod_pod_ids = set()
    
    for pod in active_runpod_pods:
        pod_id = pod.get('id')
        runpod_pod_ids.add(pod_id)
        
        if pod_id not in db_runpod_ids:
            orphaned_pods.append(pod)
    
    # Find database-only workers (in database but not in RunPod)
    db_only_workers = []
    for worker in active_db_workers:
        runpod_id = worker.get('metadata', {}).get('runpod_id')
        if runpod_id and runpod_id not in runpod_pod_ids:
            db_only_workers.append(worker)
    
    # Report findings
    print(f"\n📊 Status Summary:")
    print(f"  RunPod active pods: {len(active_runpod_pods)}")
    print(f"  Database active workers: {len(active_db_workers)}")
    print(f"  Orphaned pods (RunPod only): {len(orphaned_pods)}")
    print(f"  Stale database workers: {len(db_only_workers)}")
    
    if orphaned_pods:
        print(f"\n🚨 Orphaned Pods in RunPod (not tracked in database):")
        total_cost = 0
        for pod in orphaned_pods:
            name = pod.get('name', 'unnamed')
            pod_id = pod.get('id', 'no-id')
            status = pod.get('desiredStatus', 'unknown')
            cost_per_hr = pod.get('costPerHr', 0)
            created = pod.get('createdAt', 'unknown')
            
            print(f"  • {name} ({pod_id}) - {status}")
            print(f"    Cost: ${cost_per_hr}/hr - Created: {created}")
            total_cost += cost_per_hr
        
        print(f"\n💰 Total hourly cost of orphaned pods: ${total_cost:.3f}/hr")
    
    if db_only_workers:
        print(f"\n🗄️ Stale Database Workers (pods no longer exist):")
        for worker in db_only_workers:
            worker_id = worker['id']
            runpod_id = worker.get('metadata', {}).get('runpod_id', 'no-runpod-id')
            created = worker.get('created_at', 'unknown')[:19]
            print(f"  • {worker_id} (pod: {runpod_id}) - Created: {created}")
    
    # Perform actions
    if action == "terminate_orphaned":
        if orphaned_pods:
            print(f"\n🛑 Terminating {len(orphaned_pods)} orphaned pods...")
            terminated_count = 0
            
            for pod in orphaned_pods:
                pod_id = pod.get('id')
                name = pod.get('name', 'unnamed')
                
                try:
                    runpod.terminate_pod(pod_id)
                    print(f"  ✅ Terminated {name} ({pod_id})")
                    terminated_count += 1
                except Exception as e:
                    print(f"  ❌ Failed to terminate {name} ({pod_id}): {e}")
            
            print(f"\n✅ Successfully terminated {terminated_count}/{len(orphaned_pods)} orphaned pods")
        else:
            print("\n✅ No orphaned pods to terminate")
    
    elif action == "update_database":
        if orphaned_pods:
            print(f"\n📝 Adding {len(orphaned_pods)} orphaned pods to database...")
            added_count = 0
            
            for pod in orphaned_pods:
                pod_id = pod.get('id')
                name = pod.get('name', 'unnamed')
                
                # Generate a worker ID from the pod name or ID
                if name.startswith('gpu-'):
                    worker_id = name
                else:
                    worker_id = f"legacy-{pod_id[:8]}"
                
                try:
                    # Create worker record
                    success = await db.create_worker_record(worker_id, "RTX 4090")  # Assume RTX 4090
                    if success:
                        # Update with RunPod metadata
                        metadata = {
                            'runpod_id': pod_id,
                            'legacy_sync': True,
                            'synced_at': datetime.now(timezone.utc).isoformat()
                        }
                        await db.update_worker_status(worker_id, 'active', metadata)
                        print(f"  ✅ Added {worker_id} ({pod_id})")
                        added_count += 1
                    else:
                        print(f"  ❌ Failed to create worker record for {name}")
                        
                except Exception as e:
                    print(f"  ❌ Failed to add {name} to database: {e}")
            
            print(f"\n✅ Successfully added {added_count}/{len(orphaned_pods)} workers to database")
        else:
            print("\n✅ No orphaned pods to add")
        
        # Clean up stale database workers
        if db_only_workers:
            print(f"\n🧹 Cleaning up {len(db_only_workers)} stale database workers...")
            cleaned_count = 0
            
            for worker in db_only_workers:
                worker_id = worker['id']
                try:
                    await db.update_worker_status(worker_id, 'terminated')
                    print(f"  ✅ Marked {worker_id} as terminated")
                    cleaned_count += 1
                except Exception as e:
                    print(f"  ❌ Failed to clean up {worker_id}: {e}")
            
            print(f"\n✅ Successfully cleaned up {cleaned_count}/{len(db_only_workers)} stale workers")
    
    elif action == "analyze":
        print(f"\n💡 Recommended Actions:")
        if orphaned_pods:
            print(f"  1. Terminate orphaned pods: python scripts/sync_runpod_database.py terminate_orphaned")
            print(f"     (This will save ~${total_cost:.2f}/hr)")
        if db_only_workers:
            print(f"  2. Clean database: python scripts/sync_runpod_database.py update_database")
        if not orphaned_pods and not db_only_workers:
            print(f"  ✅ No action needed - RunPod and database are in sync!")
    
    return {
        'runpod_pods': len(active_runpod_pods),
        'db_workers': len(active_db_workers),
        'orphaned_pods': len(orphaned_pods),
        'stale_workers': len(db_only_workers)
    }

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync RunPod state with orchestrator database")
    parser.add_argument('action', nargs='?', default='analyze', 
                       choices=['analyze', 'terminate_orphaned', 'update_database'],
                       help='Action to perform (default: analyze)')
    
    args = parser.parse_args()
    
    try:
        result = asyncio.run(sync_runpod_database(args.action))
        
        if args.action == "analyze":
            print(f"\n🔧 Usage:")
            print(f"  python scripts/sync_runpod_database.py analyze           # Show differences")
            print(f"  python scripts/sync_runpod_database.py terminate_orphaned # Kill orphaned pods")
            print(f"  python scripts/sync_runpod_database.py update_database   # Sync database")
        
    except KeyboardInterrupt:
        print("\n⏹️  Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
