#!/usr/bin/env python3
"""
Cleanup Failed Deployments on Remote Server
============================================

Lists and removes failed deployments from the remote server.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from ssh import SSHConnectionManager, SSHCredentials

def run_remote_command(ssh_manager, command):
    """Run a command on the remote server and return output."""
    client = ssh_manager.get_client()
    stdin, stdout, stderr = client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode('utf-8')
    error = stderr.read().decode('utf-8')

    return exit_code, output, error

def list_deployments(ssh_manager):
    """List all deployments in /var/www/ and /opt/deployments/."""
    print("\n" + "=" * 80)
    print("LISTING DEPLOYMENTS ON REMOTE SERVER")
    print("=" * 80)

    # Check /var/www/
    print("\n📁 Checking /var/www/:")
    exit_code, output, error = run_remote_command(ssh_manager, "ls -la /var/www/ 2>/dev/null || echo 'Directory not found'")
    print(output)

    # Check /opt/deployments/
    print("\n📁 Checking /opt/deployments/:")
    exit_code, output, error = run_remote_command(ssh_manager, "ls -la /opt/deployments/ 2>/dev/null || echo 'Directory not found'")
    print(output)

    # Check nginx sites
    print("\n📁 Checking nginx sites-available:")
    exit_code, output, error = run_remote_command(ssh_manager, "ls -la /etc/nginx/sites-available/ 2>/dev/null || echo 'Directory not found'")
    print(output)

    # Check systemd services
    print("\n📁 Checking systemd services (app-related):")
    exit_code, output, error = run_remote_command(ssh_manager, "sudo systemctl list-units --type=service --all | grep -E '(raica|app|website)' || echo 'No services found'")
    print(output)

def remove_deployment(ssh_manager, deployment_name, deployment_path):
    """Remove a specific deployment."""
    print(f"\n🗑️  Removing deployment: {deployment_name}")
    print(f"   Path: {deployment_path}")

    # Stop systemd service if exists
    service_name = deployment_name.lower().replace('_', '-')
    print(f"\n   Stopping service: {service_name}")
    exit_code, output, error = run_remote_command(ssh_manager, f"sudo systemctl stop {service_name} 2>/dev/null || echo 'Service not found'")
    print(f"   {output}")

    # Disable systemd service
    print(f"   Disabling service: {service_name}")
    exit_code, output, error = run_remote_command(ssh_manager, f"sudo systemctl disable {service_name} 2>/dev/null || echo 'Service not found'")
    print(f"   {output}")

    # Remove systemd service file
    print(f"   Removing service file: /etc/systemd/system/{service_name}.service")
    exit_code, output, error = run_remote_command(ssh_manager, f"sudo rm -f /etc/systemd/system/{service_name}.service")

    # Remove deployment directory
    print(f"   Removing deployment directory: {deployment_path}")
    exit_code, output, error = run_remote_command(ssh_manager, f"sudo rm -rf {deployment_path}")

    # Remove nginx config
    nginx_config = f"/etc/nginx/sites-available/{deployment_name}"
    nginx_enabled = f"/etc/nginx/sites-enabled/{deployment_name}"
    print(f"   Removing nginx config: {nginx_config}")
    exit_code, output, error = run_remote_command(ssh_manager, f"sudo rm -f {nginx_config} {nginx_enabled}")

    # Reload systemd and nginx
    print("   Reloading systemd daemon")
    run_remote_command(ssh_manager, "sudo systemctl daemon-reload")

    print("   Reloading nginx")
    run_remote_command(ssh_manager, "sudo systemctl reload nginx 2>/dev/null || echo 'Nginx not running'")

    print(f"   ✅ Deployment '{deployment_name}' removed")

def interactive_cleanup(ssh_manager):
    """Interactive cleanup of deployments."""
    while True:
        list_deployments(ssh_manager)

        print("\n" + "=" * 80)
        print("CLEANUP OPTIONS")
        print("=" * 80)
        print("Enter deployment name to remove (or 'q' to quit):")
        print("Example: raica, RAICA_1, etc.")
        print()

        choice = input("Deployment to remove (or 'q'): ").strip()

        if choice.lower() == 'q':
            print("\n✅ Cleanup complete")
            break

        if not choice:
            continue

        # Determine deployment path
        print("\nSelect deployment location:")
        print("1. /var/www/")
        print("2. /opt/deployments/")
        print("3. Custom path")

        location = input("Choose (1-3): ").strip()

        if location == '1':
            deployment_path = f"/var/www/{choice}"
        elif location == '2':
            deployment_path = f"/opt/deployments/{choice}"
        elif location == '3':
            deployment_path = input("Enter full path: ").strip()
        else:
            print("❌ Invalid choice")
            continue

        # Confirm removal
        confirm = input(f"\n⚠️  Remove '{choice}' at '{deployment_path}'? (yes/no): ").strip().lower()

        if confirm == 'yes':
            remove_deployment(ssh_manager, choice, deployment_path)
        else:
            print("❌ Cancelled")

def main():
    """Main cleanup function."""
    # Setup SSH credentials from environment
    import os

    password = os.getenv("DEPLOYMENT_SSH_PASSWORD")
    if not password:
        print("❌ ERROR: DEPLOYMENT_SSH_PASSWORD environment variable not set")
        return

    ssh_creds = SSHCredentials(
        host="192.168.1.58",
        user="sabawi",
        password=password,
        port=22,
        timeout=30
    )

    print("=" * 80)
    print("DEPLOYMENT CLEANUP UTILITY")
    print("=" * 80)
    print(f"Target: {ssh_creds.user}@{ssh_creds.host}")
    print()

    # Connect to SSH
    with SSHConnectionManager(ssh_creds) as ssh_manager:
        interactive_cleanup(ssh_manager)

if __name__ == "__main__":
    main()
