#!/usr/bin/env python3
"""
Safe Command Execution Demo
============================

Demonstrates safe command execution with the Website Deployment Agent:
- Command safety classification
- Safe command executor
- Audit logging
- Dry-run mode

Usage:
    export DEPLOYMENT_SSH_HOST="192.168.1.100"
    export DEPLOYMENT_SSH_USER="deployer"
    export DEPLOYMENT_SSH_KEY_PATH="~/.ssh/deployment_key"

    python examples/command_execution_demo.py

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import os
import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ssh import (
    SSHConnectionManager,
    SSHCredentials,
    SafeSSHExecutor,
    SSHCommand,
    CommandSafetyClassifier
)


def demo_safety_classification():
    """Demonstrate command safety classification."""
    print("=" * 80)
    print("COMMAND SAFETY CLASSIFICATION")
    print("=" * 80)
    print()

    test_commands = [
        "ls -la",
        "cat /etc/os-release",
        "df -h",
        "mkdir /tmp/test_deploy",
        "pip install fastapi",
        "git clone https://github.com/example/repo",
        "sudo apt update",
        "sudo systemctl restart nginx",
        "sudo -u postgres psql -c 'CREATE DATABASE test'",
        "rm -rf /tmp/test",
        "DROP DATABASE production",
    ]

    for cmd in test_commands:
        classification = CommandSafetyClassifier.classify(cmd)
        icon = {
            "READ_ONLY": "🟢",
            "SAFE": "🟡",
            "PRIVILEGED": "🟠",
            "DANGEROUS": "🔴"
        }.get(classification.safety_level.name, "❓")

        print(f"{icon} {classification.safety_level.name:12} | {cmd}")
        print(f"   Reason: {classification.reason}")
        print()


def demo_safe_executor_dry_run():
    """Demonstrate safe executor in dry-run mode (no actual execution)."""
    print("=" * 80)
    print("SAFE COMMAND EXECUTOR - DRY RUN MODE")
    print("=" * 80)
    print()
    print("This demonstrates command execution WITHOUT actually running commands.")
    print()

    # Load credentials
    try:
        credentials = SSHCredentials.from_env()
    except ValueError as e:
        print(f"❌ Failed to load credentials: {e}")
        return

    # Connect and execute in dry-run mode
    with SSHConnectionManager(credentials) as manager:
        client = manager.get_client()
        executor = SafeSSHExecutor(client, dry_run=True)

        # Define test commands
        commands = [
            SSHCommand(
                command="df -h",
                description="Check disk space"
            ),
            SSHCommand(
                command="free -h",
                description="Check memory"
            ),
            SSHCommand(
                command="mkdir -p /tmp/test_deploy",
                description="Create test directory"
            ),
            SSHCommand(
                command="sudo apt update",
                description="Update package lists"
            ),
        ]

        print("Executing commands in DRY RUN mode...")
        print()

        for cmd in commands:
            print(f"  → {cmd.description}")
            result = asyncio.run(executor.execute(cmd, user_approval=False))
            print(f"     Command: {cmd.command}")
            # Handle both string and enum safety_level
            safety_level = result.safety_level if isinstance(result.safety_level, str) else result.safety_level.name
            print(f"     Safety Level: {safety_level}")
            print()

        print("=" * 80)
        print("Execution Summary (DRY RUN)")
        print("=" * 80)
        executor.print_summary()


def demo_safe_executor_real():
    """Demonstrate safe executor with real command execution."""
    print("\n" + "=" * 80)
    print("SAFE COMMAND EXECUTOR - REAL EXECUTION")
    print("=" * 80)
    print()
    print("This will execute READ-ONLY commands on the server.")
    print()

    input("Press Enter to continue...")

    # Load credentials
    try:
        credentials = SSHCredentials.from_env()
    except ValueError as e:
        print(f"❌ Failed to load credentials: {e}")
        return

    # Connect and execute
    with SSHConnectionManager(credentials) as manager:
        client = manager.get_client()
        executor = SafeSSHExecutor(client, dry_run=False)

        # Define safe READ-ONLY commands
        commands = [
            SSHCommand(
                command="hostname",
                description="Get server hostname"
            ),
            SSHCommand(
                command="cat /etc/os-release",
                description="Get OS information"
            ),
            SSHCommand(
                command="df -h /",
                description="Check root filesystem space"
            ),
            SSHCommand(
                command="free -h",
                description="Check memory usage"
            ),
            SSHCommand(
                command="python3 --version",
                description="Check Python version"
            ),
        ]

        print("\nExecuting READ-ONLY commands...")
        print()

        for cmd in commands:
            result = asyncio.run(executor.execute(cmd, user_approval=False))

            if result.success:
                print(f"✅ {cmd.description}")
                if result.stdout:
                    # Print first line only
                    first_line = result.stdout.split('\n')[0]
                    print(f"   Output: {first_line}")
            else:
                print(f"❌ {cmd.description}")
                if result.stderr:
                    print(f"   Error: {result.stderr}")
                else:
                    print(f"   Command was rejected or failed (exit code: {result.exit_code})")

            print()

        print("=" * 80)
        print("Execution Summary")
        print("=" * 80)
        executor.print_summary()

        # Save audit log
        log_path = executor.save_audit_log()
        print(f"\n📝 Audit log saved: {log_path}")


def main():
    """Run all demos."""
    print("\n" + "=" * 80)
    print("SAFE COMMAND EXECUTION DEMO")
    print("=" * 80)
    print()

    try:
        # Demo 1: Safety Classification
        demo_safety_classification()

        # Demo 2: Dry Run
        print("\nDry run demo requires SSH credentials...")
        if os.getenv("DEPLOYMENT_SSH_HOST"):
            demo_safe_executor_dry_run()

            # Demo 3: Real Execution (READ-ONLY)
            demo_safe_executor_real()
        else:
            print("⚠️  Skipping - DEPLOYMENT_SSH_HOST not set")
            print("   Set environment variables to run full demo")

        print("\n" + "=" * 80)
        print("✅ DEMO COMPLETE")
        print("=" * 80)

    except KeyboardInterrupt:
        print("\n\n❌ Demo cancelled")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
