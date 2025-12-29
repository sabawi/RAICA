#!/usr/bin/env python3
"""Web Server Detector - Detect which web server is already installed/running"""

import logging
from typing import Optional, Dict, Any
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class WebServerDetector:
    """Detects which web server (Nginx or Apache2) is installed/running on the system."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def detect(self) -> Dict[str, Any]:
        """
        Detect web server on remote system.

        Returns:
            Dict with:
            - server: "apache2", "nginx", "both", or "none"
            - apache2_installed: bool
            - apache2_running: bool
            - apache2_enabled: bool
            - nginx_installed: bool
            - nginx_running: bool
            - nginx_enabled: bool
            - recommendation: str (which one to use)
        """
        try:
            logger.info("Detecting web server configuration...")

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            result = {
                "server": "none",
                "apache2_installed": False,
                "apache2_running": False,
                "apache2_enabled": False,
                "apache2_version": None,
                "nginx_installed": False,
                "nginx_running": False,
                "nginx_enabled": False,
                "nginx_version": None,
                "recommendation": None,
                "port_80_used_by": None
            }

            # Check Apache2
            apache_check = self._check_apache2(executor)
            result.update(apache_check)

            # Check Nginx
            nginx_check = self._check_nginx(executor)
            result.update(nginx_check)

            # Check what's using port 80
            port_check = self._check_port_80(executor)
            result["port_80_used_by"] = port_check

            # Determine recommendation
            result["recommendation"] = self._recommend_server(result)
            result["server"] = result["recommendation"]

            # Log findings
            logger.info("=" * 60)
            logger.info("WEB SERVER DETECTION RESULTS")
            logger.info("=" * 60)
            logger.info(f"Apache2: {'✅ Installed' if result['apache2_installed'] else '❌ Not installed'}")
            if result['apache2_installed']:
                logger.info(f"  - Running: {'✅ Yes' if result['apache2_running'] else '❌ No'}")
                logger.info(f"  - Enabled: {'✅ Yes' if result['apache2_enabled'] else '❌ No'}")
                if result['apache2_version']:
                    logger.info(f"  - Version: {result['apache2_version']}")

            logger.info(f"Nginx: {'✅ Installed' if result['nginx_installed'] else '❌ Not installed'}")
            if result['nginx_installed']:
                logger.info(f"  - Running: {'✅ Yes' if result['nginx_running'] else '❌ No'}")
                logger.info(f"  - Enabled: {'✅ Yes' if result['nginx_enabled'] else '❌ No'}")
                if result['nginx_version']:
                    logger.info(f"  - Version: {result['nginx_version']}")

            logger.info(f"\nPort 80 Status: {result['port_80_used_by'] or 'Available'}")
            logger.info(f"Recommendation: Use {result['recommendation'].upper()}")
            logger.info("=" * 60)

            return result

        except Exception as e:
            logger.error(f"Error detecting web server: {e}")
            return {
                "server": "nginx",  # Default fallback
                "recommendation": "nginx",
                "error": str(e)
            }

    def _check_apache2(self, executor) -> Dict[str, Any]:
        """Check Apache2 installation and status."""
        result = {
            "apache2_installed": False,
            "apache2_running": False,
            "apache2_enabled": False,
            "apache2_version": None
        }

        # Check if installed
        cmd = SSHCommand(
            command="which apache2 >/dev/null 2>&1 && echo 'INSTALLED' || echo 'NOT_INSTALLED'",
            description="Check Apache2 installation"
        )
        check = executor.execute(cmd, user_approval=True)
        result["apache2_installed"] = "INSTALLED" in check.stdout

        if not result["apache2_installed"]:
            # Try alternative command
            cmd = SSHCommand(
                command="which httpd >/dev/null 2>&1 && echo 'INSTALLED' || echo 'NOT_INSTALLED'",
                description="Check httpd installation"
            )
            check = executor.execute(cmd, user_approval=True)
            result["apache2_installed"] = "INSTALLED" in check.stdout

        if result["apache2_installed"]:
            # Get version
            cmd = SSHCommand(
                command="apache2 -v 2>/dev/null | head -1 || httpd -v 2>/dev/null | head -1",
                description="Get Apache version"
            )
            check = executor.execute(cmd, user_approval=True)
            if check.success:
                result["apache2_version"] = check.stdout.strip()

            # Check if running
            cmd = SSHCommand(
                command="systemctl is-active apache2 2>/dev/null || systemctl is-active httpd 2>/dev/null",
                description="Check Apache2 status"
            )
            check = executor.execute(cmd, user_approval=True)
            result["apache2_running"] = "active" in check.stdout

            # Check if enabled
            cmd = SSHCommand(
                command="systemctl is-enabled apache2 2>/dev/null || systemctl is-enabled httpd 2>/dev/null",
                description="Check Apache2 enabled"
            )
            check = executor.execute(cmd, user_approval=True)
            result["apache2_enabled"] = "enabled" in check.stdout

        return result

    def _check_nginx(self, executor) -> Dict[str, Any]:
        """Check Nginx installation and status."""
        result = {
            "nginx_installed": False,
            "nginx_running": False,
            "nginx_enabled": False,
            "nginx_version": None
        }

        # Check if installed
        cmd = SSHCommand(
            command="which nginx >/dev/null 2>&1 && echo 'INSTALLED' || echo 'NOT_INSTALLED'",
            description="Check Nginx installation"
        )
        check = executor.execute(cmd, user_approval=True)
        result["nginx_installed"] = "INSTALLED" in check.stdout

        if result["nginx_installed"]:
            # Get version
            cmd = SSHCommand(
                command="nginx -v 2>&1 | head -1",
                description="Get Nginx version"
            )
            check = executor.execute(cmd, user_approval=True)
            if check.success:
                result["nginx_version"] = check.stdout.strip() or check.stderr.strip()

            # Check if running
            cmd = SSHCommand(
                command="systemctl is-active nginx 2>/dev/null",
                description="Check Nginx status"
            )
            check = executor.execute(cmd, user_approval=True)
            result["nginx_running"] = "active" in check.stdout

            # Check if enabled
            cmd = SSHCommand(
                command="systemctl is-enabled nginx 2>/dev/null",
                description="Check Nginx enabled"
            )
            check = executor.execute(cmd, user_approval=True)
            result["nginx_enabled"] = "enabled" in check.stdout

        return result

    def _check_port_80(self, executor) -> Optional[str]:
        """Check what's using port 80."""
        cmd = SSHCommand(
            command="ss -tlnp | grep ':80 ' | head -1",
            description="Check port 80 usage"
        )
        result = executor.execute(cmd, user_approval=True)

        if result.success and result.stdout:
            output = result.stdout.lower()
            if "apache" in output or "httpd" in output:
                return "apache2"
            elif "nginx" in output:
                return "nginx"
            else:
                return "unknown"
        return None

    def _recommend_server(self, detection: Dict[str, Any]) -> str:
        """
        Recommend which web server to use based on detection.

        Priority:
        1. Use whichever is currently running
        2. Use whichever is enabled (for auto-start)
        3. Use whichever is installed
        4. Default to nginx if nothing is installed
        """
        # If Apache2 is running, use it
        if detection["apache2_running"]:
            logger.info("💡 Apache2 is currently running - will use Apache2")
            return "apache2"

        # If Nginx is running, use it
        if detection["nginx_running"]:
            logger.info("💡 Nginx is currently running - will use Nginx")
            return "nginx"

        # If Apache2 is enabled (will run on boot), use it
        if detection["apache2_enabled"]:
            logger.info("💡 Apache2 is enabled on system - will use Apache2")
            return "apache2"

        # If Nginx is enabled, use it
        if detection["nginx_enabled"]:
            logger.info("💡 Nginx is enabled on system - will use Nginx")
            return "nginx"

        # If Apache2 is installed, prefer it (better for existing HTTPS setups)
        if detection["apache2_installed"]:
            logger.info("💡 Apache2 is installed - will use Apache2")
            return "apache2"

        # If Nginx is installed, use it
        if detection["nginx_installed"]:
            logger.info("💡 Nginx is installed - will use Nginx")
            return "nginx"

        # Default to nginx for new installations
        logger.info("💡 No web server detected - will use Nginx (default)")
        return "nginx"
