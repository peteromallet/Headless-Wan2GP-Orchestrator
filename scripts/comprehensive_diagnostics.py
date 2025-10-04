#!/usr/bin/env python3
"""
Comprehensive diagnostic script to gather ALL information needed to debug GPU worker issues.
This extends fetch_worker_logs.py with structured analysis and systematic data collection.

Features:
- Complete Railway vs Local environment comparison
- Full worker lifecycle analysis 
- SSH authentication debugging
- RunPod API deep dive
- Database state validation
- Environment variable audit
- Orchestrator behavior analysis
- S3 storage comprehensive check
- Network connectivity testing
- Code deployment verification

Usage: python comprehensive_diagnostics.py [worker_id] [--save-report] [--include-sensitive]
"""

import os
import sys
import json
import asyncio
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from gpu_orchestrator.database import DatabaseClient
from gpu_orchestrator.runpod_client import RunpodClient, get_pod_ssh_details
from scripts.fetch_worker_logs import fetch_s3_worker_logs, check_orchestrator_logs

class ComprehensiveDiagnostics:
    """Comprehensive diagnostic analysis for GPU worker issues."""
    
    def __init__(self, include_sensitive: bool = False):
        self.include_sensitive = include_sensitive
        self.report = {
            "timestamp": datetime.now().isoformat(),
            "environment": {},
            "database_state": {},
            "runpod_state": {},
            "workers": {},
            "orchestrator_analysis": {},
            "network_tests": {},
            "deployment_verification": {},
            "recommendations": []
        }
        self.db = None
        self.runpod_client = None
    
    async def initialize_clients(self):
        """Initialize database and RunPod clients."""
        try:
            self.db = DatabaseClient()
            api_key = os.getenv('RUNPOD_API_KEY')
            if api_key:
                self.runpod_client = RunpodClient(api_key)
            else:
                print("⚠️  RUNPOD_API_KEY not found")
        except Exception as e:
            print(f"❌ Error initializing clients: {e}")
    
    def analyze_environment(self):
        """Analyze environment variables and configuration."""
        print("🔍 Analyzing Environment Configuration...")
        
        # Critical environment variables
        critical_vars = [
            'RUNPOD_API_KEY',
            'SUPABASE_URL', 
            'SUPABASE_SERVICE_ROLE_KEY',
            'RUNPOD_SSH_PUBLIC_KEY',
            'RUNPOD_SSH_PRIVATE_KEY',
            'RUNPOD_SSH_PRIVATE_KEY_PATH'
        ]
        
        # Important environment variables
        important_vars = [
            'RUNPOD_STORAGE_NAME',
            'RUNPOD_GPU_TYPE',
            'RUNPOD_WORKER_IMAGE',
            'RUNPOD_VOLUME_MOUNT_PATH',
            'RUNPOD_DISK_SIZE_GB',
            'RUNPOD_CONTAINER_DISK_GB',
            'MAX_ACTIVE_GPUS',
            'MIN_ACTIVE_GPUS',
            'GPU_IDLE_TIMEOUT_SEC',
            'TASKS_PER_GPU_THRESHOLD',
            'AUTO_START_WORKER_PROCESS'
        ]
        
        # AWS/S3 variables
        aws_vars = [
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY',
            'AWS_DEFAULT_REGION'
        ]
        
        env_analysis = {
            "critical": {},
            "important": {},
            "aws": {},
            "all_runpod": {},
            "missing_critical": [],
            "missing_important": []
        }
        
        # Check critical variables
        for var in critical_vars:
            value = os.getenv(var)
            if value:
                if self.include_sensitive:
                    env_analysis["critical"][var] = value
                else:
                    # Show first/last few chars for verification
                    if len(value) > 10:
                        env_analysis["critical"][var] = f"{value[:8]}...{value[-4:]}"
                    else:
                        env_analysis["critical"][var] = "***PRESENT***"
            else:
                env_analysis["missing_critical"].append(var)
        
        # Check important variables
        for var in important_vars:
            value = os.getenv(var)
            if value:
                env_analysis["important"][var] = value
            else:
                env_analysis["missing_important"].append(var)
        
        # Check AWS variables
        for var in aws_vars:
            value = os.getenv(var)
            if value:
                if self.include_sensitive and var != 'AWS_DEFAULT_REGION':
                    env_analysis["aws"][var] = value
                else:
                    env_analysis["aws"][var] = "***PRESENT***" if var != 'AWS_DEFAULT_REGION' else value
        
        # Get all RUNPOD_* variables
        for key, value in os.environ.items():
            if key.startswith('RUNPOD_'):
                if key not in critical_vars and key not in important_vars:
                    env_analysis["all_runpod"][key] = value
        
        self.report["environment"] = env_analysis
        
        # Print summary
        print(f"   ✅ Critical vars present: {len(env_analysis['critical'])}/{len(critical_vars)}")
        print(f"   ⚠️  Important vars present: {len(env_analysis['important'])}/{len(important_vars)}")
        
        if env_analysis["missing_critical"]:
            print(f"   ❌ Missing critical: {', '.join(env_analysis['missing_critical'])}")
        
        if env_analysis["missing_important"]:
            print(f"   ⚠️  Missing important: {', '.join(env_analysis['missing_important'])}")
    
    async def analyze_database_state(self):
        """Analyze database state and RPC functions."""
        print("🗄️  Analyzing Database State...")
        
        if not self.db:
            print("   ❌ Database client not available")
            return
        
        try:
            # Get all workers
            all_workers = await self.db.get_workers()
            workers_by_status = {}
            for worker in all_workers:
                status = worker.get('status', 'unknown')
                if status not in workers_by_status:
                    workers_by_status[status] = []
                workers_by_status[status].append(worker)
            
            # Get task counts using Edge Function instead of RPC
            task_counts = await self.db.get_detailed_task_counts_via_edge_function()
            
            # Test RPC functions
            rpc_tests = {}
            
            # Test claim_next_task
            try:
                claim_result = self.db.supabase.rpc('claim_next_task', {'worker_id': 'test-worker-diagnostic'}).execute()
                rpc_tests['claim_next_task'] = "✅ Available"
            except Exception as e:
                rpc_tests['claim_next_task'] = f"❌ Error: {str(e)}"
            
            # Test reset_orphaned_tasks
            try:
                reset_result = self.db.supabase.rpc('reset_orphaned_tasks', {'timeout_minutes': 10}).execute()
                rpc_tests['reset_orphaned_tasks'] = "✅ Available"
            except Exception as e:
                rpc_tests['reset_orphaned_tasks'] = f"❌ Error: {str(e)}"
            
            db_analysis = {
                "total_workers": len(all_workers),
                "workers_by_status": {status: len(workers) for status, workers in workers_by_status.items()},
                "task_counts": task_counts,
                "rpc_function_tests": rpc_tests,
                "recent_workers": []
            }
            
            # Get recent workers (last 24 hours)
            for worker in sorted(all_workers, key=lambda w: w.get('created_at', ''), reverse=True)[:10]:
                worker_info = {
                    "id": worker['id'],
                    "status": worker.get('status'),
                    "created_at": worker.get('created_at'),
                    "last_heartbeat": worker.get('last_heartbeat'),
                    "runpod_id": worker.get('metadata', {}).get('runpod_id'),
                    "instance_type": worker.get('instance_type')
                }
                db_analysis["recent_workers"].append(worker_info)
            
            self.report["database_state"] = db_analysis
            
            print(f"   📊 Total workers: {db_analysis['total_workers']}")
            for status, count in db_analysis["workers_by_status"].items():
                print(f"      {status}: {count}")
            
            print(f"   📦 Task counts: {task_counts}")
            
        except Exception as e:
            print(f"   ❌ Database analysis error: {e}")
            self.report["database_state"] = {"error": str(e)}
    
    async def analyze_runpod_state(self):
        """Analyze RunPod API state and connectivity."""
        print("☁️  Analyzing RunPod State...")
        
        if not self.runpod_client:
            print("   ❌ RunPod client not available")
            return
        
        try:
            import runpod
            runpod.api_key = os.getenv('RUNPOD_API_KEY')
            
            # Get all pods
            pods = runpod.get_pods()
            
            # Analyze pods
            pods_by_status = {}
            active_pods = []
            
            for pod in pods:
                status = pod.get('desiredStatus', 'unknown')
                if status not in pods_by_status:
                    pods_by_status[status] = []
                pods_by_status[status].append(pod)
                
                if status in ['RUNNING', 'PROVISIONING']:
                    active_pods.append({
                        "id": pod.get('id'),
                        "name": pod.get('name'),
                        "status": status,
                        "created_at": pod.get('createdAt'),
                        "cost_per_hr": pod.get('costPerHr'),
                        "gpu_count": pod.get('gpuCount'),
                        "machine": pod.get('machine', {}).get('podHostId'),
                        "runtime": pod.get('runtime', {})
                    })
            
            # Test SSH connectivity for active pods
            ssh_tests = {}
            for pod in active_pods[:3]:  # Test first 3 active pods
                pod_id = pod['id']
                try:
                    ssh_details = get_pod_ssh_details(pod_id, os.getenv('RUNPOD_API_KEY'))
                    if ssh_details:
                        ssh_tests[pod_id] = {
                            "ssh_details": ssh_details,
                            "status": "✅ SSH details available"
                        }
                        
                        # Test actual SSH connection
                        ssh_client = self.runpod_client.get_ssh_client(pod_id)
                        if ssh_client:
                            try:
                                ssh_client.connect()
                                ssh_tests[pod_id]["connection"] = "✅ SSH connection successful"
                                ssh_client.disconnect()
                            except Exception as e:
                                ssh_tests[pod_id]["connection"] = f"❌ SSH connection failed: {e}"
                        else:
                            ssh_tests[pod_id]["connection"] = "❌ Could not create SSH client"
                    else:
                        ssh_tests[pod_id] = {
                            "status": "❌ No SSH details available"
                        }
                except Exception as e:
                    ssh_tests[pod_id] = {
                        "status": f"❌ Error getting SSH details: {e}"
                    }
            
            runpod_analysis = {
                "total_pods": len(pods),
                "pods_by_status": {status: len(pod_list) for status, pod_list in pods_by_status.items()},
                "active_pods": active_pods,
                "ssh_connectivity_tests": ssh_tests,
                "total_hourly_cost": sum(pod.get('costPerHr', 0) for pod in pods if pod.get('desiredStatus') in ['RUNNING', 'PROVISIONING'])
            }
            
            self.report["runpod_state"] = runpod_analysis
            
            print(f"   📊 Total pods: {runpod_analysis['total_pods']}")
            for status, count in runpod_analysis["pods_by_status"].items():
                print(f"      {status}: {count}")
            
            print(f"   💰 Total hourly cost: ${runpod_analysis['total_hourly_cost']:.3f}/hr")
            print(f"   🔗 SSH tests performed on {len(ssh_tests)} pods")
            
        except Exception as e:
            print(f"   ❌ RunPod analysis error: {e}")
            self.report["runpod_state"] = {"error": str(e)}
    
    async def analyze_specific_worker(self, worker_id: str):
        """Deep analysis of a specific worker."""
        print(f"🤖 Deep Analysis: Worker {worker_id}")
        
        worker_analysis = {
            "worker_id": worker_id,
            "database_record": None,
            "runpod_pod": None,
            "ssh_analysis": {},
            "log_analysis": {},
            "lifecycle_events": []
        }
        
        try:
            # Get worker from database
            if self.db:
                workers = await self.db.get_workers()
                worker = next((w for w in workers if w['id'] == worker_id), None)
                if worker:
                    worker_analysis["database_record"] = worker
                    print(f"   📋 Database record found: {worker.get('status')}")
                    
                    # Get RunPod pod info
                    runpod_id = worker.get('metadata', {}).get('runpod_id')
                    if runpod_id and self.runpod_client:
                        try:
                            import runpod
                            runpod.api_key = os.getenv('RUNPOD_API_KEY')
                            pod = runpod.get_pod(runpod_id)
                            if pod:
                                worker_analysis["runpod_pod"] = pod
                                print(f"   ☁️  RunPod pod found: {pod.get('desiredStatus')}")
                                
                                # SSH analysis
                                ssh_details = get_pod_ssh_details(runpod_id, os.getenv('RUNPOD_API_KEY'))
                                worker_analysis["ssh_analysis"]["ssh_details"] = ssh_details
                                
                                if ssh_details:
                                    print(f"   🔗 SSH available: {ssh_details['ip']}:{ssh_details['port']}")
                                    
                                    # Test SSH connection
                                    ssh_client = self.runpod_client.get_ssh_client(runpod_id)
                                    if ssh_client:
                                        try:
                                            ssh_client.connect()
                                            worker_analysis["ssh_analysis"]["connection_status"] = "✅ Connected"
                                            
                                            # Get worker process status
                                            exit_code, stdout, stderr = ssh_client.execute_command('ps aux | grep -E "(python|worker)" | grep -v grep', timeout=10)
                                            worker_analysis["ssh_analysis"]["processes"] = {
                                                "exit_code": exit_code,
                                                "stdout": stdout,
                                                "stderr": stderr
                                            }
                                            
                                            # Check if worker script exists
                                            exit_code, stdout, stderr = ssh_client.execute_command('ls -la /workspace/Headless-Wan2GP/worker.py', timeout=10)
                                            worker_analysis["ssh_analysis"]["worker_script"] = {
                                                "exists": exit_code == 0,
                                                "details": stdout if exit_code == 0 else stderr
                                            }
                                            
                                            # Check workspace directory
                                            exit_code, stdout, stderr = ssh_client.execute_command('ls -la /workspace/Headless-Wan2GP/', timeout=10)
                                            worker_analysis["ssh_analysis"]["workspace"] = {
                                                "accessible": exit_code == 0,
                                                "contents": stdout if exit_code == 0 else stderr
                                            }
                                            
                                            ssh_client.disconnect()
                                            
                                        except Exception as e:
                                            worker_analysis["ssh_analysis"]["connection_error"] = str(e)
                                            print(f"   ❌ SSH connection failed: {e}")
                                else:
                                    print("   ❌ No SSH details available")
                            else:
                                print(f"   ❌ RunPod pod {runpod_id} not found")
                        except Exception as e:
                            worker_analysis["runpod_pod"] = {"error": str(e)}
                            print(f"   ❌ Error getting RunPod pod: {e}")
                else:
                    print("   ❌ Worker not found in database")
            
            # Orchestrator log analysis
            print("   📋 Analyzing orchestrator logs...")
            # This will be captured in the log output
            await check_orchestrator_logs(worker_id, 50)
            
            # S3 log analysis
            print("   📦 Checking S3 logs...")
            s3_success = await fetch_s3_worker_logs(worker_id, 50)
            worker_analysis["log_analysis"]["s3_logs_available"] = s3_success
            
        except Exception as e:
            worker_analysis["error"] = str(e)
            print(f"   ❌ Worker analysis error: {e}")
        
        self.report["workers"][worker_id] = worker_analysis
        return worker_analysis
    
    async def analyze_orchestrator_behavior(self):
        """Analyze orchestrator behavior and patterns."""
        print("🎛️  Analyzing Orchestrator Behavior...")
        
        orchestrator_analysis = {
            "log_file_exists": False,
            "recent_cycles": [],
            "error_patterns": {},
            "scaling_decisions": [],
            "worker_lifecycle_events": []
        }
        
        # Check orchestrator log
        orchestrator_log = Path(__file__).parent.parent / "orchestrator.log"
        if orchestrator_log.exists():
            orchestrator_analysis["log_file_exists"] = True
            orchestrator_analysis["log_size_mb"] = orchestrator_log.stat().st_size / 1024 / 1024
            
            try:
                # Analyze recent log entries
                with open(orchestrator_log, 'r') as f:
                    lines = f.readlines()
                
                # Get last 100 lines for analysis
                recent_lines = lines[-100:]
                
                error_counts = {}
                cycle_count = 0
                
                for line in recent_lines:
                    # Count orchestrator cycles
                    if "ORCHESTRATOR CYCLE" in line:
                        cycle_count += 1
                    
                    # Count error patterns
                    if "ERROR" in line or "Failed" in line:
                        # Extract error type
                        if "Failed to reset orphaned tasks" in line:
                            error_counts["orphaned_tasks_reset"] = error_counts.get("orphaned_tasks_reset", 0) + 1
                        elif "SSH" in line and ("failed" in line.lower() or "error" in line.lower()):
                            error_counts["ssh_errors"] = error_counts.get("ssh_errors", 0) + 1
                        elif "Authentication failed" in line:
                            error_counts["auth_failures"] = error_counts.get("auth_failures", 0) + 1
                        else:
                            error_counts["other_errors"] = error_counts.get("other_errors", 0) + 1
                
                orchestrator_analysis["recent_cycles_count"] = cycle_count
                orchestrator_analysis["error_patterns"] = error_counts
                
                print(f"   📊 Log size: {orchestrator_analysis['log_size_mb']:.2f} MB")
                print(f"   🔄 Recent cycles: {cycle_count}")
                if error_counts:
                    print(f"   ❌ Error patterns: {error_counts}")
                
            except Exception as e:
                orchestrator_analysis["log_analysis_error"] = str(e)
                print(f"   ⚠️  Log analysis error: {e}")
        else:
            print("   ❌ orchestrator.log not found")
        
        self.report["orchestrator_analysis"] = orchestrator_analysis
    
    async def test_network_connectivity(self):
        """Test network connectivity to various services."""
        print("🌐 Testing Network Connectivity...")
        
        connectivity_tests = {}
        
        # Test endpoints
        endpoints = [
            ("Supabase", os.getenv('SUPABASE_URL')),
            ("RunPod API", "https://api.runpod.io/graphql"),
            ("RunPod S3", "https://s3api-eu-ro-1.runpod.io"),
            ("GitHub", "https://github.com"),
        ]
        
        for name, url in endpoints:
            if url:
                try:
                    import requests
                    response = requests.get(url, timeout=10)
                    connectivity_tests[name] = {
                        "status_code": response.status_code,
                        "response_time_ms": int(response.elapsed.total_seconds() * 1000),
                        "accessible": response.status_code < 500
                    }
                    print(f"   {name}: ✅ {response.status_code} ({connectivity_tests[name]['response_time_ms']}ms)")
                except Exception as e:
                    connectivity_tests[name] = {
                        "error": str(e),
                        "accessible": False
                    }
                    print(f"   {name}: ❌ {e}")
            else:
                connectivity_tests[name] = {"error": "URL not configured"}
                print(f"   {name}: ⚠️  URL not configured")
        
        self.report["network_tests"] = connectivity_tests
    
    async def verify_deployment(self):
        """Verify code deployment and version consistency."""
        print("🚀 Verifying Deployment...")
        
        deployment_info = {
            "git_status": {},
            "local_vs_remote": {},
            "railway_status": {}
        }
        
        try:
            # Git status
            result = subprocess.run(['git', 'status', '--porcelain'], 
                                  capture_output=True, text=True, timeout=10)
            deployment_info["git_status"] = {
                "clean": result.returncode == 0 and not result.stdout.strip(),
                "output": result.stdout.strip(),
                "uncommitted_files": len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
            }
            
            # Get current commit
            result = subprocess.run(['git', 'rev-parse', 'HEAD'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                deployment_info["git_status"]["current_commit"] = result.stdout.strip()
            
            # Check Railway status
            result = subprocess.run(['railway', 'status'], 
                                  capture_output=True, text=True, timeout=30)
            deployment_info["railway_status"] = {
                "command_available": result.returncode == 0,
                "output": result.stdout if result.returncode == 0 else result.stderr
            }
            
            print(f"   📊 Git clean: {deployment_info['git_status']['clean']}")
            if deployment_info["git_status"].get("current_commit"):
                print(f"   📊 Current commit: {deployment_info['git_status']['current_commit'][:8]}")
            
        except Exception as e:
            deployment_info["error"] = str(e)
            print(f"   ❌ Deployment verification error: {e}")
        
        self.report["deployment_verification"] = deployment_info
    
    def generate_recommendations(self):
        """Generate recommendations based on analysis."""
        print("💡 Generating Recommendations...")
        
        recommendations = []
        
        # Check environment issues
        env = self.report.get("environment", {})
        if env.get("missing_critical"):
            recommendations.append({
                "priority": "HIGH",
                "category": "Environment",
                "issue": f"Missing critical environment variables: {', '.join(env['missing_critical'])}",
                "action": "Add missing environment variables to Railway deployment"
            })
        
        # Check SSH authentication
        runpod_state = self.report.get("runpod_state", {})
        ssh_tests = runpod_state.get("ssh_connectivity_tests", {})
        failed_ssh = [pod_id for pod_id, test in ssh_tests.items() if "failed" in test.get("connection", "")]
        
        if failed_ssh:
            recommendations.append({
                "priority": "HIGH", 
                "category": "SSH",
                "issue": f"SSH authentication failing for {len(failed_ssh)} pods",
                "action": "Verify RUNPOD_SSH_PRIVATE_KEY is correctly set in Railway environment"
            })
        
        # Check database RPC errors
        orchestrator = self.report.get("orchestrator_analysis", {})
        error_patterns = orchestrator.get("error_patterns", {})
        if error_patterns.get("orphaned_tasks_reset", 0) > 5:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "Database",
                "issue": "Frequent 'Failed to reset orphaned tasks' errors",
                "action": "Check Supabase RPC function permissions and Edge Function logs"
            })
        
        # Check worker startup issues
        workers = self.report.get("workers", {})
        for worker_id, worker_data in workers.items():
            ssh_analysis = worker_data.get("ssh_analysis", {})
            if ssh_analysis.get("connection_status") == "✅ Connected":
                processes = ssh_analysis.get("processes", {})
                if processes.get("exit_code") == 0 and not processes.get("stdout", "").strip():
                    recommendations.append({
                        "priority": "HIGH",
                        "category": "Worker Process",
                        "issue": f"Worker {worker_id} is accessible via SSH but no worker process is running",
                        "action": "Investigate start_worker_process() execution and worker script startup"
                    })
        
        # Check cost optimization
        if runpod_state.get("total_hourly_cost", 0) > 2.0:
            recommendations.append({
                "priority": "MEDIUM",
                "category": "Cost",
                "issue": f"High hourly cost: ${runpod_state['total_hourly_cost']:.2f}/hr",
                "action": "Consider terminating idle or stuck workers"
            })
        
        self.report["recommendations"] = recommendations
        
        print(f"   📋 Generated {len(recommendations)} recommendations")
        for rec in recommendations:
            print(f"   {rec['priority']}: {rec['issue']}")
    
    async def run_comprehensive_analysis(self, worker_id: Optional[str] = None):
        """Run complete diagnostic analysis."""
        print("🔍 COMPREHENSIVE GPU ORCHESTRATOR DIAGNOSTICS")
        print("=" * 80)
        
        await self.initialize_clients()
        
        # Core analysis
        self.analyze_environment()
        print()
        
        await self.analyze_database_state()
        print()
        
        await self.analyze_runpod_state()
        print()
        
        await self.analyze_orchestrator_behavior()
        print()
        
        await self.test_network_connectivity()
        print()
        
        await self.verify_deployment()
        print()
        
        # Specific worker analysis
        if worker_id:
            await self.analyze_specific_worker(worker_id)
            print()
        else:
            # Analyze recent active workers
            db_state = self.report.get("database_state", {})
            recent_workers = db_state.get("recent_workers", [])
            active_workers = [w for w in recent_workers if w.get("status") in ["active", "spawning"]]
            
            if active_workers:
                print(f"🤖 Analyzing {len(active_workers)} recent active workers...")
                for worker in active_workers[:3]:  # Limit to first 3
                    await self.analyze_specific_worker(worker["id"])
                print()
        
        # Generate recommendations
        self.generate_recommendations()
        print()
        
        print("✅ Comprehensive analysis complete!")
        return self.report
    
    def save_report(self, filename: str = None):
        """Save diagnostic report to file."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"diagnostic_report_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(self.report, f, indent=2, default=str)
        
        print(f"📄 Report saved to: {filename}")
        return filename


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Comprehensive GPU orchestrator diagnostics')
    parser.add_argument('worker_id', nargs='?', help='Specific worker ID to analyze in detail')
    parser.add_argument('--save-report', action='store_true', help='Save detailed report to JSON file')
    parser.add_argument('--include-sensitive', action='store_true', help='Include sensitive data in report (use carefully)')
    
    args = parser.parse_args()
    
    # Check required environment variables
    if not os.getenv('RUNPOD_API_KEY'):
        print("❌ RUNPOD_API_KEY environment variable is required")
        sys.exit(1)
    
    if not os.getenv('SUPABASE_URL'):
        print("❌ SUPABASE_URL environment variable is required")
        sys.exit(1)
    
    try:
        diagnostics = ComprehensiveDiagnostics(include_sensitive=args.include_sensitive)
        report = await diagnostics.run_comprehensive_analysis(args.worker_id)
        
        if args.save_report:
            diagnostics.save_report()
        
        # Print key findings
        print("\n🎯 KEY FINDINGS:")
        print("-" * 40)
        
        recommendations = report.get("recommendations", [])
        high_priority = [r for r in recommendations if r.get("priority") == "HIGH"]
        
        if high_priority:
            print("🚨 HIGH PRIORITY ISSUES:")
            for rec in high_priority:
                print(f"   • {rec['issue']}")
                print(f"     → {rec['action']}")
        else:
            print("✅ No high priority issues found")
        
        # Show active workers summary
        workers = report.get("workers", {})
        if workers:
            print(f"\n🤖 WORKERS ANALYZED: {len(workers)}")
            for worker_id, data in workers.items():
                db_record = data.get("database_record", {})
                ssh_analysis = data.get("ssh_analysis", {})
                print(f"   • {worker_id}: {db_record.get('status', 'unknown')}")
                if ssh_analysis.get("connection_status"):
                    print(f"     SSH: {ssh_analysis['connection_status']}")
        
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
