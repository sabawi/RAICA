#!/usr/bin/env python3
"""Worker Generator - Celery tasks"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class WorkerGenerator:
    """Generates Celery worker tasks."""

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        files = []
        workers = architecture.get("workers", [])

        if not workers:
            return files

        # Generate celery_app.py
        celery_file = project_dir / "app" / "workers" / "celery_app.py"
        with open(celery_file, 'w') as f:
            f.write('''"""Celery application configuration."""
from celery import Celery

celery_app = Celery(
    "worker",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
''')
        files.append(str(celery_file.relative_to(project_dir)))

        # Generate tasks.py
        tasks_file = project_dir / "app" / "workers" / "tasks.py"
        tasks_content = '''"""Celery background tasks."""
from app.workers.celery_app import celery_app

'''
        for worker in workers:
            func_name = worker["function_name"]
            description = worker["description"]
            tasks_content += f'''
@celery_app.task
def {func_name}(*args, **kwargs):
    """{description}"""
    # Implementation here
    pass

'''
        with open(tasks_file, 'w') as f:
            f.write(tasks_content)
        files.append(str(tasks_file.relative_to(project_dir)))

        logger.info(f"✅ Generated {len(files)} worker files")
        return files
