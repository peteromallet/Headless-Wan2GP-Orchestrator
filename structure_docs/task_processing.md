# Task Processing & Headless-Wan2GP Integration

This document covers how tasks are processed by the orchestrator and the Headless-Wan2GP workers.

## Task Types

The orchestrator is designed for **video generation workloads** using the [Headless-Wan2GP](https://github.com/peteromallet/Headless-Wan2GP) system.

### Supported Task Types

1. **Video Generation** - Text-to-video using Wan2GP models
2. **Frame Interpolation** - Smooth video transitions and upscaling  
3. **Custom Prompts** - User-defined generation parameters with LoRA support
4. **Batch Processing** - Multiple video generations from prompt lists

## Task Schema

### Database Structure
Tasks are stored in the `tasks` table with this schema:

| Column | Type | Description |
|--------|------|-------------|
| `id` | `uuid` | Unique task identifier |
| `task_type` | `text` | Type of processing (e.g., "video_generation") |
| `params` | `jsonb` | Task parameters and input data |
| `status` | `text` | Current state (`Queued`, `In Progress`, `Complete`, `Failed`) |
| `attempts` | `int` | Retry counter (max 3) |
| `worker_id` | `text` | Assigned worker (NULL when queued) |
| `result_data` | `jsonb` | Output data (video URLs, metadata) |
| `error_message` | `text` | Error details for failed tasks |

### Task Parameters (`params` field)
The `params` JSONB field contains task-specific configuration:

```json
{
  "prompt": "A cat walking through a garden",
  "negative_prompt": "blurry, low quality",
  "frames": 24,
  "fps": 8,
  "width": 512,
  "height": 512,
  "guidance_scale": 7.5,
  "seed": 42,
  "model": "wan2gp_v2.1",
  "lora_weights": ["style_anime.safetensors"],
  "processing_time": 120
}
```

### Result Data (`result_data` field)
Completed tasks store output information:

```json
{
  "video_url": "https://project.supabase.co/storage/v1/object/public/videos/task_xyz123.mp4",
  "thumbnail_url": "https://project.supabase.co/storage/v1/object/public/videos/task_xyz123_thumb.jpg",
  "duration_seconds": 3.0,
  "file_size_bytes": 2048000,
  "processing_time_seconds": 145.3,
  "model_used": "wan2gp_v2.1",
  "generated_at": "2024-01-01T12:00:00Z"
}
```

## Task Lifecycle

### 1. Task Creation
Tasks are inserted into the database (usually via API):

```sql
INSERT INTO tasks (task_type, params, status, created_at) VALUES (
  'video_generation',
  '{"prompt": "A cat walking", "frames": 24}',
  'Queued',
  NOW()
);
```

### 2. Task Claiming (Worker Pull Model)
Workers poll for available tasks using atomic RPC:

```sql
SELECT * FROM func_claim_available_task('worker-xyz123');
```

**Atomic Operation:**
- Uses `FOR UPDATE SKIP LOCKED` to prevent race conditions
- Updates status to `In Progress` 
- Sets `worker_id` and `generation_started_at`
- Returns task details or NULL if no work available

### 3. Task Processing (Headless-Wan2GP)
The worker executes the video generation:

1. **Parse Parameters** - Extract prompt, model settings, etc.
2. **Load Model** - Initialize Wan2GP with specified weights
3. **Generate Video** - Run inference with provided parameters
4. **Upload Result** - Save video to Supabase storage
5. **Update Database** - Mark task complete with result metadata

### 4. Task Completion
Workers call RPC to mark success:

```sql
SELECT func_mark_task_complete(
  'task-uuid',
  '{"video_url": "https://...", "processing_time_seconds": 145.3}'
);
```

### 5. Error Handling
Failed tasks increment retry counter:

```sql
SELECT func_mark_task_failed(
  'task-uuid',
  'CUDA out of memory error'
);
```

**Retry Logic:**
- `attempts < 3`: Status → `Queued`, `worker_id` → NULL (retry)
- `attempts >= 3`: Status → `Failed` (dead letter)

## Headless-Wan2GP Integration

### Worker Startup Process
When the orchestrator spawns a worker:

1. **Pod Creation** - Runpod container with GPU access
2. **Storage Mount** - Network volume at `/workspace` 
3. **SSH Initialization** - Key-based authentication setup
4. **Worker Launch** - Background process starts

**Startup Command:**
```bash
cd /workspace/Headless-Wan2GP/ && \
source venv/bin/activate && \
python worker.py --db-type supabase \
  --supabase-url {url} \
  --supabase-access-token {key} \
  --worker {worker_id}
```

### Worker Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `WORKER_ID` | Orchestrator | Unique worker identifier |
| `SUPABASE_URL` | Orchestrator env | Database connection |
| `SUPABASE_SERVICE_ROLE_KEY` | Orchestrator env | Auth credentials |
| `DB_TYPE` | Hardcoded | Always `supabase` for orchestrator |
| `SUPABASE_VIDEO_BUCKET` | User config | Storage bucket name |
| `REPLICATE_API_TOKEN` | Orchestrator env | API token for Replicate services |

### Storage Integration
Headless-Wan2GP automatically handles file storage:

**Upload Process:**
1. Generate video locally on worker
2. Upload to Supabase storage bucket
3. Get public URL for video file
4. Store URL in task `result_data`

**Storage Configuration:**
- **Bucket Name**: Specified in `SUPABASE_VIDEO_BUCKET` 
- **File Naming**: `task_{task_id}.mp4`
- **Permissions**: Public read access for generated videos
- **Location**: Same Supabase project as database

### Worker Heartbeat System
Workers send periodic health updates:

**Heartbeat Frequency:** Every 20 seconds
**VRAM Monitoring:** Optional GPU memory usage reporting

```python
# Worker sends this periodically
await update_worker_heartbeat(
    worker_id="worker-xyz123",
    vram_total_mb=24576,
    vram_used_mb=12288
)
```

### Task Processing Implementation
Inside Headless-Wan2GP worker loop:

```python
while running:
    # Check for termination signal
    worker_status = await get_worker_status(worker_id)
    if worker_status == 'terminating':
        break
    
    # Claim next task
    task = await claim_next_task(worker_id)
    
    if task:
        try:
            # Process video generation
            result = await generate_video(task['params'])
            
            # Upload and mark complete
            video_url = await upload_to_storage(result['video_path'])
            await mark_task_complete(task['id'], {
                'video_url': video_url,
                'processing_time_seconds': result['duration']
            })
            
        except Exception as e:
            await mark_task_failed(task['id'], str(e))
    
    else:
        # No work available, send heartbeat and wait
        await send_heartbeat()
        await asyncio.sleep(5)
```

## Performance Characteristics

### Processing Times
Typical video generation durations:

| Configuration | Estimated Time | GPU Memory |
|---------------|----------------|------------|
| 512x512, 24 frames | 2-3 minutes | 8-12GB |
| 768x768, 24 frames | 4-6 minutes | 12-16GB |
| 1024x1024, 24 frames | 8-12 minutes | 16-24GB |

### Throughput Optimization
**Single Worker:** ~20-30 videos/hour (depending on complexity)
**Scaling:** Linear with additional workers
**Bottlenecks:** GPU memory, model loading time

### Cost Estimation
Based on Runpod RTX 4090 pricing (~$0.50/hour):

| Scenario | Workers | Cost/Hour | Videos/Hour |
|----------|---------|-----------|-------------|
| Light load | 2 | $1.00 | 40-60 |
| Medium load | 5 | $2.50 | 100-150 |
| High load | 10 | $5.00 | 200-300 |

## Monitoring & Debugging

### Task Queue Analytics
Monitor via database views:

- **`task_queue_analysis`** - Queue depth by task type
- **`recent_task_activity`** - Last 24 hours with processing times
- **`worker_performance`** - Success rates and throughput

### Common Issues

#### 1. Out of Memory Errors
**Symptoms:** Tasks fail with CUDA OOM
**Solutions:** 
- Reduce batch size in task parameters
- Use lower resolution settings
- Scale to larger GPU instances

#### 2. Slow Processing
**Symptoms:** Tasks exceed `TASK_STUCK_TIMEOUT_SEC`
**Solutions:**
- Optimize model parameters
- Check for I/O bottlenecks
- Increase timeout for complex tasks

#### 3. Storage Upload Failures
**Symptoms:** Tasks complete but no video URL
**Solutions:**
- Verify storage bucket permissions
- Check network connectivity
- Validate Supabase credentials

### Debug Commands
**Check worker status:**
```bash
python scripts/dashboard.py
```

**View recent tasks:**
```sql
SELECT * FROM recent_task_activity LIMIT 10;
```

**Worker health:**
```sql
SELECT * FROM active_workers_health;
```

## Integration with Other Systems

### API Integration
Tasks typically created via REST API:

```http
POST /api/tasks
Content-Type: application/json

{
  "task_type": "video_generation", 
  "params": {
    "prompt": "A sunset over mountains",
    "frames": 24
  }
}
```

### Webhook Notifications
Task completion can trigger webhooks:

```json
{
  "task_id": "uuid",
  "status": "Complete",
  "video_url": "https://storage.url/video.mp4",
  "processing_time": 145.3
}
```

### Frontend Integration
Generated videos accessed via public URLs:

```html
<video controls>
  <source src="{result_data.video_url}" type="video/mp4">
</video>
``` 