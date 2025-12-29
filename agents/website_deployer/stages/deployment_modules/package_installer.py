#!/usr/bin/env python3
"""Package Installer - Install system packages"""

import logging
from typing import Dict, Any
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class PackageInstaller:
    """Installs system packages."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def install(self, architecture: Dict[str, Any]) -> bool:
        """Install required system packages."""

        try:
            # Determine required packages based on tech stack
            packages = []
            
            backend_lang = architecture.get("backend_language", "python").lower()
            web_server = architecture.get("web_server", "nginx").lower()
            db_type = architecture.get("database_type", "postgresql").lower()
            
            # Backend language packages
            if backend_lang == "python":
                packages.extend(["python3", "python3-pip", "python3-venv"])
            elif backend_lang == "php":
                packages.extend(["php", "unzip", "curl", "git"]) # unzip/curl/git for composer
                if web_server == "apache2":
                    packages.append("libapache2-mod-php")
                elif web_server == "nginx":
                    packages.append("php-fpm")
                
                # PHP extensions
                packages.extend(["php-xml", "php-mbstring", "php-curl"])
                
                if db_type == "sqlite":
                    packages.append("php-sqlite3")
                elif db_type == "postgresql":
                    packages.append("php-pgsql")
                elif db_type == "mysql":
                    packages.append("php-mysql")

            # Web server packages
            if web_server == "nginx":
                packages.append("nginx")
            elif web_server == "apache2":
                packages.append("apache2")
                
            # Database packages
            if db_type == "postgresql":
                packages.extend(["postgresql", "postgresql-contrib"])
            elif db_type == "sqlite":
                packages.append("sqlite3")

            # Add Redis if workers enabled
            if architecture.get("workers"):
                packages.append("redis-server")

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            # Retry apt update up to 3 times
            max_retries = 3
            update_success = False
            
            import time
            
            for i in range(max_retries):
                logger.info(f"Updating package lists (Attempt {i+1}/{max_retries})...")
                update_cmd = SSHCommand(
                    command="sudo apt-get update --allow-releaseinfo-change",
                    description="Update package lists"
                )
                result = executor.execute(update_cmd, user_approval=True)
                
                if result.success:
                    update_success = True
                    break
                else:
                    logger.warning(f"apt update failed: {result.stderr}")
                    if i < max_retries - 1:
                        logger.info("Retrying in 5 seconds...")
                        time.sleep(5)
            
            if not update_success:
                logger.error("Failed to update package lists after multiple attempts")
                return False

            # Install packages
            install_cmd = SSHCommand(
                command=f"sudo apt-get install -y {' '.join(packages)}",
                description="Install system packages"
            )
            result = executor.execute(install_cmd, user_approval=True)
            
            if not result.success:
                return False

            logger.info("✅ Packages installed successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Package installation failed: {e}")
            return False
