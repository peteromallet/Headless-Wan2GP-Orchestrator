#!/usr/bin/env python3
"""
Query Supabase database for recently failed tasks and analyze failure patterns.
Can be used standalone or combined with fetch_task_logs.py for detailed failure analysis.

Usage: 
  python query_failed_tasks.py [--hours N] [--limit N] [--format json|text] [--with-logs] [--output file]
  python query_failed_tasks.py --auto-analyze [--hours N]
"""

import os
import sys
import argparse
import json
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient


class FailedTaskAnalyzer:
    """Analyzer for failed tasks in the database"""
    
    def __init__(self):
        self.db = DatabaseClient()
    
    async def get_failed_tasks(self, hours_back: int = 24, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recently failed tasks from the database"""
        try:
            # Calculate cutoff time
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
            
            # Query failed tasks
            response = self.db.supabase.table('tasks').select(
                'id, status, task_type, params, attempts, worker_id, '
                'generation_started_at, generation_processed_at, error_message, '
                'result_data, created_at, updated_at'
            ).eq('status', 'Failed').gte('updated_at', cutoff_time.isoformat()).order(
                'updated_at', desc=True
            ).limit(limit).execute()
            
            if not response.data:
                return []
            
            # Enhance task data with computed fields
            enhanced_tasks = []
            for task in response.data:
                enhanced_task = dict(task)
                
                # Calculate processing duration if available
                if task['generation_started_at'] and task['generation_processed_at']:
                    start_time = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                    end_time = datetime.fromisoformat(task['generation_processed_at'].replace('Z', '+00:00'))
                    enhanced_task['processing_duration_seconds'] = (end_time - start_time).total_seconds()
                else:
                    enhanced_task['processing_duration_seconds'] = None
                
                # Calculate time in queue
                if task['created_at'] and task['generation_started_at']:
                    created_time = datetime.fromisoformat(task['created_at'].replace('Z', '+00:00'))
                    start_time = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                    enhanced_task['queue_duration_seconds'] = (start_time - created_time).total_seconds()
                elif task['created_at']:
                    created_time = datetime.fromisoformat(task['created_at'].replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    enhanced_task['queue_duration_seconds'] = (now - created_time).total_seconds()
                else:
                    enhanced_task['queue_duration_seconds'] = None
                
                # Parse error message for common patterns
                error_msg = task.get('error_message', '') or ''
                enhanced_task['error_category'] = self.categorize_error(error_msg)
                
                enhanced_tasks.append(enhanced_task)
            
            return enhanced_tasks
            
        except Exception as e:
            print(f"❌ Error querying failed tasks: {e}")
            return []
    
    def categorize_error(self, error_message: str) -> str:
        """Categorize error messages into common failure types"""
        if not error_message:
            return 'No error message'
        
        error_lower = error_message.lower()
        
        # Common error patterns
        if 'cuda' in error_lower and ('memory' in error_lower or 'out of memory' in error_lower):
            return 'CUDA OOM'
        elif 'cuda' in error_lower:
            return 'CUDA Error'
        elif 'timeout' in error_lower or 'timed out' in error_lower:
            return 'Timeout'
        elif 'connection' in error_lower or 'network' in error_lower:
            return 'Network Error'
        elif 'permission' in error_lower or 'access denied' in error_lower:
            return 'Permission Error'
        elif 'file not found' in error_lower or 'no such file' in error_lower:
            return 'File Not Found'
        elif 'model' in error_lower and ('load' in error_lower or 'not found' in error_lower):
            return 'Model Loading Error'
        elif 'worker' in error_lower and ('unavailable' in error_lower or 'unreachable' in error_lower):
            return 'Worker Unavailable'
        elif 'json' in error_lower or 'parse' in error_lower:
            return 'Data Parsing Error'
        elif 'validation' in error_lower or 'invalid' in error_lower:
            return 'Validation Error'
        else:
            return 'Other Error'
    
    async def analyze_failure_patterns(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in failed tasks"""
        if not tasks:
            return {'total_tasks': 0}
        
        analysis = {
            'total_tasks': len(tasks),
            'time_range': {
                'oldest_failure': min(task['updated_at'] for task in tasks),
                'newest_failure': max(task['updated_at'] for task in tasks)
            },
            'error_categories': {},
            'task_types': {},
            'worker_analysis': {},
            'attempt_distribution': {},
            'timing_analysis': {
                'avg_processing_duration': None,
                'avg_queue_duration': None,
                'processing_durations': [],
                'queue_durations': []
            }
        }
        
        # Count error categories
        for task in tasks:
            category = task.get('error_category', 'Unknown')
            analysis['error_categories'][category] = analysis['error_categories'].get(category, 0) + 1
        
        # Count task types
        for task in tasks:
            task_type = task.get('task_type', 'Unknown')
            analysis['task_types'][task_type] = analysis['task_types'].get(task_type, 0) + 1
        
        # Analyze workers
        for task in tasks:
            worker_id = task.get('worker_id', 'Unassigned')
            if worker_id not in analysis['worker_analysis']:
                analysis['worker_analysis'][worker_id] = {
                    'failed_tasks': 0,
                    'error_categories': {}
                }
            analysis['worker_analysis'][worker_id]['failed_tasks'] += 1
            
            category = task.get('error_category', 'Unknown')
            worker_errors = analysis['worker_analysis'][worker_id]['error_categories']
            worker_errors[category] = worker_errors.get(category, 0) + 1
        
        # Analyze attempts
        for task in tasks:
            attempts = task.get('attempts', 0)
            analysis['attempt_distribution'][attempts] = analysis['attempt_distribution'].get(attempts, 0) + 1
        
        # Timing analysis
        processing_times = [task['processing_duration_seconds'] for task in tasks if task.get('processing_duration_seconds') is not None]
        queue_times = [task['queue_duration_seconds'] for task in tasks if task.get('queue_duration_seconds') is not None]
        
        if processing_times:
            analysis['timing_analysis']['avg_processing_duration'] = sum(processing_times) / len(processing_times)
            analysis['timing_analysis']['processing_durations'] = processing_times
        
        if queue_times:
            analysis['timing_analysis']['avg_queue_duration'] = sum(queue_times) / len(queue_times)
            analysis['timing_analysis']['queue_durations'] = queue_times
        
        return analysis
    
    async def get_most_critical_tasks(self, tasks: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        """Get the most critical failed tasks for detailed analysis"""
        if not tasks:
            return []
        
        # Score tasks by criticality
        scored_tasks = []
        for task in tasks:
            score = 0
            
            # Higher score for more recent failures
            updated_time = datetime.fromisoformat(task['updated_at'].replace('Z', '+00:00'))
            hours_ago = (datetime.now(timezone.utc) - updated_time).total_seconds() / 3600
            score += max(0, 24 - hours_ago)  # Recent failures get higher score
            
            # Higher score for more attempts (persistent failures)
            score += task.get('attempts', 0) * 5
            
            # Higher score for certain error types
            error_category = task.get('error_category', '')
            if error_category in ['CUDA OOM', 'Worker Unavailable', 'Model Loading Error']:
                score += 10
            
            # Higher score if processing took a long time before failing
            if task.get('processing_duration_seconds'):
                if task['processing_duration_seconds'] > 300:  # More than 5 minutes
                    score += 5
            
            scored_tasks.append((score, task))
        
        # Sort by score and return top tasks
        scored_tasks.sort(key=lambda x: x[0], reverse=True)
        return [task for score, task in scored_tasks[:limit]]


def format_task_output(tasks: List[Dict[str, Any]], output_format: str = 'text') -> str:
    """Format failed tasks for output"""
    if output_format == 'json':
        return json.dumps(tasks, indent=2, default=str)
    
    # Text format
    if not tasks:
        return "No failed tasks found."
    
    output = []
    output.append(f"📋 Failed Tasks ({len(tasks)} tasks)")
    output.append("=" * 80)
    
    for i, task in enumerate(tasks, 1):
        output.append(f"\n{i}. Task {task['id']}")
        output.append(f"   Status: {task['status']} | Type: {task.get('task_type', 'Unknown')}")
        output.append(f"   Worker: {task.get('worker_id', 'Unassigned')} | Attempts: {task.get('attempts', 0)}")
        output.append(f"   Error Category: {task.get('error_category', 'Unknown')}")
        output.append(f"   Created: {task.get('created_at', 'N/A')}")
        output.append(f"   Updated: {task.get('updated_at', 'N/A')}")
        
        if task.get('processing_duration_seconds'):
            output.append(f"   Processing Duration: {task['processing_duration_seconds']:.1f}s")
        if task.get('queue_duration_seconds'):
            output.append(f"   Queue Duration: {task['queue_duration_seconds']:.1f}s")
        
        error_msg = task.get('error_message', '')
        if error_msg:
            # Truncate long error messages
            if len(error_msg) > 200:
                error_msg = error_msg[:200] + "..."
            output.append(f"   Error: {error_msg}")
    
    return '\n'.join(output)


def format_analysis_output(analysis: Dict[str, Any]) -> str:
    """Format failure analysis for output"""
    if analysis['total_tasks'] == 0:
        return "No failed tasks to analyze."
    
    output = []
    output.append(f"\n📊 Failure Analysis ({analysis['total_tasks']} tasks)")
    output.append("=" * 80)
    
    # Time range
    output.append(f"📅 Time Range:")
    output.append(f"   Oldest failure: {analysis['time_range']['oldest_failure']}")
    output.append(f"   Newest failure: {analysis['time_range']['newest_failure']}")
    
    # Error categories
    output.append(f"\n❌ Error Categories:")
    for category, count in sorted(analysis['error_categories'].items(), key=lambda x: x[1], reverse=True):
        percentage = (count / analysis['total_tasks']) * 100
        output.append(f"   {category}: {count} ({percentage:.1f}%)")
    
    # Task types
    output.append(f"\n📝 Task Types:")
    for task_type, count in sorted(analysis['task_types'].items(), key=lambda x: x[1], reverse=True):
        percentage = (count / analysis['total_tasks']) * 100
        output.append(f"   {task_type}: {count} ({percentage:.1f}%)")
    
    # Worker analysis
    output.append(f"\n🤖 Worker Analysis:")
    worker_items = sorted(analysis['worker_analysis'].items(), key=lambda x: x[1]['failed_tasks'], reverse=True)
    for worker_id, worker_data in worker_items[:10]:  # Top 10 workers
        output.append(f"   {worker_id}: {worker_data['failed_tasks']} failures")
        # Show top error categories for this worker
        top_errors = sorted(worker_data['error_categories'].items(), key=lambda x: x[1], reverse=True)[:3]
        for error_cat, count in top_errors:
            output.append(f"      └─ {error_cat}: {count}")
    
    # Attempt distribution
    output.append(f"\n🔄 Attempt Distribution:")
    for attempts, count in sorted(analysis['attempt_distribution'].items()):
        percentage = (count / analysis['total_tasks']) * 100
        output.append(f"   {attempts} attempts: {count} ({percentage:.1f}%)")
    
    # Timing analysis
    timing = analysis['timing_analysis']
    output.append(f"\n⏱️  Timing Analysis:")
    if timing['avg_processing_duration']:
        output.append(f"   Avg processing duration: {timing['avg_processing_duration']:.1f}s")
    if timing['avg_queue_duration']:
        output.append(f"   Avg queue duration: {timing['avg_queue_duration']:.1f}s")
    
    return '\n'.join(output)


async def auto_analyze_with_logs(hours_back: int = 24):
    """Automatically analyze recent failures and fetch logs for the most critical ones"""
    print(f"🔍 Auto-analyzing failed tasks from the last {hours_back} hours...")
    
    analyzer = FailedTaskAnalyzer()
    
    # Get failed tasks
    failed_tasks = await analyzer.get_failed_tasks(hours_back=hours_back, limit=100)
    
    if not failed_tasks:
        print("✅ No failed tasks found in the specified time range.")
        return
    
    # Analyze patterns
    analysis = await analyzer.analyze_failure_patterns(failed_tasks)
    print(format_analysis_output(analysis))
    
    # Get most critical tasks
    critical_tasks = await analyzer.get_most_critical_tasks(failed_tasks, limit=5)
    
    if critical_tasks:
        print(f"\n🎯 Top {len(critical_tasks)} Critical Failed Tasks:")
        print("=" * 80)
        for i, task in enumerate(critical_tasks, 1):
            print(f"\n{i}. Task {task['id']} ({task.get('error_category', 'Unknown')})")
            print(f"   Worker: {task.get('worker_id', 'Unassigned')} | Attempts: {task.get('attempts', 0)}")
            error_msg = task.get('error_message') or 'No error message'
            print(f"   Error: {error_msg[:100]}{'...' if len(error_msg) > 100 else ''}")
            
            # Import and run fetch_task_logs for this task
            try:
                print(f"\n   📋 Fetching logs for task {task['id']}...")
                
                # Import the fetch_task_logs module
                sys.path.append(str(Path(__file__).parent))
                from fetch_task_logs import TaskLogParser, find_worker_for_task, search_specific_worker_logs_for_task
                
                # Parse orchestrator logs
                log_file = 'orchestrator.log'
                if os.path.exists(log_file):
                    parser = TaskLogParser(log_file)
                    entries = parser.find_task_logs(task['id'], context_lines=1)
                    
                    if entries:
                        matches = [e for e in entries if e.get('is_match')]
                        print(f"      📋 Orchestrator: {len(matches)} direct matches")
                        # Show key error entries
                        for entry in matches[-3:]:  # Last 3 matches
                            if 'error' in entry.get('message', '').lower() or 'failed' in entry.get('message', '').lower():
                                print(f"         [{entry['line_number']}] {entry.get('message', '')[:100]}{'...' if len(entry.get('message', '')) > 100 else ''}")
                    else:
                        print(f"      📋 Orchestrator: No log entries found")
                
                # Try to get worker logs if worker is assigned
                if task.get('worker_id'):
                    try:
                        # Load environment variables for consistency with other scripts
                        from dotenv import load_dotenv
                        load_dotenv()
                        
                        worker_results = await search_specific_worker_logs_for_task(task['worker_id'], task['id'], lines=50)
                        if worker_results and worker_results.get('logs_found'):
                            print(f"      🤖 Worker: {len(worker_results.get('task_entries', []))} entries found")
                            # Show recent error entries
                            for entry in worker_results.get('task_entries', [])[-2:]:
                                print(f"         [{entry['line_number']}] {entry['content'][:100]}{'...' if len(entry['content']) > 100 else ''}")
                        else:
                            print(f"      🤖 Worker: No logs found")
                    except Exception as e:
                        print(f"      🤖 Worker: Error fetching logs - {e}")
                else:
                    print(f"      🤖 Worker: No worker assigned")
                    
            except Exception as e:
                print(f"   ❌ Error fetching logs: {e}")
    
    print(f"\n💡 Recommendations:")
    error_cats = analysis['error_categories']
    if error_cats.get('CUDA OOM', 0) > 0:
        print(f"   • {error_cats['CUDA OOM']} CUDA OOM errors - Consider reducing batch size or model resolution")
    if error_cats.get('Worker Unavailable', 0) > 0:
        print(f"   • {error_cats['Worker Unavailable']} worker unavailable errors - Check worker health and scaling")
    if error_cats.get('Timeout', 0) > 0:
        print(f"   • {error_cats['Timeout']} timeout errors - Consider increasing timeout limits")
    if analysis['total_tasks'] > 20:
        print(f"   • High failure rate ({analysis['total_tasks']} failures) - Review system capacity and configuration")


def main():
    parser = argparse.ArgumentParser(description='Query and analyze recently failed tasks from Supabase')
    parser.add_argument('--hours', '-H', type=int, default=24, help='Hours back to search (default: 24)')
    parser.add_argument('--limit', '-l', type=int, default=50, help='Maximum number of tasks to return (default: 50)')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text', help='Output format (default: text)')
    parser.add_argument('--output', '-o', help='Save output to file')
    parser.add_argument('--analyze', '-a', action='store_true', help='Include failure pattern analysis')
    parser.add_argument('--auto-analyze', action='store_true', help='Auto-analyze critical failures with logs')
    parser.add_argument('--with-logs', action='store_true', help='Fetch logs for failed tasks (requires fetch_task_logs.py)')
    
    args = parser.parse_args()
    
    # Run async main
    asyncio.run(main_async(args))


async def main_async(args):
    """Async main function"""
    
    # Check required environment variables
    if not os.getenv('SUPABASE_URL'):
        print("❌ SUPABASE_URL environment variable is required")
        return
    if not os.getenv('SUPABASE_SERVICE_ROLE_KEY'):
        print("❌ SUPABASE_SERVICE_ROLE_KEY environment variable is required")
        return
    
    # Auto-analyze mode
    if args.auto_analyze:
        await auto_analyze_with_logs(args.hours)
        return
    
    # Regular query mode
    print(f"🔍 Querying failed tasks from the last {args.hours} hours...")
    
    analyzer = FailedTaskAnalyzer()
    failed_tasks = await analyzer.get_failed_tasks(hours_back=args.hours, limit=args.limit)
    
    if not failed_tasks:
        print(f"✅ No failed tasks found in the last {args.hours} hours.")
        return
    
    # Format output
    all_output = []
    
    # Task list
    task_output = format_task_output(failed_tasks, args.format)
    all_output.append(task_output)
    
    # Analysis if requested
    if args.analyze:
        analysis = await analyzer.analyze_failure_patterns(failed_tasks)
        analysis_output = format_analysis_output(analysis)
        all_output.append(analysis_output)
    
    # Logs if requested
    if args.with_logs:
        print(f"\n🔍 Fetching logs for failed tasks...")
        try:
            # Import the fetch_task_logs module
            sys.path.append(str(Path(__file__).parent))
            from fetch_task_logs import TaskLogParser, find_worker_for_task, search_specific_worker_logs_for_task
            
            # Get logs for the most recent failed tasks (up to 3)
            for task in failed_tasks[:3]:
                task_id = task['id']
                print(f"\n📋 Logs for task {task_id}:")
                
                # Orchestrator logs
                log_file = 'orchestrator.log'
                if os.path.exists(log_file):
                    parser = TaskLogParser(log_file)
                    entries = parser.find_task_logs(task_id, context_lines=1)
                    if entries:
                        matches = [e for e in entries if e.get('is_match')]
                        print(f"   📋 Orchestrator: {len(matches)} entries found")
                        for entry in matches[-2:]:  # Last 2 matches
                            print(f"      [{entry['line_number']}] {entry.get('message', '')}")
                    else:
                        print(f"   📋 Orchestrator: No entries found")
                
                # Worker logs
                worker_id = task.get('worker_id')
                if worker_id:
                    try:
                        worker_results = await search_specific_worker_logs_for_task(worker_id, task_id, lines=20)
                        if worker_results and worker_results.get('logs_found'):
                            print(f"   🤖 Worker: {len(worker_results.get('task_entries', []))} entries found")
                            for entry in worker_results.get('task_entries', [])[-2:]:
                                print(f"      [{entry['line_number']}] {entry['content']}")
                        else:
                            print(f"   🤖 Worker: No logs found")
                    except Exception as e:
                        print(f"   🤖 Worker: Error - {e}")
                else:
                    print(f"   🤖 Worker: No worker assigned")
                    
        except Exception as e:
            print(f"❌ Error fetching logs: {e}")
    
    combined_output = '\n'.join(all_output)
    
    # Save or print output
    if args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{args.output}_failed_tasks_{timestamp}.log"
        with open(filename, 'w') as f:
            f.write(f"# Failed Tasks Report\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")
            f.write(f"# Time range: Last {args.hours} hours\n")
            f.write(f"# Total tasks: {len(failed_tasks)}\n\n")
            f.write(combined_output)
        print(f"💾 Saved to {filename}")
    else:
        print(combined_output)
    
    print(f"\n✅ Query complete: {len(failed_tasks)} failed tasks found")


if __name__ == '__main__':
    main() 