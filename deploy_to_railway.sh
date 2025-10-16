#!/bin/bash

# Railway Deployment Script
# Deploys both API and GPU orchestrator services to Railway

set -e  # Exit on any error

echo "🚀 Starting Railway deployment..."

# Check if Railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI not found. Please install it first:"
    echo "   npm install -g @railway/cli"
    echo "   railway login"
    exit 1
fi

# Function to deploy a service
deploy_service() {
    local service_name=$1
    local service_dir=$2
    
    echo ""
    echo "📦 Deploying $service_name..."
    echo "   Directory: $service_dir"
    
    cd "$service_dir"
    
    # Check if railway.json exists
    if [[ ! -f "railway.json" ]]; then
        echo "⚠️  Warning: No railway.json found in $service_dir"
    fi
    
    # Deploy with detached mode
    echo "   Running: railway up --detach"
    railway up --detach
    
    if [[ $? -eq 0 ]]; then
        echo "✅ $service_name deployed successfully"
    else
        echo "❌ Failed to deploy $service_name"
        exit 1
    fi
    
    cd ..
}

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "📍 Working directory: $(pwd)"

# Deploy API Orchestrator
deploy_service "API Orchestrator" "api_orchestrator"

# Deploy GPU Orchestrator  
deploy_service "GPU Orchestrator" "gpu_orchestrator"

echo ""
echo "🎉 All services deployed successfully!"
echo ""
echo "📊 Monitor your deployments:"
echo "   Railway dashboard: https://railway.app"
echo "   API Orchestrator logs: railway logs --service api-orchestrator"
echo "   GPU Orchestrator logs: railway logs --service gpu-orchestrator"
echo ""
echo "💡 Useful commands:"
echo "   Check service status: railway status"
echo "   Open dashboard: railway open"
echo "   Restart service: railway restart --service <service-name>"
echo ""
echo "🔧 Environment variables:"
echo "   Set variable: railway variables set KEY=value --service <service-name>"
echo "   List variables: railway variables --service <service-name>"
