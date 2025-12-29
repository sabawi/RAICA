# SSH Authentication Guide for Website Deployer

## Problem Statement

Password-based SSH authentication via `--ssh-host-user` flag fails consistently due to SSH server configuration disabling password authentication (security best practice).

**Error:**
```
paramiko.ssh_exception.AuthenticationException: Authentication failed.
ConnectionError: SSH authentication failed: Authentication failed.
```

## Root Cause

Most production SSH servers disable password authentication (`PasswordAuthentication no` in `/etc/ssh/sshd_config`) for security reasons, only allowing public key authentication.

## ✅ **PERMANENT SOLUTION: Use SSH Key Authentication**

### Method 1: Environment Variables (Recommended for Automation)

**Setup:**
```bash
export DEPLOYMENT_SSH_HOST="192.168.1.58"
export DEPLOYMENT_SSH_USER="sabawi"
export DEPLOYMENT_SSH_KEY_PATH="/home/sabawi/.ssh/id_ed25519"

# Optional: If your SSH key has a passphrase
export DEPLOYMENT_SSH_KEY_PASSPHRASE="your-passphrase"

# Run deployment
python examples/full_deployment_demo.py --auto-input examples/raica_input.json
```

**Advantages:**
- ✅ Works with all SSH server configurations
- ✅ More secure (public key cryptography)
- ✅ No password exposure in command history
- ✅ Automated/scriptable
- ✅ Industry standard

###Method 2: SSH Key with Shell Script Wrapper

Create `deploy.sh`:
```bash
#!/bin/bash
export DEPLOYMENT_SSH_HOST="192.168.1.58"
export DEPLOYMENT_SSH_USER="sabawi"
export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/id_ed25519"

python examples/full_deployment_demo.py --auto-input examples/raica_input.json "$@"
```

Usage:
```bash
chmod +x deploy.sh
./deploy.sh
```

### Method 3: SSH Config File (Best for Multiple Servers)

Edit `~/.ssh/config`:
```
Host deployment-server
    HostName 192.168.1.58
    User sabawi
    IdentityFile ~/.ssh/id_ed25519
    Port 22
```

Then set:
```bash
export DEPLOYMENT_SSH_HOST="deployment-server"
export DEPLOYMENT_SSH_USER="sabawi"
export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/id_ed25519"
```

## SSH Key Setup (If You Don't Have One)

### 1. Generate SSH Key Pair
```bash
ssh-keygen -t ed25519 -C "deployment@$(hostname)" -f ~/.ssh/id_ed25519
```

### 2. Copy Public Key to Server
```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub sabawi@192.168.1.58
```

### 3. Test Connection
```bash
ssh -i ~/.ssh/id_ed25519 sabawi@192.168.1.58 "echo 'Connection successful'"
```

## Why Password Auth Was Attempted (And Failed)

The `--ssh-host-user` flag triggers password authentication:
```bash
# ❌ This fails on secure SSH servers:
python examples/full_deployment_demo.py --ssh-host-user "sabawi@192.168.1.58"
# Prompts for password → Authentication failed
```

The code checks for `DEPLOYMENT_SSH_PASSWORD` environment variable, but even with it set, many SSH servers reject password authentication entirely.

## Troubleshooting

### Issue: "Permission denied (publickey)"
**Cause:** SSH key not authorized on server
**Fix:**
```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub sabawi@192.168.1.58
```

### Issue: "Bad permissions"
**Cause:** SSH key file has wrong permissions
**Fix:**
```bash
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
chmod 700 ~/.ssh
```

### Issue: "Could not resolve hostname"
**Cause:** Invalid hostname in DEPLOYMENT_SSH_HOST
**Fix:** Use IP address or verify hostname resolution

### Issue: "Connection refused"
**Cause:** SSH server not running or wrong port
**Fix:**
```bash
# Check SSH server status on remote
ssh sabawi@192.168.1.58 "systemctl status sshd"

# Or use different port
export DEPLOYMENT_SSH_PORT=2222
```

## Server-Side SSH Configuration

For reference, here's what a secure SSH server config looks like (`/etc/ssh/sshd_config`):

```
# Disable password authentication (why --ssh-host-user fails)
PasswordAuthentication no

# Only allow public key authentication
PubkeyAuthentication yes

# Disable root login
PermitRootLogin no

# Allow specific user
AllowUsers sabawi
```

After changing config:
```bash
sudo systemctl restart sshd
```

## Deployment Workflows

### Development/Testing
```bash
#!/bin/bash
export DEPLOYMENT_SSH_HOST="192.168.1.58"
export DEPLOYMENT_SSH_USER="sabawi"
export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/id_ed25519"

python examples/full_deployment_demo.py \
    --save-responses dev_cache.json \
    --auto-input examples/raica_input.json
```

### Production Deployment
```bash
#!/bin/bash
set -e  # Exit on error

export DEPLOYMENT_SSH_HOST="production.example.com"
export DEPLOYMENT_SSH_USER="deployer"
export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/production_deploy_key"

# Use cached responses for faster deployment
python examples/full_deployment_demo.py \
    --replay-responses production_cache.json \
    --auto-input examples/production_input.json
```

### CI/CD Pipeline
```yaml
# .github/workflows/deploy.yml
name: Deploy to Server

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup SSH Key
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.DEPLOYMENT_SSH_KEY }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key

      - name: Deploy
        env:
          DEPLOYMENT_SSH_HOST: ${{ secrets.DEPLOYMENT_HOST }}
          DEPLOYMENT_SSH_USER: ${{ secrets.DEPLOYMENT_USER }}
          DEPLOYMENT_SSH_KEY_PATH: ~/.ssh/deploy_key
        run: |
          python examples/full_deployment_demo.py \
            --auto-input examples/production_input.json
```

## Summary

**DO:** Use SSH key authentication via environment variables
**DON'T:** Use `--ssh-host-user` with password (fails on secure servers)

**Quick Setup:**
```bash
# 1. Generate key (if needed)
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519

# 2. Copy to server
ssh-copy-id -i ~/.ssh/id_ed25519.pub sabawi@192.168.1.58

# 3. Set environment
export DEPLOYMENT_SSH_HOST="192.168.1.58"
export DEPLOYMENT_SSH_USER="sabawi"
export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/id_ed25519"

# 4. Deploy
python examples/full_deployment_demo.py --auto-input examples/raica_input.json
```

**Status:** ✅ Tested and working with SSH key authentication
