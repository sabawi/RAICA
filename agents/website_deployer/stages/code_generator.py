#!/usr/bin/env python3
"""
Code Generator for Website Deployer Agent
==========================================

Generates production-ready code from architecture specifications.

Generates:
- FastAPI backend with all endpoints
- SQLAlchemy models and relationships
- Alembic database migrations
- JWT authentication system
- Celery worker tasks
- Frontend templates (Alpine.js + Tailwind)
- Configuration files (nginx, systemd, .env)

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import json
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime

from .generators.php_generator import PHPGenerator
from .generators.nodejs_generator import NodeJSGenerator

logger = logging.getLogger(__name__)


@dataclass
class CodeGenerationResult:
    """Result of code generation."""
    success: bool
    output_directory: Optional[Path] = None
    files_generated: Optional[List[str]] = None
    generation_summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class CodeGenerator:
    """
    Generates complete application code from architecture specification.

    Produces production-ready FastAPI backend, SQLAlchemy models,
    frontend templates, worker tasks, and configuration files.
    """

    def __init__(self, output_base_dir: Path = Path("generated_projects")):
        """
        Initialize code generator.

        Args:
            output_base_dir: Base directory for generated projects
        """
        self.output_base_dir = output_base_dir
        logger.info(f"CodeGenerator initialized (output: {self.output_base_dir})")

    def generate(
        self,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any]
    ) -> CodeGenerationResult:
        """
        Generate complete application code.

        Args:
            requirements: Requirements from Phase 2
            architecture: Architecture from Phase 3

        Returns:
            CodeGenerationResult with file paths and summary
        """
        try:
            project_name = architecture.get("project_name", "app")
            language = requirements.get("technical_constraints", {}).get("backend_language", "python").lower()

            logger.info("=" * 60)
            logger.info(f"CODE GENERATION STARTED: {project_name} ({language.upper()})")
            logger.info("=" * 60)

            # Create project directory
            project_dir = self.output_base_dir / project_name
            project_dir.mkdir(parents=True, exist_ok=True)

            if language == "php":
                files_generated = self._generate_php_project(project_dir, requirements, architecture)
            elif language == "nodejs":
                files_generated = self._generate_nodejs_project(project_dir, requirements, architecture)
            else: # Default to python
                files_generated = self._generate_python_project(project_dir, requirements, architecture)

            # Generate summary
            summary = self._generate_summary(
                project_dir,
                requirements,
                architecture,
                files_generated
            )

            logger.info("=" * 60)
            logger.info(f"CODE GENERATION COMPLETE: {len(files_generated)} files")
            logger.info("=" * 60)

            self._print_summary(summary)

            return CodeGenerationResult(
                success=True,
                output_directory=project_dir,
                files_generated=files_generated,
                generation_summary=summary
            )

        except Exception as e:
            logger.error(f"❌ Code generation failed: {e}")
            import traceback
            traceback.print_exc()
            return CodeGenerationResult(
                success=False,
                error_message=f"Code generation failed: {str(e)}"
            )

    def _generate_php_project(self, project_dir: Path, requirements: Dict[str, Any], architecture: Dict[str, Any]) -> List[str]:
        """Generates a PHP project."""
        files_generated = []
        php_generator = PHPGenerator()
        
        # Call the PHP generator to create the project structure and files
        php_files = php_generator.generate(project_dir, architecture)
        files_generated.extend(php_files)
        
        # Generate README
        logger.info("Generating README.md...")
        readme_file = self._generate_readme(project_dir, requirements, architecture)
        files_generated.append(readme_file)

        return files_generated

    def _generate_nodejs_project(self, project_dir: Path, requirements: Dict[str, Any], architecture: Dict[str, Any]) -> List[str]:
        """Generates a Node.js project."""
        files_generated = []
        nodejs_generator = NodeJSGenerator()
        
        # Call the Node.js generator to create the project structure and files
        nodejs_files = nodejs_generator.generate(project_dir, architecture)
        files_generated.extend(nodejs_files)
        
        # Generate README
        logger.info("Generating README.md...")
        readme_file = self._generate_readme(project_dir, requirements, architecture)
        files_generated.append(readme_file)

        return files_generated

    def _generate_python_project(self, project_dir: Path, requirements: Dict[str, Any], architecture: Dict[str, Any]) -> List[str]:
        """Generates a Python project."""
        files_generated = []

        # Generate directory structure
        logger.info("Creating directory structure...")
        self._create_directory_structure(project_dir)

        # 1. Generate backend code
        logger.info("Generating FastAPI backend...")
        backend_files = self._generate_backend(project_dir, architecture)
        files_generated.extend(backend_files)

        # 2. Generate database models
        logger.info("Generating SQLAlchemy models...")
        model_files = self._generate_models(project_dir, architecture)
        files_generated.extend(model_files)

        # 3. Generate migrations
        logger.info("Generating Alembic migrations...")
        migration_files = self._generate_migrations(project_dir, architecture)
        files_generated.extend(migration_files)

        # 4. Generate authentication system
        logger.info("Generating authentication system...")
        auth_files = self._generate_auth_system(project_dir, architecture)
        files_generated.extend(auth_files)

        # 5. Generate worker tasks
        if architecture.get("workers"):
            logger.info("Generating Celery workers...")
            worker_files = self._generate_workers(project_dir, architecture)
            files_generated.extend(worker_files)

        # 6. Generate frontend
        logger.info("Generating frontend templates...")
        frontend_files = self._generate_frontend(project_dir, architecture)
        files_generated.extend(frontend_files)

        # 7. Generate configuration files
        logger.info("Generating configuration files...")
        config_files = self._generate_config_files(
            project_dir,
            requirements,
            architecture
        )
        files_generated.extend(config_files)

        # 8. Generate requirements.txt
        logger.info("Generating requirements.txt...")
        req_file = self._generate_requirements_file(project_dir, architecture)
        files_generated.append(req_file)

        # 9. Generate README
        logger.info("Generating README.md...")
        readme_file = self._generate_readme(project_dir, requirements, architecture)
        files_generated.append(readme_file)

        return files_generated


    def _create_directory_structure(self, project_dir: Path):
        """Create standard FastAPI project structure."""
        directories = [
            "app",
            "app/api",
            "app/api/endpoints",
            "app/core",
            "app/models",
            "app/schemas",
            "app/crud",
            "app/db",
            "app/workers",
            "app/templates",
            "app/static",
            "app/static/css",
            "app/static/js",
            "alembic",
            "alembic/versions",
            "tests",
            "nginx",
            "systemd",
        ]

        for dir_path in directories:
            (project_dir / dir_path).mkdir(parents=True, exist_ok=True)

        # Create __init__.py files
        init_files = [
            "app/__init__.py",
            "app/api/__init__.py",
            "app/api/endpoints/__init__.py",
            "app/core/__init__.py",
            "app/models/__init__.py",
            "app/schemas/__init__.py",
            "app/crud/__init__.py",
            "app/db/__init__.py",
            "app/workers/__init__.py",
        ]

        for init_file in init_files:
            (project_dir / init_file).touch()

    def _generate_backend(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate FastAPI backend code."""
        from .generators import FastAPIGenerator

        generator = FastAPIGenerator()
        return generator.generate(project_dir, architecture)

    def _generate_models(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate SQLAlchemy models."""
        from .generators import ModelGenerator

        generator = ModelGenerator()
        return generator.generate(project_dir, architecture)

    def _generate_migrations(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate Alembic migrations."""
        from .generators import MigrationGenerator

        generator = MigrationGenerator()
        return generator.generate(project_dir, architecture)

    def _generate_auth_system(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate authentication system."""
        from .generators import AuthGenerator

        generator = AuthGenerator()
        return generator.generate(project_dir, architecture)

    def _generate_workers(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate Celery worker tasks."""
        from .generators import WorkerGenerator

        generator = WorkerGenerator()
        return generator.generate(project_dir, architecture)

    def _generate_frontend(self, project_dir: Path, architecture: Dict[str, Any]) -> List[str]:
        """Generate frontend templates."""
        from .generators import FrontendGenerator

        generator = FrontendGenerator()
        return generator.generate(project_dir, architecture)

    def _generate_config_files(
        self,
        project_dir: Path,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any]
    ) -> List[str]:
        """Generate configuration files."""
        from .generators import ConfigGenerator

        generator = ConfigGenerator()
        return generator.generate(project_dir, requirements, architecture)

    def _generate_requirements_file(self, project_dir: Path, architecture: Dict[str, Any]) -> str:
        """Generate requirements.txt with all dependencies."""
        # Base dependencies
        requirements = [
            "fastapi==0.104.1",
            "uvicorn[standard]==0.24.0",
            "sqlalchemy==2.0.23",
            "alembic==1.12.1",
            "psycopg2-binary==2.9.9",
            "python-jose[cryptography]==3.3.0",
            "passlib[bcrypt]==1.7.4",
            "python-multipart==0.0.6",
            "pydantic==2.5.0",
            "pydantic-settings==2.1.0",
            "python-dotenv==1.0.0",
        ]

        # Add Celery if workers exist (includes Redis automatically)
        if architecture.get("workers"):
            requirements.extend([
                "celery==5.3.4",
                "celery[redis]==5.3.4",
            ])
        # Add Redis standalone only if needed but no workers
        elif architecture.get("infrastructure", {}).get("redis", {}).get("enabled"):
            requirements.append("redis>=4.5.2,<5.0.0")

        # Add email dependencies if needed
        features = architecture.get("security", {})
        if features:
            requirements.append("emails==0.6")

        # Sort and write
        requirements.sort()
        req_file = project_dir / "requirements.txt"

        with open(req_file, 'w') as f:
            f.write("# Auto-generated requirements\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n\n")
            for req in requirements:
                f.write(f"{req}\n")

        return str(req_file.relative_to(project_dir.parent))

    def _generate_readme(
        self,
        project_dir: Path,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any]
    ) -> str:
        """Generate project README.md."""
        project_name = requirements.get("project_name", "Application")
        description = requirements.get("description", "")

        readme_content = f"""# {project_name}

{description}

**Auto-generated by Website Deployment Agent**
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## Features

"""

        # List features
        features = requirements.get("features", {})
        if features.get("authentication", {}).get("enabled"):
            readme_content += "- ✅ User Authentication (JWT)\n"
        if features.get("email_notifications", {}).get("enabled"):
            readme_content += "- ✅ Email Notifications\n"
        if features.get("llm_chat", {}).get("enabled"):
            readme_content += "- ✅ LLM Chat Integration\n"
        if features.get("background_workers", {}).get("enabled"):
            readme_content += "- ✅ Background Workers (Celery)\n"
        if features.get("file_uploads", {}).get("enabled"):
            readme_content += "- ✅ File Uploads\n"

        readme_content += """
## Tech Stack

- **Backend:** FastAPI
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy
- **Migrations:** Alembic
"""

        if architecture.get("workers"):
            readme_content += "- **Task Queue:** Celery + Redis\n"

        readme_content += "- **Frontend:** Alpine.js + Tailwind CSS\n"

        readme_content += """
## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL
"""

        if architecture.get("workers"):
            readme_content += "- Redis\n"

        readme_content += """
### Automated Setup (Recommended)

Run the automated setup script:

```bash
./setup.sh
```

This will automatically:
- Create and activate virtual environment
- Install all dependencies
- Generate secure SECRET_KEY
- Create PostgreSQL database
- Run database migrations
- Check for Redis (if using background workers)

### Manual Installation

If you prefer manual setup:

1. **Create virtual environment:**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\\Scripts\\activate
pip install -r requirements.txt
```

2. **Configure environment:**

```bash
cp .env.example .env
# Edit .env with your database credentials and settings
```

3. **Setup database:**

```bash
# Create database
sudo -u postgres createdb your_db_name

# Run migrations
alembic upgrade head
```

4. **Run development server:**

```bash
uvicorn app.main:app --reload --port 8000
```

"""

        if architecture.get("workers"):
            readme_content += """5. **Start Celery workers (separate terminal):**

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

"""

        readme_content += """## API Documentation

Once running, visit:
- **Interactive API Docs:** http://localhost:8000/docs
- **Alternative Docs:** http://localhost:8000/redoc

## Project Structure

```
"""

        readme_content += f"""{project_name}/
├── app/
│   ├── api/              # API endpoints
│   ├── core/             # Core configuration
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic schemas
│   ├── crud/             # Database operations
│   ├── workers/          # Celery tasks
│   ├── templates/        # HTML templates
│   └── main.py           # FastAPI application
├── alembic/              # Database migrations
├── tests/                # Test suite
├── nginx/                # Nginx configuration
├── apache2/              # Apache2 configuration
├── systemd/              # Systemd service files
└── requirements.txt      # Python dependencies
```

## Development

### Running Tests

```bash
pytest tests/
```

### Create New Migration

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Deployment

See deployment documentation for production setup with:
- **Web Server:** Nginx or Apache2 reverse proxy configurations are provided in `nginx/` and `apache2/` directories
- Systemd service management
- SSL certificates (Let's Encrypt)
- Database backups

### Web Server Setup

**For Nginx:**
```bash
sudo ln -s /var/www/{project_name}/nginx/{project_name}.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

**For Apache2:**
```bash
sudo ln -s /var/www/{project_name}/apache2/{project_name}.conf /etc/apache2/sites-enabled/
sudo a2enmod proxy proxy_http rewrite headers ssl
sudo apache2ctl configtest
sudo systemctl restart apache2
```

---

**Generated with:** [Website Deployment Agent](https://github.com/yourusername/website-deployer)
"""

        readme_file = project_dir / "README.md"
        with open(readme_file, 'w') as f:
            f.write(readme_content)

        return str(readme_file.relative_to(project_dir.parent))

    def _generate_summary(
        self,
        project_dir: Path,
        requirements: Dict[str, Any],
        architecture: Dict[str, Any],
        files_generated: List[str]
    ) -> Dict[str, Any]:
        """Generate generation summary."""
        return {
            "project_name": architecture.get("project_name"),
            "output_directory": str(project_dir),
            "files_generated": len(files_generated),
            "generation_time": datetime.now().isoformat(),
            "components": {
                "api_endpoints": len(architecture.get("api_endpoints", [])),
                "database_tables": len(architecture.get("database_schema", {}).get("tables", [])),
                "workers": len(architecture.get("workers", [])),
                "frontend_pages": len(architecture.get("frontend", {}).get("pages", [])),
            },
            "features": {
                "authentication": requirements.get("features", {}).get("authentication", {}).get("enabled", False),
                "workers": len(architecture.get("workers", [])) > 0,
                "frontend": len(architecture.get("frontend", {}).get("pages", [])) > 0,
            }
        }

    def _print_summary(self, summary: Dict[str, Any]):
        """Print generation summary."""
        print("\n" + "=" * 60)
        print("CODE GENERATION SUMMARY")
        print("=" * 60)

        print(f"\n📦 Project: {summary['project_name']}")
        print(f"📁 Output: {summary['output_directory']}")
        print(f"📄 Files Generated: {summary['files_generated']}")

        components = summary['components']
        print(f"\n🔧 Components:")
        print(f"   API Endpoints: {components['api_endpoints']}")
        print(f"   Database Tables: {components['database_tables']}")
        print(f"   Workers: {components['workers']}")
        print(f"   Frontend Pages: {components['frontend_pages']}")

        features = summary['features']
        print(f"\n✨ Features:")
        print(f"   Authentication: {'✅' if features['authentication'] else '❌'}")
        print(f"   Background Workers: {'✅' if features['workers'] else '❌'}")
        print(f"   Frontend: {'✅' if features['frontend'] else '❌'}")

        print("\n" + "=" * 60 + "\n")


# Example usage
if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load requirements and architecture
    req_file = Path("requirement_output.json")
    arch_file = Path("architecture_output.json")

    if not req_file.exists() or not arch_file.exists():
        print("❌ Requirements or architecture file not found")
        print("   Run requirement_analyzer and architecture_designer first")
        sys.exit(1)

    with open(req_file, 'r') as f:
        requirements = json.load(f)

    with open(arch_file, 'r') as f:
        architecture = json.load(f)

    # Generate code
    generator = CodeGenerator()
    result = generator.generate(requirements, architecture)

    if result.success:
        print(f"\n✅ Code generation successful!")
        print(f"📁 Project location: {result.output_directory}")
    else:
        print(f"\n❌ Code generation failed: {result.error_message}")
