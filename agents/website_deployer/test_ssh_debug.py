#!/usr/bin/env python3
"""
Debug SSH connection issue with Paramiko
"""
import paramiko
import os
from pathlib import Path

def test_paramiko_connection():
    """Test direct Paramiko connection"""

    host = "192.168.1.58"
    user = "sabawi"
    ssh_key_path = str(Path("~/.ssh/id_ed25519").expanduser())

    print(f"Testing connection to {user}@{host}")
    print(f"SSH Key: {ssh_key_path}")
    print(f"Key exists: {Path(ssh_key_path).exists()}")
    print()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print("Attempting connection...")
        client.connect(
            hostname=host,
            port=22,
            username=user,
            key_filename=ssh_key_path,
            passphrase=None,
            timeout=10,
            look_for_keys=False,
            allow_agent=False
        )

        print("✅ Connection successful!")

        # Test command
        stdin, stdout, stderr = client.exec_command("echo 'Test command successful'")
        output = stdout.read().decode('utf-8').strip()
        print(f"Command output: {output}")

        client.close()
        return True

    except paramiko.PasswordRequiredException as e:
        print(f"❌ SSH key requires passphrase: {e}")
        return False
    except paramiko.AuthenticationException as e:
        print(f"❌ Authentication failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        client.close()

if __name__ == "__main__":
    success = test_paramiko_connection()
    exit(0 if success else 1)
