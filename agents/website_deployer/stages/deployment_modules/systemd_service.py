#!/usr/bin/env python3
"""Systemd Service - Create systemd services"""

import logging
from typing import Dict, Any
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class SystemdService:
    """Creates and manages systemd services."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def create(self, project_name: str, deploy_path: str, architecture: Dict[str, Any]) -> bool:
        """Create systemd service."""

        try:
            # Get port from architecture, default to 8000 if not specified
            app_port = architecture.get("port", 8000)

            service_content = f'''[Unit]
Description={project_name} FastAPI Application
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory={deploy_path}/{project_name}
Environment="PATH={deploy_path}/{project_name}/venv/bin"
ExecStart={deploy_path}/{project_name}/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port {app_port} --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
'''

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            commands = [
                SSHCommand(
                    command=f"echo '{service_content}' | sudo tee /etc/systemd/system/{project_name}.service",
                    description="Create systemd service file"
                ),
                SSHCommand(
                    command="sudo systemctl daemon-reload",
                    description="Reload systemd"
                ),
                SSHCommand(
                    command=f"sudo chown -R www-data:www-data {deploy_path}/{project_name}",
                    description="Set file permissions"
                ),
            ]

            for command in commands:
                result = executor.execute(command, user_approval=True)
                if not result.success:
                    return False

            logger.info("✅ Systemd service created successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Systemd service creation failed: {e}")
            return False
