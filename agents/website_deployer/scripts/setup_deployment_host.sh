#!/bin/bash
################################################################################
# Deployment Host Setup Script
################################################################################
#
# Interactive script to set up SSH key authentication and passwordless sudo
# for a new deployment host.
#
# Usage:
#   ./scripts/setup_deployment_host.sh
#
# Author: RAICA Development Team
# Version: 1.0.0
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo ""
    echo "================================================================================"
    echo "  $1"
    echo "================================================================================"
    echo ""
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_step() {
    echo ""
    echo -e "${BLUE}━━━ $1 ━━━${NC}"
    echo ""
}

# Main script
clear
print_header "DEPLOYMENT HOST SETUP"

echo "This script will set up SSH key authentication and passwordless sudo"
echo "for automated deployments to a remote server."
echo ""
read -p "Press Enter to continue..."

# Step 1: Gather information
print_step "Step 1: Host Information"

read -p "Enter the hostname or IP address: " DEPLOY_HOST
read -p "Enter the SSH username: " DEPLOY_USER
read -p "Enter the SSH port [default: 22]: " DEPLOY_PORT
DEPLOY_PORT=${DEPLOY_PORT:-22}

echo ""
echo "Configuration:"
echo "  Host: $DEPLOY_HOST"
echo "  User: $DEPLOY_USER"
echo "  Port: $DEPLOY_PORT"
echo ""
read -p "Is this correct? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
    print_error "Setup cancelled"
    exit 1
fi

# Step 2: SSH Key Setup
print_step "Step 2: SSH Key Setup"

KEY_PATH="$HOME/.ssh/deployment_key"

if [ -f "$KEY_PATH" ]; then
    print_warning "Deployment key already exists at $KEY_PATH"
    read -p "Do you want to use the existing key? (yes/no): " use_existing
    if [[ "$use_existing" != "yes" ]]; then
        read -p "Enter new key path [default: $HOME/.ssh/deployment_key_new]: " new_path
        KEY_PATH=${new_path:-$HOME/.ssh/deployment_key_new}
    fi
fi

if [ ! -f "$KEY_PATH" ]; then
    print_info "Generating new SSH key at $KEY_PATH"
    ssh-keygen -t ed25519 -f "$KEY_PATH" -C "deployment@$(hostname)" -N ""
    print_success "SSH key generated"
else
    print_success "Using existing SSH key"
fi

# Step 3: Remove old host key if exists
print_step "Step 3: Checking SSH Host Key"

if ssh-keygen -F "$DEPLOY_HOST" >/dev/null 2>&1; then
    print_warning "Host key exists in known_hosts"
    read -p "Remove old host key and accept new one? (yes/no): " remove_key
    if [[ "$remove_key" == "yes" ]]; then
        ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$DEPLOY_HOST"
        print_success "Old host key removed"
    fi
fi

# Step 4: Test basic SSH connection
print_step "Step 4: Testing Basic SSH Connection"

echo "Attempting to connect to $DEPLOY_USER@$DEPLOY_HOST"
echo "You will be prompted for your password..."
echo ""

if ! ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "echo 'Connection successful'" 2>/dev/null; then
    print_error "Cannot connect to remote host"
    print_info "Please verify:"
    print_info "  - Host is reachable: ping $DEPLOY_HOST"
    print_info "  - SSH server is running on port $DEPLOY_PORT"
    print_info "  - Username and password are correct"
    exit 1
fi

print_success "Basic SSH connection works"

# Step 5: Copy SSH key
print_step "Step 5: Copying SSH Key to Remote Host"

echo "You will be prompted for your password to copy the SSH key..."
echo ""

if ssh-copy-id -i "${KEY_PATH}.pub" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST"; then
    print_success "SSH key copied successfully"
else
    print_error "Failed to copy SSH key"
    exit 1
fi

# Step 6: Test key-based authentication
print_step "Step 6: Testing Key-Based Authentication"

if ssh -i "$KEY_PATH" -o ConnectTimeout=10 -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "echo 'Key authentication works'"; then
    print_success "Key-based authentication works"
else
    print_error "Key-based authentication failed"
    exit 1
fi

# Step 7: Configure passwordless sudo
print_step "Step 7: Configuring Passwordless Sudo"

echo "This step requires sudo access on the remote host."
echo "You will be prompted for your password one more time..."
echo ""

SUDOERS_CONTENT="$DEPLOY_USER ALL=(ALL) NOPASSWD:ALL"

# Create sudoers drop-in file
if ssh -i "$KEY_PATH" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "echo '$SUDOERS_CONTENT' | sudo tee /etc/sudoers.d/$DEPLOY_USER > /dev/null && sudo chmod 0440 /etc/sudoers.d/$DEPLOY_USER"; then
    print_success "Passwordless sudo configured"
else
    print_warning "Could not configure passwordless sudo"
    print_info "You may need to manually add the following to /etc/sudoers.d/$DEPLOY_USER:"
    print_info "  $SUDOERS_CONTENT"
fi

# Step 8: Test sudo access
print_step "Step 8: Testing Sudo Access"

if ssh -i "$KEY_PATH" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "sudo -n whoami" 2>/dev/null | grep -q "root"; then
    print_success "Passwordless sudo works"
else
    print_warning "Passwordless sudo not working"
    print_info "Deployments may require manual password entry"
fi

# Step 9: Set environment variables
print_step "Step 9: Setting Environment Variables"

ENV_FILE="$HOME/.bashrc"

# Check if variables already exist
if grep -q "DEPLOYMENT_SSH_HOST" "$ENV_FILE"; then
    print_warning "Environment variables already exist in $ENV_FILE"
    read -p "Do you want to update them? (yes/no): " update_env
    if [[ "$update_env" == "yes" ]]; then
        # Remove old variables
        sed -i '/DEPLOYMENT_SSH_HOST/d' "$ENV_FILE"
        sed -i '/DEPLOYMENT_SSH_USER/d' "$ENV_FILE"
        sed -i '/DEPLOYMENT_SSH_PORT/d' "$ENV_FILE"
        sed -i '/DEPLOYMENT_SSH_KEY_PATH/d' "$ENV_FILE"
    else
        print_info "Skipping environment variable update"
        ENV_FILE="$HOME/.deployment_env"
        print_info "Variables will be saved to $ENV_FILE instead"
    fi
fi

# Add environment variables
cat >> "$ENV_FILE" << EOF

# Deployment SSH Configuration (added by setup script)
export DEPLOYMENT_SSH_HOST="$DEPLOY_HOST"
export DEPLOYMENT_SSH_USER="$DEPLOY_USER"
export DEPLOYMENT_SSH_PORT="$DEPLOY_PORT"
export DEPLOYMENT_SSH_KEY_PATH="$KEY_PATH"
EOF

print_success "Environment variables saved to $ENV_FILE"

# Step 10: Get system information
print_step "Step 10: System Information"

echo "Gathering remote system information..."
echo ""

OS_INFO=$(ssh -i "$KEY_PATH" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "cat /etc/os-release | grep PRETTY_NAME | cut -d'=' -f2 | tr -d '\"'")
DISK_FREE=$(ssh -i "$KEY_PATH" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "df -h / | tail -1 | awk '{print \$4}'")
MEM_FREE=$(ssh -i "$KEY_PATH" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "free -h | grep Mem | awk '{print \$4}'")
HOSTNAME=$(ssh -i "$KEY_PATH" -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "hostname")

echo "Remote System:"
echo "  Hostname: $HOSTNAME"
echo "  OS: $OS_INFO"
echo "  Disk Free: $DISK_FREE"
echo "  Memory Free: $MEM_FREE"

# Final summary
print_header "SETUP COMPLETE"

print_success "Deployment host configured successfully!"
echo ""
echo "Connection Details:"
echo "  Host: $DEPLOY_HOST"
echo "  User: $DEPLOY_USER"
echo "  Port: $DEPLOY_PORT"
echo "  Key:  $KEY_PATH"
echo ""
echo "Next Steps:"
echo "  1. Load environment variables:"
echo "     source $ENV_FILE"
echo ""
echo "  2. Test the connection:"
echo "     cd examples"
echo "     python3 ssh_connection_demo.py"
echo ""
echo "  3. Or run a deployment:"
echo "     python3 full_deployment_demo.py"
echo ""

# Offer to test connection now
read -p "Do you want to test the connection now? (yes/no): " test_now

if [[ "$test_now" == "yes" ]]; then
    print_step "Running Connection Test"

    # Export variables for the current session
    export DEPLOYMENT_SSH_HOST="$DEPLOY_HOST"
    export DEPLOYMENT_SSH_USER="$DEPLOY_USER"
    export DEPLOYMENT_SSH_PORT="$DEPLOY_PORT"
    export DEPLOYMENT_SSH_KEY_PATH="$KEY_PATH"

    # Run the demo
    cd "$(dirname "$0")/../examples"
    python3 ssh_connection_demo.py
fi

print_success "All done!"
