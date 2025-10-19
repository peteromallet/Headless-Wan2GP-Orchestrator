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
from .logging_config import setup_logging, set_current_cycle, get_db_logging_stats

# Initial setup without database client
setup_logging()

from .control_loop import OrchestratorControlLoop

logger = logging.getLogger(__name__)

def validate_environment():
    """Validate all required environment variables are present."""
    logger.info("🔍 Validating environment configuration...")
    
    # Required environment variables
    required_vars = {
        'RUNPOD_API_KEY': 'RunPod API key for creating/managing GPU workers',
        'SUPABASE_URL': 'Supabase database URL',
        'SUPABASE_SERVICE_ROLE_KEY': 'Supabase service role key for database access',
    }
    
    # Optional but important environment variables
    important_vars = {
        'RUNPOD_SSH_PUBLIC_KEY': 'SSH public key for worker authentication',
        'RUNPOD_STORAGE_NAME': 'RunPod storage volume name (e.g., "Peter")',
        'RUNPOD_GPU_TYPE': 'GPU type to spawn (e.g., "NVIDIA GeForce RTX 4090")',
        'RUNPOD_WORKER_IMAGE': 'Docker image for workers',
        'RUNPOD_VOLUME_MOUNT_PATH': 'Volume mount path in containers',
        'RUNPOD_DISK_SIZE_GB': 'Disk size in GB for workers',
        'RUNPOD_CONTAINER_DISK_GB': 'Container disk size in GB',
        'RUNPOD_MIN_VCPU_COUNT': 'Minimum vCPU count for workers (default: 8)',
        'RUNPOD_MIN_MEMORY_GB': 'Minimum system RAM in GB for workers (default: 32)',
        'RUNPOD_RAM_TIER_FALLBACK': 'Enable RAM tier fallback (default: true) - tries 72/60/48/32/16 GB',
        'MAX_ACTIVE_GPUS': 'Maximum number of active GPU workers',
        'MIN_ACTIVE_GPUS': 'Minimum number of active GPU workers',
        'GPU_IDLE_TIMEOUT_SEC': 'Timeout before terminating idle workers',
        'TASKS_PER_GPU_THRESHOLD': 'Number of tasks per GPU for scaling decisions',
    }
    
    # Check required variables
    missing_required = []
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing_required.append(f"  ❌ {var}: {description}")
            logger.error(f"Missing required environment variable: {var}")
        else:
            # Show partial value for security (don't log full API keys)
            if 'KEY' in var or 'SECRET' in var:
                display_value = f"{value[:10]}..." if len(value) > 10 else "***"
            else:
                display_value = value
            logger.info(f"  ✅ {var}: {display_value}")
    
    # Check important variables
    missing_important = []
    for var, description in important_vars.items():
        value = os.getenv(var)
        if not value:
            missing_important.append(f"  ⚠️  {var}: {description} (using default)")
            logger.warning(f"Missing important environment variable: {var} - {description}")
        else:
            # Show partial value for security
            if 'KEY' in var:
                display_value = f"{value[:20]}..." if len(value) > 20 else value
            else:
                display_value = value
            logger.info(f"  ✅ {var}: {display_value}")
    
    # Report results
    if missing_required:
        logger.error("❌ CRITICAL: Missing required environment variables:")
        for msg in missing_required:
            logger.error(msg)
        logger.error("🛑 Cannot start orchestrator without required configuration!")
        return False
    
    if missing_important:
        logger.warning("⚠️  Missing important environment variables (will use defaults):")
        for msg in missing_important:
            logger.warning(msg)
    
    logger.info("✅ Environment validation completed successfully")
    return True

async def run_single_cycle():
    """Run a single orchestrator cycle."""
    try:
        # Validate environment before starting
        if not validate_environment():
            error_summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "Missing required environment variables",
                "success": False
            }
            print(json.dumps(error_summary, indent=2))
            return error_summary
        
        # Initialize orchestrator (which has database client)
        orchestrator = OrchestratorControlLoop()
        
        # Re-initialize logging with database client if DB logging is enabled
        from .logging_config import setup_logging as reinit_logging
        reinit_logging(db_client=orchestrator.db, source_type="orchestrator_gpu")
        
        # Run cycle
        summary = await orchestrator.run_single_cycle()
        
        # Add database logging stats if available
        db_stats = get_db_logging_stats()
        if db_stats:
            summary['db_logging_stats'] = db_stats
        
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
    
    # Validate environment before starting continuous loop
    if not validate_environment():
        logger.error("🛑 Cannot start continuous loop without required configuration!")
        sys.exit(1)
    
    poll_interval = int(os.getenv("ORCHESTRATOR_POLL_SEC", "30"))
    
    logger.info(f"Starting orchestrator in continuous mode (polling every {poll_interval}s)")
    
    orchestrator = OrchestratorControlLoop()
    
    # Re-initialize logging with database client if DB logging is enabled
    from .logging_config import setup_logging as reinit_logging
    reinit_logging(db_client=orchestrator.db, source_type="orchestrator_gpu")
    
    while True:
        try:
            cycle_start = datetime.now(timezone.utc)
            
            # Set current cycle for logging context
            set_current_cycle(orchestrator.cycle_count + 1)
            
            summary = await orchestrator.run_single_cycle()
            
            # Log summary
            logger.info(f"Cycle completed: {summary['actions']}")
            
            # Log database logging stats periodically (every 10 cycles)
            if orchestrator.cycle_count % 10 == 0:
                db_stats = get_db_logging_stats()
                if db_stats:
                    logger.info(f"📊 Database logging stats: {db_stats}")
            
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
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug mode (same as --verbose)"
    )
    
    args = parser.parse_args()
    
    if args.verbose or args.debug:
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