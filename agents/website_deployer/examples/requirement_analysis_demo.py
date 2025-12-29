#!/usr/bin/env python3
"""
Requirement Analysis Demo
=========================

Demonstrates how to use the RequirementAnalyzer to convert natural language
specifications into structured JSON requirements.

Uses the multi-provider LLM system configured in /config/llm_config.yaml.
Supports: Anthropic Claude, OpenAI GPT, Google Gemini, Qwen, Local Ollama.

Usage:
    # Ensure at least one LLM API key is set in .env file
    # The system will use the provider configured in config/llm_config.yaml
    python examples/requirement_analysis_demo.py

Author: RAICA Development Team
Version: 1.0.1
"""

import os
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from stages import RequirementAnalyzer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Run requirement analysis demo."""
    print("=" * 60)
    print("WEBSITE DEPLOYMENT AGENT - REQUIREMENT ANALYSIS DEMO")
    print("=" * 60)
    print()
    print("Using multi-provider LLM system")
    print("Provider: Configured in /config/llm_config.yaml")
    print("API Keys: Loaded from .env file")
    print()

    # Example specifications
    examples = {
        "1. Simple Todo App": """
        I want a simple todo list application where users can:
        - Sign up with email and password
        - Create, edit, and delete tasks
        - Mark tasks as complete
        - See all their tasks in a list

        Each task should have:
        - Title (required)
        - Description (optional)
        - Due date (optional)
        - Completed checkbox

        The UI should be clean and minimal.
        """,

        "2. E-Learning Platform": """
        Build an online learning platform with the following features:

        User Roles:
        - Students can enroll in courses and take lessons
        - Instructors can create and manage courses
        - Admins can manage users and courses

        Core Features:
        - Course catalog with search and filtering
        - Video lessons with progress tracking
        - Quizzes and assignments
        - Discussion forums for each course
        - Certificates upon course completion
        - LLM-powered study assistant for students
        - Email notifications for:
          - New course enrollments
          - Assignment deadlines
          - Certificate awards

        Database:
        - Users (students, instructors, admins)
        - Courses with lessons, quizzes, assignments
        - Enrollments linking students to courses
        - Progress tracking
        - Certificates

        The platform should have separate dashboards for students and instructors.
        """,

        "3. Inventory Management System": """
        Create an inventory management system for a small warehouse:

        Features:
        - Product catalog with SKU, name, description, quantity, price
        - Supplier management
        - Purchase orders
        - Stock adjustments
        - Low stock alerts via email
        - Barcode scanning for products
        - Reports: inventory value, stock movement, low stock items
        - Multi-location support (different warehouses)
        - Background worker to:
          - Send daily inventory reports via email
          - Check for low stock and alert managers
          - Sync with external systems

        Users:
        - Warehouse staff can view and update inventory
        - Managers can generate reports and manage suppliers
        - Admin can manage users

        The system should have a dashboard showing:
        - Total inventory value
        - Low stock items
        - Recent stock movements
        - Top products by value
        """
    }

    # Let user choose example
    print("\nAvailable example specifications:")
    for key, spec in examples.items():
        print(f"  {key}")

    choice = input("\nEnter number (1-3) or 'q' to quit: ").strip()

    if choice.lower() == 'q':
        print("Goodbye!")
        return

    # Get selected example
    example_key = list(examples.keys())[int(choice) - 1]
    spec = examples[example_key]

    print(f"\n{'=' * 60}")
    print(f"ANALYZING: {example_key}")
    print(f"{'=' * 60}")
    print("\nUser Specification:")
    print(spec)

    # Create analyzer
    analyzer = RequirementAnalyzer()

    # Analyze specification
    print("\n" + "=" * 60)
    print("CALLING LLM API FOR REQUIREMENT EXTRACTION...")
    print("=" * 60)

    result = analyzer.analyze(spec)

    if not result.success:
        print(f"\n❌ Analysis failed: {result.error_message}")
        return

    print("\n✅ ANALYSIS SUCCESSFUL!\n")

    # Save results
    output_dir = Path("requirement_output")
    output_dir.mkdir(exist_ok=True)

    filename = example_key.split('.')[1].strip().lower().replace(' ', '_')
    output_path = output_dir / f"{filename}_requirements.json"

    analyzer.save_requirements(result.requirements, output_path)

    # Show validation warnings if any
    if result.validation_errors:
        print("\n⚠️  VALIDATION WARNINGS:")
        for error in result.validation_errors:
            print(f"  - {error}")

    # Interactive exploration
    print("\n" + "=" * 60)
    print("INTERACTIVE EXPLORATION")
    print("=" * 60)

    while True:
        print("\nOptions:")
        print("  1. View feature summary")
        print("  2. View database models")
        print("  3. View UI pages")
        print("  4. View tech stack")
        print("  5. View full JSON")
        print("  q. Quit")

        option = input("\nSelect option: ").strip()

        if option == 'q':
            break
        elif option == '1':
            _show_features(result.requirements)
        elif option == '2':
            _show_database_models(result.requirements)
        elif option == '3':
            _show_ui_pages(result.requirements)
        elif option == '4':
            _show_tech_stack(result.requirements)
        elif option == '5':
            import json
            print("\n" + json.dumps(result.requirements, indent=2))
        else:
            print("Invalid option")

    print("\n" + "=" * 60)
    print(f"Requirements saved to: {output_path}")
    print("=" * 60)


def _show_features(requirements):
    """Show enabled features."""
    print("\n" + "=" * 60)
    print("ENABLED FEATURES")
    print("=" * 60)

    features = requirements.get("features", {})

    for feature_name, config in features.items():
        if isinstance(config, dict):
            enabled = config.get("enabled", False)
            status = "✅" if enabled else "❌"
            print(f"{status} {feature_name.replace('_', ' ').title()}")

            if enabled and feature_name == "authentication":
                methods = config.get("methods", [])
                print(f"    Methods: {', '.join(methods)}")
                print(f"    Email verification: {config.get('email_verification')}")
                print(f"    Two-factor: {config.get('two_factor')}")

            elif enabled and feature_name == "llm_chat":
                provider = config.get("provider", "unknown")
                print(f"    Provider: {provider}")

            elif enabled and feature_name == "background_workers":
                queue = config.get("queue_system", "unknown")
                tasks = config.get("tasks", [])
                print(f"    Queue: {queue}")
                print(f"    Tasks: {len(tasks)}")


def _show_database_models(requirements):
    """Show database models."""
    print("\n" + "=" * 60)
    print("DATABASE MODELS")
    print("=" * 60)

    models = requirements.get("database", {}).get("models", [])
    print(f"\nTotal models: {len(models)}\n")

    for model in models:
        name = model.get("name", "Unknown")
        description = model.get("description", "")
        fields = model.get("fields", [])

        print(f"📦 {name}")
        if description:
            print(f"   {description}")

        print(f"   Fields ({len(fields)}):")
        for field in fields:
            field_name = field.get("name")
            field_type = field.get("type")
            required = "required" if field.get("required") else "optional"
            unique = "unique" if field.get("unique") else ""
            flags = f"{required} {unique}".strip()
            print(f"      - {field_name}: {field_type} ({flags})")

        relationships = model.get("relationships", [])
        if relationships:
            print(f"   Relationships:")
            for rel in relationships:
                rel_type = rel.get("type")
                target = rel.get("target_model")
                print(f"      - {rel_type} → {target}")

        print()


def _show_ui_pages(requirements):
    """Show UI pages."""
    print("\n" + "=" * 60)
    print("UI PAGES")
    print("=" * 60)

    pages = requirements.get("ui_pages", [])
    print(f"\nTotal pages: {len(pages)}\n")

    for page in pages:
        name = page.get("name")
        route = page.get("route")
        auth = "🔒" if page.get("auth_required") else "🌐"
        description = page.get("description", "")

        print(f"{auth} {route} - {name}")
        if description:
            print(f"   {description}")


def _show_tech_stack(requirements):
    """Show technology stack."""
    print("\n" + "=" * 60)
    print("TECHNOLOGY STACK")
    print("=" * 60)

    tech = requirements.get("tech_preferences", {})
    deployment = requirements.get("deployment", {})

    print(f"\n🔧 Backend: {tech.get('backend', 'fastapi')}")
    print(f"🎨 Frontend: {tech.get('frontend', 'alpine_tailwind')}")
    print(f"💾 Database: {tech.get('database', 'postgresql')}")
    print(f"🎨 CSS: {tech.get('css_framework', 'tailwind')}")

    print(f"\n🚀 Deployment:")
    print(f"   SSL: {'✅' if deployment.get('ssl') else '❌'}")
    print(f"   Monitoring: {'✅' if deployment.get('monitoring') else '❌'}")
    print(f"   Backup: {'✅' if deployment.get('backup') else '❌'}")

    complexity = requirements.get("complexity_estimate", "unknown")
    time = requirements.get("estimated_deployment_time_minutes", "unknown")
    print(f"\n📊 Complexity: {complexity.upper()}")
    print(f"⏱️  Deployment Time: {time} minutes")


if __name__ == "__main__":
    main()
