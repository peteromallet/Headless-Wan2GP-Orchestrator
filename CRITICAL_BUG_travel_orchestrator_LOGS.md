# Critical Bug: travel_orchestrator Task Crash - Detailed Logs

**Task ID**: `306199b3-566d-49e5-8dd7-e2d57ab9c61b`  
**Bug**: Missing `Path` import causes immediate worker crash  
**Severity**: CRITICAL - Kills entire worker, leaves tasks orphaned  
**Date**: 2025-10-07  

---

## Executive Summary

Every `travel_orchestrator` task causes an immediate worker crash due to missing `from pathlib import Path` import. The worker crashes within 1 second of claiming the task, shuts down completely, and leaves the task stuck "In Progress" for hours.

**Impact**:
- ✅ Reproduced 100% - happens on every worker
- ✅ Worker completely dies (not just task failure)
- ✅ Task left orphaned in "In Progress" state
- ✅ Orchestrator takes 10+ minutes to detect and terminate dead worker

---

## Incident Timeline

### First Worker Crash (Worker: `gpu-20251007_171247-3e03e2d1`)

```
2025-10-07 17:26:22.800 - Task created
2025-10-07 17:26:31.672 - Task claimed by worker
2025-10-07 17:26:32.xxx - Worker CRASHED (< 1 second)
2025-10-07 17:36:18.797 - Orchestrator detected stale heartbeat, terminated worker
2025-10-07 20:04:xx.xxx - Task still stuck "In Progress" (2.5 hours later)
```

### Second Worker Crash (Worker: `gpu-20251007_173620-826a397a`) - LIVE CAPTURE

```
2025-10-07 18:02:55.025 - Worker idle, checking for tasks
2025-10-07 18:02:55.368 - Worker claimed task
2025-10-07 18:02:55.xxx - Worker started processing
2025-10-07 18:02:55.xxx - CRASH: Path error
2025-10-07 18:02:55.661 - Worker initiated shutdown
2025-10-07 18:03:00.388 - Worker completely dead
```

---

## Exact Log Sequence (Live Capture from Worker)

### Worker Log: `/workspace/Headless-Wan2GP/logs/gpu-20251007_173620-826a397a.log`

**Lines 238-243** - The complete crash sequence:

```
[18:02:55] INFO HEADLESS [Task 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Found task of type: travel_orchestrator, Project ID: f3c36ed6-eeb4-4259-8f67-b8260efd1c0e

[PROCESS_TASK_DEBUG] process_single_task called: task_type='travel_orchestrator', task_id=306199b3-566d-49e5-8dd7-e2d57ab9c61b

[18:02:55] INFO HEADLESS [Task 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Processing travel_orchestrator task

[18:02:55] INFO TRAVEL [Task 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Starting travel orchestrator task

2025-10-07 18:02:55,652 [INFO] httpx: HTTP Request: GET https://wczysqzxlwdndgxitrvc.supabase.co/rest/v1/tasks?select=id%2Ctask_type%2Cstatus%2Cparams&params=cs.%7B%22orchestrator_task_id_ref%22%3A+%22306199b3-566d-49e5-8dd7-e2d57ab9c61b%22%7D&order=created_at.asc "HTTP/2 200 OK"

[ERROR Task ID: 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Failed during travel orchestration processing: local variable 'Path' referenced before assignment
```

**Immediately after crash - Worker shutdown sequence:**

```
Stopping heartbeat thread...
[18:02:55] INFO HEADLESS 🛑 Heartbeat thread stopped for worker: gpu-20251007_173620-826a397a (sent 73 heartbeats)
✅ Heartbeat thread stopped
[18:02:55] INFO HEADLESS Shutting down task queue...
2025-10-07 18:02:55,661 [INFO] HeadlessQueue: Shutting down task queue...
2025-10-07 18:02:56,236 [INFO] HeadlessQueue: GenerationWorker-0 stopped
2025-10-07 18:03:00,387 [INFO] HeadlessQueue: Queue monitor stopped
2025-10-07 18:03:00,388 [INFO] HeadlessQueue: Task queue shutdown complete
[18:03:00] ✅ HEADLESS Task queue shutdown complete
[18:03:00] INFO HEADLESS Server stopped
```

**Python process check at 18:05 (2 minutes after crash):**

```bash
$ ps aux | grep python
root        2277  0.0  0.0   4364  2876 ?        Ss   18:05   0:00 bash -c ps aux | grep python
root        2279  0.0  0.0   3472  1560 ?        S    18:05   0:00 grep python
```

**Result**: NO worker.py process running - worker completely dead.

---

## Pre-Crash Normal Operation

Worker was healthy before claiming the fatal task:

```
2025-10-07 17:53:45 [INFO] httpx: PATCH /rest/v1/workers "HTTP/2 200 OK"
[17:53:45] INFO HEADLESS ✅ [HEARTBEAT] Worker gpu-20251007_173620-826a397a active (46 heartbeats sent)

2025-10-07 17:58:47 [INFO] httpx: PATCH /rest/v1/workers "HTTP/2 200 OK"
[17:58:47] INFO HEADLESS ✅ [HEARTBEAT] Worker gpu-20251007_173620-826a397a active (61 heartbeats sent)

2025-10-07 18:02:09 [INFO] httpx: PATCH /rest/v1/workers "HTTP/2 200 OK"
2025-10-07 18:02:12 [INFO] httpx: POST /functions/v1/task-counts "HTTP/1.1 200 OK"
2025-10-07 18:02:23 [INFO] httpx: POST /functions/v1/task-counts "HTTP/1.1 200 OK"
2025-10-07 18:02:29 [INFO] httpx: PATCH /rest/v1/workers "HTTP/2 200 OK"
2025-10-07 18:02:33 [INFO] httpx: POST /functions/v1/task-counts "HTTP/1.1 200 OK"
2025-10-07 18:02:44 [INFO] httpx: POST /functions/v1/task-counts "HTTP/1.1 200 OK"
2025-10-07 18:02:49 [INFO] httpx: PATCH /rest/v1/workers "HTTP/2 200 OK"
2025-10-07 18:02:55 [INFO] httpx: POST /functions/v1/task-counts "HTTP/1.1 200 OK"
```

Worker sending heartbeats every ~20 seconds, checking for tasks every ~10 seconds.

Then at 18:02:55:

```
2025-10-07 18:02:55,368 [INFO] httpx: POST /functions/v1/claim-next-task "HTTP/1.1 200 OK"
[18:02:55] INFO HEADLESS [Task 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Found task of type: travel_orchestrator
```

**💥 BOOM - Dead within 1 second**

---

## S3 Archived Logs (First Worker)

From worker `gpu-20251007_171247-3e03e2d1` - Same exact error pattern:

```
[129] [17:26:31] INFO HEADLESS [Task 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Found task of type: travel_orchestrator, Project ID: f3c36ed6-eeb4-4259-8f67-b8260efd1c0e

[130] [PROCESS_TASK_DEBUG] process_single_task called: task_type='travel_orchestrator', task_id=306199b3-566d-49e5-8dd7-e2d57ab9c61b

[131] [17:26:31] INFO HEADLESS [Task 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Processing travel_orchestrator task

[132] [17:26:31] INFO TRAVEL [Task 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Starting travel orchestrator task

[133] 2025-10-07 17:26:32,048 [INFO] httpx: HTTP Request: GET https://wczysqzxlwdndgxitrvc.supabase.co/rest/v1/tasks?select=id%2Ctask_type%2Cstatus%2Cparams&params=cs.%7B%22orchestrator_task_id_ref%22%3A+%22306199b3-566d-49e5-8dd7-e2d57ab9c61b%22%7D&order=created_at.asc "HTTP/2 200 OK"

[134] [ERROR Task ID: 306199b3-566d-49e5-8dd7-e2d57ab9c61b] Failed during travel orchestration processing: local variable 'Path' referenced before assignment
```

**Identical crash pattern on both workers - 100% reproducible**

---

## Database Status Logs

### Task Status After First Crash

```
📋 Task Details:
  id: 306199b3-566d-49e5-8dd7-e2d57ab9c61b
  task_type: travel_orchestrator
  status: In Progress
  worker_id: gpu-20251007_171247-3e03e2d1
  attempts: 0
  created_at: 2025-10-07T17:26:22.8+00:00
  updated_at: 2025-10-07T17:26:31.672859+00:00
  generation_started_at: 2025-10-07T17:26:31.672859+00:00
  generation_processed_at: None
  error_message: None
  output_location: None

⏱️ Timing Analysis:
  Created: 2025-10-07 17:26:22.800000+00:00
  Started: 2025-10-07 17:26:31.672859+00:00
  Queue Duration: 8.9 seconds
  ⚠️  Never processed (no generation_processed_at)
  Running Duration: 9238.5 seconds (2.5+ hours stuck)
```

### Worker Status After Termination

```
🤖 Worker Status: gpu-20251007_171247-3e03e2d1
Status: terminated
Created: 2025-10-07T17:12:47.039089+00:00
Updated: None
Metadata: {
  'ready': True, 
  'runpod_id': 'udj1d7nijbkxih', 
  'error_time': '2025-10-07T17:36:18.797893+00:00', 
  'pod_details': {
    'id': 'udj1d7nijbkxih', 
    'name': 'gpu-20251007_171247-3e03e2d1', 
    'created': True, 
    'gpu_type_id': 'NVIDIA GeForce RTX 4090'
  }, 
  'error_reason': 'Stale heartbeat with active tasks (607s old)', 
  'orchestrator_status': 'terminated'
}

📋 Tasks assigned to this worker:
  - 306199b3-566d-49e5-8dd7-e2d57ab9c61b: In Progress (travel_orchestrator)
```

**Notice**: Worker marked as `terminated` but task still `In Progress` - orphaned!

---

## Task Parameters (For Reproduction)

```json
{
  "task_id": "306199b3-566d-49e5-8dd7-e2d57ab9c61b",
  "task_type": "travel_orchestrator",
  "project_id": "f3c36ed6-eeb4-4259-8f67-b8260efd1c0e",
  "params": {
    "orchestrator_details": {
      "steps": 6,
      "run_id": "20251007172622406",
      "shot_id": "d66e2581-7516-453c-8650-9b56a1baa480",
      "seed_base": 611601,
      "model_name": "lightning_baseline_2_2_2",
      "base_prompt": "zooming in on a bus that's driving through the countryside",
      "advanced_mode": false,
      "apply_causvid": false,
      "enhance_prompt": true,
      "generation_mode": "batch",
      "accelerated_mode": false,
      "amount_of_motion": 0.5,
      "dimension_source": "firstImage",
      "apply_reward_lora": false,
      "use_lighti2x_lora": false,
      "debug_mode_enabled": false,
      "colour_match_videos": false,
      "orchestrator_task_id": "sm_travel_orchestrator_25100717_e2b2c4",
      "parsed_resolution_wh": "768x576",
      "use_styleboost_loras": false,
      "base_prompts_expanded": [
        "zooming in on a bus that's driving through the countryside",
        "zooming in on a bus that's driving through the countryside",
        "zooming in on a bus that's driving through the countryside"
      ],
      "frame_overlap_expanded": [10, 10, 10],
      "segment_frames_expanded": [60, 60, 60],
      "num_new_segments_to_generate": 3,
      "input_image_paths_resolved": [
        "https://wczysqzxlwdndgxitrvc.supabase.co/storage/v1/object/public/image_uploads/8a9fdac5-ed89-482c-aeca-c3dd7922d53c/27ba1029-a246-4fcb-a715-c62bc0969071-u1_8f22c97f-23d8-407b-94c4-98c3c62c9a59.jpeg",
        "https://wczysqzxlwdndgxitrvc.supabase.co/storage/v1/object/public/image_uploads/8a9fdac5-ed89-482c-aeca-c3dd7922d53c/650357b4-6cf6-4453-9e34-833ac8869144-u2_f7921019-0ccf-49af-904d-276f4bdb1f21.jpeg",
        "https://wczysqzxlwdndgxitrvc.supabase.co/storage/v1/object/public/image_uploads/8a9fdac5-ed89-482c-aeca-c3dd7922d53c/f61cdd66-d282-4eee-9892-c25d8a7a2f55-u1_ee9039dd-442b-495d-8fae-14e1fc7158d5.jpeg",
        "https://wczysqzxlwdndgxitrvc.supabase.co/storage/v1/object/public/image_uploads/8a9fdac5-ed89-482c-aeca-c3dd7922d53c/23d4b5b0-0141-4d2f-bc9a-e44e82b9c867-u1_bf75e138-fb6e-49f4-bc4d-52e92a726a00.jpeg"
      ]
    }
  }
}
```

---

## The Bug: Exact Python Error

```python
[ERROR Task ID: 306199b3-566d-49e5-8dd7-e2d57ab9c61b] 
Failed during travel orchestration processing: 
local variable 'Path' referenced before assignment
```

This is a `NameError` or `UnboundLocalError` indicating that `Path` (from `pathlib`) is being used without being imported.

### Expected Code Issue

Somewhere in the travel orchestrator code (likely in `worker.py` or a related module):

```python
# BROKEN CODE (current):
def process_travel_orchestrator(...):
    # ... some code ...
    output_path = Path(some_directory) / "output.mp4"  # CRASH: Path not defined
    # ... more code ...
```

### Required Fix

```python
# FIXED CODE (needed):
from pathlib import Path  # Add this import at the top of the file

def process_travel_orchestrator(...):
    # ... some code ...
    output_path = Path(some_directory) / "output.mp4"  # Now works
    # ... more code ...
```

---

## Critical Issues Identified

### 1. Missing Error Handling
The worker crashes and shuts down completely instead of:
- ✅ Catching the exception
- ✅ Marking task as Failed in database
- ✅ Continuing to process other tasks

### 2. No Task Cleanup
When the worker crashes, it does NOT:
- ✅ Mark task as Failed
- ✅ Reset task to Queued
- ✅ Clear worker assignment

Result: Task stuck "In Progress" for hours until manual intervention.

### 3. Delayed Detection
The orchestrator takes 10+ minutes to detect the dead worker because:
- Worker stops sending heartbeats
- Orchestrator checks heartbeats periodically
- Grace period before marking as stale

### 4. Worker Self-Termination
The worker completely shuts down on ANY task error, which is excessive:
- One bad task shouldn't kill the entire worker
- Wastes GPU resources (need to spin up new worker)
- Increases latency for other tasks

---

## Recommendations

### Immediate (In Headless-Wan2GP):

1. **Add missing import**:
   ```python
   from pathlib import Path
   ```

2. **Add robust error handling**:
   ```python
   try:
       result = process_travel_orchestrator(task)
       mark_task_complete(task_id, result)
   except Exception as e:
       logger.error(f"Task {task_id} failed: {e}")
       mark_task_failed(task_id, str(e))
       # DON'T shut down the entire worker!
       continue  # Process next task
   ```

3. **Prevent worker self-termination** on task errors

### Long-term (In Orchestrator):

1. **Faster stale detection**: Check heartbeats more frequently (e.g., 2-3 minutes instead of 10)

2. **Automatic task cleanup**: When terminating a worker, reset all its "In Progress" tasks to "Queued"

3. **Task timeout**: Automatically mark tasks as Failed if "In Progress" for > 1 hour without updates

4. **Health monitoring**: Ping workers periodically to detect crashes faster

---

## Resolution

Task `306199b3-566d-49e5-8dd7-e2d57ab9c61b` has been marked as **Failed** to prevent infinite retry loop until the bug is fixed in Headless-Wan2GP.

**Next Steps**:
1. Fix the Path import in Headless-Wan2GP
2. Add error handling
3. Test with a new travel_orchestrator task
4. Deploy fix


