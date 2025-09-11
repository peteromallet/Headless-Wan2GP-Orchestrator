#!/usr/bin/env python3
"""
Main entry point for the Runpod GPU Worker Orchestrator.
Can run as a single cycle (for cron/edge functions) or continuous loop.
"""

import os
import sys
import asyncio
import logging
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

# Configure structured logging before importing internal modules that emit logs
from logging_config import setup_logging

setup_logging()

from control_loop import OrchestratorControlLoop

logger = logging.getLogger(__name__)

async def run_single_cycle():
    """Run a single orchestrator cycle."""
    try:
        orchestrator = OrchestratorControlLoop()
        summary = await orchestrator.run_single_cycle()
        
        # Output structured JSON for logging/monitoring
        print(json.dumps(summary, indent=2))
        
        return summary
        
    except Exception as e:
        logger.error(f"Failed to run orchestrator cycle: {e}")
        error_summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "success": False
        }
        print(json.dumps(error_summary, indent=2))
        return error_summary

async def run_continuous_loop():
    """Run orchestrator in continuous loop mode."""
    load_dotenv()
    poll_interval = int(os.getenv("ORCHESTRATOR_POLL_SEC", "30"))
    
    logger.info(f"Starting orchestrator in continuous mode (polling every {poll_interval}s)")
    
    orchestrator = OrchestratorControlLoop()
    
    while True:
        try:
            cycle_start = datetime.now(timezone.utc)
            
            summary = await orchestrator.run_single_cycle()
            
            # Log summary
            logger.info(f"Cycle completed: {summary['actions']}")
            
            # Calculate sleep time to maintain consistent interval
            cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            sleep_time = max(0, poll_interval - cycle_duration)
            
            if sleep_time > 0:
                logger.debug(f"Sleeping for {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
            else:
                logger.warning(f"Cycle took {cycle_duration:.1f}s, longer than {poll_interval}s interval")
                
        except KeyboardInterrupt:
            logger.info("Orchestrator stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in orchestrator loop: {e}")
            # Sleep before retrying
            await asyncio.sleep(30)

async def check_status():
    """Check and display current orchestrator status."""
    try:
        from .database import DatabaseClient
        
        db = DatabaseClient()
        
        # Get overall status
        status = await db.get_orchestrator_status()
        print("=== Orchestrator Status ===")
        print(json.dumps(status, indent=2, default=str))
        
        # Get worker health
        worker_health = await db.get_active_workers_health()
        print("\n=== Worker Health ===")
        for worker in worker_health:
            print(f"Worker {worker['id']}: {worker['status']} - {worker.get('health_status', 'UNKNOWN')}")
            if worker.get('current_task_id'):
                print(f"  Current task: {worker['current_task_id']} (running {worker.get('task_runtime_seconds', 0):.0f}s)")
            if worker.get('vram_usage_percent'):
                print(f"  VRAM: {worker['vram_usage_percent']}% ({worker.get('vram_used_mb', 0)}/{worker.get('vram_total_mb', 0)} MB)")
        
        return status
        
    except Exception as e:
        logger.error(f"Failed to check status: {e}")
        return None

def main():
    """Main entry point with command line argument handling."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Runpod GPU Worker Orchestrator")
    parser.add_argument(
        "mode", 
        choices=["single", "continuous", "status"],
        default="single",
        nargs="?",
        help="Run mode: single cycle, continuous loop, or status check"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        if args.mode == "single":
            result = asyncio.run(run_single_cycle())
            # Exit with non-zero code if there were errors
            if "error" in result:
                sys.exit(1)
        elif args.mode == "continuous":
            asyncio.run(run_continuous_loop())
        elif args.mode == "status":
            asyncio.run(check_status())
            
    except KeyboardInterrupt:
        logger.info("Orchestrator stopped by user")
    except Exception as e:
        logger.error(f"Orchestrator failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 