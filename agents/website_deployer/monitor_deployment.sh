#!/bin/bash
# monitor_deployment.sh - Script to monitor deployment progress

LOG_FILE="agents/website_deployer/full_deployment_demo.log"

echo "🔍 Monitoring Full Deployment Demo Progress"
echo "📄 Log file: $LOG_FILE"
echo "🕒 Started at: $(date)"
echo ""
echo "=== LIVE PROGRESS ==="
echo ""

# Show live progress
tail -f "$LOG_FILE" | while read line; do
    # Highlight important messages
    if [[ $line == *"✅"* ]] || [[ $line == *"PHASE"* ]] || [[ $line == *"SUCCESS"* ]] || [[ $line == *"COMPLETE"* ]]; then
        echo -e "\033[1;32m$line\033[0m"  # Green for success
    elif [[ $line == *"❌"* ]] || [[ $line == *"ERROR"* ]] || [[ $line == *"FAILED"* ]]; then
        echo -e "\033[1;31m$line\033[0m"  # Red for errors
    elif [[ $line == *"🔧"* ]] || [[ $line == *"STEPS"* ]] || [[ $line == *"DEPLOYMENT"* ]]; then
        echo -e "\033[1;34m$line\033[0m"  # Blue for deployment info
    else
        echo "$line"
    fi
done