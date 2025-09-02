#!/usr/bin/env python3
"""
Monitor for orphaned RunPod instances and alert when sync issues occur.
This script should be run regularly (e.g., every 5 minutes) to catch orphaned pods early.
"""

import os
import sys
import asyncio
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add parent directory to path to import orchestrator modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.sync_runpod_database import sync_runpod_database

async def monitor_orphaned_pods():
    """Monitor for orphaned pods and send alerts if found."""
    
    try:
        # Analyze current state
        result = await sync_runpod_database("analyze")
        
        orphaned_count = result['orphaned_pods']
        stale_workers = result['stale_workers']
        
        # Calculate cost impact
        cost_per_pod = float(os.getenv("RUNPOD_COST_PER_HOUR", "0.69"))
        hourly_waste = orphaned_count * cost_per_pod
        
        # Determine alert level
        if orphaned_count == 0 and stale_workers == 0:
            print(f"✅ No orphaned pods detected at {datetime.now()}")
            return "OK"
        elif orphaned_count <= 2:
            alert_level = "WARNING"
        else:
            alert_level = "CRITICAL"
        
        # Create alert message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        alert_msg = f"""
🚨 {alert_level}: Orphaned RunPod Resources Detected

Timestamp: {timestamp}
Orphaned Pods: {orphaned_count}
Stale Database Workers: {stale_workers}
Estimated Hourly Waste: ${hourly_waste:.2f}

RunPod State: {result['runpod_pods']} active pods
Database State: {result['db_workers']} active workers

Recommended Action:
cd /Users/peteromalley/Headless_WGP_Orchestrator
python scripts/sync_runpod_database.py terminate_orphaned

This indicates a database sync failure in the orchestrator.
Check orchestrator logs for "CRITICAL DATABASE ERROR" messages.
        """.strip()
        
        print(alert_msg)
        
        # Send email alert if configured
        email_recipient = os.getenv("ALERT_EMAIL")
        if email_recipient and alert_level == "CRITICAL":
            send_email_alert(alert_msg, email_recipient)
        
        # Write to alert log
        log_alert(alert_msg)
        
        return alert_level
        
    except Exception as e:
        error_msg = f"❌ Error monitoring orphaned pods: {e}"
        print(error_msg)
        log_alert(error_msg)
        return "ERROR"

def send_email_alert(message: str, recipient: str):
    """Send email alert about orphaned pods."""
    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_username = os.getenv("SMTP_USERNAME")
        smtp_password = os.getenv("SMTP_PASSWORD")
        
        if not all([smtp_username, smtp_password]):
            print("⚠️  Email credentials not configured, skipping email alert")
            return
        
        msg = MIMEText(message)
        msg['Subject'] = '🚨 RunPod Orchestrator Alert: Orphaned Pods Detected'
        msg['From'] = smtp_username
        msg['To'] = recipient
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        print(f"📧 Alert email sent to {recipient}")
        
    except Exception as e:
        print(f"❌ Failed to send email alert: {e}")

def log_alert(message: str):
    """Log alert to file."""
    try:
        log_file = "/Users/peteromalley/Headless_WGP_Orchestrator/orphaned_pods.log"
        timestamp = datetime.now().isoformat()
        
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] {message}\n\n")
            
    except Exception as e:
        print(f"❌ Failed to log alert: {e}")

if __name__ == "__main__":
    load_dotenv()
    
    try:
        result = asyncio.run(monitor_orphaned_pods())
        
        # Exit codes for monitoring systems
        exit_codes = {
            "OK": 0,
            "WARNING": 1,
            "CRITICAL": 2,
            "ERROR": 3
        }
        
        sys.exit(exit_codes.get(result, 3))
        
    except KeyboardInterrupt:
        print("\n⏹️  Monitoring cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Monitoring failed: {e}")
        sys.exit(3)
