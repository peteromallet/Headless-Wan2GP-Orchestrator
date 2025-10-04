#!/bin/bash

# Script to help set up SSH keys for Railway deployment
# WARNING: This script shows private keys - only run in secure environment

echo "🔧 Railway SSH Key Setup Helper"
echo "================================"
echo ""
echo "⚠️  WARNING: This will display private key content!"
echo "    Only run this in a secure terminal session."
echo ""
read -p "Continue? (y/N): " confirm
if [[ $confirm != [yY] ]]; then
    echo "Aborted."
    exit 0
fi

echo ""

# Check if Ed25519 key exists
if [ -f "/Users/peteromalley/.ssh/id_ed25519" ]; then
    echo "✅ Found Ed25519 key pair"
    echo ""
    echo "📋 STEP 1: Copy PRIVATE key to Railway (keep this secret!):"
    echo "Variable name: RUNPOD_SSH_PRIVATE_KEY"
    echo "Value (copy everything including BEGIN/END lines):"
    echo "----------------------------------------------------------------------"
    cat /Users/peteromalley/.ssh/id_ed25519
    echo ""
    echo "----------------------------------------------------------------------"
    echo ""
    echo "📋 STEP 2: Copy PUBLIC key to Railway:"
    echo "Variable name: RUNPOD_SSH_PUBLIC_KEY"
    echo "Value:"
    echo "---------------------------------------------------------------------"
    cat /Users/peteromalley/.ssh/id_ed25519.pub
    echo ""
    echo "---------------------------------------------------------------------"
else
    echo "❌ Ed25519 key not found at /Users/peteromalley/.ssh/id_ed25519"
    echo ""
    echo "🔑 Generate new Ed25519 key pair first:"
    echo "ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''"
    exit 1
fi

echo ""
echo "🚀 Railway Setup Steps:"
echo "1. Go to your Railway project dashboard"
echo "2. Click on your gpu_orchestrator service"
echo "3. Go to Variables tab"
echo "4. Add RUNPOD_SSH_PRIVATE_KEY (paste the private key above)"
echo "5. Add RUNPOD_SSH_PUBLIC_KEY (paste the public key above)"
echo "6. Click 'Deploy' to redeploy your service"
echo ""
echo "✅ Local .env is already configured correctly for local development"
echo ""
echo "🔒 Security Note: Private keys are NOT stored in git (.env is in .gitignore)"
