#!/usr/bin/env python3
"""
Comprehensive task failure analysis script.
Combines database queries for failed tasks with detailed log analysis.

This script:
1. Queries recently failed tasks from Supabase
2. Analyzes failure patterns and trends
3. Fetches detailed logs from orchestrator and workers
4. Provides actionable insights and recommendations

Usage:
  python analyze_task_failures.py                    # Quick analysis of last 24 hours
  python analyze_task_failures.py --hours 48         # Analyze last 48 hours
  python analyze_task_failures.py --detailed         # Include full log analysis
  python analyze_task_failures.py --save-report      # Save comprehensive report
"""

import os
import sys
import argparse
import asyncio
from datetime import datetime
from pathlib import Path

# Add project root to Python path
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent))

# Import our custom modules
from query_failed_tasks import FailedTaskAnalyzer, format_analysis_output
from fetch_task_logs import TaskLogParser, find_worker_for_task, search_specific_worker_logs_for_task


async def comprehensive_failure_analysis(hours_back: int = 24, detailed_logs: bool = True, save_report: bool = False):
    """Run comprehensive failure analysis"""
    
    print(f"🔍 Comprehensive Task Failure Analysis")
    print(f"📅 Time Range: Last {hours_back} hours")
    print(f"📋 Detailed Logs: {'Enabled' if detailed_logs else 'Disabled'}")
    print("=" * 80)
    
    # Initialize analyzer
    analyzer = FailedTaskAnalyzer()
    
    # Step 1: Get failed tasks from database
    print(f"\n📊 Step 1: Querying failed tasks from database...")
    failed_tasks = await analyzer.get_failed_tasks(hours_back=hours_back, limit=100)
    
    if not failed_tasks:
        print("✅ No failed tasks found in the specified time range.")
        print("🎉 System appears to be running smoothly!")
        return
    
    print(f"   Found {len(failed_tasks)} failed tasks")
    
    # Step 2: Analyze failure patterns
    print(f"\n📈 Step 2: Analyzing failure patterns...")
    analysis = await analyzer.analyze_failure_patterns(failed_tasks)
    
    # Step 3: Get most critical tasks
    print(f"\n🎯 Step 3: Identifying critical failures...")
    critical_tasks = await analyzer.get_most_critical_tasks(failed_tasks, limit=10)
    print(f"   Identified {len(critical_tasks)} critical tasks for detailed analysis")
    
    # Prepare comprehensive report
    report_sections = []
    
    # Executive Summary
    report_sections.append("📋 EXECUTIVE SUMMARY")
    report_sections.append("=" * 80)
    report_sections.append(f"• Total Failed Tasks: {len(failed_tasks)}")
    report_sections.append(f"• Time Period: Last {hours_back} hours")
    report_sections.append(f"• Critical Tasks: {len(critical_tasks)}")
    
    # Top error categories
    error_cats = analysis['error_categories']
    top_errors = sorted(error_cats.items(), key=lambda x: x[1], reverse=True)[:3]
    report_sections.append(f"• Top Error Types:")
    for error_type, count in top_errors:
        percentage = (count / len(failed_tasks)) * 100
        report_sections.append(f"  - {error_type}: {count} ({percentage:.1f}%)")
    
    # Worker impact
    worker_analysis = analysis['worker_analysis']
    affected_workers = len([w for w in worker_analysis.values() if w['failed_tasks'] > 0])
    report_sections.append(f"• Affected Workers: {affected_workers}")
    
    # Pattern Analysis
    report_sections.append(f"\n{format_analysis_output(analysis)}")
    
    # Step 4: Detailed log analysis for critical tasks
    if detailed_logs and critical_tasks:
        print(f"\n📋 Step 4: Fetching detailed logs for critical tasks...")
        
        report_sections.append(f"\n🔍 DETAILED LOG ANALYSIS")
        report_sections.append("=" * 80)
        
        # Check if orchestrator log exists
        log_file = 'orchestrator.log'
        orchestrator_available = os.path.exists(log_file)
        
        if not orchestrator_available:
            print(f"   ⚠️  Orchestrator log not found at {log_file}")
            report_sections.append(f"⚠️  Orchestrator log not found at {log_file}")
        
        # Analyze each critical task
        for i, task in enumerate(critical_tasks[:5], 1):  # Limit to top 5 for performance
            task_id = task['id']
            worker_id = task.get('worker_id')
            error_category = task.get('error_category', 'Unknown')
            
            print(f"   📄 Analyzing task {i}/{min(5, len(critical_tasks))}: {task_id}")
            
            task_report = []
            task_report.append(f"\n🔍 Task {i}: {task_id}")
            task_report.append(f"   Category: {error_category}")
            task_report.append(f"   Worker: {worker_id or 'Unassigned'}")
            task_report.append(f"   Attempts: {task.get('attempts', 0)}")
            task_report.append(f"   Created: {task.get('created_at', 'N/A')}")
            task_report.append(f"   Failed: {task.get('updated_at', 'N/A')}")
            
            # Processing duration
            if task.get('processing_duration_seconds'):
                duration = task['processing_duration_seconds']
                task_report.append(f"   Processing Duration: {duration:.1f}s")
                if duration > 600:  # More than 10 minutes
                    task_report.append(f"   ⚠️  Long processing time may indicate hung process")
            
            # Error message
            error_msg = task.get('error_message', '')
            if error_msg:
                # Clean and truncate error message
                error_lines = error_msg.split('\n')[:3]  # First 3 lines
                for line in error_lines:
                    if line.strip():
                        task_report.append(f"   Error: {line.strip()[:150]}{'...' if len(line.strip()) > 150 else ''}")
            
            # Orchestrator logs
            if orchestrator_available:
                try:
                    parser = TaskLogParser(log_file)
                    entries = parser.find_task_logs(task_id, context_lines=1)
                    
                    if entries:
                        matches = [e for e in entries if e.get('is_match')]
                        task_report.append(f"   📋 Orchestrator Log: {len(matches)} entries")
                        
                        # Show key error/failure entries
                        error_entries = []
                        for entry in matches:
                            msg = entry.get('message', '').lower()
                            if any(keyword in msg for keyword in ['error', 'failed', 'exception', 'timeout']):
                                error_entries.append(entry)
                        
                        for entry in error_entries[-2:]:  # Last 2 error entries
                            timestamp = entry.get('timestamp', 'N/A')
                            message = entry.get('message', '')[:120]
                            task_report.append(f"      [{entry['line_number']}] {timestamp} | {message}{'...' if len(entry.get('message', '')) > 120 else ''}")
                    else:
                        task_report.append(f"   📋 Orchestrator Log: No entries found")
                        
                except Exception as e:
                    task_report.append(f"   📋 Orchestrator Log: Error - {e}")
            
            # Worker logs
            if worker_id:
                try:
                    print(f"      🤖 Fetching worker logs for {worker_id}...")
                    worker_results = await search_specific_worker_logs_for_task(worker_id, task_id, lines=30)
                    
                    if worker_results and worker_results.get('logs_found'):
                        entries_count = len(worker_results.get('task_entries', []))
                        search_method = worker_results.get('search_method', 'Unknown')
                        task_report.append(f"   🤖 Worker Log ({search_method}): {entries_count} entries")
                        
                        # Show recent relevant entries
                        task_entries = worker_results.get('task_entries', [])
                        for entry in task_entries[-3:]:  # Last 3 entries
                            line_num = entry.get('line_number', 'N/A')
                            content = entry.get('content', '')[:120]
                            task_report.append(f"      [{line_num}] {content}{'...' if len(entry.get('content', '')) > 120 else ''}")
                    else:
                        error_msg = worker_results.get('error', 'No logs found')
                        task_report.append(f"   🤖 Worker Log: {error_msg}")
                        
                except Exception as e:
                    task_report.append(f"   🤖 Worker Log: Error - {e}")
            else:
                task_report.append(f"   🤖 Worker Log: No worker assigned")
            
            report_sections.extend(task_report)
    
    # Step 5: Generate recommendations
    print(f"\n💡 Step 5: Generating recommendations...")
    
    recommendations = []
    recommendations.append(f"\n💡 RECOMMENDATIONS")
    recommendations.append("=" * 80)
    
    error_cats = analysis['error_categories']
    total_tasks = len(failed_tasks)
    
    # Specific recommendations based on error patterns
    if error_cats.get('CUDA OOM', 0) > total_tasks * 0.2:  # More than 20% are OOM
        recommendations.append(f"🔥 HIGH PRIORITY: CUDA Out of Memory ({error_cats['CUDA OOM']} failures)")
        recommendations.append(f"   • Reduce batch size in task parameters")
        recommendations.append(f"   • Consider using higher VRAM GPU instances")
        recommendations.append(f"   • Implement dynamic batch size adjustment")
    
    if error_cats.get('Worker Unavailable', 0) > 0:
        recommendations.append(f"⚠️  INFRASTRUCTURE: Worker Availability Issues ({error_cats['Worker Unavailable']} failures)")
        recommendations.append(f"   • Check worker health monitoring")
        recommendations.append(f"   • Review scaling policies")
        recommendations.append(f"   • Verify network connectivity")
    
    if error_cats.get('Timeout', 0) > 0:
        recommendations.append(f"⏱️  PERFORMANCE: Timeout Issues ({error_cats['Timeout']} failures)")
        recommendations.append(f"   • Review task timeout configurations")
        recommendations.append(f"   • Check for hung processes")
        recommendations.append(f"   • Consider task complexity limits")
    
    if error_cats.get('Model Loading Error', 0) > 0:
        recommendations.append(f"🤖 MODEL: Loading Issues ({error_cats['Model Loading Error']} failures)")
        recommendations.append(f"   • Verify model file availability")
        recommendations.append(f"   • Check storage permissions")
        recommendations.append(f"   • Review model cache policies")
    
    # Worker-specific recommendations
    problematic_workers = [(w_id, w_data) for w_id, w_data in worker_analysis.items() 
                          if w_data['failed_tasks'] > total_tasks * 0.1]  # Workers with >10% of failures
    
    if problematic_workers:
        recommendations.append(f"\n🤖 PROBLEMATIC WORKERS:")
        for worker_id, worker_data in sorted(problematic_workers, key=lambda x: x[1]['failed_tasks'], reverse=True)[:5]:
            recommendations.append(f"   • {worker_id}: {worker_data['failed_tasks']} failures")
            top_error = max(worker_data['error_categories'].items(), key=lambda x: x[1]) if worker_data['error_categories'] else ('Unknown', 0)
            recommendations.append(f"     └─ Primary issue: {top_error[0]} ({top_error[1]} times)")
    
    # General system health
    if total_tasks > 50:
        recommendations.append(f"\n⚠️  SYSTEM HEALTH: High failure volume ({total_tasks} failures)")
        recommendations.append(f"   • Review overall system capacity")
        recommendations.append(f"   • Consider maintenance window")
        recommendations.append(f"   • Audit recent configuration changes")
    
    # Operational recommendations
    recommendations.append(f"\n📋 OPERATIONAL:")
    recommendations.append(f"   • Monitor failure trends over longer periods")
    recommendations.append(f"   • Set up automated alerts for error spikes")
    recommendations.append(f"   • Review task retry policies")
    recommendations.append(f"   • Consider implementing circuit breakers")
    
    report_sections.extend(recommendations)
    
    # Combine all sections
    full_report = '\n'.join(report_sections)
    
    # Display or save report
    if save_report:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"failure_analysis_report_{timestamp}.md"
        with open(filename, 'w') as f:
            f.write(f"# Task Failure Analysis Report\n\n")
            f.write(f"**Generated:** {datetime.now().isoformat()}\n")
            f.write(f"**Time Range:** Last {hours_back} hours\n")
            f.write(f"**Total Failed Tasks:** {len(failed_tasks)}\n")
            f.write(f"**Critical Tasks Analyzed:** {len(critical_tasks)}\n\n")
            f.write(full_report)
        print(f"\n💾 Comprehensive report saved to: {filename}")
    else:
        print(full_report)
    
    # Final summary
    print(f"\n✅ Analysis Complete")
    print(f"   📊 Failed Tasks: {len(failed_tasks)}")
    print(f"   🎯 Critical Tasks: {len(critical_tasks)}")
    print(f"   📋 Log Entries: {'Analyzed' if detailed_logs else 'Skipped'}")
    
    if len(failed_tasks) == 0:
        print(f"   🎉 No failures detected - system is healthy!")
    elif len(failed_tasks) < 10:
        print(f"   ✅ Low failure rate - monitor trends")
    elif len(failed_tasks) < 30:
        print(f"   ⚠️  Moderate failure rate - review recommendations")
    else:
        print(f"   🔥 High failure rate - immediate action recommended")


def main():
    parser = argparse.ArgumentParser(description='Comprehensive task failure analysis')
    parser.add_argument('--hours', '-H', type=int, default=24, help='Hours back to analyze (default: 24)')
    parser.add_argument('--detailed', '-d', action='store_true', help='Include detailed log analysis (slower)')
    parser.add_argument('--save-report', '-s', action='store_true', help='Save comprehensive report to file')
    parser.add_argument('--quick', '-q', action='store_true', help='Quick analysis without detailed logs')
    
    args = parser.parse_args()
    
    # Determine if we should fetch detailed logs
    detailed_logs = args.detailed and not args.quick
    if not args.detailed and not args.quick:
        detailed_logs = True  # Default to detailed analysis
    
    # Run the analysis
    asyncio.run(comprehensive_failure_analysis(
        hours_back=args.hours,
        detailed_logs=detailed_logs,
        save_report=args.save_report
    ))


if __name__ == '__main__':
    main() 