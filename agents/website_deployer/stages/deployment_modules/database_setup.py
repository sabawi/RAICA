#!/usr/bin/env python3
"""Database Setup - Configure PostgreSQL or MySQL"""

import logging
import secrets
import string
from typing import Dict, Any
from ssh import SSHCommand, SafeSSHExecutor

logger = logging.getLogger(__name__)


class DatabaseSetup:
    """Configures PostgreSQL or MySQL database."""

    def __init__(self, ssh_manager):
        self.ssh_manager = ssh_manager

    def configure(self, project_name: str, architecture: Dict[str, Any]) -> bool:
        """Configure the appropriate database."""
        db_type = architecture.get("database_type", "postgresql").lower()

        if db_type == "sqlite":
            logger.info("ℹ️  Skipping database setup for SQLite (file-based)")
            return True
        elif db_type == "mysql":
            return self._configure_mysql(project_name)
        elif db_type == "postgresql":
            return self._configure_postgresql(project_name)
        else:
            logger.error(f"Unsupported database type: {db_type}")
            return False

    def _configure_postgresql(self, project_name: str) -> bool:
        """Configure PostgreSQL database."""
        try:
            db_name = project_name.replace('-', '_').replace('.', '_').lower()
            db_user = db_name
            db_password = self._generate_password()

            logger.info(f"Configuring PostgreSQL database: {db_name}")

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            commands = [
                SSHCommand(
                    command=f"sudo -u postgres psql -c \"SELECT 1 FROM pg_database WHERE datname='{db_name}'\" | grep -q 1 || sudo -u postgres psql -c 'CREATE DATABASE {db_name};'",
                    description="Create PostgreSQL database (if not exists)"
                ),
                SSHCommand(
                    command=f"sudo -u postgres psql -c \"SELECT 1 FROM pg_roles WHERE rolname='{db_user}'\" | grep -q 1 || sudo -u postgres psql -c \\\"CREATE USER {db_user} WITH PASSWORD '{db_password}';\\\"",
                    description="Create PostgreSQL user (if not exists)"
                ),
                SSHCommand(
                    command=f'sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};"',
                    description="Grant PostgreSQL privileges"
                ),
                SSHCommand(
                    command=f'sudo -u postgres psql -d {db_name} -c "GRANT ALL ON SCHEMA public TO {db_user};"',
                    description="Grant PostgreSQL schema privileges"
                ),
            ]

            if not self._execute_db_commands(executor, commands):
                return False

            logger.info("✅ PostgreSQL database configured successfully")
            logger.info(f"   Database: {db_name}")
            logger.info(f"   User: {db_user}")
            logger.info(f"   Connection string: postgresql://{db_user}:{db_password}@localhost/{db_name}")

            return True

        except Exception as e:
            logger.error(f"❌ PostgreSQL setup failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _configure_mysql(self, project_name: str) -> bool:
        """Configure MySQL database."""
        try:
            db_name = project_name.replace('-', '_').replace('.', '_').lower()
            db_user = db_name
            db_password = self._generate_password()

            logger.info(f"Configuring MySQL database: {db_name}")

            client = self.ssh_manager.get_client()
            executor = SafeSSHExecutor(client, dry_run=False)

            # Note: MySQL commands are less idempotent by default
            commands = [
                SSHCommand(
                    command=f"sudo mysql -e \"CREATE DATABASE IF NOT EXISTS {db_name};\"",
                    description="Create MySQL database (if not exists)"
                ),
                SSHCommand(
                    command=f"sudo mysql -e \"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';\"",
                    description="Create MySQL user (if not exists)"
                ),
                SSHCommand(
                    command=f"sudo mysql -e \"GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'localhost';\"",
                    description="Grant MySQL privileges"
                ),
                SSHCommand(
                    command="sudo mysql -e \"FLUSH PRIVILEGES;\"",
                    description="Flush MySQL privileges"
                ),
            ]

            if not self._execute_db_commands(executor, commands):
                return False

            logger.info("✅ MySQL database configured successfully")
            logger.info(f"   Database: {db_name}")
            logger.info(f"   User: {db_user}")
            logger.info(f"   Connection string: mysql+pymysql://{db_user}:{db_password}@localhost/{db_name}")

            return True

        except Exception as e:
            logger.error(f"❌ MySQL setup failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _generate_password(self, length: int = 16) -> str:
        """Generate a random alphanumeric password."""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for i in range(length))

    def _execute_db_commands(self, executor: SafeSSHExecutor, commands: list) -> bool:
        """Execute a list of database commands."""
        for command in commands:
            result = executor.execute(command, user_approval=True)
            if not result.success:
                logger.warning(f"⚠️  Database command had issues: {command.description}")
                logger.debug(f"   stdout: {result.stdout[:200]}")
                logger.debug(f"   stderr: {result.stderr[:200]}")
                # Unlike before, we will not continue on failure for more robustness
                return False
        return True
