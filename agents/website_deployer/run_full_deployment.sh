#!/bin/bash
# full_deployment_runner.sh - Script to run full deployment with proper environment setup

# Set environment variables for SSH authentication
export DEPLOYMENT_SSH_HOST="192.168.1.58"
export DEPLOYMENT_SSH_USER="sabawi"
export DEPLOYMENT_SSH_PASSWORD="Down2earth!"

# Set up logging
LOG_FILE="agents/website_deployer/full_deployment_demo.log"

echo "🚀 Starting Full Deployment Demo"
echo "📝 Logging to: $LOG_FILE"
echo "🖥️  Target Server: $DEPLOYMENT_SSH_HOST"
echo "👤 SSH User: $DEPLOYMENT_SSH_USER"
echo "📂 Auto Input: agents/website_deployer/comprehensive_deployment_test.json"
echo ""

# Run the deployment with logging
{
    echo "=== FULL DEPLOYMENT DEMO STARTED AT $(date) ==="
    echo ""
    
    python3 agents/website_deployer/examples/full_deployment_demo.py \
        --auto-input agents/website_deployer/comprehensive_deployment_test.json \
        --save-responses agents/website_deployer/deployment_llm_cache.json
    
    echo ""
    echo "=== FULL DEPLOYMENT DEMO COMPLETED AT $(date) ==="
    
} 2>&1 | tee "$LOG_FILE"

echo ""
echo "✅ Deployment process completed!"
echo "📄 Log file saved to: $LOG_FILE"