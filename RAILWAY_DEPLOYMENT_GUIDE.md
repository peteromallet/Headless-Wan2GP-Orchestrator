# Railway.com Deployment Guide

This guide walks you through deploying both the API Orchestrator and GPU Orchestrator services to Railway.com using your existing `.env` credentials.

## Prerequisites

1. **Railway Account**: Sign up at [railway.app](https://railway.app)
2. **GitHub Repository**: Your code should be pushed to a GitHub repository
3. **Environment Variables**: Your `.env` file with all necessary credentials

## Project Structure

This project contains two main services:
- **API Orchestrator** (`api_orchestrator/`): Handles CPU-bound API tasks (Wavespeed AI, image processing)
- **GPU Orchestrator** (`gpu_orchestrator/`): Manages RunPod GPU workers and orchestration

## Deployment Steps

### Step 1: Create a New Railway Project

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Connect your GitHub account and select this repository

### Step 2: Set Up API Orchestrator Service

1. **Create the Service**:
   - In your Railway project, click **"+ New"**
   - Select **"GitHub Repo"** 
   - Choose your repository
   - Name the service: `api-orchestrator`

2. **Configure Root Directory**:
   - Go to service **Settings** → **Source**
   - Set **Root Directory** to: `api_orchestrator`
   - Set **Build Command**: (leave empty - uses Dockerfile)
   - Set **Start Command**: (leave empty - uses Dockerfile CMD)

3. **Set Environment Variables**:
   - Go to **Variables** tab
   - Copy variables from `railway-env-api.template`:
   
   ```bash
   # Core Supabase Configuration
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
   SUPABASE_ACCESS_TOKEN=your_access_token_here
   
   # API Service Configuration
   API_WORKER_CONCURRENCY=20
   API_RUN_TYPE=api
   API_PARENT_POLL_SEC=10
   API_WORKER_ID=railway-api-worker-1
   
   # Third-party API Keys
   WAVESPEED_API_KEY=your_wavespeed_api_key_here
   REPLICATE_API_TOKEN=your_replicate_api_token_here
   
   # Logging
   LOG_LEVEL=INFO
   ```

4. **Deploy**:
   - Click **"Deploy"**
   - Monitor the build logs for any issues

### Step 3: Set Up GPU Orchestrator Service

1. **Create the Service**:
   - Click **"+ New"** in your project
   - Select **"GitHub Repo"**
   - Choose the same repository
   - Name the service: `gpu-orchestrator`

2. **Configure Root Directory**:
   - Go to service **Settings** → **Source**
   - Set **Root Directory** to: `gpu_orchestrator`
   - Set **Build Command**: (leave empty - uses Dockerfile)
   - Set **Start Command**: (leave empty - uses Dockerfile CMD)

3. **Set Environment Variables**:
   - Go to **Variables** tab
   - Copy variables from `railway-env-gpu.template`:
   
   ```bash
   # Core Supabase Configuration
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here
   SUPABASE_ACCESS_TOKEN=your_access_token_here
   
   # RunPod Configuration
   RUNPOD_API_KEY=your_runpod_api_key_here
   RUNPOD_INSTANCE_TYPE=NVIDIA RTX A4000
   RUNPOD_CONTAINER_IMAGE=your_worker_image:latest
   RUNPOD_CONTAINER_DISK_SIZE_GB=20
   
   # Scaling Parameters
   MIN_ACTIVE_GPUS=2
   MAX_ACTIVE_GPUS=10
   TASKS_PER_GPU_THRESHOLD=3
   MACHINES_TO_KEEP_IDLE=0
   
   # Timeouts (seconds)
   GPU_IDLE_TIMEOUT_SEC=300
   GPU_OVERCAPACITY_IDLE_TIMEOUT_SEC=30
   TASK_STUCK_TIMEOUT_SEC=1200
   SPAWNING_TIMEOUT_SEC=300
   GPU_HEALTH_CHECK_TIMEOUT_SEC=120
   ERROR_CLEANUP_GRACE_PERIOD_SEC=600
   FAILSAFE_STALE_THRESHOLD_SEC=7200
   
   # Orchestrator Settings
   ORCHESTRATOR_POLL_SEC=30
   
   # Logging
   LOG_LEVEL=INFO
   ```

4. **Deploy**:
   - Click **"Deploy"**
   - Monitor the build logs for any issues

### Step 4: Configure Service Communication (Optional)

If your services need to communicate with each other:

1. **Use Railway Private Networking**:
   - Services within the same project can communicate via private domains
   - Reference other services using: `${{service-name.RAILWAY_PRIVATE_DOMAIN}}`

2. **Example Environment Variables**:
   ```bash
   # In API Orchestrator
   GPU_ORCHESTRATOR_URL=http://${{gpu-orchestrator.RAILWAY_PRIVATE_DOMAIN}}
   
   # In GPU Orchestrator  
   API_ORCHESTRATOR_URL=http://${{api-orchestrator.RAILWAY_PRIVATE_DOMAIN}}
   ```

### Step 5: Monitoring and Logs

1. **View Logs**:
   - Click on each service to view real-time logs
   - Use the **Logs** tab to monitor application output

2. **Monitor Metrics**:
   - Check **Metrics** tab for CPU, memory usage
   - Set up alerts if needed

3. **Health Checks**:
   - Both services include health check endpoints
   - Railway will automatically restart unhealthy services

## Environment Variables Mapping

Use your existing `.env` file values and map them as follows:

| Your .env Variable | Railway Variable | Service |
|-------------------|------------------|---------|
| `SUPABASE_URL` | `SUPABASE_URL` | Both |
| `SUPABASE_SERVICE_ROLE_KEY` | `SUPABASE_SERVICE_ROLE_KEY` | Both |
| `WAVESPEED_API_KEY` | `WAVESPEED_API_KEY` | API |
| `RUNPOD_API_KEY` | `RUNPOD_API_KEY` | GPU |
| `API_WORKER_CONCURRENCY` | `API_WORKER_CONCURRENCY` | API |
| `MIN_ACTIVE_GPUS` | `MIN_ACTIVE_GPUS` | GPU |
| `MAX_ACTIVE_GPUS` | `MAX_ACTIVE_GPUS` | GPU |

## Troubleshooting

### Common Issues

1. **Build Failures**:
   - Check that `requirements.txt` is in the project root
   - Ensure Dockerfile paths are correct
   - Verify Python version compatibility

2. **Runtime Errors**:
   - Check environment variables are set correctly
   - Verify API keys are valid and have proper permissions
   - Check service logs for specific error messages

3. **Connection Issues**:
   - Ensure Supabase URL is accessible from Railway
   - Verify RunPod API key has necessary permissions
   - Check firewall/network settings

### Debugging Commands

```bash
# Check service status
railway status

# View logs
railway logs

# Connect to service shell (if needed)
railway shell
```

## Cost Optimization

1. **Resource Limits**:
   - Set appropriate memory limits for each service
   - Monitor CPU usage and scale accordingly

2. **Auto-scaling**:
   - Configure auto-scaling based on load
   - Set minimum/maximum replica counts

3. **Sleep Mode**:
   - Enable sleep mode for development environments
   - Disable for production services

## Security Best Practices

1. **Environment Variables**:
   - Never commit `.env` files to git
   - Use Railway's encrypted environment variables
   - Rotate API keys regularly

2. **Access Control**:
   - Limit Railway project access to necessary team members
   - Use service-specific environment variables where possible

3. **Monitoring**:
   - Set up alerts for unusual activity
   - Monitor logs for security events
   - Regular security audits

## Next Steps

After successful deployment:

1. **Test Services**: Verify both orchestrators are processing tasks correctly
2. **Monitor Performance**: Check logs and metrics regularly
3. **Scale as Needed**: Adjust resources based on actual usage
4. **Set Up Alerts**: Configure notifications for service failures
5. **Backup Strategy**: Ensure critical data is backed up

## Support

- **Railway Documentation**: [docs.railway.app](https://docs.railway.app)
- **Railway Community**: [Railway Discord](https://discord.gg/railway)
- **Project Issues**: Create issues in your GitHub repository
