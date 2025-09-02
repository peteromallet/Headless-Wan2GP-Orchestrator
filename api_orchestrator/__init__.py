"""API Orchestrator package (CPU-bound, concurrent task runner).

This service pulls `api_query` tasks from the shared Supabase task queue
and executes them concurrently using asyncio. It reuses the same edge
function-based task claiming model and result reporting as the GPU
orchestrator but targets I/O-bound API workloads.
"""


