# Fix for `generation_created: false` Issue

## Problem Summary

Tasks completed by GPU workers were showing `generation_created: false` even though they had:
- ✅ Status = "Complete"  
- ✅ Valid `output_location` URLs
- ✅ No error messages

**Example affected tasks:**
- `b79e251d-101c-4d92-ab75-a4cbcd760820` (travel_stitch)
- `8ae218dc-6881-4d86-9b4d-2006d3389000` (travel_segment)
- `dc6eee24-98d0-4298-8307-a8356d6db9db` (travel_orchestrator)

All processed by worker `gpu-20251107_064928-62141071`.

## Root Cause

GPU workers (Headless-Wan2GP) were not receiving the correct Supabase edge function URLs. Without explicit configuration, they likely defaulted to using `/functions/v1/update-task-status` which:

- ✅ Sets task status to "Complete"
- ✅ Sets `generation_processed_at` timestamp
- ❌ **Does NOT create generation records** (missing the critical step!)

The correct endpoint is `/functions/v1/complete-task` which does everything above PLUS creates generation records.

## What Was Changed

### 1. GPU Orchestrator (`gpu_orchestrator/runpod_client.py`)
When spawning GPU workers, the orchestrator now passes explicit edge function URLs:

```python
env_vars = {
    "WORKER_ID": worker_id,
    "SUPABASE_URL": supabase_url,
    "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
    "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY", ""),
    "REPLICATE_API_TOKEN": os.getenv("REPLICATE_API_TOKEN", ""),
    # NEW: Pass correct edge function URLs to GPU workers
    "SUPABASE_EDGE_COMPLETE_TASK_URL": f"{supabase_url}/functions/v1/complete-task",
    "SUPABASE_EDGE_MARK_FAILED_URL": f"{supabase_url}/functions/v1/mark-task-failed",
}
```

### 2. Documentation Updates
- `structure_docs/debugging.md` - Corrected to show GPU workers ARE affected
- `structure_docs/task_processing.md` - Updated environment variables table
- `env.example` - Clarified edge function URL usage

## What Still Needs to Be Done

### 🚨 CRITICAL: Update Headless-Wan2GP Worker Code

The GPU workers (Headless-Wan2GP repository) need to be updated to **USE** these new environment variables:

**File to modify:** `Headless-Wan2GP/db_operations.py` (or wherever task completion happens)

**Changes needed:**
```python
# Old (probably):
completion_url = os.getenv("SUPABASE_EDGE_UPDATE_TASK_URL") or f"{supabase_url}/functions/v1/update-task-status"

# New (should be):
completion_url = os.getenv("SUPABASE_EDGE_COMPLETE_TASK_URL") or f"{supabase_url}/functions/v1/complete-task"
```

Search for where the worker calls the edge function to complete tasks and ensure it uses:
1. `SUPABASE_EDGE_COMPLETE_TASK_URL` environment variable (now provided by orchestrator)
2. Falls back to constructing `{SUPABASE_URL}/functions/v1/complete-task` if not set

### Testing

After updating Headless-Wan2GP:

1. **Deploy updated orchestrator:**
   ```bash
   # This repo is now ready - deploy it to Railway
   ./deploy_to_railway.sh  # or your deployment method
   ```

2. **Rebuild GPU worker Docker image:**
   ```bash
   # In Headless-Wan2GP repo after making changes
   docker build -t your-registry/headless-wan2gp:latest .
   docker push your-registry/headless-wan2gp:latest
   ```

3. **Update `RUNPOD_WORKER_IMAGE` in `.env`:**
   ```bash
   RUNPOD_WORKER_IMAGE=your-registry/headless-wan2gp:latest
   ```

4. **Terminate existing workers and let new ones spawn:**
   ```bash
   python scripts/shutdown_all_workers.py
   # Orchestrator will spawn new workers with correct env vars
   ```

5. **Test with a sample task:**
   ```bash
   python scripts/create_test_task.py
   python scripts/debug.py task <new_task_id>
   ```

6. **Verify generation_created is now true:**
   ```bash
   python scripts/debug.py task <task_id> --json | jq '.generation_created'
   # Should return: true
   ```

## Edge Function Requirements

Your Supabase project must have these edge functions deployed:

1. **`complete-task`** - Completes task AND creates generation record
   - Sets status to "Complete"
   - Sets `generation_processed_at`
   - Sets `output_location`
   - Creates entry in `generations` table
   - Sets `generation_created: true`

2. **`mark-task-failed`** - Handles task failures
   - Sets status to "Failed"
   - Increments `attempts`
   - Handles retry logic

If these edge functions don't exist or aren't working correctly, that's a separate issue that needs to be addressed.

## Verification Query

To check if future tasks are creating generations:

```sql
SELECT 
    t.id,
    t.task_type,
    t.status,
    t.generation_created,
    t.output_location,
    COUNT(g.id) as generation_count
FROM tasks t
LEFT JOIN generations g ON g.task_id = t.id
WHERE t.status = 'Complete'
  AND t.created_at > NOW() - INTERVAL '1 hour'
GROUP BY t.id
ORDER BY t.created_at DESC
LIMIT 20;
```

Expected results after fix:
- `generation_created: true`
- `generation_count: 1` (or more if multiple outputs)

## Timeline

1. ✅ **Orchestrator fix** - Complete (this repo)
2. ⏳ **Headless-Wan2GP update** - Needs to be done
3. ⏳ **Docker rebuild** - After step 2
4. ⏳ **Worker redeployment** - After step 3
5. ⏳ **Verification** - After step 4

---

**Questions?** Run `python scripts/debug.py task <task_id>` to investigate any task issues.





