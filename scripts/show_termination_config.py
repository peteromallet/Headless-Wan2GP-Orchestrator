#!/usr/bin/env python3
"""Show the current worker termination configuration."""

import os
from dotenv import load_dotenv

load_dotenv()

print("🕐 Worker Termination Timing Configuration")
print("=" * 50)

# Key timing configurations
configs = [
    ("ORCHESTRATOR_POLL_SEC", "30", "How often orchestrator checks workers"),
    ("WORKER_GRACE_PERIOD_SEC", "120", "Grace period before idle check"),
    ("GPU_IDLE_TIMEOUT_SEC", "300", "Heartbeat timeout for active workers"),
    ("MIN_ACTIVE_GPUS", "2", "Minimum workers to keep running"),
    ("MAX_ACTIVE_GPUS", "10", "Maximum workers allowed"),
    ("TASKS_PER_GPU_THRESHOLD", "3", "Tasks per GPU before scaling up"),
]

for env_var, default, description in configs:
    value = os.getenv(env_var, default)
    print(f"\n{env_var}: {value}")
    print(f"  └─ {description}")
    if env_var == "WORKER_GRACE_PERIOD_SEC":
        mins = int(value) / 60
        print(f"  └─ {mins:.1f} minutes after promotion to active")
    elif env_var == "ORCHESTRATOR_POLL_SEC":
        print(f"  └─ Workers checked every {value} seconds")

print("\n" + "=" * 50)
print("📋 Termination Logic:")
print("""
1. Worker is promoted to 'active' status
2. Grace period starts ({} seconds)
3. After grace period, worker is eligible for idle checks
4. Every {} seconds, orchestrator checks:
   - Does worker have running tasks? → Keep active
   - No tasks AND above MIN_ACTIVE_GPUS ({})? → Terminate
   - No tasks BUT at/below minimum? → Keep active
5. Termination is immediate once marked

Note: If tasks are queued, at least 1 worker is kept regardless of MIN_ACTIVE_GPUS
""".format(
    os.getenv("WORKER_GRACE_PERIOD_SEC", "120"),
    os.getenv("ORCHESTRATOR_POLL_SEC", "30"),
    os.getenv("MIN_ACTIVE_GPUS", "2")
))

# Calculate effective termination time
grace = int(os.getenv("WORKER_GRACE_PERIOD_SEC", "120"))
poll = int(os.getenv("ORCHESTRATOR_POLL_SEC", "30"))
min_time = grace
max_time = grace + poll

print(f"\n⏱️  Idle Termination Time Range: {min_time/60:.1f} - {max_time/60:.1f} minutes")
print(f"   (Depends on when orchestrator cycle runs after grace period expires)") 