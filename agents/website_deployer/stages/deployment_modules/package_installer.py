#!/usr/bin/env python3
"""Package Installer - Install system packages via SSH."""

import logging
import time
from typing import Dict, Any, List
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class PackageInstaller:
    """Installs system packages using system package manager (apt-get)."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def install(self, architecture: Dict[str, Any]) -> bool:
        """Install required system packages based on specified architecture.
        
        Args:
            architecture: Dictionary containing system architecture details:
                - backend_language: python, php, nodejs/node, go/golang, ruby, etc.
                - web_server: nginx, apache2/apache, etc.
                - database_type: postgresql, mysql/mariadb, sqlite, mongodb, etc.
                - workers: boolean flag for background workers (installs redis-server)
                - additional_packages / system_packages / extra_packages / packages: optional list of custom packages

        Returns:
            bool: True if installation succeeded (or no packages needed), False otherwise.
        """
        try:
            packages: List[str] = []
            
            # Helper to extract clean string value
            def _get_str_option(key: str, default: str = "") -> str:
                val = architecture.get(key)
                if isinstance(val, str):
                    return val.strip().lower()
                return default.lower()

            backend_lang = _get_str_option("backend_language", "python")
            web_server = _get_str_option("web_server", "nginx")
            db_type = _get_str_option("database_type", "postgresql")

            # 1. Backend language packages
            if backend_lang in ("python", "py"):
                packages.extend(["python3", "python3-pip", "python3-venv"])
            elif backend_lang in ("php",):
                packages.extend(["php", "unzip", "curl", "git"])  # Required for Composer
                if web_server in ("apache2", "apache"):
                    packages.append("libapache2-mod-php")
                elif web_server == "nginx":
                    packages.append("php-fpm")
                
                # Standard PHP extensions
                packages.extend(["php-xml", "php-mbstring", "php-curl", "php-zip"])
                
                if db_type in ("sqlite", "sqlite3"):
                    packages.append("php-sqlite3")
                elif db_type in ("postgresql", "postgres"):
                    packages.append("php-pgsql")
                elif db_type in ("mysql", "mariadb"):
                    packages.append("php-mysql")
            elif backend_lang in ("nodejs", "node", "js", "javascript"):
                packages.extend(["nodejs", "npm"])
            elif backend_lang in ("go", "golang"):
                packages.append("golang-go")
            elif backend_lang in ("ruby",):
                packages.extend(["ruby", "ruby-dev"])

            # 2. Web server packages
            if web_server == "nginx":
                packages.append("nginx")
            elif web_server in ("apache2", "apache"):
                packages.append("apache2")

            # 3. Database packages
            if db_type in ("postgresql", "postgres"):
                packages.extend(["postgresql", "postgresql-contrib"])
            elif db_type in ("mysql", "mariadb"):
                packages.append("mysql-server")
            elif db_type in ("sqlite", "sqlite3"):
                packages.append("sqlite3")
            elif db_type in ("mongodb", "mongo"):
                packages.append("mongodb")

            # 4. Redis if workers or caching enabled
            if architecture.get("workers") or architecture.get("redis"):
                packages.append("redis-server")

            # 5. Support custom/additional packages specified in architecture dict
            for custom_key in ("additional_packages", "system_packages", "extra_packages", "packages"):
                custom_pkgs = architecture.get(custom_key)
                if isinstance(custom_pkgs, (list, tuple, set)):
                    for pkg in custom_pkgs:
                        if isinstance(pkg, str) and pkg.strip():
                            packages.append(pkg.strip().lower())

            # Deduplicate packages while preserving insertion order
            packages = list(dict.fromkeys(packages))

            # Handle case where no packages are required
            if not packages:
                logger.info("No system packages required to install.")
                return True

            logger.info(f"Target system packages to install: {', '.join(packages)}")

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            # Retry apt update up to max_retries times
            max_retries = 3
            update_success = False

            for i in range(max_retries):
                logger.info(f"Updating package lists (Attempt {i + 1}/{max_retries})...")
                update_cmd = SSHCommand(
                    command="sudo DEBIAN_FRONTEND=noninteractive apt-get update -y --allow-releaseinfo-change",
                    description="Update package lists"
                )
                result = executor.execute(update_cmd, user_approval=True)

                if result.success:
                    update_success = True
                    break
                else:
                    logger.warning(f"apt-get update failed (Attempt {i + 1}/{max_retries}): {result.stderr}")
                    if i < max_retries - 1:
                        logger.info("Retrying package update in 5 seconds...")
                        time.sleep(5)

            if not update_success:
                logger.error("Failed to update package lists after multiple attempts")
                return False

            # Install packages non-interactively
            pkg_str = " ".join(packages)
            install_cmd = SSHCommand(
                command=f"sudo DEBIAN_FRONTEND=noninteractive apt-get install -y {pkg_str}",
                description=f"Install system packages: {pkg_str}"
            )
            result = executor.execute(install_cmd, user_approval=True)

            if not result.success:
                logger.error(f"Failed to install packages: {result.stderr}")
                return False

            logger.info("✅ System packages installed successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Package installation failed: {e}", exc_info=True)
            return False

