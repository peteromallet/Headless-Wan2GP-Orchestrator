#!/usr/bin/env python3
"""
Analyze the most recent tasks in the database regardless of status.
Provides overview of task distribution, timing, and status patterns.

Usage:
  python analyze_recent_tasks.py                    # Analyze last 50 tasks
  python analyze_recent_tasks.py --limit 100        # Analyze last 100 tasks
  python analyze_recent_tasks.py --format json      # Output as JSON
  python analyze_recent_tasks.py --detailed         # Include detailed breakdown
"""

import os
import sys
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import Counter
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient


class RecentTaskAnalyzer:
    """Analyzer for recent tasks in the database"""
    
    def __init__(self):
        self.db = DatabaseClient()
    
    async def get_recent_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get the most recent tasks from the database"""
        try:
            # Query recent tasks ordered by creation time
            response = self.db.supabase.table('tasks').select(
                'id, status, task_type, params, attempts, worker_id, '
                'generation_started_at, generation_processed_at, error_message, '
                'result_data, created_at, updated_at'
            ).order('created_at', desc=True).limit(limit).execute()
            
            tasks = response.data or []
            
            # Calculate durations and add derived fields
            for task in tasks:
                self._add_derived_fields(task)
            
            return tasks
            
        except Exception as e:
            print(f"❌ Error querying recent tasks: {e}")
            return []
    
    def _add_derived_fields(self, task: Dict[str, Any]) -> None:
        """Add calculated fields to a task"""
        try:
            created_at = datetime.fromisoformat(task['created_at'].replace('Z', '+00:00'))
            updated_at = datetime.fromisoformat(task['updated_at'].replace('Z', '+00:00'))
            
            # Age of task
            task['age_hours'] = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
            
            # Time since last update
            task['last_updated_hours'] = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
            
            # Processing duration if available
            if task.get('generation_started_at') and task.get('generation_processed_at'):
                started = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                processed = datetime.fromisoformat(task['generation_processed_at'].replace('Z', '+00:00'))
                task['processing_duration_seconds'] = (processed - started).total_seconds()
            else:
                task['processing_duration_seconds'] = None
            
            # Queue duration if task was started
            if task.get('generation_started_at'):
                started = datetime.fromisoformat(task['generation_started_at'].replace('Z', '+00:00'))
                task['queue_duration_seconds'] = (started - created_at).total_seconds()
            else:
                task['queue_duration_seconds'] = None
                
        except Exception as e:
            print(f"⚠️  Error calculating durations for task {task.get('id', 'unknown')}: {e}")
    
    def analyze_tasks(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in recent tasks"""
        if not tasks:
            return {'total_tasks': 0}
        
        analysis = {
            'total_tasks': len(tasks),
            'time_range': {
                'oldest_task': min(task['created_at'] for task in tasks),
                'newest_task': max(task['created_at'] for task in tasks),
                'age_range_hours': {
                    'min': min(task['age_hours'] for task in tasks),
                    'max': max(task['age_hours'] for task in tasks)
                }
            },
            'status_distribution': {},
            'task_types': {},
            'worker_distribution': {},
            'attempt_distribution': {},
            'timing_analysis': {
                'avg_processing_duration': None,
                'avg_queue_duration': None,
                'processing_durations': [],
                'queue_durations': []
            }
        }
        
        # Status distribution
        statuses = [task['status'] for task in tasks]
        analysis['status_distribution'] = dict(Counter(statuses))
        
        # Task types
        task_types = [task.get('task_type', 'Unknown') for task in tasks]
        analysis['task_types'] = dict(Counter(task_types))
        
        # Worker distribution
        workers = [task.get('worker_id', 'Unassigned') for task in tasks]
        analysis['worker_distribution'] = dict(Counter(workers))
        
        # Attempt distribution
        attempts = [task.get('attempts', 0) for task in tasks]
        analysis['attempt_distribution'] = dict(Counter(attempts))
        
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
    
    def get_task_details(self, tasks: List[Dict[str, Any]], detailed: bool = False) -> List[Dict[str, Any]]:
        """Get detailed view of tasks"""
        task_details = []
        
        for task in tasks:
            detail = {
                'id': task['id'],
                'status': task['status'],
                'task_type': task.get('task_type', 'Unknown'),
                'worker_id': task.get('worker_id', 'Unassigned'),
                'attempts': task.get('attempts', 0),
                'age_hours': round(task['age_hours'], 2),
                'last_updated_hours': round(task['last_updated_hours'], 2),
                'created_at': task['created_at']
            }
            
            if detailed:
                detail.update({
                    'params': task.get('params'),
                    'error_message': task.get('error_message'),
                    'result_data': task.get('result_data'),
                    'processing_duration_seconds': task.get('processing_duration_seconds'),
                    'queue_duration_seconds': task.get('queue_duration_seconds')
                })
            
            task_details.append(detail)
        
        return task_details


def format_analysis_output(analysis: Dict[str, Any], detailed: bool = False) -> str:
    """Format analysis results for human-readable output"""
    output = []
    
    output.append(f"📊 Recent Task Analysis")
    output.append(f"{'=' * 50}")
    output.append(f"📋 Total Tasks: {analysis['total_tasks']}")
    
    if analysis['total_tasks'] == 0:
        return "\n".join(output)
    
    # Time range
    time_range = analysis['time_range']
    output.append(f"⏰ Time Range: {time_range['age_range_hours']['min']:.1f}h - {time_range['age_range_hours']['max']:.1f}h ago")
    
    # Status distribution
    output.append(f"\n📈 Status Distribution:")
    for status, count in sorted(analysis['status_distribution'].items()):
        percentage = (count / analysis['total_tasks']) * 100
        output.append(f"   {status}: {count} ({percentage:.1f}%)")
    
    # Task types
    if analysis['task_types']:
        output.append(f"\n🔧 Task Types:")
        for task_type, count in sorted(analysis['task_types'].items(), key=lambda x: x[1], reverse=True):
            percentage = (count / analysis['total_tasks']) * 100
            output.append(f"   {task_type}: {count} ({percentage:.1f}%)")
    
    # Worker distribution (top 5)
    if analysis['worker_distribution']:
        output.append(f"\n👷 Worker Distribution (top 5):")
        worker_items = sorted(analysis['worker_distribution'].items(), key=lambda x: x[1], reverse=True)[:5]
        for worker_id, count in worker_items:
            percentage = (count / analysis['total_tasks']) * 100
            worker_display = worker_id if worker_id != 'Unassigned' else 'Unassigned'
            output.append(f"   {worker_display}: {count} ({percentage:.1f}%)")
    
    # Timing analysis
    timing = analysis['timing_analysis']
    if timing['avg_processing_duration'] is not None or timing['avg_queue_duration'] is not None:
        output.append(f"\n⏱️  Timing Analysis:")
        if timing['avg_queue_duration'] is not None:
            output.append(f"   Avg Queue Time: {timing['avg_queue_duration']:.1f}s")
        if timing['avg_processing_duration'] is not None:
            output.append(f"   Avg Processing Time: {timing['avg_processing_duration']:.1f}s")
    
    return "\n".join(output)


async def main():
    parser = argparse.ArgumentParser(description='Analyze recent tasks in the database')
    parser.add_argument('--limit', type=int, default=50, help='Number of recent tasks to analyze (default: 50)')
    parser.add_argument('--format', choices=['text', 'json'], default='text', help='Output format')
    parser.add_argument('--detailed', action='store_true', help='Include detailed task breakdown')
    parser.add_argument('--output', type=str, help='Save output to file')
    
    args = parser.parse_args()
    
    # Initialize analyzer
    analyzer = RecentTaskAnalyzer()
    
    print(f"🔍 Analyzing {args.limit} most recent tasks...")
    
    # Get recent tasks
    tasks = await analyzer.get_recent_tasks(limit=args.limit)
    
    if not tasks:
        print("❌ No tasks found or error occurred")
        return
    
    # Analyze tasks
    analysis = analyzer.analyze_tasks(tasks)
    
    if args.format == 'json':
        # JSON output
        result = {
            'analysis': analysis,
            'tasks': analyzer.get_task_details(tasks, detailed=args.detailed)
        }
        output_text = json.dumps(result, indent=2, default=str)
    else:
        # Human-readable output
        output_text = format_analysis_output(analysis, detailed=args.detailed)
        
        if args.detailed:
            output_text += "\n\n📋 Task Details:\n"
            task_details = analyzer.get_task_details(tasks, detailed=True)
            for i, task in enumerate(task_details, 1):
                output_text += f"\n{i}. Task {task['id'][:8]}... ({task['status']})\n"
                output_text += f"   Type: {task['task_type']}, Worker: {task['worker_id']}, Attempts: {task['attempts']}\n"
                output_text += f"   Age: {task['age_hours']:.1f}h, Last Update: {task['last_updated_hours']:.1f}h ago\n"
                if task.get('error_message'):
                    output_text += f"   Error: {task['error_message'][:100]}...\n"
    
    # Output results
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_text)
        print(f"✅ Results saved to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 