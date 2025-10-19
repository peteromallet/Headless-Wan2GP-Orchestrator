# What You'll See Now - Quick Reference

**After deploying these changes, scaling decisions will be ABUNDANTLY CLEAR.**

---

## 📺 What Shows Up in Railway Logs

### Every Orchestrator Cycle (Every ~30s)

```
================================================================================
ORCHESTRATOR CYCLE #638 - TASK COUNT
  Queued only: 2
  Active (cloud): 0
  Total workload: 2
================================================================================

🔢 TASK COUNT (Cycle #638): Queued=2, Active=0, Total=2

================================================================================
SCALING DECISION (Cycle #638)
  Task Count: 2 queued + 0 active = 2 total
  Current: 2 active + 0 spawning = 2 total
  Desired: 2 workers
  Decision: MAINTAIN (at capacity)
================================================================================

🎯 SCALING DECISION (Cycle #638): Current=2+0, Desired=2
```

**This tells you:**
- ✅ What task count the orchestrator sees
- ✅ How many workers it currently has
- ✅ How many workers it wants
- ✅ What decision it made

---

## 🚀 What a Scale-Up Looks Like

```
================================================================================
ORCHESTRATOR CYCLE #640 - TASK COUNT
  Queued only: 51
  Active (cloud): 0
  Total workload: 51
================================================================================

🔢 TASK COUNT (Cycle #640): Queued=51, Active=0, Total=51

🚨 ANOMALY DETECTED: Task count jumped from 0 to 51
   This could indicate:
   - Legitimate batch submission
   - Edge function bug (old tasks becoming visible)
   - Database query issue

================================================================================
SCALING DECISION (Cycle #640)
  Task Count: 51 queued + 0 active = 51 total
  Current: 0 active + 0 spawning = 0 total
  Desired: 10 workers
  Decision: SCALE UP by 10
================================================================================

🚀 SCALING UP: Creating 10 new workers

✅ Worker 1/10 spawned successfully
✅ Worker 2/10 spawned successfully
✅ Worker 3/10 spawned successfully
✅ Worker 4/10 spawned successfully

🚨 ANOMALY DETECTED: Rapid scale-up of 10 workers in one cycle
   Task count: 51
   Previous worker count: 0
   This may indicate:
   - Large batch of new tasks submitted
   - Edge function returning incorrect count
   - Workers failing rapidly and being replaced
```

**This tells you:**
- ⚠️ **ANOMALY** alert if task count spikes
- 📊 Exact task count that triggered scaling
- 🎯 Exact desired worker count
- ✅ Each worker spawn (success/failure)
- 🚨 **ANOMALY** alert if scaling up rapidly

---

## ❌ What Database Logging Failure Looks Like

**On startup:**
```
❌ CRITICAL: Database logging initialization FAILED: ModuleNotFoundError
   Exception type: ModuleNotFoundError
   This will cause LOSS OF OBSERVABILITY
   Error details saved to: db_logging_errors.log
```

**Every 10 cycles (~5 minutes):**
```
❌ HEALTH CHECK: Database logging is NOT enabled
⚠️  Database logging is degraded - check logs above
```

**But orchestrator keeps running!** ✅
- Logs still go to stdout/stderr (Railway logs)
- Logs still go to file
- Just not to database

---

## 📊 Health Summaries (Every 20 Cycles)

```
📊 HEALTH SUMMARY (Cycle #200):
   • Database logging: ✅ Healthy
   • Last task count: 2
   • Last worker count: 2
```

---

## 🔍 How to Diagnose Issues

### Question: "Why did it scale to 4 workers?"

**Search logs for:**
```bash
railway logs --tail 1000 | grep "TASK COUNT"
```

**You'll see:**
```
🔢 TASK COUNT (Cycle #638): Queued=2, Active=0, Total=2
🔢 TASK COUNT (Cycle #639): Queued=51, Active=0, Total=51  ← SPIKE!
🔢 TASK COUNT (Cycle #640): Queued=51, Active=0, Total=51
```

**Then search scaling decisions:**
```bash
railway logs --tail 1000 | grep "SCALING DECISION"
```

**You'll see:**
```
SCALING DECISION (Cycle #638): Current=2+0, Desired=2
SCALING DECISION (Cycle #639): Current=2+0, Desired=10  ← CHANGE!
SCALING UP: Creating 10 new workers
```

**Answer:** Task count jumped from 2 to 51, orchestrator wanted 10 workers, but scaled to 4 (probably hit MAX_ACTIVE_GPUS).

---

### Question: "Is database logging working?"

**Search logs for:**
```bash
railway logs --tail 1000 | grep "HEALTH CHECK"
```

**If healthy:**
```
# (no output - only alerts on problems)
```

**If broken:**
```
❌ HEALTH CHECK: Database logging is NOT enabled
⚠️  Database logging is degraded - check logs above
```

---

### Question: "Were there any anomalies?"

**Search logs for:**
```bash
railway logs --tail 1000 | grep "ANOMALY"
```

**You'll see:**
```
🚨 ANOMALY DETECTED: Task count jumped from 0 to 51
🚨 ANOMALY DETECTED: Rapid scale-up of 10 workers in one cycle
```

---

## 🎯 Key Log Lines to Watch

| Log Line | What It Means |
|----------|---------------|
| `🔢 TASK COUNT` | Shows task count orchestrator sees |
| `🎯 SCALING DECISION` | Shows desired vs current workers |
| `🚀 SCALING UP` | Orchestrator is creating workers |
| `✅ Worker 1/4 spawned` | Worker created successfully |
| `❌ Failed to spawn worker` | Worker creation failed |
| `🚨 ANOMALY DETECTED` | Unusual behavior detected |
| `❌ CRITICAL: Database logging FAILED` | Logging broken on startup |
| `❌ HEALTH CHECK` | Logging broken during operation |
| `📊 HEALTH SUMMARY` | Periodic status report |

---

## 🚨 Anomaly Alerts

The system now alerts on:

1. **Task Count Spike**
   - Task count increases by 10x or more
   - Example: 2 → 51 tasks

2. **Task Count Appearing**
   - Task count jumps from 0 to 10+
   - Example: 0 → 51 tasks

3. **Rapid Scale-Up**
   - Scaling up by 3+ workers in one cycle
   - Example: Creating 10 workers at once

4. **Database Logging Failure**
   - Logging fails on startup
   - Logging stops during operation

---

## 🔧 Optional: Fail Fast on Logging Failure

**To make orchestrator exit if database logging fails:**

```bash
# In Railway environment variables
DB_LOGGING_REQUIRED=true
```

**When to use:**
- Production deployments where you must have logs
- Debugging sessions where you need database logs

**When NOT to use:**
- Development (logging failures are common)
- If you're okay with file/stdout logs only

---

## ✅ Bottom Line

**With these changes:**

1. ✅ You'll always see what task count the orchestrator sees
2. ✅ You'll always see what scaling decision it makes
3. ✅ You'll always see when workers are spawned
4. ✅ You'll get alerts for unusual behavior
5. ✅ You'll know if database logging breaks
6. ✅ Orchestrator keeps running even if logging fails (unless you set `DB_LOGGING_REQUIRED=true`)

**It's now ABUNDANTLY CLEAR what's happening!** 🎯





