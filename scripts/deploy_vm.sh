#!/bin/bash
# 
# VM Deployment Script for Runpod GPU Worker Orchestrator
# Run this on a fresh Ubuntu/Debian VM to set up the orchestrator
#

set -e

echo "🚀 Setting up Runpod GPU Worker Orchestrator on VM..."
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/yourusername/your-orchestrator-repo.git"  # UPDATE THIS
INSTALL_DIR="$HOME/runpod-orchestrator"
LOG_FILE="/var/log/orchestrator.log"

# Function to print colored output
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Don't run this script as root. Run as a regular user."
    exit 1
fi

# Step 1: Update system and install dependencies
print_status "Installing system dependencies..."
sudo apt update
sudo apt install -y python3 python3-pip git cron curl nano

# Step 2: Clone repository
print_status "Cloning orchestrator repository..."
if [ -d "$INSTALL_DIR" ]; then
    print_warning "Directory $INSTALL_DIR already exists. Updating..."
    cd "$INSTALL_DIR"
    git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Step 3: Install Python dependencies
print_status "Installing Python dependencies..."
pip3 install -r requirements.txt

# Step 4: Set up environment file
print_status "Setting up environment configuration..."
if [ ! -f ".env" ]; then
    cp env.example .env
    print_warning "Environment file created at $INSTALL_DIR/.env"
    print_warning "You MUST edit this file with your API keys before the orchestrator will work!"
    echo ""
    echo "Required environment variables:"
    echo "  - SUPABASE_URL"
    echo "  - SUPABASE_SERVICE_ROLE_KEY" 
    echo "  - RUNPOD_API_KEY"
    echo "  - RUNPOD_CONTAINER_IMAGE"
    echo ""
    read -p "Press Enter to open the .env file for editing..." -n1 -s
    nano .env
else
    print_status "Environment file already exists"
fi

# Step 5: Test the setup
print_status "Testing configuration..."
if python3 scripts/test_supabase.py; then
    print_status "Supabase connection successful"
else
    print_error "Supabase connection failed. Check your .env file."
    exit 1
fi

if python3 scripts/test_runpod.py; then
    print_status "Runpod connection successful"
else
    print_error "Runpod connection failed. Check your .env file."
    exit 1
fi

# Step 6: Test single orchestrator run
print_status "Testing orchestrator execution..."
if python3 -m gpu_orchestrator.main single; then
    print_status "Orchestrator test successful"
else
    print_warning "Orchestrator test had issues. Check the output above."
fi

# Step 7: Set up log file
print_status "Setting up log file..."
sudo touch "$LOG_FILE"
sudo chmod 666 "$LOG_FILE"

# Step 8: Set up cron job
print_status "Setting up cron scheduling..."

# Create cron job content
CRON_JOB1="* * * * * cd $INSTALL_DIR && python3 -m gpu_orchestrator.main single >> $LOG_FILE 2>&1"
CRON_JOB2="* * * * * sleep 30 && cd $INSTALL_DIR && python3 -m gpu_orchestrator.main single >> $LOG_FILE 2>&1"

# Check if cron jobs already exist
if crontab -l 2>/dev/null | grep -q "gpu_orchestrator.main"; then
    print_warning "Cron jobs already exist. Skipping cron setup."
else
    # Add cron jobs
    (crontab -l 2>/dev/null; echo "$CRON_JOB1"; echo "$CRON_JOB2") | crontab -
    print_status "Cron jobs added (runs every 30 seconds)"
fi

# Step 9: Start cron service
print_status "Starting cron service..."
sudo systemctl enable cron
sudo systemctl start cron

# Final instructions
print_status "Deployment completed!"
echo ""
echo "🎉 Your Runpod GPU Worker Orchestrator is now running!"
echo ""
echo "📋 Next steps:"
echo "  1. Monitor logs: tail -f $LOG_FILE"
echo "  2. Check status: cd $INSTALL_DIR && python3 -m gpu_orchestrator.main status"
echo "  3. Run dashboard: cd $INSTALL_DIR && python3 scripts/dashboard.py"
echo "  4. Create test tasks: cd $INSTALL_DIR && python3 scripts/test_supabase.py --create-task"
echo ""
echo "🔧 Management commands:"
echo "  - View cron jobs: crontab -l"
echo "  - Edit cron jobs: crontab -e" 
echo "  - Disable orchestrator: crontab -r"
echo "  - Update code: cd $INSTALL_DIR && git pull"
echo ""
echo "📊 Files and locations:"
echo "  - Code: $INSTALL_DIR"
echo "  - Logs: $LOG_FILE"
echo "  - Config: $INSTALL_DIR/.env"
echo ""
print_status "Setup complete! The orchestrator is now running automatically."

# Optional: Show some initial logs
echo ""
read -p "Would you like to watch the logs for a minute to see the orchestrator in action? (y/N): " -n1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_status "Watching logs for 60 seconds (press Ctrl+C to stop)..."
    timeout 60 tail -f "$LOG_FILE" || true
fi

print_status "All done! 🚀" 