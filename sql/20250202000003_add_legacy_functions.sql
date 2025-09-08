-- Legacy function compatibility for existing worker code
-- This ensures backward compatibility for legacy worker integrations

-- Legacy function: func_claim_task (wrapper around func_claim_available_task)
-- The old worker code expects this function signature
CREATE OR REPLACE FUNCTION func_claim_task(p_table_name text, p_worker_id text)
RETURNS TABLE(
    id uuid,
    status task_status,
    attempts int,
    worker_id text,
    generation_started_at timestamptz,
    task_data jsonb,
    created_at timestamptz,
    task_type text
) 
LANGUAGE plpgsql
AS $$
BEGIN
    -- The p_table_name parameter is ignored since we know it's always 'tasks'
    -- Just delegate to the new function with correct parameter name
    RETURN QUERY
    SELECT * FROM func_claim_available_task(worker_id_param => p_worker_id);
END;
$$;

-- Create an index to optimize task claiming if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_tasks_claim_optimization 
ON tasks (status, created_at) 
WHERE status = 'Queued';

-- Grant execute permissions
GRANT EXECUTE ON FUNCTION func_claim_task(text, text) TO anon;
GRANT EXECUTE ON FUNCTION func_claim_task(text, text) TO authenticated; 