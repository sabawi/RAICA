#!/bin/bash
#
# RAICA Deployment Script
# ======================
# Deploys RAICA to remote server using SSH key authentication
#
# Usage:
#   ./deploy_raica.sh                    # Deploy to configured server
#   ./deploy_raica.sh --help             # Show help
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SSH_HOST="${DEPLOYMENT_SSH_HOST:-192.168.1.58}"
SSH_USER="${DEPLOYMENT_SSH_USER:-sabawi}"
SSH_KEY_PATH="${DEPLOYMENT_SSH_KEY_PATH:-$HOME/.ssh/deployment_key}"
INPUT_FILE="${DEPLOYMENT_INPUT_FILE:-examples/raica_input.json}"

# Show help
if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    echo "RAICA Deployment Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Environment Variables:"
    echo "  DEPLOYMENT_SSH_HOST      Target server (default: 192.168.1.58)"
    echo "  DEPLOYMENT_SSH_USER      SSH username (default: sabawi)"
    echo "  DEPLOYMENT_SSH_KEY_PATH  SSH key path (default: ~/.ssh/id_ed25519)"
    echo "  DEPLOYMENT_INPUT_FILE    Input JSON file (default: examples/raica_input.json)"
    echo ""
    echo "Options:"
    echo "  --help, -h              Show this help message"
    echo "  --test-connection       Test SSH connection only"
    echo "  --replay CACHE_FILE     Replay from cached LLM responses"
    echo ""
    echo "Examples:"
    echo "  # Deploy with default settings"
    echo "  ./deploy_raica.sh"
    echo ""
    echo "  # Deploy to different server"
    echo "  DEPLOYMENT_SSH_HOST=production.example.com ./deploy_raica.sh"
    echo ""
    echo "  # Replay from cache (faster, deterministic)"
    echo "  ./deploy_raica.sh --replay raica_deployment_cache.json"
    echo ""
    exit 0
fi

# Test connection mode
if [[ "$1" == "--test-connection" ]]; then
    echo -e "${YELLOW}Testing SSH connection...${NC}"
    echo "  Host: $SSH_HOST"
    echo "  User: $SSH_USER"
    echo "  Key:  $SSH_KEY_PATH"
    echo ""

    if ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$SSH_USER@$SSH_HOST" "echo 'Connection successful'"; then
        echo -e "${GREEN}✅ SSH connection successful${NC}"
        exit 0
    else
        echo -e "${RED}❌ SSH connection failed${NC}"
        exit 1
    fi
fi

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if [ ! -f "$SSH_KEY_PATH" ]; then
    echo -e "${RED}❌ SSH key not found: $SSH_KEY_PATH${NC}"
    echo ""
    echo "Generate one with:"
    echo "  ssh-keygen -t ed25519 -f $SSH_KEY_PATH"
    echo ""
    echo "Then copy to server:"
    echo "  ssh-copy-id -i $SSH_KEY_PATH.pub $SSH_USER@$SSH_HOST"
    exit 1
fi

if [ ! -f "$INPUT_FILE" ]; then
    echo -e "${RED}❌ Input file not found: $INPUT_FILE${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Prerequisites OK${NC}"

# Export environment variables
export DEPLOYMENT_SSH_HOST="$SSH_HOST"
export DEPLOYMENT_SSH_USER="$SSH_USER"
export DEPLOYMENT_SSH_KEY_PATH="$SSH_KEY_PATH"

# Build command
CMD="python examples/full_deployment_demo.py --auto-input $INPUT_FILE"

# Check for replay mode
if [[ "$1" == "--replay" ]] && [[ -n "$2" ]]; then
    CACHE_FILE="$2"
    if [ ! -f "$CACHE_FILE" ]; then
        echo -e "${RED}❌ Cache file not found: $CACHE_FILE${NC}"
        exit 1
    fi
    CMD="$CMD --replay-responses $CACHE_FILE"
    echo -e "${YELLOW}Using cached LLM responses from: $CACHE_FILE${NC}"
else
    # Save responses for future replay
    CACHE_FILE="raica_deployment_$(date +%Y%m%d_%H%M%S).json"
    CMD="$CMD --save-responses $CACHE_FILE"
    echo -e "${YELLOW}Will save LLM responses to: $CACHE_FILE${NC}"
fi

# Show configuration
echo ""
echo -e "${YELLOW}Deployment Configuration:${NC}"
echo "  Target Server: $SSH_USER@$SSH_HOST"
echo "  SSH Key:       $SSH_KEY_PATH"
echo "  Input File:    $INPUT_FILE"
echo "  Log File:      raica_deployment.log"
echo ""

# Confirm
read -p "Proceed with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Deployment cancelled${NC}"
    exit 0
fi

# Run deployment
echo ""
echo -e "${GREEN}🚀 Starting deployment...${NC}"
echo ""

$CMD 2>&1 | tee raica_deployment.log

# Check result
if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Deployment successful!${NC}"
    echo ""
    echo "Log file: raica_deployment.log"
    [ -f "$CACHE_FILE" ] && echo "Cache file: $CACHE_FILE"
else
    echo ""
    echo -e "${RED}❌ Deployment failed${NC}"
    echo ""
    echo "Check log file for details: raica_deployment.log"
    exit 1
fi
