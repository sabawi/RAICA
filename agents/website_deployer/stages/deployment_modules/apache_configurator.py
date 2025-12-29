#!/usr/bin/env python3
"""Apache2 Configurator - Configure Apache2 as reverse proxy for deployed app"""

import logging
from typing import Optional, Dict, Any
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class ApacheConfigurator:
    """Configures Apache2 reverse proxy for deployed application."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def configure(
        self,
        project_name: str,
        domain: Optional[str],
        architecture: Dict[str, Any]
    ) -> bool:
        """
        Configure Apache2 reverse proxy.

        Args:
            project_name: Sanitized project name
            domain: Domain name (optional)
            architecture: Architecture configuration

        Returns:
            True if successful
        """
        try:
            logger.info("Configuring Apache2 reverse proxy...")

            # Get port from architecture or default to 8000
            app_port = architecture.get("port", architecture.get("infrastructure", {}).get("port", 8000))
            server_name = domain if domain else "localhost"

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            # Add the port to Apache's ports.conf if it's not already there
            logger.info(f"Ensuring Apache2 listens on port {app_port}...")
            check_port = SSHCommand(
                command=f"grep -q 'Listen {app_port}' /etc/apache2/ports.conf || echo 'Listen {app_port}' | sudo tee -a /etc/apache2/ports.conf > /dev/null",
                description=f"Add port {app_port} to Apache2 ports.conf"
            )
            executor.execute(check_port, user_approval=True)

            # Create Apache2 site configuration
            config_content = self._generate_apache_config(
                project_name,
                server_name,
                app_port,
                architecture
            )

            logger.info(f"Creating Apache2 configuration for {project_name}...")

            # Write configuration file
            write_config = SSHCommand(
                command=f"sudo tee /etc/apache2/sites-available/{project_name}.conf > /dev/null <<'EOF'\n{config_content}\nEOF",
                description="Write Apache2 configuration"
            )
            result = executor.execute(write_config, user_approval=True)
            if not result.success:
                logger.error("Failed to write Apache2 configuration")
                return False

            # Enable required Apache modules
            logger.info("Enabling required Apache modules...")
            modules = ["proxy", "proxy_http", "rewrite", "headers", "ssl"]
            for module in modules:
                enable_mod = SSHCommand(
                    command=f"sudo a2enmod {module}",
                    description=f"Enable Apache module: {module}"
                )
                executor.execute(enable_mod, user_approval=True)

            # Enable the site
            logger.info(f"Enabling site configuration: {project_name}")
            enable_site = SSHCommand(
                command=f"sudo a2ensite {project_name}.conf",
                description="Enable Apache site"
            )
            result = executor.execute(enable_site, user_approval=True)
            if not result.success:
                logger.warning("Failed to enable site, but continuing...")

            # Disable default site if it conflicts
            logger.info("Disabling default Apache site...")
            disable_default = SSHCommand(
                command="sudo a2dissite 000-default.conf",
                description="Disable default site"
            )
            executor.execute(disable_default, user_approval=True)

            # Test Apache configuration
            logger.info("Testing Apache configuration...")
            test_config = SSHCommand(
                command="sudo apache2ctl configtest",
                description="Test Apache configuration"
            )
            test_result = executor.execute(test_config, user_approval=True)

            if not test_result.success:
                logger.error("Apache configuration test failed!")
                logger.error(f"Error: {test_result.stderr[:500]}")
                return False

            logger.info("✅ Apache2 configured successfully")
            return True

        except Exception as e:
            logger.error(f"Error configuring Apache2: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _generate_apache_config(
        self,
        project_name: str,
        server_name: str,
        app_port: int,
        architecture: Dict[str, Any] = None
    ) -> str:
        """Generate Apache2 VirtualHost configuration."""

        backend_lang = "python"
        if architecture:
            backend_lang = architecture.get("backend_language", "python").lower()

        if backend_lang == "php":
            # PHP Configuration (Document Root)
            # Get deploy path from architecture - CRITICAL: Don't use hardcoded defaults
            if not architecture or "deploy_path" not in architecture:
                logger.error("Missing deploy_path in architecture for PHP deployment!")
                raise ValueError("deploy_path must be provided in architecture for PHP deployments")

            deploy_path = architecture["deploy_path"]
            use_ssl = architecture.get("use_ssl", False)
            ssl_cert = architecture.get("ssl_cert_path", "")
            ssl_key = architecture.get("ssl_key_path", "")

            # DEBUG: Log SSL configuration values
            logger.info(f"🔍 DEBUG SSL Config: use_ssl={use_ssl}, ssl_cert={ssl_cert}, ssl_key={ssl_key}")

            # Build SSL directives if SSL is enabled
            ssl_config = ""
            if use_ssl and ssl_cert and ssl_key:
                ssl_config = f"""
    # SSL Configuration
    SSLEngine on
    SSLCertificateFile {ssl_cert}
    SSLCertificateKeyFile {ssl_key}"""

            return f"""<VirtualHost *:{app_port}>
    ServerAdmin webmaster@localhost
    ServerName {server_name}
    DocumentRoot {deploy_path}
{ssl_config}
    <Directory {deploy_path}>
        Options Indexes FollowSymLinks MultiViews
        AllowOverride All
        Require all granted
    </Directory>

    # Logging
    ErrorLog ${{APACHE_LOG_DIR}}/{project_name}_error.log
    CustomLog ${{APACHE_LOG_DIR}}/{project_name}_access.log combined

    # Security headers
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-XSS-Protection "1; mode=block"
</VirtualHost>"""
        else:
            # Python/FastAPI Configuration (Reverse Proxy)
            return f"""<VirtualHost *:{app_port}>
    ServerAdmin webmaster@localhost
    ServerName {server_name}

    # Proxy settings for FastAPI
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:{app_port}/
    ProxyPassReverse / http://127.0.0.1:{app_port}/

    # WebSocket support
    RewriteEngine On
    RewriteCond %{{HTTP:Upgrade}} websocket [NC]
    RewriteCond %{{HTTP:Connection}} upgrade [NC]
    RewriteRule ^/?(.*) "ws://127.0.0.1:{app_port}/$1" [P,L]

    # Logging
    ErrorLog ${{APACHE_LOG_DIR}}/{project_name}_error.log
    CustomLog ${{APACHE_LOG_DIR}}/{project_name}_access.log combined

    # Security headers
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-XSS-Protection "1; mode=block"
</VirtualHost>"""
