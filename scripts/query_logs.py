#!/usr/bin/env python3
"""
System Logs Query Tool
======================

Utility to query and analyze system logs from the centralized logging system.

Usage Examples:
    # Get all errors from last 24 hours
    python query_logs.py --level ERROR --hours 24

    # Get complete timeline for a specific worker
    python query_logs.py --worker-timeline gpu-20250115-abc123

    # Get all logs for a specific task
    python query_logs.py --task-timeline 8755aa83-a502-4089-990d-df4414f90d58

    # Search for specific error message
    python query_logs.py --search "CUDA" --level ERROR

    # Export orchestrator logs to JSON
    python query_logs.py --source-type orchestrator_gpu --hours 48 --export orchestrator_logs.json

    # Get error summary
    python query_logs.py --errors-summary
    
    # View logs from specific orchestrator cycle
    python query_logs.py --source-type orchestrator_gpu --cycle 42
"""

import argparse
import os
import sys
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

load_dotenv()

from supabase import create_client


class LogQueryClient:
    """Client for querying system logs from Supabase."""
    
    def __init__(self):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
        
        self.supabase = create_client(supabase_url, supabase_key)
    
    def get_logs(
        self,
        start_time: datetime = None,
        end_time: datetime = None,
        source_type: str = None,
        source_id: str = None,
        worker_id: str = None,
        task_id: str = None,
        log_level: str = None,
        cycle_number: int = None,
        search_term: str = None,
        limit: int = 1000,
        order_desc: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Query logs with flexible filters.
        
        Args:
            start_time: Filter logs after this time (default: 24 hours ago)
            end_time: Filter logs before this time (default: now)
            source_type: Filter by source type ('orchestrator_gpu', 'orchestrator_api', 'worker')
            source_id: Filter by specific source ID
            worker_id: Filter by worker ID
            task_id: Filter by task ID
            log_level: Filter by log level ('ERROR', 'WARNING', etc.)
            cycle_number: Filter by orchestrator cycle number
            search_term: Search in message text
            limit: Maximum number of results
            order_desc: Order by timestamp descending
        
        Returns:
            List of log entry dictionaries
        """
        
        # Default time range: last 24 hours
        if not start_time:
            start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        if not end_time:
            end_time = datetime.now(timezone.utc)
        
        # Build query
        query = self.supabase.table('system_logs').select('*')
        
        # Apply filters
        query = query.gte('timestamp', start_time.isoformat())
        query = query.lte('timestamp', end_time.isoformat())
        
        if source_type:
            query = query.eq('source_type', source_type)
        if source_id:
            query = query.eq('source_id', source_id)
        if worker_id:
            query = query.eq('worker_id', worker_id)
        if task_id:
            query = query.eq('task_id', task_id)
        if log_level:
            query = query.eq('log_level', log_level)
        if cycle_number is not None:
            query = query.eq('cycle_number', cycle_number)
        if search_term:
            query = query.ilike('message', f'%{search_term}%')
        
        # Order and limit
        query = query.order('timestamp', desc=order_desc)
        query = query.limit(limit)
        
        result = query.execute()
        return result.data or []
    
    def get_worker_timeline(
        self,
        worker_id: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get complete timeline of logs for a specific worker.
        
        Args:
            worker_id: Worker ID to query
            hours: Hours of history to fetch
        
        Returns:
            List of log entries in chronological order
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return self.get_logs(
            worker_id=worker_id,
            start_time=start_time,
            limit=10000,
            order_desc=False  # Chronological order
        )
    
    def get_task_timeline(
        self,
        task_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get complete timeline of logs for a specific task.
        
        Args:
            task_id: Task ID to query
        
        Returns:
            List of log entries in chronological order
        """
        return self.get_logs(
            task_id=task_id,
            limit=10000,
            order_desc=False  # Chronological order
        )
    
    def get_cycle_logs(
        self,
        cycle_number: int,
        source_type: str = "orchestrator_gpu"
    ) -> List[Dict[str, Any]]:
        """
        Get all logs from a specific orchestrator cycle.
        
        Args:
            cycle_number: Cycle number to query
            source_type: Source type (default: orchestrator_gpu)
        
        Returns:
            List of log entries in chronological order
        """
        return self.get_logs(
            source_type=source_type,
            cycle_number=cycle_number,
            limit=10000,
            order_desc=False  # Chronological order
        )
    
    def get_errors_summary(
        self,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get summary of all errors in time window.
        
        Args:
            hours: Hours of history to analyze
        
        Returns:
            Dictionary with error summary and statistics
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        errors = self.get_logs(
            start_time=start_time,
            log_level='ERROR',
            limit=5000
        )
        
        # Group by source
        by_source = {}
        by_worker = {}
        by_task = {}
        
        for error in errors:
            source = error['source_id']
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(error)
            
            # Group by worker if applicable
            if error.get('worker_id'):
                worker = error['worker_id']
                if worker not in by_worker:
                    by_worker[worker] = []
                by_worker[worker].append(error)
            
            # Group by task if applicable
            if error.get('task_id'):
                task = str(error['task_id'])
                if task not in by_task:
                    by_task[task] = []
                by_task[task].append(error)
        
        return {
            'total_errors': len(errors),
            'by_source': {
                source: {
                    'count': len(errors_list),
                    'sample_messages': [e['message'] for e in errors_list[:3]]
                }
                for source, errors_list in by_source.items()
            },
            'by_worker': {
                worker: len(errors_list)
                for worker, errors_list in by_worker.items()
            },
            'by_task': {
                task: len(errors_list)
                for task, errors_list in by_task.items()
            },
            'time_range': {
                'start': start_time.isoformat(),
                'end': datetime.now(timezone.utc).isoformat(),
                'hours': hours
            }
        }
    
    def get_log_stats(
        self,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get overall logging statistics.
        
        Args:
            hours: Hours of history to analyze
        
        Returns:
            Dictionary with logging statistics
        """
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Get all logs in time range
        all_logs = self.get_logs(start_time=start_time, limit=10000)
        
        # Count by level
        by_level = {}
        by_source_type = {}
        
        for log in all_logs:
            level = log['log_level']
            by_level[level] = by_level.get(level, 0) + 1
            
            source_type = log['source_type']
            by_source_type[source_type] = by_source_type.get(source_type, 0) + 1
        
        return {
            'total_logs': len(all_logs),
            'by_level': by_level,
            'by_source_type': by_source_type,
            'time_range': {
                'start': start_time.isoformat(),
                'end': datetime.now(timezone.utc).isoformat(),
                'hours': hours
            }
        }
    
    def export_logs_to_json(
        self,
        output_file: str,
        **query_kwargs
    ):
        """
        Export logs to JSON file.
        
        Args:
            output_file: Path to output JSON file
            **query_kwargs: Arguments to pass to get_logs()
        """
        logs = self.get_logs(**query_kwargs)
        
        with open(output_file, 'w') as f:
            json.dump(logs, f, indent=2, default=str)
        
        print(f"✅ Exported {len(logs)} logs to {output_file}")
        return len(logs)
    
    def print_logs_table(self, logs: List[Dict[str, Any]], max_message_len: int = 80):
        """
        Print logs in a formatted table.
        
        Args:
            logs: List of log entries
            max_message_len: Maximum message length to display
        """
        if not logs:
            print("No logs found")
            return
        
        print(f"\n{'='*120}")
        print(f"Found {len(logs)} logs")
        print(f"{'='*120}\n")
        
        for log in logs:
            timestamp = log['timestamp']
            level = log['log_level']
            source = f"{log['source_type']}/{log['source_id']}"
            message = log['message']
            
            # Truncate long messages
            if len(message) > max_message_len:
                message = message[:max_message_len-3] + "..."
            
            # Color code by level (if terminal supports it)
            level_color = {
                'ERROR': '\033[91m',    # Red
                'WARNING': '\033[93m',  # Yellow
                'INFO': '\033[92m',     # Green
                'DEBUG': '\033[94m',    # Blue
            }.get(level, '')
            reset_color = '\033[0m' if level_color else ''
            
            print(f"{timestamp} | {level_color}{level:8}{reset_color} | {source:40} | {message}")
            
            # Print additional context if available
            if log.get('worker_id'):
                print(f"  → Worker: {log['worker_id']}")
            if log.get('task_id'):
                print(f"  → Task: {log['task_id']}")
            if log.get('cycle_number'):
                print(f"  → Cycle: {log['cycle_number']}")
            
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Query system logs from centralized logging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get recent errors
  %(prog)s --level ERROR --hours 24

  # Get worker timeline
  %(prog)s --worker-timeline gpu-20250115-abc123

  # Get task timeline
  %(prog)s --task-timeline 8755aa83-a502-4089-990d-df4414f90d58

  # Get orchestrator cycle logs
  %(prog)s --source-type orchestrator_gpu --cycle 42

  # Search for specific error
  %(prog)s --search "CUDA" --level ERROR

  # Export to JSON
  %(prog)s --source-type orchestrator_gpu --hours 48 --export logs.json
        """
    )
    
    # Filter arguments
    parser.add_argument('--worker', help='Filter by worker ID')
    parser.add_argument('--task', help='Filter by task ID')
    parser.add_argument('--source-type', choices=['orchestrator_gpu', 'orchestrator_api', 'worker'],
                       help='Filter by source type')
    parser.add_argument('--source-id', help='Filter by source ID')
    parser.add_argument('--level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='Filter by log level')
    parser.add_argument('--cycle', type=int, help='Filter by orchestrator cycle number')
    parser.add_argument('--search', help='Search term in message')
    parser.add_argument('--hours', type=int, default=24, help='Hours of history (default: 24)')
    parser.add_argument('--limit', type=int, default=1000, help='Maximum results (default: 1000)')
    
    # Special queries
    parser.add_argument('--worker-timeline', help='Get complete timeline for worker')
    parser.add_argument('--task-timeline', help='Get complete timeline for task')
    parser.add_argument('--errors-summary', action='store_true', help='Show error summary')
    parser.add_argument('--stats', action='store_true', help='Show logging statistics')
    
    # Output options
    parser.add_argument('--export', help='Export to JSON file')
    parser.add_argument('--format', choices=['table', 'json'], default='table',
                       help='Output format (default: table)')
    
    args = parser.parse_args()
    
    try:
        client = LogQueryClient()
        
        # Handle special queries
        if args.errors_summary:
            summary = client.get_errors_summary(hours=args.hours)
            print(json.dumps(summary, indent=2, default=str))
            return
        
        if args.stats:
            stats = client.get_log_stats(hours=args.hours)
            print(json.dumps(stats, indent=2, default=str))
            return
        
        if args.worker_timeline:
            logs = client.get_worker_timeline(args.worker_timeline, hours=args.hours)
        elif args.task_timeline:
            logs = client.get_task_timeline(args.task_timeline)
        else:
            # General query
            start_time = datetime.now(timezone.utc) - timedelta(hours=args.hours)
            
            logs = client.get_logs(
                start_time=start_time,
                source_type=args.source_type,
                source_id=args.source_id,
                worker_id=args.worker,
                task_id=args.task,
                log_level=args.level,
                cycle_number=args.cycle,
                search_term=args.search,
                limit=args.limit
            )
        
        # Export if requested
        if args.export:
            client.export_logs_to_json(args.export, **{
                'start_time': datetime.now(timezone.utc) - timedelta(hours=args.hours),
                'source_type': args.source_type,
                'source_id': args.source_id,
                'worker_id': args.worker,
                'task_id': args.task,
                'log_level': args.level,
                'cycle_number': args.cycle,
                'search_term': args.search,
                'limit': args.limit
            })
        else:
            # Display results
            if args.format == 'json':
                print(json.dumps(logs, indent=2, default=str))
            else:
                client.print_logs_table(logs)
    
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

