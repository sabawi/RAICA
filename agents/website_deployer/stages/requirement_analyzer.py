#!/usr/bin/env python3
"""
Requirement Analyzer for Website Deployer Agent
================================================

Transforms natural language website specifications into structured JSON requirements.

Uses LLM to parse user prompts and extract:
- Core features (authentication, email, LLM chat, workers)
- Database models and relationships
- UI pages and components
- Technology preferences
- Complexity estimation

Author: RAICA Development Team
Version: 1.0.0
"""

import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict
from .llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class RequirementAnalysisResult:
    """Result of requirement analysis."""
    success: bool
    requirements: Optional[Dict[str, Any]] = None
    validation_errors: Optional[list] = None
    raw_llm_response: Optional[str] = None
    error_message: Optional[str] = None


class RequirementAnalyzer:
    """
    Analyzes natural language specifications and produces structured requirements.

    Uses Claude to understand user intent and extract detailed requirements
    in JSON format matching the requirement schema.
    """

    # LLM prompt template for requirement extraction
    ANALYSIS_PROMPT_TEMPLATE = """You are a senior software architect analyzing website requirements.

Given a natural language description of a website, extract detailed structured requirements.

USER SPECIFICATION:
{user_specification}

Your task is to analyze this specification and produce a comprehensive JSON requirement document.

EXTRACTION GUIDELINES:

1. **Project Name**: Extract or infer a concise project name
2. **Description**: Summarize the core purpose in 1-2 sentences
3. **Features**: Identify which features are needed:
   - Authentication: Look for login, signup, user accounts
   - Email: Look for notifications, verification, password reset
   - LLM Chat: Look for AI assistant, chatbot, LLM integration
   - Background Workers: Look for scheduled tasks, async processing, email sending
   - File Uploads: Look for image upload, file storage, attachments
   - API: Determine if REST API, GraphQL, or WebSockets needed

4. **Database Models**: Extract entities and their attributes
   - Identify nouns that represent data entities (User, Product, Order, etc.)
   - For each entity, determine fields with appropriate types
   - Identify relationships between entities

5. **UI Pages**: Identify required pages/views
   - Home, Login, Register (always for auth systems)
   - Dashboard, Profile (common for user systems)
   - CRUD pages for each major entity
   - Admin pages if mentioned

6. **Tech Preferences**: Use defaults unless specified:
   - Backend: FastAPI (default)
   - Frontend: Alpine.js + Tailwind (default)
   - Database: PostgreSQL (default)

7. **Complexity Estimate**:
   - Simple: Basic CRUD, 1-3 models, no background tasks
   - Moderate: Authentication, 3-5 models, basic background tasks
   - Complex: LLM integration, 5-10 models, multiple workers
   - Enterprise: Multi-tenant, advanced security, 10+ models

OUTPUT FORMAT:
Respond with ONLY valid JSON matching this exact structure (no markdown, no explanation):

{schema_example}

IMPORTANT:
- Return ONLY the JSON object (no markdown code blocks, no extra text)
- Ensure all JSON is valid and properly escaped
- Include reasonable defaults for unspecified features
- Be conservative - only enable features explicitly mentioned or clearly implied
- For database models, infer standard fields (id, created_at, updated_at automatically added)
"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize requirement analyzer.

        Args:
            config_path: Optional path to llm_config.yaml (uses project default if not provided)
        """
        self.client = LLMClient(config_path=config_path)

        # Load JSON schema
        schema_path = Path(__file__).parent.parent / "schemas" / "requirement_schema.json"
        with open(schema_path, 'r') as f:
            self.schema = json.load(f)

        logger.info("RequirementAnalyzer initialized")

    def analyze(self, user_specification: str) -> RequirementAnalysisResult:
        """
        Analyze natural language specification and extract structured requirements.

        Args:
            user_specification: Natural language description of website

        Returns:
            RequirementAnalysisResult with extracted requirements or errors
        """
        try:
            logger.info("=" * 60)
            logger.info("REQUIREMENT ANALYSIS STARTED")
            logger.info("=" * 60)
            logger.info(f"Input specification length: {len(user_specification)} characters")

            # Create schema example for prompt
            schema_example = self._create_schema_example()

            # Build prompt
            prompt = self.ANALYSIS_PROMPT_TEMPLATE.format(
                user_specification=user_specification,
                schema_example=schema_example
            )

            # Call LLM API (with multi-provider support and fallback)
            logger.info("Calling LLM API for requirement extraction...")

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
                requirements = json.loads(json_text)
                logger.info("✅ Successfully parsed JSON requirements")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse JSON response: {e}")
                logger.error(f"Raw response: {raw_response[:500]}...")

                return RequirementAnalysisResult(
                    success=False,
                    raw_llm_response=raw_response,
                    error_message=f"JSON parsing failed: {str(e)}"
                )

            # Validate against schema
            validation_errors = self._validate_requirements(requirements)

            if validation_errors:
                logger.warning(f"⚠️ Validation warnings: {len(validation_errors)} issues")
                for error in validation_errors:
                    logger.warning(f"  - {error}")
            else:
                logger.info("✅ Requirements passed validation")

            # Print summary
            self._print_summary(requirements)

            logger.info("=" * 60)
            logger.info("REQUIREMENT ANALYSIS COMPLETE")
            logger.info("=" * 60)

            return RequirementAnalysisResult(
                success=True,
                requirements=requirements,
                validation_errors=validation_errors if validation_errors else None,
                raw_llm_response=raw_response
            )



        except Exception as e:
            logger.error(f"❌ Unexpected error during analysis: {e}")
            return RequirementAnalysisResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}"
            )

    def _create_schema_example(self) -> str:
        """Create a minimal example matching the schema structure."""
        example = {
            "project_name": "Example App",
            "description": "Brief description of the application",
            "features": {
                "authentication": {
                    "enabled": True,
                    "methods": ["email_password"],
                    "email_verification": True,
                    "password_reset": True,
                    "two_factor": False
                },
                "email_notifications": {
                    "enabled": False
                },
                "llm_chat": {
                    "enabled": False
                },
                "background_workers": {
                    "enabled": False
                },
                "file_uploads": {
                    "enabled": False
                },
                "api": {
                    "rest_api": True,
                    "graphql": False,
                    "websockets": False,
                    "rate_limiting": True
                }
            },
            "database": {
                "type": "postgresql",
                "models": [
                    {
                        "name": "User",
                        "description": "Application user",
                        "fields": [
                            {"name": "email", "type": "email", "required": True, "unique": True},
                            {"name": "name", "type": "string", "required": True}
                        ],
                        "relationships": []
                    }
                ]
            },
            "ui_pages": [
                {"name": "Home", "route": "/", "auth_required": False},
                {"name": "Login", "route": "/login", "auth_required": False},
                {"name": "Dashboard", "route": "/dashboard", "auth_required": True}
            ],
            "tech_preferences": {
                "backend": "fastapi",
                "frontend": "alpine_tailwind",
                "css_framework": "tailwind",
                "database": "postgresql"
            },
            "deployment": {
                "ssl": True,
                "monitoring": True,
                "backup": True
            },
            "complexity_estimate": "moderate",
            "estimated_deployment_time_minutes": 30
        }

        return json.dumps(example, indent=2)

    def _validate_requirements(self, requirements: Dict[str, Any]) -> list:
        """
        Validate requirements against schema and business rules.

        Args:
            requirements: Extracted requirements dictionary

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check required top-level fields
        required_fields = ["project_name", "description", "features", "tech_preferences"]
        for field in required_fields:
            if field not in requirements:
                errors.append(f"Missing required field: {field}")

        # Validate project name
        if "project_name" in requirements:
            if not requirements["project_name"] or len(requirements["project_name"]) < 2:
                errors.append("Project name too short")

        # Validate database models if present
        if "database" in requirements and "models" in requirements["database"]:
            models = requirements["database"]["models"]
            if not models:
                errors.append("No database models defined")

            for model in models:
                if "name" not in model:
                    errors.append(f"Model missing name: {model}")
                if "fields" not in model or not model["fields"]:
                    errors.append(f"Model '{model.get('name', 'unknown')}' has no fields")

        # Validate UI pages if present
        if "ui_pages" in requirements:
            pages = requirements["ui_pages"]
            if not pages:
                errors.append("No UI pages defined")

            for page in pages:
                if "name" not in page or "route" not in page:
                    errors.append(f"Page missing name or route: {page}")

        # Business rule: Authentication enabled should have User model
        if requirements.get("features", {}).get("authentication", {}).get("enabled"):
            models = requirements.get("database", {}).get("models", [])
            model_names = [m.get("name", "").lower() for m in models]
            if "user" not in model_names:
                errors.append("Authentication enabled but no User model defined")

        return errors

    def _print_summary(self, requirements: Dict[str, Any]):
        """Print human-readable summary of requirements."""
        print("\n" + "=" * 60)
        print("REQUIREMENT ANALYSIS SUMMARY")
        print("=" * 60)

        print(f"\n📋 Project: {requirements.get('project_name', 'Unknown')}")
        print(f"Description: {requirements.get('description', 'N/A')}")

        # Features
        print("\n✨ Features:")
        features = requirements.get("features", {})
        for feature_name, feature_config in features.items():
            if isinstance(feature_config, dict) and feature_config.get("enabled"):
                print(f"  ✓ {feature_name.replace('_', ' ').title()}")

        # Database
        if "database" in requirements:
            models = requirements["database"].get("models", [])
            print(f"\n💾 Database Models: {len(models)}")
            for model in models:
                field_count = len(model.get("fields", []))
                print(f"  - {model.get('name')}: {field_count} fields")

        # UI Pages
        if "ui_pages" in requirements:
            pages = requirements["ui_pages"]
            print(f"\n🎨 UI Pages: {len(pages)}")
            for page in pages:
                auth = "🔒" if page.get("auth_required") else "🌐"
                print(f"  {auth} {page.get('route')}: {page.get('name')}")

        # Tech stack
        tech = requirements.get("tech_preferences", {})
        print(f"\n🔧 Tech Stack:")
        print(f"  Backend: {tech.get('backend', 'fastapi')}")
        print(f"  Frontend: {tech.get('frontend', 'alpine_tailwind')}")
        print(f"  Database: {tech.get('database', 'postgresql')}")

        # Complexity
        complexity = requirements.get("complexity_estimate", "unknown")
        deployment_time = requirements.get("estimated_deployment_time_minutes", "unknown")
        print(f"\n📊 Complexity: {complexity.upper()}")
        print(f"⏱️  Estimated Deployment Time: {deployment_time} minutes")

        print("=" * 60 + "\n")

    def save_requirements(self, requirements: Dict[str, Any], filepath: Path):
        """
        Save requirements to JSON file.

        Args:
            requirements: Requirements dictionary
            filepath: Path to save file
        """
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(requirements, f, indent=2)

            logger.info(f"✅ Requirements saved to: {filepath}")

        except Exception as e:
            logger.error(f"❌ Failed to save requirements: {e}")


# Example usage
if __name__ == "__main__":
    import os

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Example specification
    example_spec = """
    I need a task management application where users can:
    - Sign up and log in with email/password
    - Create, edit, and delete tasks
    - Organize tasks into projects
    - Assign tasks to team members
    - Set due dates and priorities
    - Receive email notifications for upcoming deadlines
    - View a dashboard with task statistics

    Each task should have a title, description, due date, priority level, and status.
    Projects should have a name, description, and color.
    Users should have email, name, and profile picture.

    The app should have a clean, modern interface with a sidebar for navigation.
    """

    # Get API key from environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY environment variable not set")
        exit(1)

    # Analyze requirements
    analyzer = RequirementAnalyzer(anthropic_api_key=api_key)
    result = analyzer.analyze(example_spec)

    if result.success:
        print("\n✅ Analysis successful!")

        # Save to file
        output_path = Path("requirement_output.json")
        analyzer.save_requirements(result.requirements, output_path)
    else:
        print(f"\n❌ Analysis failed: {result.error_message}")
