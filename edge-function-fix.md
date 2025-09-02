# Fix for update-task-status Edge Function

## Problem
The Edge Function is overwriting successfully completed tasks with "Failed" status.

## Solution
Add a safety check to prevent overwriting Complete tasks:

```typescript
// BEFORE updating, check current status
const { data: currentTask } = await supabaseAdmin
  .from("tasks")
  .select("status")
  .eq("id", task_id)
  .single();

// Don't overwrite Complete tasks with Failed status
if (currentTask?.status === "Complete" && status === "Failed") {
  console.log(`Refusing to mark completed task ${task_id} as Failed`);
  return new Response(JSON.stringify({
    success: false,
    task_id: task_id,
    message: "Cannot mark completed task as failed"
  }), {
    status: 400,
    headers: { "Content-Type": "application/json" }
  });
}
```

## Alternative: Add timestamps check
Only allow status changes if they make logical sense based on timing.
