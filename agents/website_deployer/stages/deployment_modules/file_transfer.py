#!/usr/bin/env python3
"""File Transfer Module - Transfer files to server via SFTP"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FileTransfer:
    """Transfers project files to server."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def transfer(self, local_dir: Path, remote_base: str, project_name: str) -> bool:
        """
        Transfer project files to server.

        Args:
            local_dir: Local project directory
            remote_base: Remote base path - full deployment path (e.g., /var/www/myproject)
            project_name: Project name (not used if remote_base is full path)

        Returns:
            True if successful
        """
        try:
            client = self.ssh_manager.get_client()
            sftp = client.open_sftp()

            # Use remote_base as the final destination directly
            # (deploy_path already includes the full target path)
            remote_path = remote_base

            logger.info(f"Transferring files to {remote_path}...")

            # Ensure base directory exists (create with sudo if needed)
            logger.info(f"Ensuring base directory exists: {remote_base}")
            stdin, stdout, stderr = client.exec_command(f"sudo mkdir -p {remote_base}")
            stdout.channel.recv_exit_status()  # Wait for command

            # Set proper permissions on base directory
            stdin, stdout, stderr = client.exec_command(f"sudo chown -R $USER:$USER {remote_base}")
            stdout.channel.recv_exit_status()

            # Create remote project directory recursively
            self._mkdir_p(sftp, remote_path)

            # Transfer files recursively
            self._transfer_directory(sftp, local_dir, remote_path)

            sftp.close()
            logger.info(f"✅ Files transferred successfully to {remote_path}")
            return True

        except Exception as e:
            logger.error(f"❌ File transfer failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _mkdir_p(self, sftp, remote_path: str):
        """
        Create directory recursively via SFTP (like mkdir -p).

        Args:
            sftp: SFTP client instance
            remote_path: Remote directory path to create
        """
        parts = remote_path.split('/')
        current = ''

        for part in parts:
            if not part:
                continue
            current = f"{current}/{part}" if current else f"/{part}"

            try:
                sftp.stat(current)
                logger.debug(f"  Directory exists: {current}")
            except FileNotFoundError:
                logger.debug(f"  Creating directory: {current}")
                sftp.mkdir(current)

    def _transfer_directory(self, sftp, local_dir: Path, remote_dir: str):
        """Recursively transfer directory."""
        for item in local_dir.iterdir():
            local_path = item
            remote_path = f"{remote_dir}/{item.name}"

            if item.is_file():
                logger.debug(f"  Transferring: {item.name}")
                sftp.put(str(local_path), remote_path)
            elif item.is_dir():
                try:
                    sftp.mkdir(remote_path)
                except:
                    pass
                self._transfer_directory(sftp, local_path, remote_path)
