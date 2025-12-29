#!/usr/bin/env python3
"""Migration Generator - Alembic migrations"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class MigrationGenerator:
    """Generates Alembic migration configuration."""

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        files = []

        # Generate alembic.ini
        alembic_ini = project_dir / "alembic.ini"
        with open(alembic_ini, 'w') as f:
            f.write('''[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url = postgresql://user:password@localhost/dbname

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
''')
        files.append(str(alembic_ini.relative_to(project_dir)))

        # Generate alembic/env.py
        env_file = project_dir / "alembic" / "env.py"
        with open(env_file, 'w') as f:
            f.write('''"""Alembic environment configuration."""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.db.base import Base
from app.models import *
from app.core.config import settings

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata

# Override sqlalchemy.url with DATABASE_URL from settings
# This allows using environment variables instead of hardcoded alembic.ini values
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
''')
        files.append(str(env_file.relative_to(project_dir)))

        logger.info(f"✅ Generated {len(files)} migration files")
        return files
