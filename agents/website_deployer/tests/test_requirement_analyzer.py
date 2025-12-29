#!/usr/bin/env python3
"""
Test Suite for Requirement Analyzer
====================================

Tests the LLM-powered requirement extraction from natural language.

Author: RAICA Development Team
Version: 1.0.0
"""

import os
import json
import pytest
import logging
from pathlib import Path
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from stages.requirement_analyzer import RequirementAnalyzer, RequirementAnalysisResult

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@pytest.fixture
def analyzer():
    """Create analyzer instance (reads config from central llm_config.yaml)."""
    # Check if any LLM provider is configured
    api_keys = [
        os.getenv("ANTHROPIC_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("GEMINI_API_KEY"),
        os.getenv("QWEN_API_KEY"),
    ]

    if not any(api_keys):
        pytest.skip("No LLM API keys configured (set ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or QWEN_API_KEY)")

    return RequirementAnalyzer()


@pytest.fixture
def simple_task_manager_spec():
    """Simple task management app specification."""
    return """
    I need a simple task manager where users can:
    - Sign up and log in
    - Create and delete tasks
    - Mark tasks as complete

    Each task should have a title and completed status.
    """


@pytest.fixture
def complex_ecommerce_spec():
    """Complex e-commerce specification."""
    return """
    Build a full-featured e-commerce platform with:

    User Management:
    - Customer registration with email verification
    - OAuth login (Google, GitHub)
    - Two-factor authentication
    - User profiles with shipping addresses

    Product Catalog:
    - Product listings with images, descriptions, prices
    - Categories and subcategories
    - Inventory tracking
    - Product search and filtering

    Shopping:
    - Shopping cart
    - Wishlist
    - Checkout with multiple payment options
    - Order history

    Backend:
    - LLM-powered product recommendations
    - AI chatbot for customer support
    - Background workers for:
      - Email notifications (order confirmation, shipping updates)
      - Inventory sync
      - Daily sales reports

    Admin:
    - Admin dashboard with sales analytics
    - Product management (CRUD)
    - Order management
    - Customer management

    The app should have a modern, responsive design with a clean interface.
    """


@pytest.fixture
def blog_platform_spec():
    """Blog platform with LLM features."""
    return """
    Create a blog platform with AI-powered writing assistance:

    Features:
    - User registration and authentication
    - Create, edit, publish blog posts
    - Rich text editor
    - Image uploads for post headers
    - Comment system
    - LLM integration for:
      - Content suggestions
      - Grammar checking
      - Title generation
      - SEO optimization
    - Email notifications for new comments
    - RSS feed

    Database:
    - Users with email, name, bio, avatar
    - Posts with title, content, author, published date, status
    - Comments with author, post, content, timestamp
    - Categories and tags
    """


class TestRequirementAnalyzer:
    """Test cases for RequirementAnalyzer."""

    def test_analyzer_initialization(self, analyzer):
        """Test analyzer initializes correctly."""
        assert analyzer is not None
        assert analyzer.client is not None
        assert analyzer.schema is not None

    def test_simple_task_manager(self, analyzer, simple_task_manager_spec):
        """Test analysis of simple task manager specification."""
        result = analyzer.analyze(simple_task_manager_spec)

        assert result.success is True
        assert result.requirements is not None
        assert result.error_message is None

        # Check basic structure
        requirements = result.requirements
        assert "project_name" in requirements
        assert "features" in requirements
        assert "database" in requirements

        # Check authentication enabled
        assert requirements["features"]["authentication"]["enabled"] is True

        # Check has User and Task models
        models = requirements["database"]["models"]
        model_names = [m["name"].lower() for m in models]
        assert "user" in model_names
        assert "task" in model_names

        # Check complexity
        assert requirements["complexity_estimate"] in ["simple", "moderate"]

        # Print results
        print("\n" + "=" * 60)
        print("SIMPLE TASK MANAGER - EXTRACTED REQUIREMENTS")
        print("=" * 60)
        print(json.dumps(requirements, indent=2))

    def test_complex_ecommerce(self, analyzer, complex_ecommerce_spec):
        """Test analysis of complex e-commerce specification."""
        result = analyzer.analyze(complex_ecommerce_spec)

        assert result.success is True
        assert result.requirements is not None

        requirements = result.requirements

        # Check advanced features enabled
        assert requirements["features"]["authentication"]["enabled"] is True
        assert requirements["features"]["llm_chat"]["enabled"] is True
        assert requirements["features"]["background_workers"]["enabled"] is True
        assert requirements["features"]["file_uploads"]["enabled"] is True

        # Check OAuth methods
        auth_methods = requirements["features"]["authentication"]["methods"]
        assert "email_password" in auth_methods

        # Check has multiple models
        models = requirements["database"]["models"]
        assert len(models) >= 5  # User, Product, Order, Category, etc.

        # Check complexity
        assert requirements["complexity_estimate"] in ["complex", "enterprise"]

        # Print results
        print("\n" + "=" * 60)
        print("COMPLEX E-COMMERCE - EXTRACTED REQUIREMENTS")
        print("=" * 60)
        print(json.dumps(requirements, indent=2))

    def test_blog_platform_llm(self, analyzer, blog_platform_spec):
        """Test analysis of blog platform with LLM features."""
        result = analyzer.analyze(blog_platform_spec)

        assert result.success is True
        assert result.requirements is not None

        requirements = result.requirements

        # Check LLM chat enabled
        assert requirements["features"]["llm_chat"]["enabled"] is True

        # Check file uploads enabled (for images)
        assert requirements["features"]["file_uploads"]["enabled"] is True

        # Check email notifications
        assert requirements["features"]["email_notifications"]["enabled"] is True

        # Check has Post, Comment models
        models = requirements["database"]["models"]
        model_names = [m["name"].lower() for m in models]
        assert "post" in model_names or "blogpost" in model_names
        assert "comment" in model_names

        # Print results
        print("\n" + "=" * 60)
        print("BLOG PLATFORM - EXTRACTED REQUIREMENTS")
        print("=" * 60)
        print(json.dumps(requirements, indent=2))

    def test_validation_errors(self, analyzer):
        """Test validation catches missing required fields."""
        # Create invalid requirements
        invalid_requirements = {
            "project_name": "",  # Too short
            # Missing required fields
        }

        errors = analyzer._validate_requirements(invalid_requirements)
        assert len(errors) > 0
        assert any("project_name" in error.lower() for error in errors)
        assert any("missing required field" in error.lower() for error in errors)

    def test_save_requirements(self, analyzer, simple_task_manager_spec, tmp_path):
        """Test saving requirements to file."""
        result = analyzer.analyze(simple_task_manager_spec)
        assert result.success is True

        # Save to temp file
        output_file = tmp_path / "test_requirements.json"
        analyzer.save_requirements(result.requirements, output_file)

        # Verify file exists and is valid JSON
        assert output_file.exists()

        with open(output_file, 'r') as f:
            loaded = json.load(f)

        assert loaded == result.requirements

    def test_minimal_specification(self, analyzer):
        """Test with minimal specification."""
        minimal_spec = "Build a simple todo list app with user login."

        result = analyzer.analyze(minimal_spec)
        assert result.success is True
        assert result.requirements is not None

        # Should still have basic structure
        requirements = result.requirements
        assert "project_name" in requirements
        assert "features" in requirements
        assert requirements["features"]["authentication"]["enabled"] is True

    def test_schema_validation(self, analyzer):
        """Test schema validation for business rules."""
        # Requirements with authentication but no User model
        requirements = {
            "project_name": "Test App",
            "description": "Test",
            "features": {
                "authentication": {"enabled": True}
            },
            "tech_preferences": {},
            "database": {
                "models": [
                    {"name": "Task", "fields": [{"name": "title", "type": "string"}]}
                ]
            }
        }

        errors = analyzer._validate_requirements(requirements)
        # Should warn about missing User model
        assert any("user model" in error.lower() for error in errors)


class TestIntegration:
    """Integration tests with real specifications."""

    def test_end_to_end_workflow(self, analyzer, tmp_path):
        """Test complete workflow from spec to saved requirements."""
        spec = """
        Build a customer support ticketing system:
        - Users can submit support tickets
        - Support agents can respond to tickets
        - Email notifications for ticket updates
        - Admin dashboard with ticket statistics
        - LLM-powered suggested responses for agents
        """

        # Analyze
        result = analyzer.analyze(spec)
        assert result.success is True

        # Validate
        errors = analyzer._validate_requirements(result.requirements)
        # Warnings OK, but should have requirements
        assert result.requirements is not None

        # Save
        output_file = tmp_path / "support_system.json"
        analyzer.save_requirements(result.requirements, output_file)
        assert output_file.exists()

        # Verify saved file
        with open(output_file, 'r') as f:
            loaded = json.load(f)

        # Check key features
        assert loaded["features"]["authentication"]["enabled"] is True
        assert loaded["features"]["llm_chat"]["enabled"] is True
        assert loaded["features"]["email_notifications"]["enabled"] is True

        print(f"\n✅ End-to-end test passed: {output_file}")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
