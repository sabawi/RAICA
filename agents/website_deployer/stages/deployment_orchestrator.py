#!/usr/bin/env python3
"""
Deployment Orchestrator for Website Deployer Agent
===================================================

Orchestrates complete deployment of generated code to production server.

Deployment Steps:
1. Transfer files to server
2. Install system packages (Python, PostgreSQL, Redis, Nginx)
3. Setup Python virtual environment
4. Install Python dependencies
5. Configure PostgreSQL database
6. Run database migrations
7. Configure Nginx with reverse proxy
8. Setup SSL with Let's Encrypt
9. Create systemd services
10. Start services and verify

Author: RAICA Development Team
Version: 1.0.0
"""

import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


@dataclass
class DeploymentResult:
    """Result of deployment."""
    success: bool
    deployment_url: Optional[str] = None
    steps_completed: Optional[List[str]] = None
    deployment_summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_step: Optional[str] = None


class DeploymentOrchestrator:
    """
    Orchestrates complete deployment to production server.

    Uses SSH infrastructure from Phase 1 to safely deploy
    generated code from Phase 4-5.
    """

    def __init__(self, ssh_manager):
        """
        Initialize deployment orchestrator.

        Args:
            ssh_manager: SSHConnectionManager instance
        """
        self.ssh_manager = ssh_manager
        self.steps_completed = []
        self.deployment_start_time = None

        logger.info("DeploymentOrchestrator initialized")

    def deploy(
        self,
        project_dir: Path,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any],
        domain: Optional[str] = None,
        deploy_path: str = "/var/www",
        deployment_config: Optional[Any] = None
    ) -> DeploymentResult:
        """
        Deploy application to server.
        """
        try:
            safe_project_name, domain, deploy_path = self._initial_setup(architecture, domain, deploy_path, deployment_config)

            self._configure_deployment(architecture, deployment_config, domain, deploy_path)

            self._transfer_and_install(project_dir, deploy_path, safe_project_name, architecture)

            self._language_specific_setup(architecture, deploy_path, safe_project_name)

            # Add deploy_path to architecture for web server configuration
            architecture["deploy_path"] = deploy_path

            # Preserve SSL settings from deployment_config if available
            if deployment_config:
                # SSL settings can be in two places:
                # 1. Top-level: deployment_config.ssl_cert_path / ssl_key_path (legacy)
                # 2. Nested: deployment_config.web_server['ssl_config']['cert_path'] / ['key_path'] (current)

                # Check nested location first (current approach)
                if isinstance(deployment_config.web_server, dict) and deployment_config.web_server.get('ssl_config'):
                    ssl_config = deployment_config.web_server['ssl_config']
                    architecture["ssl_cert_path"] = ssl_config.get('cert_path')
                    architecture["ssl_key_path"] = ssl_config.get('key_path')
                    architecture["use_ssl"] = deployment_config.web_server.get('ssl_enabled', False)
                    logger.info(f"🔍 DEBUG: Preserved SSL from deployment_config.web_server.ssl_config: use_ssl={architecture['use_ssl']}, cert={architecture.get('ssl_cert_path')}, key={architecture.get('ssl_key_path')}")
                # Fallback to legacy top-level fields
                elif hasattr(deployment_config, 'ssl_cert_path') and deployment_config.ssl_cert_path:
                    architecture["use_ssl"] = deployment_config.use_ssl
                    architecture["ssl_cert_path"] = deployment_config.ssl_cert_path
                    architecture["ssl_key_path"] = deployment_config.ssl_key_path
                    logger.info(f"🔍 DEBUG: Preserved SSL from deployment_config (legacy): use_ssl={deployment_config.use_ssl}, cert={deployment_config.ssl_cert_path}, key={deployment_config.ssl_key_path}")

            self._configure_web_server_and_ssl(architecture, safe_project_name, domain)

            self._create_and_start_services(architecture, safe_project_name, deploy_path, domain)

            return self._run_verification_and_summarize(safe_project_name, architecture, domain)

        except Exception as e:
            logger.error(f"❌ Deployment failed: {e}")
            import traceback
            traceback.print_exc()

            return DeploymentResult(
                success=False,
                error_message=str(e),
                error_step=self.steps_completed[-1] if self.steps_completed else "initialization",
                steps_completed=self.steps_completed
            )

    def _initial_setup(self, architecture, domain, deploy_path, deployment_config):
        self.deployment_start_time = datetime.now()
        project_name = architecture.get("project_name", "app")
        safe_project_name = project_name.replace(' ', '_').replace('&', 'and')

        logger.info("=" * 60)
        logger.info(f"DEPLOYMENT STARTED: {project_name}")
        logger.info(f"Safe project name: {safe_project_name}")
        logger.info("=" * 60)

        if deployment_config:
            if deployment_config.domain:
                domain = deployment_config.domain
            if deployment_config.deploy_path:
                deploy_path = deployment_config.deploy_path
        
        return safe_project_name, domain, deploy_path

    def _configure_deployment(self, architecture, deployment_config, domain, deploy_path):
        if deployment_config:
            logger.info("\n[0/10] Using provided deployment configuration...")

            # Handle web_server being either a dict or a string
            if isinstance(deployment_config.web_server, dict):
                architecture["web_server"] = deployment_config.web_server.get('type', 'nginx')
                architecture["port"] = deployment_config.web_server.get('port', 80)
                architecture["use_ssl"] = deployment_config.web_server.get('ssl_enabled', False)
            else:
                architecture["web_server"] = deployment_config.web_server
                architecture["port"] = deployment_config.port if deployment_config.port else 80
                architecture["use_ssl"] = deployment_config.use_ssl

            logger.info(f"✅ Web server: {architecture['web_server'].upper()}")
            logger.info(f"✅ Port: {architecture['port']}")
            logger.info(f"✅ SSL: {'Enabled' if architecture['use_ssl'] else 'Disabled'}")
            logger.info(f"🔍 DEBUG _configure_deployment: deployment_config.ssl_cert_path={deployment_config.ssl_cert_path}, ssl_key_path={deployment_config.ssl_key_path}")
            self.steps_completed.append("Configuration applied")
        else:
            logger.info("\n[0/10] Detecting installed web server...")
            from .deployment_modules import WebServerDetector
            detector = WebServerDetector(self.ssh_manager)
            web_server_info = detector.detect()
            architecture["web_server"] = web_server_info["recommendation"]
            logger.info(f"✅ Will use: {architecture['web_server'].upper()}")
            self.steps_completed.append("Web server detection")

    def _transfer_and_install(self, project_dir, deploy_path, safe_project_name, architecture):
        logger.info("\n[1/10] Transferring files to server...")
        from .deployment_modules import FileTransfer
        file_transfer = FileTransfer(self.ssh_manager)
        if not file_transfer.transfer(project_dir, deploy_path, safe_project_name):
            raise Exception("File transfer failed")
        self.steps_completed.append("File transfer")

        backend_lang = architecture.get("backend_language")
        if not backend_lang:
            backend_lang = "php" if architecture.get("web_server", "").lower() == "apache2" else "python"
        architecture["backend_language"] = backend_lang

        db_type = architecture.get("database_type")
        if not db_type:
            db_type = "sqlite"
        architecture["database_type"] = db_type

        logger.info("\n[2/10] Installing system packages...")
        from .deployment_modules import PackageInstaller
        package_installer = PackageInstaller(self.ssh_manager)
        if not package_installer.install(architecture):
            raise Exception("Package installation failed")
        self.steps_completed.append("System packages")

    def _language_specific_setup(self, architecture, deploy_path, safe_project_name):
        backend_lang = architecture["backend_language"]
        self._current_backend_lang = backend_lang

        if backend_lang == "python":
            self._setup_python_project(deploy_path, safe_project_name, architecture)
        elif backend_lang == "php":
            self._setup_php_project(deploy_path, safe_project_name)
        elif backend_lang == "nodejs":
            self._setup_nodejs_project(deploy_path, safe_project_name)

    def _setup_python_project(self, deploy_path, safe_project_name, architecture):
        logger.info("\n[3/10] Setting up Python virtual environment...")
        if not self._setup_virtualenv(deploy_path, safe_project_name):
            raise Exception("Virtual environment setup failed")
        self.steps_completed.append("Virtual environment")

        logger.info("\n[4/10] Installing Python dependencies...")
        if not self._install_python_dependencies(deploy_path, safe_project_name):
            raise Exception("Python dependency installation failed")
        self.steps_completed.append("Python dependencies")

        logger.info("\n[5/10] Configuring database...")
        from .deployment_modules import DatabaseSetup
        db_setup = DatabaseSetup(self.ssh_manager)
        if not db_setup.configure(safe_project_name, architecture):
            raise Exception("Database configuration failed")
        self.steps_completed.append("Database configuration")

        logger.info("\n[6/10] Running database migrations...")
        if not self._run_migrations(deploy_path, safe_project_name):
            raise Exception("Database migrations failed")
        self.steps_completed.append("Database migrations")

    def _setup_php_project(self, deploy_path, safe_project_name):
        logger.info("\n[3/10] Installing PHP dependencies...")
        if not self._install_php_dependencies(deploy_path, safe_project_name):
            raise Exception("PHP dependency installation failed")
        self.steps_completed.append("PHP dependencies")
        logger.info("\n[4-6/10] Skipping Python/DB steps for PHP...")
        self.steps_completed.append("Skipped Python setup")

    def _setup_nodejs_project(self, deploy_path, safe_project_name):
        logger.info("\n[3/10] Installing Node.js dependencies...")
        if not self._install_nodejs_dependencies(deploy_path, safe_project_name):
            raise Exception("Node.js dependency installation failed")
        self.steps_completed.append("Node.js dependencies")
        logger.info("\n[4-6/10] Skipping Python/DB steps for Node.js...")
        self.steps_completed.append("Skipped Python/DB setup")

    def _configure_web_server_and_ssl(self, architecture, safe_project_name, domain):
        web_server = architecture.get("web_server", "nginx")
        logger.info(f"\n[7/10] Configuring {web_server.upper()}...")
        
        web_config = None
        if web_server == "apache2":
            from .deployment_modules import ApacheConfigurator
            web_config = ApacheConfigurator(self.ssh_manager)
        else:
            from .deployment_modules import NginxConfigurator
            web_config = NginxConfigurator(self.ssh_manager)

        if not web_config.configure(safe_project_name, domain, architecture):
            raise Exception(f"{web_server.capitalize()} configuration failed")
        self.steps_completed.append(f"{web_server.capitalize()} configuration")

        if domain:
            logger.info("\n[8/10] Setting up SSL with Let's Encrypt...")
            from .deployment_modules import SSLSetup
            ssl_setup = SSLSetup(self.ssh_manager)
            if not ssl_setup.setup(domain, safe_project_name):
                logger.warning("SSL setup failed, continuing without HTTPS")
            else:
                self.steps_completed.append("SSL certificate")
        else:
            logger.info("\n[8/10] Skipping SSL setup (no domain provided)")

    def _create_and_start_services(self, architecture, safe_project_name, deploy_path, domain):
        backend_lang = architecture["backend_language"]
        if backend_lang != "php":
            logger.info("\n[9/10] Creating systemd service...")
            from .deployment_modules import SystemdService
            systemd_service = SystemdService(self.ssh_manager)
            if not systemd_service.create(safe_project_name, deploy_path, architecture):
                raise Exception("Systemd service creation failed")
            self.steps_completed.append("Systemd service")
        else:
            logger.info("\n[9/10] Skipping systemd service creation for PHP deployment")
            self.steps_completed.append("Skipped systemd service (PHP)")

        logger.info("\n[10/10] Starting services and verifying deployment...")
        web_server = architecture.get("web_server", "nginx")
        if not self._start_and_verify(safe_project_name, domain, web_server):
            raise Exception("Service startup or verification failed")
        self.steps_completed.append("Service startup")

    def _run_verification_and_summarize(self, safe_project_name, architecture, domain):
        logger.info("\n" + "=" * 60)
        logger.info("RUNNING DEPLOYMENT VERIFICATION")
        logger.info("=" * 60)

        from .deployment_modules import DeploymentVerifier
        verifier = DeploymentVerifier(self.ssh_manager)
        verification_success, verification_report = verifier.verify(safe_project_name, architecture)

        deployment_url = self._get_deployment_url(domain, architecture)
        summary = self._generate_summary(safe_project_name, deployment_url, self.steps_completed)
        summary["verification_report"] = verification_report
        summary["verification_passed"] = verification_success

        logger.info("\n" + "=" * 60)
        logger.info(f"DEPLOYMENT COMPLETE: {safe_project_name}")
        logger.info("=" * 60)

        self._print_summary(summary)

        return DeploymentResult(
            success=True,
            deployment_url=deployment_url,
            steps_completed=self.steps_completed,
            deployment_summary=summary
        )

    def _setup_virtualenv(self, deploy_path: str, project_name: str) -> bool:
        """Setup Python virtual environment."""
        commands = [
            SSHCommand(
                command=f"cd {deploy_path}/{project_name} && python3 -m venv venv",
                description="Create virtual environment"
            ),
        ]

        return self._execute_commands(commands)

    def _install_python_dependencies(self, deploy_path: str, project_name: str) -> bool:
        """Install Python dependencies from requirements.txt."""
        commands = [
            SSHCommand(
                command=f"cd {deploy_path}/{project_name} && venv/bin/pip install --upgrade pip",
                description="Upgrade pip"
            ),
            SSHCommand(
                command=f"cd {deploy_path}/{project_name} && venv/bin/pip install -r requirements.txt",
                description="Install requirements"
            ),
        ]

        return self._execute_commands(commands)

    def _install_php_dependencies(self, deploy_path: str, project_name: str) -> bool:
        """Install PHP dependencies using Composer."""
        # Check if composer.json exists
        client = self.ssh_manager.get_client()
        stdin, stdout, stderr = client.exec_command(
            f"test -f {deploy_path}/{project_name}/composer.json && echo 'EXISTS' || echo 'NOT_FOUND'"
        )
        result = stdout.read().decode('utf-8').strip()

        if result == 'NOT_FOUND':
            logger.info("ℹ️  No composer.json found, skipping dependency installation")
            return True

        logger.info("Found composer.json, installing dependencies...")

        # Check if composer is installed
        stdin, stdout, stderr = client.exec_command("which composer")
        if not stdout.read().decode('utf-8').strip():
            logger.warning("⚠️  Composer not found on server. Attempting to install...")
            # Simple composer installation (might need sudo)
            install_cmds = [
                SSHCommand(
                    command="curl -sS https://getcomposer.org/installer | php",
                    description="Download Composer installer"
                ),
                SSHCommand(
                    command="sudo mv composer.phar /usr/local/bin/composer",
                    description="Move Composer to global path"
                )
            ]
            if not self._execute_commands(install_cmds):
                logger.error("Failed to install Composer")
                return False

        commands = [
            SSHCommand(
                command=f"cd {deploy_path}/{project_name} && composer install --no-dev --optimize-autoloader --no-interaction",
                description="Install PHP dependencies"
            ),
        ]

        # Execute commands and capture detailed output on failure
        result = self._execute_commands(commands)

        if not result:
            # Try to get more detailed error information
            logger.info("Getting detailed composer error information...")
            stdin, stdout, stderr = client.exec_command(
                f"cd {deploy_path}/{project_name} && composer install --no-dev --optimize-autoloader --no-interaction -vvv 2>&1 || true"
            )
            detailed_output = stdout.read().decode('utf-8')
            if detailed_output:
                logger.error(f"Detailed composer output:\n{detailed_output}")

        return result

    def _install_nodejs_dependencies(self, deploy_path: str, project_name: str) -> bool:
        """Install Node.js dependencies using npm."""
        # Check if package.json exists
        client = self.ssh_manager.get_client()
        stdin, stdout, stderr = client.exec_command(
            f"test -f {deploy_path}/{project_name}/package.json && echo 'EXISTS' || echo 'NOT_FOUND'"
        )
        result = stdout.read().decode('utf-8').strip()

        if result == 'NOT_FOUND':
            logger.info("ℹ️  No package.json found, skipping dependency installation")
            return True

        logger.info("Found package.json, installing dependencies...")

        # Check if npm is installed
        stdin, stdout, stderr = client.exec_command("which npm")
        if not stdout.read().decode('utf-8').strip():
            logger.error("❌ npm not found on server. Please install Node.js and npm.")
            return False

        commands = [
            SSHCommand(
                command=f"cd {deploy_path}/{project_name} && npm install --production",
                description="Install Node.js dependencies"
            ),
        ]

        return self._execute_commands(commands)

    def _run_migrations(self, deploy_path: str, project_name: str) -> bool:
        """Run Alembic database migrations (if configured)."""
        try:
            client = self.ssh_manager.get_client()
            stdin, stdout, stderr = client.exec_command(
                f"test -f {deploy_path}/{project_name}/alembic.ini && echo 'EXISTS' || echo 'NOT_FOUND'"
            )
            result = stdout.read().decode('utf-8').strip()

            if result == 'NOT_FOUND':
                logger.info("ℹ️  No alembic.ini found, skipping migrations.")
                return True

            logger.info("Found alembic.ini, attempting migrations...")
            commands = [
                SSHCommand(
                    command=f"cd {deploy_path}/{project_name} && venv/bin/alembic upgrade head",
                    description="Run database migrations"
                ),
            ]

            if not self._execute_commands(commands):
                logger.error("❌ Database migrations failed.")
                # We now return False to stop the deployment
                return False

            return True

        except Exception as e:
            logger.error(f"❌ Migration check or execution failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _start_and_verify(self, project_name: str, domain: Optional[str], web_server: str = "nginx") -> bool:
        """Start services and verify deployment."""
        try:
            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            # Get backend language from architecture (set during deployment)
            backend_lang = getattr(self, '_current_backend_lang', 'python')  # Default to python

            # For PHP applications, we don't need to start a systemd service
            # PHP apps are served directly by Apache/PHP-FPM
            if backend_lang != "php":
                # Start and enable the application service (for Python, Node.js, etc.)
                app_commands = [
                    SSHCommand(
                        command=f"sudo systemctl start {project_name}",
                        description="Start application service"
                    ),
                    SSHCommand(
                        command=f"sudo systemctl enable {project_name}",
                        description="Enable service on boot"
                    ),
                    SSHCommand(
                        command=f"sudo systemctl status {project_name}",
                        description="Check service status"
                    ),
                ]

                for command in app_commands:
                    result = executor.execute(command, user_approval=True)
                    if not result.success:
                        logger.error(f"Application service command failed: {command.description}")
                        return False

            # Test and restart the appropriate web server
            if web_server == "apache2":
                logger.info("Testing Apache2 configuration...")
                test_cmd = SSHCommand(
                    command="sudo apache2ctl configtest",
                    description="Test Apache2 configuration"
                )
                test_result = executor.execute(test_cmd, user_approval=True)

                if test_result.success:
                    logger.info("✅ Apache2 config valid, restarting...")
                    restart_cmd = SSHCommand(
                        command="sudo systemctl restart apache2",
                        description="Restart Apache2"
                    )
                    restart_result = executor.execute(restart_cmd, user_approval=True)

                    if not restart_result.success:
                        logger.warning("⚠️  Apache2 restart failed, but continuing")
                        logger.warning("   You may need to manually fix apache config and restart")
                        return False
                else:
                    logger.warning("⚠️  Apache2 config test failed, skipping restart")
                    logger.warning("   You may need to manually fix apache config")
                    logger.debug(f"   Test output: {test_result.stderr[:500]}")
                    return False
            else:
                logger.info("Testing Nginx configuration...")
                test_cmd = SSHCommand(
                    command="sudo nginx -t",
                    description="Test Nginx configuration"
                )
                test_result = executor.execute(test_cmd, user_approval=True)

                if test_result.success:
                    logger.info("✅ Nginx config valid, restarting...")
                    restart_cmd = SSHCommand(
                        command="sudo systemctl restart nginx",
                        description="Restart Nginx"
                    )
                    restart_result = executor.execute(restart_cmd, user_approval=True)

                    if not restart_result.success:
                        logger.warning("⚠️  Nginx restart failed, but continuing")
                        logger.warning("   You may need to manually fix nginx config and restart")
                        return False
                else:
                    logger.warning("⚠️  Nginx config test failed, skipping restart")
                    logger.warning("   You may need to manually fix nginx config")
                    logger.debug(f"   Test output: {test_result.stderr[:500]}")
                    return False

            logger.info("✅ Services restarted successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Service startup failed: {e}")
            return False

    def _execute_commands(self, commands: List) -> bool:
        """Execute list of commands."""
        try:
            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            for command in commands:
                result = executor.execute(command, user_approval=True)
                if not result.success:
                    logger.error(f"Command failed: {command.description}")
                    return False

            return True
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return False

    def _get_deployment_url(self, domain: Optional[str], architecture: Dict[str, Any]) -> str:
        """Generate deployment URL."""
        # Check for SSL in architecture (use_ssl is set during configuration)
        use_ssl = architecture.get("use_ssl", False)
        protocol = "https" if use_ssl else "http"
        port = architecture.get("port", 80)

        if domain:
            # Include port if non-standard
            if (use_ssl and port != 443) or (not use_ssl and port != 80):
                return f"{protocol}://{domain}:{port}"
            return f"{protocol}://{domain}"
        else:
            # Use server IP
            host = self.ssh_manager.credentials.host
            if (use_ssl and port != 443) or (not use_ssl and port != 80):
                return f"{protocol}://{host}:{port}"
            return f"{protocol}://{host}"

    def _generate_summary(
        self,
        project_name: str,
        deployment_url: str,
        steps_completed: List[str]
    ) -> Dict[str, Any]:
        """Generate deployment summary."""
        deployment_time = (datetime.now() - self.deployment_start_time).total_seconds()

        return {
            "project_name": project_name,
            "deployment_url": deployment_url,
            "steps_completed": len(steps_completed),
            "total_steps": 10,
            "deployment_time_seconds": deployment_time,
            "deployment_timestamp": datetime.now().isoformat(),
            "steps": steps_completed,
        }

    def _print_summary(self, summary: Dict[str, Any]):
        """Print deployment summary."""
        print("\n" + "=" * 60)
        print("DEPLOYMENT SUMMARY")
        print("=" * 60)

        print(f"\n✅ Project: {summary['project_name']}")
        print(f"🌐 URL: {summary['deployment_url']}")
        print(f"⏱️  Deployment Time: {summary['deployment_time_seconds']:.1f}s")
        print(f"\n📋 Steps Completed: {summary['steps_completed']}/{summary['total_steps']}")

        for i, step in enumerate(summary['steps'], 1):
            print(f"  {i}. ✓ {step}")

        print("\n" + "=" * 60 + "\n")


# Example usage
if __name__ == "__main__":
    import sys
    import json

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("❌ This module requires SSH connection setup")
    print("   Use the complete deployment demo instead:")
    print("   python examples/complete_deployment_demo.py")
