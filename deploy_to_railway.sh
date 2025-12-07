#!/bin/bash

# Railway Deployment Script
# Deploys both API and GPU orchestrator services to Railway
# Usage:
#   ./deploy_to_railway.sh           # Deploy both services
#   ./deploy_to_railway.sh --gpu     # Deploy GPU orchestrator only
#   ./deploy_to_railway.sh --api     # Deploy API orchestrator only

set -e  # Exit on any error

# Parse command line arguments
DEPLOY_GPU=false
DEPLOY_API=false

if [[ $# -eq 0 ]]; then
    # No arguments - deploy both
    DEPLOY_GPU=true
    DEPLOY_API=true
else
    # Parse flags
    while [[ $# -gt 0 ]]; do
        case $1 in
            --gpu)
                DEPLOY_GPU=true
                shift
                ;;
            --api)
                DEPLOY_API=true
                shift
                ;;
            *)
                echo "❌ Unknown option: $1"
                echo "Usage: $0 [--gpu] [--api]"
                echo "  --gpu    Deploy GPU orchestrator only"
                echo "  --api    Deploy API orchestrator only"
                echo "  (no args) Deploy both services"
                exit 1
                ;;
        esac
    done
fi

echo "🚀 Starting Railway deployment..."
if [[ "$DEPLOY_GPU" == true ]] && [[ "$DEPLOY_API" == true ]]; then
    echo "   Deploying: Both services"
elif [[ "$DEPLOY_GPU" == true ]]; then
    echo "   Deploying: GPU Orchestrator only"
elif [[ "$DEPLOY_API" == true ]]; then
    echo "   Deploying: API Orchestrator only"
fi

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
if [[ "$DEPLOY_API" == true ]]; then
    deploy_service "API Orchestrator" "api_orchestrator"
fi

# Deploy GPU Orchestrator  
if [[ "$DEPLOY_GPU" == true ]]; then
    deploy_service "GPU Orchestrator" "gpu_orchestrator"
fi

echo ""
if [[ "$DEPLOY_GPU" == true ]] && [[ "$DEPLOY_API" == true ]]; then
    echo "🎉 All services deployed successfully!"
elif [[ "$DEPLOY_GPU" == true ]]; then
    echo "🎉 GPU Orchestrator deployed successfully!"
elif [[ "$DEPLOY_API" == true ]]; then
    echo "🎉 API Orchestrator deployed successfully!"
fi
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
