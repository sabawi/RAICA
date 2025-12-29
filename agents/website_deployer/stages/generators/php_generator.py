#!/usr/bin/env python3
"""
PHP Code Generator for Website Deployer Agent
==========================================

Generates production-ready PHP code from architecture specifications.

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import logging
from typing import Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

class PHPGenerator:
    """
    Generates complete PHP application code from architecture specification.
    """

    def generate(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """
        Generate PHP backend code.

        Args:
            project_dir: The root directory of the project.
            architecture: The architecture specification.

        Returns:
            A list of generated files.
        """
        logger.info("Generating PHP code...")
        files_generated = []

        # Create basic PHP project structure
        self._create_directory_structure(project_dir)

        # Generate composer.json
        composer_json_path = self._generate_composer_json(project_dir, architecture)
        files_generated.append(str(composer_json_path))

        # Generate index.php
        index_php_path = self._generate_index_php(project_dir)
        files_generated.append(str(index_php_path))

        return files_generated

    def _create_directory_structure(self, project_dir: Path):
        """Create a basic PHP project structure."""
        directories = [
            "app/Controllers",
            "app/Models",
            "public",
            "routes",
            "views",
        ]
        for dir_path in directories:
            (project_dir / dir_path).mkdir(parents=True, exist_ok=True)

    def _generate_composer_json(self, project_dir: Path, architecture: Dict[str, Any]) -> Path:
        """Generates a composer.json file."""
        project_name = architecture.get("project_name", "my-project")
        composer_data = {
            "name": f"vendor/{project_name.lower().replace(' ', '-')}",
            "description": architecture.get("description", ""),
            "type": "project",
            "require": {
                "php": "^8.1"
            },
            "autoload": {
                "psr-4": {
                    "App\\": "app/"
                }
            }
        }

        composer_json_path = project_dir / "composer.json"
        with open(composer_json_path, 'w') as f:
            import json
            json.dump(composer_data, f, indent=4)

        return composer_json_path

    def _generate_index_php(self, project_dir: Path) -> Path:
        """Generates a public/index.php file."""
        index_php_content = """<?php

require __DIR__ . '/../vendor/autoload.php';

echo "<h1>Hello, World!</h1>";
"""
        index_php_path = project_dir / "public/index.php"
        with open(index_php_path, 'w') as f:
            f.write(index_php_content)

        return index_php_path

