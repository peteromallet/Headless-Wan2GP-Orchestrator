# Railway Deployment Guide

This document covers the complete deployment process for both the API Orchestrator and GPU Orchestrator services on Railway.com, including how to push new versions, monitor logs, and troubleshoot issues.

## Overview

The orchestrator system is deployed as two separate Railway services:
- **API Orchestrator**: Handles CPU-bound API tasks (Wavespeed AI, image processing)
- **GPU Orchestrator**: Manages RunPod GPU workers and orchestration

Both services use a unified Dockerfile at the project root with different start commands specified in their respective `railway.json` files.

## Architecture

```
GitHub Repository (main branch)
├── Dockerfile (unified for both services)
├── requirements.txt
├── api_orchestrator/
│   ├── railway.json (points to ../Dockerfile, API start command)
│   ├── main.py
│   └── ...
├── gpu_orchestrator/
│   ├── railway.json (points to ../Dockerfile, GPU start command)
│   ├── main.py
│   └── ...
└── ...
```

## Railway Projects Structure

- **Project 1**: `api-orchestrator`
  - Service: `api-orchestrator`
  - Root Directory: `api_orchestrator`
  - Start Command: `python -m api_orchestrator.main`

- **Project 2**: `gpu-orchestrator`
  - Service: `gpu-orchestrator`
  - Root Directory: `gpu_orchestrator`
  - Start Command: `python -m gpu_orchestrator.main continuous`

## Prerequisites

1. **Railway CLI installed**:
   ```bash
   npm install -g @railway/cli
   ```

2. **Logged into Railway**:
   ```bash
   railway login
   ```

3. **Git repository with latest changes**:
   ```bash
   git add .
   git commit -m "Your changes"
   git push origin main
   ```

## Environment Variables

### Shared Variables (Both Services)
```bash
SUPABASE_URL=https://wczysqzxlwdndgxitrvc.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here
SUPABASE_ANON_KEY=your_supabase_anon_key_here
RUNPOD_API_KEY=your_runpod_api_key_here
WAVESPEED_API_KEY=your_wavespeed_api_key_here
REPLICATE_API_TOKEN=your_replicate_api_token_here
AWS_ACCESS_KEY_ID=your_aws_access_key_id_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key_here
AWS_DEFAULT_REGION=eu-ro-1
LOG_LEVEL=INFO
```

### API Orchestrator Specific
```bash
API_WORKER_CONCURRENCY=20
API_RUN_TYPE=api
API_PARENT_POLL_SEC=10
API_WORKER_ID=railway-api-worker-1
```

### GPU Orchestrator Specific
```bash
MIN_ACTIVE_GPUS=0
MAX_ACTIVE_GPUS=10
TASKS_PER_GPU_THRESHOLD=3
ORCHESTRATOR_POLL_SEC=30
RUNPOD_GPU_TYPE=NVIDIA GeForce RTX 4090
RUNPOD_WORKER_IMAGE=runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
RUNPOD_VOLUME_MOUNT_PATH=/workspace
RUNPOD_DISK_SIZE_GB=20
RUNPOD_CONTAINER_DISK_GB=50
GPU_IDLE_TIMEOUT_SEC=600
TASK_STUCK_TIMEOUT_SEC=700
SPAWNING_TIMEOUT_SEC=1000
GPU_HEALTH_CHECK_TIMEOUT_SEC=600
FAILSAFE_STALE_THRESHOLD_SEC=900
GRACEFUL_SHUTDOWN_TIMEOUT_SEC=600
SPAWNING_GRACE_PERIOD_SEC=180
SCALE_DOWN_GRACE_PERIOD_SEC=60
SCALE_UP_MULTIPLIER=1.0
SCALE_DOWN_MULTIPLIER=0.9
MIN_SCALING_INTERVAL_SEC=45
MACHINES_TO_KEEP_IDLE=0
WORKER_GRACE_PERIOD_SEC=360
WORKER_REPO_URL=https://github.com/your-org/worker-repo.git
WORKER_SCRIPT_PATH=worker/worker.py
AUTO_START_WORKER_PROCESS=true
RUNPOD_STORAGE_NAME=Peter
RUNPOD_WORKER_REPO_URL=https://github.com/runpod/worker-template.git
```

## Deployment Workflows

### 1. Push New Version Live

#### Method A: Automatic Deployment (Recommended)
If services are connected to GitHub:
```bash
# 1. Make your changes
git add .
git commit -m "Description of changes"
git push origin main

# 2. Railway automatically deploys both services
# Monitor deployment in Railway dashboard or via CLI
```

#### Method B: Manual Deployment via CLI
```bash
# Deploy API Orchestrator
cd api_orchestrator
railway link  # Select api-orchestrator project
railway up

# Deploy GPU Orchestrator  
cd ../gpu_orchestrator
railway link  # Select gpu-orchestrator project
railway up
```

#### Method C: Force Deployment from Root
```bash
# From project root, deploy to specific services
railway up --service api-orchestrator
railway up --service gpu-orchestrator
```

### 2. Check Deployment Status

```bash
# Check which project you're linked to
railway status

# List all projects
railway list

# Link to specific project
railway link  # Interactive selection

# Check service health
railway logs --deployment
railway logs --build
```

### 3. Monitor Logs

#### Real-time Logs
```bash
# Link to desired service first
railway link

# View real-time logs
railway logs

# View build logs
railway logs --build

# View deployment logs
railway logs --deployment
```

#### Historical Logs
```bash
# View logs for specific deployment
railway logs [DEPLOYMENT_ID]

# View logs with context
railway logs -n 100  # Last 100 lines
```

#### Service-Specific Logs
```bash
# API Orchestrator logs
railway logs --service api-orchestrator

# GPU Orchestrator logs  
railway logs --service gpu-orchestrator
```

### 4. Environment Variable Management

#### View Current Variables
```bash
railway variables
```

#### Set Variables via CLI
```bash
# Set single variable
railway variables --set "KEY=value"

# Set multiple variables
railway variables --set "KEY1=value1" --set "KEY2=value2"
```

#### Set Variables via Dashboard
1. Go to Railway dashboard
2. Select project → service
3. Go to Variables tab
4. Add/edit variables
5. Save (triggers automatic redeploy)

### 5. Debug Deployment Issues

#### Check Build Logs
```bash
railway logs --build
```

#### Common Issues and Solutions

**Issue: "Dockerfile does not exist"**
- Solution: Ensure `railway.json` has correct `dockerfilePath: "../Dockerfile"`
- Verify unified Dockerfile exists at project root

**Issue: "SUPABASE_URL not configured"**
- Check environment variables are set: `railway variables`
- Set missing variables via CLI or dashboard
- Verify service redeployed after setting variables

**Issue: "No deployments found"**
- Service exists but hasn't deployed successfully
- Check build logs for errors
- Trigger manual deployment: `railway up`

**Issue: Old code still running**
- Force new deployment: `railway up --detach`
- Check if GitHub integration is working
- Verify latest commit is being deployed

#### Debug Environment Variables
Add temporary debug logging to your code:
```python
# Add to main.py for debugging
print("=== ENVIRONMENT VARIABLES DEBUG ===")
for key, value in sorted(os.environ.items()):
    if 'KEY' in key or 'TOKEN' in key or 'SECRET' in key:
        print(f"{key}: {value[:10]}..." if value else f"{key}: EMPTY")
    else:
        print(f"{key}: {value}")
print("=== END DEBUG ===")
```

### 6. Rollback Deployment

```bash
# View recent deployments
railway logs --deployment

# Rollback to previous deployment
railway down  # Removes most recent deployment

# Or redeploy specific commit
git checkout [COMMIT_HASH]
railway up
git checkout main  # Return to main branch
```

### 7. Scale Services

```bash
# Check current scaling
railway status

# Scale via dashboard (recommended)
# Go to service → Settings → Scaling
```

## Monitoring and Health Checks

### Service Health Indicators

#### API Orchestrator Health
- ✅ **Healthy**: Shows debug environment variables, no "SUPABASE_URL not configured" errors
- ✅ **Processing**: Logs show "Claimed task", "Processed task via Wavespeed API"
- ❌ **Unhealthy**: Repeated connection errors, environment variable errors

#### GPU Orchestrator Health  
- ✅ **Healthy**: Shows debug environment variables, successful Supabase connections
- ✅ **Processing**: Logs show "Available tasks: N", HTTP 200 responses
- ❌ **Unhealthy**: SUPABASE_URL errors, connection timeouts

### Log Patterns to Monitor

#### Normal Operation
```
INFO:httpx:HTTP Request: POST https://wczysqzxlwdndgxitrvc.supabase.co/functions/v1/task-counts "HTTP/1.1 200 OK"
INFO:__main__:Available tasks: 0
```

#### Error Patterns
```
ERROR:__main__:SUPABASE_URL not configured
ERROR:__main__:Failed to claim task: [error details]
```

### Performance Monitoring
- Monitor CPU/Memory usage in Railway dashboard
- Set up alerts for service failures
- Track task processing rates in application logs

## Best Practices

### 1. Development Workflow
```bash
# 1. Make changes locally
# 2. Test locally if possible
# 3. Commit and push to main
git add .
git commit -m "Descriptive commit message"
git push origin main

# 4. Monitor deployment
railway logs --build
railway logs
```

### 2. Environment Management
- Use Railway CLI for environment variables (more reliable than dashboard)
- Keep `.env.example` updated with all required variables
- Never commit actual `.env` files to git

### 3. Debugging
- Add temporary debug logging for troubleshooting
- Remove debug logging after issues are resolved
- Use structured logging for production monitoring

### 4. Deployment Safety
- Always check logs after deployment
- Monitor both services after changes
- Keep deployment commands in this documentation updated

## Troubleshooting Checklist

When deployment issues occur:

1. **Check Git Status**
   ```bash
   git status
   git log --oneline -5  # Recent commits
   ```

2. **Verify Railway Connection**
   ```bash
   railway status
   railway list
   ```

3. **Check Environment Variables**
   ```bash
   railway variables
   ```

4. **Monitor Deployment**
   ```bash
   railway logs --build
   railway logs --deployment
   railway logs
   ```

5. **Force Fresh Deployment**
   ```bash
   railway up --detach
   ```

6. **Check Service Health**
   - Look for debug environment variable output
   - Verify no "not configured" errors
   - Confirm HTTP 200 responses to Supabase

## Emergency Procedures

### Service Down
1. Check Railway dashboard for service status
2. View recent logs: `railway logs`
3. Check for recent deployments that might have caused issues
4. Rollback if needed: `railway down`
5. Redeploy known good version

### Environment Variables Lost
1. Re-set all variables using CLI:
   ```bash
   railway variables --set "SUPABASE_URL=..." --set "SUPABASE_SERVICE_ROLE_KEY=..."
   ```
2. Verify variables are set: `railway variables`
3. Service should auto-redeploy

### Build Failures
1. Check build logs: `railway logs --build`
2. Verify Dockerfile syntax and paths
3. Check requirements.txt for dependency issues
4. Test build locally if possible

## Reference Links

- **Railway Dashboard**: [railway.app/dashboard](https://railway.app/dashboard)
- **Railway CLI Docs**: [docs.railway.app/develop/cli](https://docs.railway.app/develop/cli)
- **Project Repository**: [GitHub Repository URL]

## Maintenance

### Regular Tasks
- Monitor service health weekly
- Review and rotate API keys quarterly
- Update dependencies as needed
- Clean up old deployments periodically

### Updates
- Keep Railway CLI updated: `npm update -g @railway/cli`
- Monitor Railway changelog for breaking changes
- Test deployments in development environment when possible

---

*Last updated: $(date)*
*Maintainer: Development Team*
