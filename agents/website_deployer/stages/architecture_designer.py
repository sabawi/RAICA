#!/usr/bin/env python3
"""
Architecture Designer for Website Deployer Agent
=================================================

Transforms structured requirements into detailed technical architecture.

Generates:
- RESTful API endpoint specifications
- Complete database schema with relationships
- Background worker task definitions
- Security configuration
- Infrastructure component selection
- Deployment plan

Author: RAICA Development Team
Version: 1.0.0
"""

import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass
from .llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class ArchitectureDesignResult:
    """Result of architecture design."""
    success: bool
    architecture: Optional[Dict[str, Any]] = None
    validation_errors: Optional[list] = None
    raw_llm_response: Optional[str] = None
    error_message: Optional[str] = None


class ArchitectureDesigner:
    """
    Designs detailed technical architecture from requirements.

    Uses Claude to transform structured requirements into comprehensive
    architecture specifications including API endpoints, database schema,
    workers, security, and deployment plan.
    """

    # LLM prompt template for architecture design
    DESIGN_PROMPT_TEMPLATE = """You are a senior software architect designing production-grade web application architecture.

Given structured requirements, design a complete technical architecture including API endpoints, database schema, workers, security, and infrastructure.

REQUIREMENTS:
{requirements_json}

Your task is to design comprehensive architecture covering all aspects of the application.

ARCHITECTURE DESIGN GUIDELINES:

## 1. API ENDPOINTS

Design RESTful API endpoints following best practices:

**Standard CRUD Patterns:**
- GET /api/resource - List all (with pagination)
- GET /api/resource/{{id}} - Get single item
- POST /api/resource - Create new
- PUT /api/resource/{{id}} - Update existing
- DELETE /api/resource/{{id}} - Delete

**Authentication Endpoints:**
- POST /api/auth/register - User registration
- POST /api/auth/login - User login
- POST /api/auth/logout - User logout
- POST /api/auth/refresh - Refresh token
- POST /api/auth/verify-email - Email verification
- POST /api/auth/forgot-password - Password reset request
- POST /api/auth/reset-password - Password reset

**For each endpoint specify:**
- HTTP method (GET, POST, PUT, DELETE)
- URL path with route parameters
- Handler function name (snake_case)
- Description
- Authentication required (true/false)
- Request body schema (for POST/PUT)
- Response schema with status code
- Query parameters (for filtering, pagination)
- Required permissions/roles

## 2. DATABASE SCHEMA

Design complete database schema with SQLAlchemy/Alembic in mind:

**Standard Tables for Authentication:**
```
users:
  - id: Integer (primary_key)
  - email: String(255) (unique, indexed)
  - hashed_password: String(255)
  - is_active: Boolean (default=True)
  - is_verified: Boolean (default=False)
  - created_at: DateTime
  - updated_at: DateTime
```

**For each table:**
- Table name (plural, snake_case)
- All columns with proper SQLAlchemy types
- Primary keys, foreign keys, indexes
- Unique constraints
- Default values
- Nullable settings

**Column Types:**
- Use Integer, String, Text, Boolean, DateTime, Date, Float, JSON, UUID
- String columns must have max_length
- Use Text for long content
- Use DateTime for timestamps
- Use JSON for flexible data

**Relationships:**
- Define all foreign key relationships
- Specify cascade behavior (CASCADE, SET NULL, RESTRICT)
- Include ORM relationship definitions (one_to_many, many_to_one, many_to_many)

**Standard Timestamp Pattern:**
Every table should have:
- created_at: DateTime (default=datetime.utcnow)
- updated_at: DateTime (default=datetime.utcnow, onupdate=datetime.utcnow)

## 3. BACKGROUND WORKERS

Design Celery/RQ worker tasks:

**Common Worker Tasks:**
- Email sending (welcome, verification, password reset, notifications)
- Report generation
- Data export/import
- Cleanup tasks (old data, temporary files)
- Scheduled analytics/aggregations
- LLM processing tasks

**For each worker:**
- Task name and description
- Function name (snake_case + _task suffix)
- Schedule type (periodic, on_demand, triggered)
- Cron expression or interval for periodic tasks
- Parameters with types
- Retry policy (max_retries, retry_delay)
- Timeout

## 4. SECURITY

Design security configuration:

**Authentication:**
- JWT with HS256 algorithm
- Access token: 30 minutes expiry
- Refresh token: 7 days expiry
- Bcrypt password hashing (12 rounds)

**CORS:**
- Allow specific origins
- Enable credentials
- Specify allowed methods

**Rate Limiting:**
- 60 requests/minute default
- Burst size: 10

**Input Validation:**
- Sanitize HTML inputs
- Max request size: 10MB

## 5. INFRASTRUCTURE

Select infrastructure components:

**Standard Stack:**
- Web Server: Nginx or Apache2 (choose based on requirements or user preference)
- App Server: Uvicorn with 4 workers
- Database: PostgreSQL
- Redis: For caching, sessions, task queue (if workers enabled)
- SSL: Let's Encrypt (if domain provided)
- Monitoring: systemd logs, web server logs

## 6. FRONTEND

Design frontend architecture:

**Alpine.js + Tailwind (default):**
- Server-side rendered HTML templates
- Alpine.js for interactivity
- Tailwind CSS for styling
- No build step required

**For each page:**
- Template file name
- Required components (navbar, forms, tables, modals)
- API dependencies (which endpoints it calls)

## 7. DEPLOYMENT PLAN

Create ordered deployment steps:

**Standard Steps:**
1. Install system packages (python3, postgresql, nginx, redis)
2. Create application user and directories
3. Setup Python virtual environment
4. Install Python dependencies
5. Configure PostgreSQL database
6. Run database migrations
7. Configure Nginx
8. Setup SSL with Let's Encrypt
9. Create systemd services
10. Start services
11. Verify deployment

OUTPUT FORMAT:

Respond with ONLY valid JSON matching this structure (no markdown, no explanation):

{architecture_example}

IMPORTANT:
- Return ONLY the JSON object (no markdown code blocks, no extra text)
- Ensure all JSON is valid and properly escaped
- Design for production-grade quality
- Include all security best practices
- Make architecture consistent with requirements
- Use proper naming conventions (snake_case for Python, PascalCase for models)
- Include reasonable defaults and industry standards
"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize architecture designer.

        Args:
            config_path: Optional path to llm_config.yaml (uses project default if not provided)
        """
        self.client = LLMClient(config_path=config_path)

        # Load JSON schema
        schema_path = Path(__file__).parent.parent / "schemas" / "architecture_schema.json"
        with open(schema_path, 'r') as f:
            self.schema = json.load(f)

        logger.info("ArchitectureDesigner initialized")

    def design(self, requirements: Dict[str, Any]) -> ArchitectureDesignResult:
        """
        Design technical architecture from requirements.

        Args:
            requirements: Structured requirements from RequirementAnalyzer

        Returns:
            ArchitectureDesignResult with architecture specification or errors
        """
        try:
            logger.info("=" * 60)
            logger.info("ARCHITECTURE DESIGN STARTED")
            logger.info("=" * 60)
            logger.info(f"Project: {requirements.get('project_name', 'Unknown')}")

            # Create architecture example for prompt
            architecture_example = self._create_architecture_example()

            # Build prompt
            prompt = self.DESIGN_PROMPT_TEMPLATE.format(
                requirements_json=json.dumps(requirements, indent=2),
                architecture_example=architecture_example
            )

            # Call LLM API (with multi-provider support and fallback)
            logger.info("Calling LLM API for architecture design...")

            response = self.client.generate(prompt)

            if not response.success:
                raise Exception(f"LLM generation failed: {response.error}")

            logger.info(f"✅ Used provider: {response.provider} / {response.model}")

            # Extract response
            raw_response = response.content.strip()
            logger.debug(f"Raw LLM response length: {len(raw_response)} characters")

            # Strip markdown code fences if present (common with some LLM providers)
            json_text = raw_response
            if json_text.startswith("```"):
                # Remove opening fence (```json or ```)
                lines = json_text.split('\n')
                if lines[0].startswith("```"):
                    lines = lines[1:]
                # Remove closing fence
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                json_text = '\n'.join(lines).strip()
                logger.debug("Stripped markdown code fences from response")

            # Parse JSON response
            try:
                architecture = json.loads(json_text)
                logger.info("✅ Successfully parsed JSON architecture")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse JSON response: {e}")
                logger.error(f"Raw response: {raw_response[:500]}...")

                return ArchitectureDesignResult(
                    success=False,
                    raw_llm_response=raw_response,
                    error_message=f"JSON parsing failed: {str(e)}"
                )

            # Validate architecture
            validation_errors = self._validate_architecture(architecture, requirements)

            if validation_errors:
                logger.warning(f"⚠️ Validation warnings: {len(validation_errors)} issues")
                for error in validation_errors:
                    logger.warning(f"  - {error}")
            else:
                logger.info("✅ Architecture passed validation")

            # Print summary
            self._print_summary(architecture)

            logger.info("=" * 60)
            logger.info("ARCHITECTURE DESIGN COMPLETE")
            logger.info("=" * 60)

            return ArchitectureDesignResult(
                success=True,
                architecture=architecture,
                validation_errors=validation_errors if validation_errors else None,
                raw_llm_response=raw_response
            )

        except anthropic.APIError as e:
            logger.error(f"❌ Anthropic API error: {e}")
            return ArchitectureDesignResult(
                success=False,
                error_message=f"API error: {str(e)}"
            )

        except Exception as e:
            logger.error(f"❌ Unexpected error during design: {e}")
            return ArchitectureDesignResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}"
            )

    def _create_architecture_example(self) -> str:
        """Create a minimal example architecture."""
        example = {
            "project_name": "example_app",
            "api_endpoints": [
                {
                    "method": "POST",
                    "path": "/api/auth/register",
                    "handler_name": "register_user",
                    "description": "Register new user account",
                    "auth_required": False,
                    "request_body": {
                        "fields": [
                            {"name": "email", "type": "string", "required": True},
                            {"name": "password", "type": "string", "required": True}
                        ]
                    },
                    "response": {
                        "status_code": 201,
                        "example": {"id": 1, "email": "user@example.com"}
                    }
                },
                {
                    "method": "GET",
                    "path": "/api/tasks",
                    "handler_name": "get_tasks",
                    "description": "List all tasks for authenticated user",
                    "auth_required": True,
                    "query_parameters": [
                        {"name": "page", "type": "integer", "required": False},
                        {"name": "limit", "type": "integer", "required": False}
                    ],
                    "response": {
                        "status_code": 200,
                        "example": {"tasks": [], "total": 0, "page": 1}
                    }
                }
            ],
            "database_schema": {
                "database_type": "postgresql",
                "tables": [
                    {
                        "name": "users",
                        "description": "User accounts",
                        "columns": [
                            {"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "email", "type": "String", "max_length": 255, "unique": True, "indexed": True, "nullable": False},
                            {"name": "hashed_password", "type": "String", "max_length": 255, "nullable": False},
                            {"name": "is_active", "type": "Boolean", "default": True},
                            {"name": "created_at", "type": "DateTime", "nullable": False},
                            {"name": "updated_at", "type": "DateTime", "nullable": False}
                        ]
                    },
                    {
                        "name": "tasks",
                        "description": "User tasks",
                        "columns": [
                            {"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "user_id", "type": "Integer", "nullable": False, "foreign_key": {"references": "users.id", "ondelete": "CASCADE"}},
                            {"name": "title", "type": "String", "max_length": 200, "nullable": False},
                            {"name": "completed", "type": "Boolean", "default": False},
                            {"name": "created_at", "type": "DateTime", "nullable": False}
                        ]
                    }
                ],
                "relationships": [
                    {
                        "model": "User",
                        "relationship_name": "tasks",
                        "target_model": "Task",
                        "relationship_type": "one_to_many",
                        "back_populates": "user"
                    }
                ]
            },
            "workers": [
                {
                    "name": "send_welcome_email",
                    "description": "Send welcome email to new users",
                    "function_name": "send_welcome_email_task",
                    "schedule": {"type": "on_demand"},
                    "parameters": [
                        {"name": "user_id", "type": "integer", "required": True},
                        {"name": "email", "type": "string", "required": True}
                    ],
                    "retry_policy": {"max_retries": 3, "retry_delay_seconds": 60}
                }
            ],
            "security": {
                "authentication": {
                    "method": "jwt",
                    "jwt_config": {
                        "algorithm": "HS256",
                        "access_token_expire_minutes": 30,
                        "refresh_token_expire_days": 7
                    },
                    "password_hashing": {
                        "algorithm": "bcrypt",
                        "rounds": 12
                    }
                },
                "cors": {
                    "allow_origins": ["http://localhost:3000"],
                    "allow_credentials": True,
                    "allow_methods": ["GET", "POST", "PUT", "DELETE"]
                },
                "rate_limiting": {
                    "enabled": True,
                    "requests_per_minute": 60
                }
            },
            "infrastructure": {
                "web_server": "nginx",  # or "apache2"
                "app_server": "uvicorn",
                "workers_per_instance": 4,
                "redis": {"enabled": True, "use_cases": ["task_queue", "caching"]},
                "ssl": {"enabled": True, "provider": "letsencrypt"}
            },
            "frontend": {
                "framework": "alpine_tailwind",
                "pages": [
                    {
                        "name": "Home",
                        "route": "/",
                        "template_file": "index.html",
                        "components": ["navbar"],
                        "api_dependencies": []
                    }
                ]
            }
        }

        return json.dumps(example, indent=2)

    def _validate_architecture(
        self,
        architecture: Dict[str, Any],
        requirements: Dict[str, Any]
    ) -> list:
        """
        Validate architecture against requirements.

        Args:
            architecture: Generated architecture
            requirements: Original requirements

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check required top-level fields
        required_fields = ["project_name", "api_endpoints", "database_schema", "security"]
        for field in required_fields:
            if field not in architecture:
                errors.append(f"Missing required field: {field}")

        # Validate API endpoints
        if "api_endpoints" in architecture:
            endpoints = architecture["api_endpoints"]

            # If auth is enabled, must have auth endpoints
            if requirements.get("features", {}).get("authentication", {}).get("enabled"):
                endpoint_paths = [ep.get("path", "") for ep in endpoints]
                if not any("/auth/" in path for path in endpoint_paths):
                    errors.append("Authentication enabled but no auth endpoints defined")

            # Check for duplicate paths
            paths = [(ep.get("method"), ep.get("path")) for ep in endpoints]
            if len(paths) != len(set(paths)):
                errors.append("Duplicate API endpoints detected")

        # Validate database schema
        if "database_schema" in architecture:
            schema = architecture["database_schema"]
            tables = schema.get("tables", [])

            if not tables:
                errors.append("No database tables defined")

            # If auth enabled, must have users table
            if requirements.get("features", {}).get("authentication", {}).get("enabled"):
                table_names = [t.get("name", "").lower() for t in tables]
                if "users" not in table_names:
                    errors.append("Authentication enabled but no users table")

            # Validate foreign keys reference existing tables
            table_names = [t.get("name") for t in tables]
            for table in tables:
                for column in table.get("columns", []):
                    fk = column.get("foreign_key")
                    if fk:
                        ref = fk.get("references", "").split(".")[0]
                        if ref and ref not in table_names:
                            errors.append(f"Foreign key references non-existent table: {ref}")

        # Validate workers
        if requirements.get("features", {}).get("background_workers", {}).get("enabled"):
            if "workers" not in architecture or not architecture["workers"]:
                errors.append("Background workers enabled but no workers defined")

        # Validate Redis for workers
        if architecture.get("workers"):
            redis_enabled = architecture.get("infrastructure", {}).get("redis", {}).get("enabled")
            if not redis_enabled:
                errors.append("Workers defined but Redis not enabled (required for task queue)")

        return errors

    def _print_summary(self, architecture: Dict[str, Any]):
        """Print human-readable summary of architecture."""
        print("\n" + "=" * 60)
        print("ARCHITECTURE DESIGN SUMMARY")
        print("=" * 60)

        print(f"\n🏗️  Project: {architecture.get('project_name', 'Unknown')}")

        # API Endpoints
        endpoints = architecture.get("api_endpoints", [])
        print(f"\n🌐 API Endpoints: {len(endpoints)}")
        methods = {}
        for ep in endpoints:
            method = ep.get("method", "GET")
            methods[method] = methods.get(method, 0) + 1
        for method, count in sorted(methods.items()):
            print(f"  {method}: {count}")

        # Database
        schema = architecture.get("database_schema", {})
        tables = schema.get("tables", [])
        print(f"\n💾 Database Tables: {len(tables)}")
        for table in tables:
            cols = len(table.get("columns", []))
            print(f"  - {table.get('name')}: {cols} columns")

        # Workers
        workers = architecture.get("workers", [])
        if workers:
            print(f"\n⚙️  Background Workers: {len(workers)}")
            for worker in workers:
                schedule_type = worker.get("schedule", {}).get("type", "on_demand")
                print(f"  - {worker.get('name')}: {schedule_type}")

        # Security
        security = architecture.get("security", {})
        auth = security.get("authentication", {})
        print(f"\n🔒 Security:")
        print(f"  Auth Method: {auth.get('method', 'N/A')}")
        print(f"  Rate Limiting: {'✓' if security.get('rate_limiting', {}).get('enabled') else '✗'}")

        # Infrastructure
        infra = architecture.get("infrastructure", {})
        print(f"\n🚀 Infrastructure:")
        print(f"  Web Server: {infra.get('web_server', 'N/A')}")
        print(f"  App Server: {infra.get('app_server', 'N/A')}")
        print(f"  Workers: {infra.get('workers_per_instance', 'N/A')}")
        print(f"  Redis: {'✓' if infra.get('redis', {}).get('enabled') else '✗'}")
        print(f"  SSL: {'✓' if infra.get('ssl', {}).get('enabled') else '✗'}")

        # Frontend
        frontend = architecture.get("frontend", {})
        pages = frontend.get("pages", [])
        print(f"\n🎨 Frontend Pages: {len(pages)}")
        for page in pages:
            print(f"  - {page.get('route')}: {page.get('name')}")

        print("=" * 60 + "\n")

    def save_architecture(self, architecture: Dict[str, Any], filepath: Path):
        """
        Save architecture to JSON file.

        Args:
            architecture: Architecture dictionary
            filepath: Path to save file
        """
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(architecture, f, indent=2)

            logger.info(f"✅ Architecture saved to: {filepath}")

        except Exception as e:
            logger.error(f"❌ Failed to save architecture: {e}")


# Example usage
if __name__ == "__main__":
    import os

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Load example requirements
    requirements_file = Path("requirement_output.json")
    if not requirements_file.exists():
        print("❌ No requirements file found. Run requirement_analyzer first.")
        exit(1)

    with open(requirements_file, 'r') as f:
        requirements = json.load(f)

    # Get API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY environment variable not set")
        exit(1)

    # Design architecture
    designer = ArchitectureDesigner(anthropic_api_key=api_key)
    result = designer.design(requirements)

    if result.success:
        print("\n✅ Architecture design successful!")

        # Save to file
        output_path = Path("architecture_output.json")
        designer.save_architecture(result.architecture, output_path)
    else:
        print(f"\n❌ Architecture design failed: {result.error_message}")
