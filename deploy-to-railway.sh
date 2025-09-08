#!/bin/bash

# Railway Deployment Helper Script
# This script helps set up environment variables from your .env file

set -e

echo "🚂 Railway Deployment Helper"
echo "=============================="

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "Please create a .env file with your credentials first."
    exit 1
fi

# Check if railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI not found!"
    echo "Install it with: npm install -g @railway/cli"
    echo "Or visit: https://docs.railway.app/develop/cli"
    exit 1
fi

echo "✅ Found .env file and Railway CLI"
echo ""

# Function to extract value from .env file
get_env_value() {
    local key=$1
    local value=$(grep "^${key}=" .env | cut -d '=' -f2- | sed 's/^"//' | sed 's/"$//')
    echo "$value"
}

# Function to set Railway environment variable
set_railway_var() {
    local service=$1
    local key=$2
    local value=$3
    
    if [ -n "$value" ]; then
        echo "Setting $key for $service..."
        railway variables set "$key=$value" --service "$service" || echo "⚠️  Warning: Could not set $key"
    else
        echo "⚠️  Warning: $key not found in .env file"
    fi
}

echo "Please select which service to configure:"
echo "1) API Orchestrator"
echo "2) GPU Orchestrator"
echo "3) Both services"
read -p "Enter choice (1-3): " choice

case $choice in
    1|3)
        echo ""
        echo "🔧 Configuring API Orchestrator..."
        echo "Please ensure you have created the 'api-orchestrator' service in Railway first."
        read -p "Press Enter to continue..."
        
        # API Orchestrator environment variables
        set_railway_var "api-orchestrator" "SUPABASE_URL" "$(get_env_value 'SUPABASE_URL')"
        set_railway_var "api-orchestrator" "SUPABASE_SERVICE_ROLE_KEY" "$(get_env_value 'SUPABASE_SERVICE_ROLE_KEY')"
        set_railway_var "api-orchestrator" "SUPABASE_ACCESS_TOKEN" "$(get_env_value 'SUPABASE_ACCESS_TOKEN')"
        set_railway_var "api-orchestrator" "WAVESPEED_API_KEY" "$(get_env_value 'WAVESPEED_API_KEY')"
        set_railway_var "api-orchestrator" "REPLICATE_API_TOKEN" "$(get_env_value 'REPLICATE_API_TOKEN')"
        set_railway_var "api-orchestrator" "API_WORKER_CONCURRENCY" "$(get_env_value 'API_WORKER_CONCURRENCY')"
        set_railway_var "api-orchestrator" "API_RUN_TYPE" "$(get_env_value 'API_RUN_TYPE')"
        set_railway_var "api-orchestrator" "API_PARENT_POLL_SEC" "$(get_env_value 'API_PARENT_POLL_SEC')"
        set_railway_var "api-orchestrator" "API_WORKER_ID" "railway-api-worker-1"
        set_railway_var "api-orchestrator" "LOG_LEVEL" "INFO"
        
        echo "✅ API Orchestrator configuration completed!"
        ;;
esac

case $choice in
    2|3)
        echo ""
        echo "🔧 Configuring GPU Orchestrator..."
        echo "Please ensure you have created the 'gpu-orchestrator' service in Railway first."
        read -p "Press Enter to continue..."
        
        # GPU Orchestrator environment variables
        set_railway_var "gpu-orchestrator" "SUPABASE_URL" "$(get_env_value 'SUPABASE_URL')"
        set_railway_var "gpu-orchestrator" "SUPABASE_SERVICE_ROLE_KEY" "$(get_env_value 'SUPABASE_SERVICE_ROLE_KEY')"
        set_railway_var "gpu-orchestrator" "SUPABASE_ACCESS_TOKEN" "$(get_env_value 'SUPABASE_ACCESS_TOKEN')"
        set_railway_var "gpu-orchestrator" "RUNPOD_API_KEY" "$(get_env_value 'RUNPOD_API_KEY')"
        set_railway_var "gpu-orchestrator" "RUNPOD_INSTANCE_TYPE" "$(get_env_value 'RUNPOD_INSTANCE_TYPE')"
        set_railway_var "gpu-orchestrator" "RUNPOD_CONTAINER_IMAGE" "$(get_env_value 'RUNPOD_CONTAINER_IMAGE')"
        set_railway_var "gpu-orchestrator" "RUNPOD_CONTAINER_DISK_SIZE_GB" "$(get_env_value 'RUNPOD_CONTAINER_DISK_SIZE_GB')"
        set_railway_var "gpu-orchestrator" "MIN_ACTIVE_GPUS" "$(get_env_value 'MIN_ACTIVE_GPUS')"
        set_railway_var "gpu-orchestrator" "MAX_ACTIVE_GPUS" "$(get_env_value 'MAX_ACTIVE_GPUS')"
        set_railway_var "gpu-orchestrator" "TASKS_PER_GPU_THRESHOLD" "$(get_env_value 'TASKS_PER_GPU_THRESHOLD')"
        set_railway_var "gpu-orchestrator" "MACHINES_TO_KEEP_IDLE" "$(get_env_value 'MACHINES_TO_KEEP_IDLE')"
        set_railway_var "gpu-orchestrator" "GPU_IDLE_TIMEOUT_SEC" "$(get_env_value 'GPU_IDLE_TIMEOUT_SEC')"
        set_railway_var "gpu-orchestrator" "TASK_STUCK_TIMEOUT_SEC" "$(get_env_value 'TASK_STUCK_TIMEOUT_SEC')"
        set_railway_var "gpu-orchestrator" "ORCHESTRATOR_POLL_SEC" "$(get_env_value 'ORCHESTRATOR_POLL_SEC')"
        set_railway_var "gpu-orchestrator" "LOG_LEVEL" "INFO"
        
        echo "✅ GPU Orchestrator configuration completed!"
        ;;
esac

echo ""
echo "🎉 Configuration completed!"
echo ""
echo "Next steps:"
echo "1. Go to your Railway dashboard"
echo "2. Verify both services are deploying successfully"
echo "3. Check the logs for any issues"
echo "4. Monitor the services for proper operation"
echo ""
echo "For detailed instructions, see: RAILWAY_DEPLOYMENT_GUIDE.md"
