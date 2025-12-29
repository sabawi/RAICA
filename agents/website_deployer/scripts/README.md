# Deployment Scripts

Helper scripts for setting up and managing deployment hosts.

## setup_deployment_host.sh

Interactive script to set up a new deployment host with SSH key authentication and passwordless sudo.

### Usage

```bash
./scripts/setup_deployment_host.sh
```

### What It Does

1. **Gathers Information**
   - Prompts for hostname/IP, username, and SSH port
   - Validates configuration

2. **SSH Key Setup**
   - Generates new SSH key (Ed25519) or uses existing key
   - Default location: `~/.ssh/deployment_key`

3. **Host Key Management**
   - Removes old host keys if server was reinstalled
   - Accepts new host key automatically

4. **Key Distribution**
   - Copies public key to remote server
   - Tests key-based authentication

5. **Sudo Configuration**
   - Configures passwordless sudo for automated deployments
   - Creates `/etc/sudoers.d/<username>` file

6. **Environment Setup**
   - Adds deployment variables to `~/.bashrc`
   - Sets `DEPLOYMENT_SSH_HOST`, `DEPLOYMENT_SSH_USER`, etc.

7. **System Information**
   - Displays remote system details (OS, disk, memory)

8. **Connection Test**
   - Optionally runs the SSH connection demo

### Example Session

```
$ ./scripts/setup_deployment_host.sh

================================================================================
  DEPLOYMENT HOST SETUP
================================================================================

This script will set up SSH key authentication and passwordless sudo
for automated deployments to a remote server.

Press Enter to continue...

━━━ Step 1: Host Information ━━━

Enter the hostname or IP address: 192.168.1.100
Enter the SSH username: deployer
Enter the SSH port [default: 22]:

Configuration:
  Host: 192.168.1.100
  User: deployer
  Port: 22

Is this correct? (yes/no): yes

━━━ Step 2: SSH Key Setup ━━━

ℹ️  Generating new SSH key at /home/user/.ssh/deployment_key
✅ SSH key generated

━━━ Step 3: Checking SSH Host Key ━━━

✅ No existing host key found

━━━ Step 4: Testing Basic SSH Connection ━━━

Attempting to connect to deployer@192.168.1.100
You will be prompted for your password...

✅ Basic SSH connection works

━━━ Step 5: Copying SSH Key to Remote Host ━━━

You will be prompted for your password to copy the SSH key...

✅ SSH key copied successfully

━━━ Step 6: Testing Key-Based Authentication ━━━

✅ Key-based authentication works

━━━ Step 7: Configuring Passwordless Sudo ━━━

This step requires sudo access on the remote host.
You will be prompted for your password one more time...

✅ Passwordless sudo configured

━━━ Step 8: Testing Sudo Access ━━━

✅ Passwordless sudo works

━━━ Step 9: Setting Environment Variables ━━━

✅ Environment variables saved to /home/user/.bashrc

━━━ Step 10: System Information ━━━

Gathering remote system information...

Remote System:
  Hostname: prod-server
  OS: Ubuntu 24.04 LTS
  Disk Free: 450G
  Memory Free: 7.2Gi

================================================================================
  SETUP COMPLETE
================================================================================

✅ Deployment host configured successfully!

Connection Details:
  Host: 192.168.1.100
  User: deployer
  Port: 22
  Key:  /home/user/.ssh/deployment_key

Next Steps:
  1. Load environment variables:
     source /home/user/.bashrc

  2. Test the connection:
     cd examples
     python3 ssh_connection_demo.py

  3. Or run a deployment:
     python3 full_deployment_demo.py

Do you want to test the connection now? (yes/no): yes
```

### Requirements

- **Local Machine:**
  - Bash shell
  - SSH client (`ssh`, `ssh-keygen`, `ssh-copy-id`)
  - Network access to remote host

- **Remote Host:**
  - SSH server running
  - User account with sudo privileges
  - Network connectivity

### Troubleshooting

#### "Cannot connect to remote host"
- Verify hostname/IP is correct: `ping <hostname>`
- Check SSH server is running: `telnet <hostname> 22`
- Verify firewall allows SSH: `sudo ufw status`

#### "Failed to copy SSH key"
- Check username and password are correct
- Ensure SSH server allows password authentication
- Verify user's home directory exists

#### "Passwordless sudo not working"
- User needs sudo privileges
- Check `/etc/sudoers.d/<username>` file exists
- Verify file permissions: `ls -l /etc/sudoers.d/`

#### "Permission denied (publickey)"
- SSH key permissions: `chmod 600 ~/.ssh/deployment_key`
- Remote authorized_keys: `chmod 600 ~/.ssh/authorized_keys`
- Remote .ssh directory: `chmod 700 ~/.ssh/`

### Security Notes

1. **SSH Keys Without Passphrases**
   - Default: No passphrase for automation
   - For production: Add passphrase and use `ssh-agent`

2. **Passwordless Sudo**
   - Required for automated deployments
   - Limits exposure by using specific user account
   - Alternative: Use sudo with password prompts (manual)

3. **Host Key Verification**
   - Script accepts new host keys automatically
   - For maximum security: Verify fingerprint manually

### Advanced Usage

#### Use Existing SSH Key

```bash
# Script will detect and offer to use existing key
# Or specify a custom key path when prompted
```

#### Different SSH Port

```bash
# Enter custom port when prompted
# Default is 22
```

#### Multiple Deployment Hosts

```bash
# Run script for each host
# Use different key names (deployment_key_1, deployment_key_2, etc.)
```

#### Environment File Location

```bash
# Variables saved to ~/.bashrc by default
# Script offers to use separate file if conflicts exist
```

### Related Commands

```bash
# Manually test SSH connection
ssh -i ~/.ssh/deployment_key user@host

# Check remote sudo access
ssh -i ~/.ssh/deployment_key user@host "sudo -n whoami"

# View environment variables
grep DEPLOYMENT ~/.bashrc

# Remove host from known_hosts
ssh-keygen -f ~/.ssh/known_hosts -R <hostname>
```

### See Also

- [SSH Connection Demo](../examples/ssh_connection_demo.py)
- [Full Deployment Demo](../examples/full_deployment_demo.py)
- [Website Deployer Documentation](../README.md)
