# Railway Deployment Quick Reference

## 🚀 Quick Start

1. **Create Railway Project**: Connect your GitHub repo
2. **Create Two Services**:
   - `api-orchestrator` (Root: `api_orchestrator/`)
   - `gpu-orchestrator` (Root: `gpu_orchestrator/`)
3. **Set Environment Variables**: Use the templates provided
4. **Deploy**: Both services will auto-deploy

## 📁 Files Created

- `railway.json` - Railway configuration files (3 files)
- `api_orchestrator/Dockerfile` - API orchestrator container
- `gpu_orchestrator/Dockerfile` - GPU orchestrator container
- `railway-env-api.template` - API service environment variables
- `railway-env-gpu.template` - GPU service environment variables
- `deploy-to-railway.sh` - Automated environment setup script
- `RAILWAY_DEPLOYMENT_GUIDE.md` - Complete deployment guide

## ⚡ Quick Commands

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login to Railway
railway login

# Set environment variables automatically
./deploy-to-railway.sh

# View logs
railway logs --service api-orchestrator
railway logs --service gpu-orchestrator

# Check status
railway status
```

## 🔧 Environment Variables Checklist

### API Orchestrator
- ✅ `SUPABASE_URL`
- ✅ `SUPABASE_SERVICE_ROLE_KEY` 
- ✅ `WAVESPEED_API_KEY`
- ✅ `API_WORKER_CONCURRENCY`
- ✅ `API_RUN_TYPE=api`

### GPU Orchestrator  
- ✅ `SUPABASE_URL`
- ✅ `SUPABASE_SERVICE_ROLE_KEY`
- ✅ `RUNPOD_API_KEY`
- ✅ `MIN_ACTIVE_GPUS`
- ✅ `MAX_ACTIVE_GPUS`
- ✅ `RUNPOD_INSTANCE_TYPE`

## 🔍 Monitoring

- **Logs**: Real-time in Railway dashboard
- **Metrics**: CPU/Memory usage tracking  
- **Health Checks**: Automatic service restart
- **Alerts**: Configure for failures

## 🆘 Troubleshooting

1. **Build fails**: Check Dockerfile paths and requirements.txt
2. **Runtime errors**: Verify environment variables
3. **Connection issues**: Test API keys and Supabase connectivity
4. **Performance**: Monitor logs and adjust concurrency settings
