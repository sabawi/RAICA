#!/usr/bin/env python3
"""Deployment Verifier - Verify deployed application is working correctly"""

import logging
from typing import Dict, Any, List, Tuple
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class DeploymentVerifier:
    """Verifies deployment health and provides detailed status report."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def verify(self, project_name: str, architecture: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Verify deployment is healthy.

        Args:
            project_name: Project name
            architecture: Architecture configuration

        Returns:
            Tuple of (success, verification_report)
        """
        try:
            logger.info("=" * 60)
            logger.info("DEPLOYMENT VERIFICATION")
            logger.info("=" * 60)

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            report = {
                "project_name": project_name,
                "checks": {},
                "warnings": [],
                "errors": []
            }

            # Determine web server type from architecture
            web_server = architecture.get("web_server", "nginx")

            # Check 1: Application directory exists
            logger.info("\n[1/8] Checking application directory...")
            check = self._check_directory(executor, f"/var/www/{project_name}")
            report["checks"]["application_directory"] = check
            self._log_check("Application Directory", check)

            # Check 2: Main application file exists
            logger.info("\n[2/8] Checking application files...")
            check = self._check_application_files(executor, project_name)
            report["checks"]["application_files"] = check
            self._log_check("Application Files", check)

            # Check 3: Virtual environment
            logger.info("\n[3/8] Checking Python virtual environment...")
            check = self._check_venv(executor, project_name)
            report["checks"]["virtual_environment"] = check
            self._log_check("Virtual Environment", check)

            # Check 4: Systemd service
            logger.info("\n[4/8] Checking systemd service...")
            check = self._check_service(executor, project_name)
            report["checks"]["systemd_service"] = check
            self._log_check("Systemd Service", check)

            # Check 5: Application port
            logger.info("\n[5/8] Checking application port (8000)...")
            check = self._check_port(executor, "8000")
            report["checks"]["application_port"] = check
            self._log_check("Application Port", check)

            # Check 6: Web server (Nginx or Apache)
            logger.info(f"\n[6/8] Checking {web_server.title()} web server...")
            check = self._check_web_server(executor, web_server)
            report["checks"]["web_server"] = check
            self._log_check(f"{web_server.title()} Web Server", check)

            # Check 7: Web server configuration
            logger.info(f"\n[7/8] Checking {web_server.title()} configuration...")
            check = self._check_web_server_config(executor, web_server, project_name)
            report["checks"]["web_server_config"] = check
            self._log_check(f"{web_server.title()} Configuration", check)

            # Check 8: Application response
            logger.info("\n[8/8] Testing application response...")
            check = self._check_application_response(executor)
            report["checks"]["application_response"] = check
            self._log_check("Application Response", check)

            # Generate summary
            logger.info("\n" + "=" * 60)
            logger.info("VERIFICATION SUMMARY")
            logger.info("=" * 60)

            passed = sum(1 for c in report["checks"].values() if c["status"] == "pass")
            failed = sum(1 for c in report["checks"].values() if c["status"] == "fail")
            warnings = sum(1 for c in report["checks"].values() if c["status"] == "warning")

            logger.info(f"✅ Passed: {passed}")
            logger.info(f"⚠️  Warnings: {warnings}")
            logger.info(f"❌ Failed: {failed}")

            # Overall success if no failures
            success = failed == 0

            if success:
                logger.info("\n✅ Deployment verification PASSED")
            else:
                logger.warning("\n⚠️  Deployment verification completed with issues")

            logger.info("=" * 60)

            return success, report

        except Exception as e:
            logger.error(f"❌ Verification failed: {e}")
            import traceback
            traceback.print_exc()
            return False, {"error": str(e)}

    def _check_directory(self, executor, path: str) -> Dict[str, Any]:
        """Check if directory exists."""
        cmd = SSHCommand(
            command=f"test -d {path} && echo 'EXISTS' || echo 'NOT_FOUND'",
            description=f"Check {path}"
        )
        result = executor.execute(cmd, user_approval=True)

        if result.success and 'EXISTS' in result.stdout:
            return {"status": "pass", "message": f"Directory exists: {path}"}
        else:
            return {"status": "fail", "message": f"Directory not found: {path}"}

    def _check_application_files(self, executor, project_name: str) -> Dict[str, Any]:
        """Check if main application file exists."""
        paths = [
            f"/var/www/{project_name}/main.py",
            f"/var/www/{project_name}/app/main.py",
            f"/var/www/{project_name}/app.py"
        ]

        for path in paths:
            cmd = SSHCommand(
                command=f"test -f {path} && echo 'EXISTS' || echo 'NOT_FOUND'",
                description=f"Check {path}"
            )
            result = executor.execute(cmd, user_approval=True)

            if result.success and 'EXISTS' in result.stdout:
                return {"status": "pass", "message": f"Application file found: {path}"}

        return {"status": "fail", "message": "No main application file found"}

    def _check_venv(self, executor, project_name: str) -> Dict[str, Any]:
        """Check if virtual environment exists and has packages."""
        cmd = SSHCommand(
            command=f"test -f /var/www/{project_name}/venv/bin/python && echo 'EXISTS' || echo 'NOT_FOUND'",
            description="Check venv"
        )
        result = executor.execute(cmd, user_approval=True)

        if result.success and 'EXISTS' in result.stdout:
            return {"status": "pass", "message": "Virtual environment exists"}
        else:
            return {"status": "fail", "message": "Virtual environment not found"}

    def _check_service(self, executor, project_name: str) -> Dict[str, Any]:
        """Check if systemd service is running."""
        cmd = SSHCommand(
            command=f"systemctl is-active {project_name} && echo 'ACTIVE' || echo 'INACTIVE'",
            description="Check service status"
        )
        result = executor.execute(cmd, user_approval=True)

        if 'ACTIVE' in result.stdout:
            return {"status": "pass", "message": f"Service {project_name} is running"}
        else:
            return {"status": "fail", "message": f"Service {project_name} is not running"}

    def _check_port(self, executor, port: str) -> Dict[str, Any]:
        """Check if application is listening on port."""
        cmd = SSHCommand(
            command=f"ss -tlnp | grep ':{port}' && echo 'LISTENING' || echo 'NOT_LISTENING'",
            description=f"Check port {port}"
        )
        result = executor.execute(cmd, user_approval=True)

        if 'LISTENING' in result.stdout:
            return {"status": "pass", "message": f"Application listening on port {port}"}
        else:
            return {"status": "warning", "message": f"No listener on port {port} (may still be starting)"}

    def _check_web_server(self, executor, web_server: str) -> Dict[str, Any]:
        """Check if web server is running."""
        service_name = "nginx" if web_server == "nginx" else "apache2"

        cmd = SSHCommand(
            command=f"systemctl is-active {service_name} && echo 'ACTIVE' || echo 'INACTIVE'",
            description=f"Check {service_name} status"
        )
        result = executor.execute(cmd, user_approval=True)

        if 'ACTIVE' in result.stdout:
            return {"status": "pass", "message": f"{service_name.title()} is running"}
        else:
            return {"status": "warning", "message": f"{service_name.title()} is not running"}

    def _check_web_server_config(self, executor, web_server: str, project_name: str) -> Dict[str, Any]:
        """Check if web server config exists."""
        if web_server == "nginx":
            paths = [
                f"/etc/nginx/sites-enabled/{project_name}",
                f"/etc/nginx/conf.d/{project_name}.conf"
            ]
        else:  # apache2
            paths = [
                f"/etc/apache2/sites-enabled/{project_name}.conf",
                f"/etc/apache2/conf-enabled/{project_name}.conf"
            ]

        for path in paths:
            cmd = SSHCommand(
                command=f"test -f {path} && echo 'EXISTS' || echo 'NOT_FOUND'",
                description=f"Check {path}"
            )
            result = executor.execute(cmd, user_approval=True)

            if result.success and 'EXISTS' in result.stdout:
                return {"status": "pass", "message": f"Config found: {path}"}

        return {"status": "warning", "message": f"No {web_server} config found (may need manual setup)"}

    def _check_application_response(self, executor) -> Dict[str, Any]:
        """Check if application responds to HTTP requests."""
        cmd = SSHCommand(
            command="curl -s -o /dev/null -w '%{http_code}' http://localhost:8000 2>/dev/null",
            description="Test application response"
        )
        result = executor.execute(cmd, user_approval=True)

        if result.success:
            status_code = result.stdout.strip()
            if status_code.startswith('2') or status_code.startswith('3'):
                return {"status": "pass", "message": f"Application responding (HTTP {status_code})"}
            elif status_code == '000':
                return {"status": "warning", "message": "Application not responding yet (may still be starting)"}
            else:
                return {"status": "warning", "message": f"Application returned HTTP {status_code}"}
        else:
            return {"status": "warning", "message": "Cannot test application response (curl may not be installed)"}

    def _log_check(self, name: str, check: Dict[str, Any]):
        """Log check result with appropriate emoji."""
        status = check["status"]
        message = check["message"]

        if status == "pass":
            logger.info(f"   ✅ {name}: {message}")
        elif status == "warning":
            logger.warning(f"   ⚠️  {name}: {message}")
        else:
            logger.error(f"   ❌ {name}: {message}")
