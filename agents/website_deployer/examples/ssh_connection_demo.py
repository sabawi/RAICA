#!/usr/bin/env python3
"""
SSH Connection Demo
===================

Demonstrates basic SSH connection functionality:
- Loading credentials from environment variables
- Connecting to remote server
- Testing connection
- Testing sudo access

Usage:
    export DEPLOYMENT_SSH_HOST="192.168.1.100"
    export DEPLOYMENT_SSH_USER="deployer"
    export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/deployment_key"

    python examples/ssh_connection_demo.py

Author: RAICA Development Team
Version: 1.0.0
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ssh import SSHConnectionManager, SSHCredentials


def main():
    """Demonstrate SSH connection."""
    print("=" * 80)
    print("SSH CONNECTION DEMO")
    print("=" * 80)
    print()

    # Load credentials from environment
    print("Loading credentials from environment...")
    try:
        credentials = SSHCredentials.from_env()
        print(f"✅ Credentials loaded")
        print(f"   Host: {credentials.host}")
        print(f"   User: {credentials.user}")
        print(f"   Port: {credentials.port}")
        print(f"   Key Path: {credentials.ssh_key_path}")
    except ValueError as e:
        print(f"❌ Failed to load credentials: {e}")
        print()
        print("Required environment variables:")
        print("  DEPLOYMENT_SSH_HOST")
        print("  DEPLOYMENT_SSH_USER")
        print("  DEPLOYMENT_SSH_KEY_PATH")
        return

    print()
    input("Press Enter to test connection...")

    # Connect to server
    print("\nConnecting to server...")
    try:
        with SSHConnectionManager(credentials) as manager:
            print("✅ Connected successfully!")

            # Get SSH client
            client = manager.get_client()
            print(f"   Connection status: Active")

            # Test basic command
            print("\nTesting basic command (hostname)...")
            stdin, stdout, stderr = client.exec_command("hostname")
            hostname = stdout.read().decode().strip()
            print(f"✅ Remote hostname: {hostname}")

            # Test sudo access
            print("\nTesting sudo access...")
            has_sudo = manager.test_sudo_access()
            if has_sudo:
                print("✅ Sudo access available")
            else:
                print("❌ Sudo access not available")
                print("   Configure passwordless sudo for deployment user")

            # Get system information
            print("\nGetting system information...")

            # OS version
            stdin, stdout, stderr = client.exec_command("cat /etc/os-release | grep PRETTY_NAME")
            os_version = stdout.read().decode().strip().split('=')[1].strip('"')
            print(f"   OS: {os_version}")

            # Disk space
            stdin, stdout, stderr = client.exec_command("df -h / | tail -1 | awk '{print $4}'")
            disk_free = stdout.read().decode().strip()
            print(f"   Disk Free: {disk_free}")

            # Memory
            stdin, stdout, stderr = client.exec_command("free -h | grep Mem | awk '{print $4}'")
            mem_free = stdout.read().decode().strip()
            print(f"   Memory Free: {mem_free}")

            print("\n" + "=" * 80)
            print("✅ CONNECTION TEST SUCCESSFUL")
            print("=" * 80)
            print()
            print("Your server is ready for deployment!")

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
