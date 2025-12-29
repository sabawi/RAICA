#!/usr/bin/env python3
"""
Test Suite for Architecture Designer
=====================================

Tests the LLM-powered architecture generation from requirements.

Author: Agentic-RAG Development Team
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

from stages.architecture_designer import ArchitectureDesigner, ArchitectureDesignResult

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@pytest.fixture
def designer():
    """Create designer instance (reads config from central llm_config.yaml)."""
    # Check if any LLM provider is configured
    api_keys = [
        os.getenv("ANTHROPIC_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("GEMINI_API_KEY"),
        os.getenv("QWEN_API_KEY"),
    ]

    if not any(api_keys):
        pytest.skip("No LLM API keys configured (set ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or QWEN_API_KEY)")

    return ArchitectureDesigner()


@pytest.fixture
def simple_task_requirements():
    """Simple task manager requirements."""
    return {
        "project_name": "Task Manager",
        "description": "Simple task management application",
        "features": {
            "authentication": {
                "enabled": True,
                "methods": ["email_password"],
                "email_verification": True,
                "password_reset": True
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
                "rest_api": True
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
                    ]
                },
                {
                    "name": "Task",
                    "description": "User task",
                    "fields": [
                        {"name": "title", "type": "string", "required": True},
                        {"name": "description", "type": "text"},
                        {"name": "completed", "type": "boolean"}
                    ]
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
            "database": "postgresql"
        },
        "complexity_estimate": "simple"
    }


@pytest.fixture
def complex_ecommerce_requirements():
    """Complex e-commerce requirements."""
    return {
        "project_name": "E-Commerce Platform",
        "description": "Full-featured e-commerce platform",
        "features": {
            "authentication": {
                "enabled": True,
                "methods": ["email_password", "oauth_google"],
                "email_verification": True,
                "password_reset": True,
                "two_factor": True
            },
            "email_notifications": {
                "enabled": True,
                "notification_types": ["order_confirmation", "shipping_update"]
            },
            "llm_chat": {
                "enabled": True,
                "provider": "openai",
                "features": ["chat", "completion"]
            },
            "background_workers": {
                "enabled": True,
                "queue_system": "celery",
                "tasks": [
                    {"name": "process_orders", "schedule": "on_demand"},
                    {"name": "send_notifications", "schedule": "periodic"},
                    {"name": "generate_reports", "schedule": "periodic"}
                ]
            },
            "file_uploads": {
                "enabled": True,
                "max_file_size_mb": 10,
                "allowed_types": ["image/jpeg", "image/png"]
            },
            "api": {
                "rest_api": True,
                "websockets": True,
                "rate_limiting": True
            }
        },
        "database": {
            "type": "postgresql",
            "models": [
                {"name": "User", "fields": [{"name": "email", "type": "email"}]},
                {"name": "Product", "fields": [{"name": "name", "type": "string"}]},
                {"name": "Order", "fields": [{"name": "total", "type": "float"}]},
                {"name": "OrderItem", "fields": [{"name": "quantity", "type": "integer"}]},
                {"name": "Category", "fields": [{"name": "name", "type": "string"}]}
            ]
        },
        "ui_pages": [
            {"name": "Home", "route": "/"},
            {"name": "Products", "route": "/products"},
            {"name": "Cart", "route": "/cart", "auth_required": True},
            {"name": "Checkout", "route": "/checkout", "auth_required": True},
            {"name": "Admin", "route": "/admin", "auth_required": True}
        ],
        "tech_preferences": {
            "backend": "fastapi",
            "frontend": "alpine_tailwind",
            "database": "postgresql"
        },
        "complexity_estimate": "complex"
    }


class TestArchitectureDesigner:
    """Test cases for ArchitectureDesigner."""

    def test_designer_initialization(self, designer):
        """Test designer initializes correctly."""
        assert designer is not None
        assert designer.client is not None
        assert designer.schema is not None

    def test_simple_task_architecture(self, designer, simple_task_requirements):
        """Test architecture design for simple task manager."""
        result = designer.design(simple_task_requirements)

        assert result.success is True
        assert result.architecture is not None
        assert result.error_message is None

        arch = result.architecture

        # Check basic structure
        assert "project_name" in arch
        assert "api_endpoints" in arch
        assert "database_schema" in arch
        assert "security" in arch

        # Check auth endpoints exist
        endpoints = arch["api_endpoints"]
        endpoint_paths = [ep["path"] for ep in endpoints]
        assert any("/auth/" in path for path in endpoint_paths)

        # Check CRUD endpoints for tasks
        assert any("/tasks" in path for path in endpoint_paths)

        # Check database tables
        tables = arch["database_schema"]["tables"]
        table_names = [t["name"] for t in tables]
        assert "users" in table_names
        assert "tasks" in table_names

        # Check security config
        security = arch["security"]
        assert "authentication" in security
        assert security["authentication"]["method"] == "jwt"

        print("\n" + "=" * 60)
        print("SIMPLE TASK MANAGER - ARCHITECTURE")
        print("=" * 60)
        print(json.dumps(arch, indent=2))

    def test_complex_ecommerce_architecture(self, designer, complex_ecommerce_requirements):
        """Test architecture design for complex e-commerce platform."""
        result = designer.design(complex_ecommerce_requirements)

        assert result.success is True
        assert result.architecture is not None

        arch = result.architecture

        # Check has many endpoints (products, orders, cart, etc.)
        endpoints = arch["api_endpoints"]
        assert len(endpoints) >= 15  # Complex app should have many endpoints

        # Check has many database tables
        tables = arch["database_schema"]["tables"]
        assert len(tables) >= 5

        # Check workers defined (background processing enabled)
        assert "workers" in arch
        workers = arch["workers"]
        assert len(workers) >= 3  # Email, reports, processing

        # Check Redis enabled for workers
        redis_config = arch["infrastructure"]["redis"]
        assert redis_config["enabled"] is True
        assert "task_queue" in redis_config["use_cases"]

        # Check security has OAuth
        security = arch["security"]
        auth = security["authentication"]
        if "oauth_providers" in auth:
            assert len(auth["oauth_providers"]) > 0

        print("\n" + "=" * 60)
        print("COMPLEX E-COMMERCE - ARCHITECTURE")
        print("=" * 60)
        print(json.dumps(arch, indent=2))

    def test_validation_catches_missing_auth_endpoints(self, designer):
        """Test validation catches missing auth endpoints when auth is enabled."""
        requirements = {
            "project_name": "Test",
            "features": {
                "authentication": {"enabled": True}
            },
            "database": {"models": [{"name": "User"}]},
            "tech_preferences": {}
        }

        architecture = {
            "project_name": "test",
            "api_endpoints": [
                {"method": "GET", "path": "/api/items"}
                # Missing auth endpoints
            ],
            "database_schema": {
                "tables": [{"name": "users", "columns": []}]
            },
            "security": {}
        }

        errors = designer._validate_architecture(architecture, requirements)
        assert any("auth endpoints" in error.lower() for error in errors)

    def test_validation_catches_missing_users_table(self, designer):
        """Test validation catches missing users table when auth is enabled."""
        requirements = {
            "project_name": "Test",
            "features": {
                "authentication": {"enabled": True}
            },
            "database": {"models": []},
            "tech_preferences": {}
        }

        architecture = {
            "project_name": "test",
            "api_endpoints": [],
            "database_schema": {
                "tables": [
                    {"name": "tasks", "columns": []}
                    # Missing users table
                ]
            },
            "security": {}
        }

        errors = designer._validate_architecture(architecture, requirements)
        assert any("users table" in error.lower() for error in errors)

    def test_validation_catches_invalid_foreign_keys(self, designer):
        """Test validation catches foreign keys to non-existent tables."""
        requirements = {"project_name": "Test", "features": {}, "database": {"models": []}, "tech_preferences": {}}

        architecture = {
            "project_name": "test",
            "api_endpoints": [],
            "database_schema": {
                "tables": [
                    {
                        "name": "tasks",
                        "columns": [
                            {
                                "name": "user_id",
                                "type": "Integer",
                                "foreign_key": {"references": "nonexistent.id"}
                            }
                        ]
                    }
                ]
            },
            "security": {}
        }

        errors = designer._validate_architecture(architecture, requirements)
        assert any("non-existent table" in error.lower() for error in errors)

    def test_validation_catches_workers_without_redis(self, designer):
        """Test validation catches workers without Redis enabled."""
        requirements = {
            "project_name": "Test",
            "features": {"background_workers": {"enabled": True}},
            "database": {"models": []},
            "tech_preferences": {}
        }

        architecture = {
            "project_name": "test",
            "api_endpoints": [],
            "database_schema": {"tables": []},
            "security": {},
            "workers": [
                {"name": "send_email", "function_name": "send_email_task"}
            ],
            "infrastructure": {
                "redis": {"enabled": False}  # Redis not enabled!
            }
        }

        errors = designer._validate_architecture(architecture, requirements)
        assert any("redis" in error.lower() and "task queue" in error.lower() for error in errors)

    def test_save_architecture(self, designer, simple_task_requirements, tmp_path):
        """Test saving architecture to file."""
        result = designer.design(simple_task_requirements)
        assert result.success is True

        # Save to temp file
        output_file = tmp_path / "test_architecture.json"
        designer.save_architecture(result.architecture, output_file)

        # Verify file exists and is valid JSON
        assert output_file.exists()

        with open(output_file, 'r') as f:
            loaded = json.load(f)

        assert loaded == result.architecture

    def test_api_endpoint_structure(self, designer, simple_task_requirements):
        """Test API endpoint structure is complete."""
        result = designer.design(simple_task_requirements)
        assert result.success is True

        endpoints = result.architecture["api_endpoints"]
        assert len(endpoints) > 0

        # Check first endpoint has required fields
        first_endpoint = endpoints[0]
        required_fields = ["method", "path", "handler_name", "description"]
        for field in required_fields:
            assert field in first_endpoint

    def test_database_schema_structure(self, designer, simple_task_requirements):
        """Test database schema structure is complete."""
        result = designer.design(simple_task_requirements)
        assert result.success is True

        schema = result.architecture["database_schema"]
        assert "database_type" in schema
        assert "tables" in schema

        tables = schema["tables"]
        assert len(tables) > 0

        # Check first table has required structure
        first_table = tables[0]
        assert "name" in first_table
        assert "columns" in first_table

        # Check columns have required fields
        columns = first_table["columns"]
        assert len(columns) > 0

        first_column = columns[0]
        assert "name" in first_column
        assert "type" in first_column


class TestIntegration:
    """Integration tests combining requirements and architecture."""

    def test_end_to_end_pipeline(self, designer, tmp_path):
        """Test complete pipeline from requirements to architecture."""
        from stages import RequirementAnalyzer

        # Get API key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        # Step 1: Analyze requirements
        spec = """
        Build a blog platform where users can:
        - Register and log in
        - Create and publish blog posts
        - Comment on posts
        - Upload header images
        """

        analyzer = RequirementAnalyzer(anthropic_api_key=api_key)
        req_result = analyzer.analyze(spec)
        assert req_result.success is True

        # Step 2: Design architecture
        arch_result = designer.design(req_result.requirements)
        assert arch_result.success is True

        # Verify architecture has key components
        arch = arch_result.architecture
        assert "api_endpoints" in arch
        assert "database_schema" in arch

        # Check has auth, posts, comments endpoints
        endpoints = [ep["path"] for ep in arch["api_endpoints"]]
        assert any("/auth/" in path for path in endpoints)
        assert any("post" in path.lower() for path in endpoints)
        assert any("comment" in path.lower() for path in endpoints)

        # Save both
        analyzer.save_requirements(req_result.requirements, tmp_path / "requirements.json")
        designer.save_architecture(arch_result.architecture, tmp_path / "architecture.json")

        assert (tmp_path / "requirements.json").exists()
        assert (tmp_path / "architecture.json").exists()

        print("\n✅ End-to-end pipeline test passed!")


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
