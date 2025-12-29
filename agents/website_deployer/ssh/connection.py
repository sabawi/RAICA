#!/usr/bin/env python3
"""
SSH Connection Manager for Website Deployer Agent
==================================================

Secure SSH connection handling with key-based authentication.

Features:
- SSH key-based authentication only (no passwords)
- Connection pooling
- Automatic reconnection
- Connection validation
- Environment variable configuration

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import paramiko
from paramiko import SSHClient, AutoAddPolicy

logger = logging.getLogger(__name__)


@dataclass
class SSHCredentials:
    """SSH connection credentials."""
    host: str
    port: int = 22
    user: str = "root"
    ssh_key_path: Optional[str] = None
    ssh_key_passphrase: Optional[str] = None
    password: Optional[str] = None  # Password authentication (alternative to key)
    timeout: int = 10

    @classmethod
    def from_env(cls) -> "SSHCredentials":
        """
        Load SSH credentials from environment variables.

        Required environment variables:
        - DEPLOYMENT_SSH_HOST: Target server hostname or IP
        - DEPLOYMENT_SSH_USER: SSH username
        - DEPLOYMENT_SSH_KEY_PATH: Path to SSH private key

        Optional environment variables:
        - DEPLOYMENT_SSH_PORT: SSH port (default: 22)
        - DEPLOYMENT_SSH_KEY_PASSPHRASE: SSH key passphrase (if encrypted)
        - DEPLOYMENT_SSH_TIMEOUT: Connection timeout (default: 10)

        Returns:
            SSHCredentials instance

        Raises:
            ValueError: If required environment variables are missing
        """
        host = os.getenv("DEPLOYMENT_SSH_HOST")
        user = os.getenv("DEPLOYMENT_SSH_USER")
        ssh_key_path = os.getenv("DEPLOYMENT_SSH_KEY_PATH")

        if not host:
            raise ValueError("DEPLOYMENT_SSH_HOST environment variable not set")
        if not user:
            raise ValueError("DEPLOYMENT_SSH_USER environment variable not set")
        if not ssh_key_path:
            raise ValueError("DEPLOYMENT_SSH_KEY_PATH environment variable not set")

        # Validate SSH key exists
        key_path = Path(ssh_key_path).expanduser()
        if not key_path.exists():
            raise ValueError(f"SSH key not found: {key_path}")

        port = int(os.getenv("DEPLOYMENT_SSH_PORT", "22"))
        timeout = int(os.getenv("DEPLOYMENT_SSH_TIMEOUT", "10"))
        passphrase = os.getenv("DEPLOYMENT_SSH_KEY_PASSPHRASE")

        return cls(
            host=host,
            port=port,
            user=user,
            ssh_key_path=str(key_path),
            ssh_key_passphrase=passphrase,
            timeout=timeout
        )


class SSHConnectionManager:
    """
    Manages SSH connections with automatic reconnection and validation.

    Features:
    - Key-based authentication only
    - Connection validation
    - Automatic reconnection on failure
    - Connection pooling (single connection per instance)
    - Proper resource cleanup
    """

    def __init__(self, credentials: SSHCredentials):
        """
        Initialize SSH connection manager.

        Args:
            credentials: SSH connection credentials
        """
        self.credentials = credentials
        self._client: Optional[SSHClient] = None
        self._connected = False

        logger.info(f"SSH Connection Manager initialized for {credentials.user}@{credentials.host}")

    def connect(self) -> SSHClient:
        """
        Establish SSH connection.

        Returns:
            Connected SSHClient instance

        Raises:
            ConnectionError: If connection fails
        """
        if self._connected and self._client:
            # Check if connection is still alive
            if self._is_connection_alive():
                logger.debug("Reusing existing SSH connection")
                return self._client
            else:
                logger.warning("Existing connection is dead, reconnecting...")
                self.disconnect()

        try:
            logger.info(f"Connecting to {self.credentials.user}@{self.credentials.host}:{self.credentials.port}")

            # Create new SSH client
            self._client = SSHClient()

            # Auto-add host keys (in production, should verify known_hosts)
            self._client.set_missing_host_key_policy(AutoAddPolicy())

            # Connect using password OR SSH key
            if self.credentials.password:
                # Password authentication
                logger.info("Using password authentication")
                self._client.connect(
                    hostname=self.credentials.host,
                    port=self.credentials.port,
                    username=self.credentials.user,
                    password=self.credentials.password,
                    timeout=self.credentials.timeout,
                    look_for_keys=False,
                    allow_agent=False
                )
            else:
                # SSH key authentication
                logger.info("Using SSH key authentication")
                self._client.connect(
                    hostname=self.credentials.host,
                    port=self.credentials.port,
                    username=self.credentials.user,
                    key_filename=self.credentials.ssh_key_path,
                    passphrase=self.credentials.ssh_key_passphrase,
                    timeout=self.credentials.timeout,
                    look_for_keys=True,   # Allow Paramiko to find keys
                    allow_agent=True      # Allow SSH agent for encrypted keys
                )

            self._connected = True
            logger.info(f"✅ SSH connection established to {self.credentials.host}")

            # Validate connection with test command
            if not self._validate_connection():
                raise ConnectionError("Connection validation failed")

            return self._client

        except paramiko.PasswordRequiredException:
            # SSH key is encrypted but no passphrase provided
            logger.warning("SSH key is encrypted and requires a passphrase")

            # Prompt user for passphrase
            import getpass
            passphrase = getpass.getpass("Enter passphrase for SSH key: ")

            # Retry connection with passphrase
            try:
                self._client.connect(
                    hostname=self.credentials.host,
                    port=self.credentials.port,
                    username=self.credentials.user,
                    key_filename=self.credentials.ssh_key_path,
                    passphrase=passphrase,
                    timeout=self.credentials.timeout,
                    look_for_keys=False,
                    allow_agent=False
                )

                self._connected = True
                logger.info(f"✅ SSH connection established to {self.credentials.host}")

                if not self._validate_connection():
                    raise ConnectionError("Connection validation failed")

                # Store passphrase for future reconnections
                self.credentials.ssh_key_passphrase = passphrase

                return self._client

            except Exception as e:
                logger.error(f"❌ SSH authentication failed with passphrase: {e}")
                raise ConnectionError(f"SSH authentication failed: Invalid passphrase or key")

        except paramiko.AuthenticationException as e:
            logger.error(f"❌ SSH authentication failed: {e}")
            raise ConnectionError(f"SSH authentication failed: {e}")

        except paramiko.SSHException as e:
            logger.error(f"❌ SSH connection error: {e}")
            raise ConnectionError(f"SSH connection error: {e}")

        except Exception as e:
            logger.error(f"❌ Unexpected error during SSH connection: {e}")
            raise ConnectionError(f"Failed to connect to SSH server: {e}")

    def disconnect(self):
        """Close SSH connection and cleanup resources."""
        if self._client:
            try:
                self._client.close()
                logger.info("SSH connection closed")
            except Exception as e:
                logger.warning(f"Error closing SSH connection: {e}")
            finally:
                self._client = None
                self._connected = False

    def _is_connection_alive(self) -> bool:
        """
        Check if SSH connection is still alive.

        Returns:
            True if connection is alive, False otherwise
        """
        if not self._client:
            return False

        try:
            transport = self._client.get_transport()
            if transport is None or not transport.is_active():
                return False

            # Send keepalive packet
            transport.send_ignore()
            return True

        except Exception as e:
            logger.debug(f"Connection alive check failed: {e}")
            return False

    def _validate_connection(self) -> bool:
        """
        Validate SSH connection with test command.

        Returns:
            True if validation successful, False otherwise
        """
        try:
            logger.debug("Validating SSH connection...")

            stdin, stdout, stderr = self._client.exec_command("echo 'SSH_CONNECTION_TEST'")
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8').strip()

            if exit_code == 0 and output == "SSH_CONNECTION_TEST":
                logger.debug("✅ SSH connection validated")
                return True
            else:
                logger.error(f"❌ SSH validation failed: exit_code={exit_code}, output={output}")
                return False

        except Exception as e:
            logger.error(f"❌ SSH connection validation error: {e}")
            return False

    def test_sudo_access(self) -> bool:
        """
        Test if user has sudo access without password.

        Returns:
            True if sudo access available, False otherwise
        """
        try:
            logger.info("Testing sudo access...")

            stdin, stdout, stderr = self._client.exec_command("sudo -n true")
            exit_code = stdout.channel.recv_exit_status()

            if exit_code == 0:
                logger.info("✅ Sudo access confirmed")
                return True
            else:
                logger.warning("❌ Sudo access not available or requires password")
                logger.warning("Ensure user has passwordless sudo configured:")
                logger.warning(f"  {self.credentials.user} ALL=(ALL) NOPASSWD:ALL")
                return False

        except Exception as e:
            logger.error(f"❌ Error testing sudo access: {e}")
            return False

    def get_client(self) -> SSHClient:
        """
        Get connected SSH client.

        Returns:
            SSHClient instance

        Raises:
            ConnectionError: If not connected
        """
        if not self._connected or not self._client:
            raise ConnectionError("Not connected. Call connect() first.")

        # Verify connection is still alive
        if not self._is_connection_alive():
            logger.warning("Connection lost, reconnecting...")
            return self.connect()

        return self._client

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

    def __del__(self):
        """Cleanup on deletion."""
        self.disconnect()
