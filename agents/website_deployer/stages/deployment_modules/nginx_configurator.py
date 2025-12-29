#!/usr/bin/env python3
"""Nginx Configurator - Setup Nginx reverse proxy"""

import logging
from typing import Dict, Any, Optional
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class NginxConfigurator:
    """Configures Nginx reverse proxy."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def configure(self, project_name: str, domain: Optional[str], architecture: Dict[str, Any]) -> bool:
        """Configure Nginx."""

        try:
            server_name = domain if domain else "_"
            # Get port from architecture or default to 8000
            app_port = architecture.get("port", architecture.get("infrastructure", {}).get("port", 8000))

            # Create Nginx config
            config = f'''server {{
    listen 80;
    server_name {server_name};

    location / {{
        proxy_pass http://127.0.0.1:{app_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location /static {{
        alias /var/www/{project_name}/app/static;
    }}
}}
'''

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            commands = [
                SSHCommand(
                    command=f"echo '{config}' | sudo tee /etc/nginx/sites-available/{project_name}",
                    description="Create Nginx config"
                ),
                SSHCommand(
                    command=f"sudo ln -sf /etc/nginx/sites-available/{project_name} /etc/nginx/sites-enabled/",
                    description="Enable site"
                ),
                SSHCommand(
                    command="sudo nginx -t",
                    description="Test Nginx config"
                ),
            ]

            for command in commands:
                result = executor.execute(command, user_approval=True)
                if not result.success and "nginx -t" in command.command:
                    return False

            logger.info("✅ Nginx configured successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Nginx configuration failed: {e}")
            return False
