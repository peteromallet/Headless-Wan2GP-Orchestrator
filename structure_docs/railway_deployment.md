# Railway Deployment Guide

Simple guide for deploying the orchestrator services to Railway.

## Overview

Two Railway services:
- **API Orchestrator**: Handles Wavespeed AI tasks
- **GPU Orchestrator**: Manages RunPod GPU workers

## Quick Deploy

### Method 1: Auto-deploy (Recommended)
Services auto-deploy when you push to `main` branch:

```bash
git add .
git commit -m "Your changes"
git push origin main
# Railway automatically deploys both services
```

### Method 2: Manual deploy
```bash
# Deploy API service
cd api_orchestrator
railway up --detach

# Deploy GPU service  
cd ../gpu_orchestrator
railway up --detach
```

## Setup (One-time)

1. **Install Railway CLI**:
   ```bash
   npm install -g @railway/cli
   railway login
   ```

2. **Link services** (in each directory):
   ```bash
   cd api_orchestrator
   railway link  # Select api-orchestrator project
   
   cd ../gpu_orchestrator  
   railway link  # Select gpu-orchestrator project
   ```

## Monitor Deployment

```bash
# Check logs
railway logs

# Check build logs  
railway logs --build

# Check specific service
railway logs --service api-orchestrator
railway logs --service gpu-orchestrator
```

## Common Issues

**Build fails with "Dockerfile not found"**
- Make sure you're in the right directory (`api_orchestrator` or `gpu_orchestrator`)
- Check `railway.json` has correct `dockerfilePath`

**Environment variables missing**
```bash
# Set variables via CLI
railway variables --set "SUPABASE_URL=..." --set "WAVESPEED_API_KEY=..."

# Or set via Railway dashboard: Project → Service → Variables
```

**Old code still running**
```bash
# Force redeploy
railway up --detach
```

## Troubleshooting

1. Check git status: `git status`
2. Check Railway connection: `railway status`  
3. Check environment variables: `railway variables`
4. Check logs: `railway logs --build` and `railway logs`
5. Force fresh deploy: `railway up --detach`
