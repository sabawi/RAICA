#!/usr/bin/env python3
"""
Assembly Coordinator - Stage 5 of Intelligent Code Generation
==============================================================

Collects all generated files and creates project structure.

This stage:
1. Creates directory structure
2. Writes all generated files
3. Generates supporting files (README, .gitignore, etc.)
4. Creates requirements.txt from dependencies
5. Verifies file structure completeness
"""

import logging
import os
import shutil
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

from .llm_code_generator import GeneratedFile
from .tech_stack_config import TechStackConfig

logger = logging.getLogger(__name__)


@dataclass
class AssembledProject:
    """Result of project assembly."""
    name: str
    path: Path
    files: List[GeneratedFile]
    readme_path: Path
    requirements_path: Path


class AssemblyCoordinator:
    """
    Assembles generated files into complete project.
    
    Handles directory creation, file writing, and generation of
    supporting files to create a runnable project.
    """

    def __init__(self, base_dir: str = "generated_projects", tech_config: Optional[TechStackConfig] = None):
        """
        Initialize assembly coordinator.

        Args:
            base_dir: Base directory for generated projects
            tech_config: Technology stack configuration
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tech_config = tech_config
        logger.info(f"AssemblyCoordinator initialized with base_dir: {self.base_dir}")

    def assemble(self, 
                generated_files: List[GeneratedFile], 
                project_name: str) -> AssembledProject:
        """
        Assemble generated files into a project.

        Args:
            generated_files: List of generated code files
            project_name: Name of the project

        Returns:
            AssembledProject object with project details
        """
        logger.info("=" * 60)
        logger.info("PROJECT ASSEMBLY STARTED")
        logger.info("=" * 60)

        # Create project directory
        project_dir = self.base_dir / project_name
        self._create_project_structure(project_dir)
        logger.info(f"Created project directory: {project_dir}")

        # Write generated files
        logger.info(f"Writing {len(generated_files)} generated files...")
        for file in generated_files:
            self._write_file(project_dir, file)

        # Generate supporting files
        logger.info("Generating supporting files...")
        readme_path = self._generate_readme(project_dir, project_name)
        gitignore_path = self._generate_gitignore(project_dir)
        requirements_path = self._generate_requirements(project_dir, generated_files)

        # Create virtual environment setup script
        self._create_setup_script(project_dir)

        logger.info("=" * 60)
        logger.info("PROJECT ASSEMBLY COMPLETE")
        logger.info("=" * 60)

        return AssembledProject(
            name=project_name,
            path=project_dir,
            files=generated_files,
            readme_path=readme_path,
            requirements_path=requirements_path
        )

    def _create_project_structure(self, project_dir: Path):
        """Create clean project directory structure."""
        if project_dir.exists():
            logger.warning(f"Project directory {project_dir} exists, cleaning up...")
            shutil.rmtree(project_dir)
        
        project_dir.mkdir(parents=True)
        
        # Create tech-specific directory structure
        if self.tech_config:
            directories = self.tech_config.get_directory_structure()
            for dir_path in directories:
                (project_dir / dir_path).mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created directory: {dir_path}")
        else:
            # Fallback to basic structure
            logger.warning("No tech_config provided, using basic structure")
            (project_dir / "src").mkdir()
            (project_dir / "tests").mkdir()

    def _write_file(self, project_dir: Path, file: GeneratedFile):
        """Write a single generated file to disk."""
        file_path = project_dir / file.path

        # Log the file being written
        logger.debug(f"Writing file: {file.path} (type: {file.file_type})")

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        with open(file_path, "w") as f:
            f.write(file.content)
            
        logger.debug(f"Wrote {file.path}")

    def _generate_readme(self, project_dir: Path, project_name: str) -> Path:
        """Generate README.md file."""
        
        # Get tech stack info
        if self.tech_config:
            tech_desc = self.tech_config.get_tech_stack_description()
            dep_manager = self.tech_config.get_dependency_manager()
            dep_file = self.tech_config.get_dependency_file_name()
            orm = self.tech_config.get_orm_library()
            backend_lang = self.tech_config.backend_language
            
            # Build setup instructions based on tech stack
            if backend_lang == "python":
                setup_steps = f"""1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\\\\Scripts\\\\activate  # Windows
   ```

2. Install dependencies:
   ```bash
   {dep_manager} install -r {dep_file}
   ```

3. Configure environment:
   Copy `.env.example` to `.env` and update values.

4. Run migrations:
   ```bash
   alembic upgrade head
   ```

5. Start the server:
   ```bash
   uvicorn app.main:app --reload
   ```"""
            elif backend_lang == "php":
                setup_steps = f"""1. Install dependencies:
   ```bash
   {dep_manager} install
   ```

2. Configure environment:
   Copy `.env.example` to `.env` and update values.

3. Generate application key:
   ```bash
   php artisan key:generate
   ```

4. Run migrations:
   ```bash
   php artisan migrate
   ```

5. Start the server:
   ```bash
   php artisan serve
   ```"""
            elif backend_lang == "nodejs":
                setup_steps = f"""1. Install dependencies:
   ```bash
   {dep_manager} install
   ```

2. Configure environment:
   Copy `.env.example` to `.env` and update values.

3. Run migrations:
   ```bash
   npx sequelize-cli db:migrate
   ```

4. Start the server:
   ```bash
   {dep_manager} start
   ```"""
            else:
                setup_steps = f"""1. Install dependencies:
   ```bash
   {dep_manager} install
   ```

2. Configure environment and run the application."""
            
            content = f"""# {project_name}

Generated by Intelligent Code Generator Agent.

## Overview
This is a fully generated web application using {tech_desc}.

## Setup

{setup_steps}

## Tech Stack
- Backend: {tech_desc}
- ORM: {orm}
- Package Manager: {dep_manager}
"""
        else:
            # Fallback README
            content = f"""# {project_name}

Generated by Intelligent Code Generator Agent.

## Setup

1. Install dependencies
2. Configure environment
3. Run the application
"""
        
        path = project_dir / "README.md"
        with open(path, "w") as f:
            f.write(content)
        return path

    def _generate_gitignore(self, project_dir: Path) -> Path:
        """Generate .gitignore file."""
        content = """
# Python
__pycache__/
*.py[cod]
*$py.class
venv/
.env

# IDEs
.vscode/
.idea/

# Database
*.sqlite
*.db

# OS
.DS_Store
Thumbs.db
"""
        path = project_dir / ".gitignore"
        with open(path, "w") as f:
            f.write(content.strip())
        return path

    def _generate_requirements(self, project_dir: Path, generated_files: List[GeneratedFile]) -> Path:
        """Generate dependency file based on tech stack."""

        if not self.tech_config:
            # Fallback to requirements.txt
            path = project_dir / "requirements.txt"
            with open(path, "w") as f:
                f.write("# Add your dependencies here\n")
            return path

        backend_lang = self.tech_config.backend_language
        dep_file = self.tech_config.get_dependency_file_name()

        # If no dependency file is specified, return a dummy path
        if dep_file == "none":
            return project_dir / "no-dependencies.txt"

        if backend_lang == "python":
            # Generate requirements.txt
            requirements = {
                "fastapi", "uvicorn[standard]", "sqlalchemy", "alembic", 
                "pydantic", "pydantic-settings", "python-dotenv", 
                "jinja2", "python-multipart", "requests", "httpx"
            }
            
            # Add specific requirements based on file content
            for file in generated_files:
                if "passlib" in file.content:
                    requirements.add("passlib[bcrypt]")
                if "jose" in file.content or "jwt" in file.content:
                    requirements.add("python-jose[cryptography]")
                if "celery" in file.content:
                    requirements.add("celery[redis]")
                if "redis" in file.content:
                    requirements.add("redis")
                if "psycopg2" in file.content or "postgres" in file.content.lower():
                    requirements.add("psycopg2-binary")
                    
            content = "\n".join(sorted(requirements))
            path = project_dir / dep_file
            with open(path, "w") as f:
                f.write(content)
                
        elif backend_lang == "php":
            # Generate composer.json - tech stack aware
            import json

            # Determine the appropriate composer.json based on tech stack
            tech_key = self.tech_config.tech_key

            if tech_key == "php_laravel":
                # Full Laravel application
                composer_data = {
                    "name": "generated/laravel-app",
                    "type": "project",
                    "require": {
                        "php": "^8.1",
                        "laravel/framework": "^10.0",
                        "laravel/sanctum": "^3.2",
                        "laravel/tinker": "^2.8"
                    },
                    "require-dev": {
                        "fakerphp/faker": "^1.9.1",
                        "laravel/pint": "^1.0",
                        "laravel/sail": "^1.18",
                        "mockery/mockery": "^1.4.4",
                        "nunomaduro/collision": "^7.0",
                        "phpunit/phpunit": "^10.0",
                        "spatie/laravel-ignition": "^2.0"
                    },
                    "autoload": {
                        "psr-4": {
                            "App\\\\": "app/",
                            "Database\\\\Factories\\\\": "database/factories/",
                            "Database\\\\Seeders\\\\": "database/seeders/"
                        }
                    },
                    "scripts": {
                        "post-autoload-dump": [
                            "Illuminate\\\\Foundation\\\\ComposerScripts::postAutoloadDump",
                            "@php artisan package:discover --ansi"
                        ]
                    },
                    "config": {
                        "optimize-autoloader": True,
                        "preferred-install": "dist",
                        "sort-packages": True
                    },
                    "minimum-stability": "stable",
                    "prefer-stable": True
                }
            else:
                # Plain PHP or Apache PHP application
                composer_data = {
                    "name": "generated/php-app",
                    "type": "project",
                    "require": {
                        "php": "^8.1",
                        "illuminate/database": "^10.0",
                        "illuminate/http": "^10.0",
                        "illuminate/routing": "^10.0",
                        "illuminate/support": "^10.0",
                        "illuminate/validation": "^10.0",
                        "illuminate/session": "^10.0",
                        "vlucas/phpdotenv": "^5.5"
                    },
                    "autoload": {
                        "psr-4": {
                            "App\\\\": "app/"
                        }
                    },
                    "config": {
                        "optimize-autoloader": True,
                        "preferred-install": "dist",
                        "sort-packages": True
                    },
                    "minimum-stability": "stable",
                    "prefer-stable": True
                }

            path = project_dir / dep_file
            with open(path, "w") as f:
                json.dump(composer_data, f, indent=4)
                
        elif backend_lang == "nodejs":
            # Generate package.json
            import json
            package_data = {
                "name": "generated-express-app",
                "version": "1.0.0",
                "description": "Generated Express.js application",
                "main": "server.js",
                "scripts": {
                    "start": "node server.js",
                    "dev": "nodemon server.js",
                    "test": "jest"
                },
                "dependencies": {
                    "express": "^4.18.0",
                    "sequelize": "^6.32.0",
                    "pg": "^8.11.0",
                    "pg-hstore": "^2.3.4",
                    "dotenv": "^16.3.0",
                    "cors": "^2.8.5",
                    "helmet": "^7.0.0",
                    "express-validator": "^7.0.0",
                    "bcryptjs": "^2.4.3",
                    "jsonwebtoken": "^9.0.0"
                },
                "devDependencies": {
                    "nodemon": "^3.0.0",
                    "jest": "^29.6.0",
                    "supertest": "^6.3.0"
                }
            }
            
            path = project_dir / dep_file
            with open(path, "w") as f:
                json.dump(package_data, f, indent=2)
        else:
            # Generic fallback
            path = project_dir / dep_file
            with open(path, "w") as f:
                f.write("# Add your dependencies here\n")
        
        return path

    def _create_setup_script(self, project_dir: Path):
        """Create tech-aware setup script for easy installation."""
        if not self.tech_config:
            logger.warning("No tech_config available, skipping setup script")
            return

        backend_lang = self.tech_config.backend_language
        dep_manager = self.tech_config.get_dependency_manager()
        dep_file = self.tech_config.get_dependency_file_name()

        # Python-specific setup script
        if backend_lang == "python":
            content = f"""#!/bin/bash
echo "Setting up Python project..."

# Create venv if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
{dep_manager} install -r {dep_file}

echo "Setup complete! Run 'source venv/bin/activate' to start."
"""
            # Ensure scripts directory exists for Python
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            path = scripts_dir / "setup.sh"

        # PHP-specific setup script
        elif backend_lang == "php":
            content = f"""#!/bin/bash
echo "Setting up PHP project..."

# Install PHP dependencies
echo "Installing dependencies with {dep_manager}..."
{dep_manager} install

echo "Setup complete! Configure your web server to point to public/ directory."
"""
            # PHP projects typically put scripts in root
            path = project_dir / "setup.sh"

        # Node.js-specific setup script
        elif backend_lang == "nodejs":
            content = f"""#!/bin/bash
echo "Setting up Node.js project..."

# Install npm dependencies
echo "Installing dependencies..."
{dep_manager} install

echo "Setup complete! Run 'npm start' or 'node server.js' to start the server."
"""
            path = project_dir / "setup.sh"

        else:
            logger.warning(f"Unknown backend language: {backend_lang}, skipping setup script")
            return

        with open(path, "w") as f:
            f.write(content)

        # Make executable
        os.chmod(path, 0o755)
        logger.info(f"Created setup script: {path}")
