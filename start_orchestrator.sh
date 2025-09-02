#!/bin/bash

# Start the Orchestrator with production-ready logging defaults
# 
# This script automatically:
# - Creates JSON logs for easy parsing
# - Saves logs to files with rotation (orchestrator.log)
# - Runs in continuous mode
# - Uses INFO level logging

echo "Starting GPU Orchestrator with automatic log file creation..."
echo "Logs will be saved to: ./orchestrator.log (rotated at 10MB, 5 backups)"
echo "JSON format for easy parsing by log aggregation tools"
echo ""
echo "To customize:"
echo "  LOG_FILE=/path/to/logs/orchestrator.log ./start_orchestrator.sh"
echo "  LOG_FILE=\"\" ./start_orchestrator.sh  # Disable file logging"
echo "  LOG_FORMAT=plain ./start_orchestrator.sh  # Human-readable logs"
echo ""

# Set defaults if not already set
export LOG_FORMAT=${LOG_FORMAT:-json}
export LOG_LEVEL=${LOG_LEVEL:-INFO}
# LOG_FILE will default to ./orchestrator.log via the logging config

python -m gpu_orchestrator.main continuous 