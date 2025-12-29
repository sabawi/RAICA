#!/usr/bin/env python3
"""SSL Setup - Configure Let's Encrypt"""

import logging
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class SSLSetup:
    """Configures SSL with Let's Encrypt."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def setup(self, domain: str, project_name: str) -> bool:
        """Setup SSL certificate."""

        try:
            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            commands = [
                SSHCommand(
                    command="sudo apt install -y certbot python3-certbot-nginx",
                    description="Install certbot"
                ),
                SSHCommand(
                    command=f"sudo certbot --nginx -d {domain} --non-interactive --agree-tos --email admin@{domain}",
                    description="Obtain SSL certificate"
                ),
            ]

            for command in commands:
                result = executor.execute(command, user_approval=True)
                if not result.success:
                    logger.warning("SSL setup failed, continuing without HTTPS")
                    return False

            logger.info("✅ SSL configured successfully")
            return True

        except Exception as e:
            logger.error(f"❌ SSL setup failed: {e}")
            return False
