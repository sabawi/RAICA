#!/usr/bin/env python3
"""
Architecture Design Demo
========================

Demonstrates the complete pipeline from natural language specification
to detailed technical architecture.

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python examples/architecture_design_demo.py

Author: RAICA Development Team
Version: 1.0.0
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from stages import RequirementAnalyzer, ArchitectureDesigner

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Run complete architecture design demo."""
    print("=" * 60)
    print("WEBSITE DEPLOYMENT AGENT - ARCHITECTURE DESIGN DEMO")
    print("=" * 60)
    print()
    print("Using multi-provider LLM system")
    print("Provider: Configured in /config/llm_config.yaml")
    print()

    # Example specifications
    examples = {
        "1. Task Manager (Simple)": """
        Build a task management app where users can:
        - Sign up and log in with email/password
        - Create, edit, and delete tasks
        - Mark tasks as complete
        - Organize tasks into projects

        Each task should have title, description, due date, and priority.
        Simple, clean interface.
        """,

        "2. Blog Platform (Moderate)": """
        Create a blog platform with:

        Features:
        - User registration and authentication
        - Create, edit, publish blog posts with rich text
        - Comment system
        - Image uploads for post headers
        - Categories and tags
        - Email notifications for new comments

        Users should be able to see their own posts and drafts.
        Public pages for viewing published posts.
        """,

        "3. E-Commerce (Complex)": """
        Build an e-commerce platform with:

        Features:
        - Customer accounts with OAuth (Google)
        - Product catalog with search and filters
        - Shopping cart and wishlist
        - Checkout with order processing
        - Order history and tracking
        - Admin dashboard for product/order management
        - Email notifications (order confirmation, shipping)
        - Background workers for:
          - Processing orders
          - Sending emails
          - Generating daily sales reports
        - Product image uploads
        - LLM-powered product recommendations

        Modern, responsive design with professional UI.
        """
    }

    # Let user choose
    print("\nAvailable example specifications:")
    for key in examples.keys():
        print(f"  {key}")

    choice = input("\nEnter number (1-3) or 'q' to quit: ").strip()

    if choice.lower() == 'q':
        print("Goodbye!")
        return

    # Get selected example
    example_key = list(examples.keys())[int(choice) - 1]
    spec = examples[example_key]

    print(f"\n{'=' * 60}")
    print(f"DESIGNING: {example_key}")
    print(f"{'=' * 60}")
    print("\nUser Specification:")
    print(spec)

    # Create output directory
    output_dir = Path("architecture_output")
    output_dir.mkdir(exist_ok=True)

    filename = example_key.split('.')[1].strip().lower().replace(' ', '_')

    # Phase 1: Requirements Analysis
    print("\n" + "=" * 60)
    print("PHASE 1: REQUIREMENTS ANALYSIS")
    print("=" * 60)

    analyzer = RequirementAnalyzer()
    req_result = analyzer.analyze(spec)

    if not req_result.success:
        print(f"\n❌ Requirements analysis failed: {req_result.error_message}")
        return

    print("\n✅ Requirements analysis successful!")

    # Save requirements
    req_path = output_dir / f"{filename}_requirements.json"
    analyzer.save_requirements(req_result.requirements, req_path)

    # Phase 2: Architecture Design
    print("\n" + "=" * 60)
    print("PHASE 2: ARCHITECTURE DESIGN")
    print("=" * 60)

    designer = ArchitectureDesigner()
    arch_result = designer.design(req_result.requirements)

    if not arch_result.success:
        print(f"\n❌ Architecture design failed: {arch_result.error_message}")
        return

    print("\n✅ Architecture design successful!")

    # Save architecture
    arch_path = output_dir / f"{filename}_architecture.json"
    designer.save_architecture(arch_result.architecture, arch_path)

    # Show validation warnings if any
    if arch_result.validation_errors:
        print("\n⚠️  VALIDATION WARNINGS:")
        for error in arch_result.validation_errors:
            print(f"  - {error}")

    # Interactive exploration
    print("\n" + "=" * 60)
    print("ARCHITECTURE EXPLORATION")
    print("=" * 60)

    while True:
        print("\nOptions:")
        print("  1. View API endpoints")
        print("  2. View database schema")
        print("  3. View background workers")
        print("  4. View security configuration")
        print("  5. View infrastructure")
        print("  6. View frontend pages")
        print("  7. View deployment plan")
        print("  8. View full architecture JSON")
        print("  9. Compare with requirements")
        print("  q. Quit")

        option = input("\nSelect option: ").strip()

        if option == 'q':
            break
        elif option == '1':
            _show_api_endpoints(arch_result.architecture)
        elif option == '2':
            _show_database_schema(arch_result.architecture)
        elif option == '3':
            _show_workers(arch_result.architecture)
        elif option == '4':
            _show_security(arch_result.architecture)
        elif option == '5':
            _show_infrastructure(arch_result.architecture)
        elif option == '6':
            _show_frontend(arch_result.architecture)
        elif option == '7':
            _show_deployment_plan(arch_result.architecture)
        elif option == '8':
            print("\n" + json.dumps(arch_result.architecture, indent=2))
        elif option == '9':
            _compare_with_requirements(req_result.requirements, arch_result.architecture)
        else:
            print("Invalid option")

    print("\n" + "=" * 60)
    print(f"Requirements saved to: {req_path}")
    print(f"Architecture saved to: {arch_path}")
    print("=" * 60)


def _show_api_endpoints(arch):
    """Show API endpoints grouped by resource."""
    print("\n" + "=" * 60)
    print("API ENDPOINTS")
    print("=" * 60)

    endpoints = arch.get("api_endpoints", [])
    print(f"\nTotal endpoints: {len(endpoints)}\n")

    # Group by resource
    grouped = {}
    for ep in endpoints:
        path = ep["path"]
        # Extract resource (e.g., /api/tasks -> tasks)
        parts = path.split('/')
        resource = parts[2] if len(parts) > 2 else "other"

        if resource not in grouped:
            grouped[resource] = []
        grouped[resource].append(ep)

    # Display grouped
    for resource, eps in sorted(grouped.items()):
        print(f"📁 /{resource}")
        for ep in eps:
            method = ep["method"].ljust(6)
            auth = "🔒" if ep.get("auth_required") else "🌐"
            print(f"  {auth} {method} {ep['path']}")
            print(f"      → {ep['handler_name']}()")
            print(f"      {ep['description']}")
        print()


def _show_database_schema(arch):
    """Show database schema with relationships."""
    print("\n" + "=" * 60)
    print("DATABASE SCHEMA")
    print("=" * 60)

    schema = arch.get("database_schema", {})
    db_type = schema.get("database_type", "unknown")
    tables = schema.get("tables", [])

    print(f"\nDatabase: {db_type}")
    print(f"Tables: {len(tables)}\n")

    for table in tables:
        name = table.get("name")
        description = table.get("description", "")
        columns = table.get("columns", [])

        print(f"📊 {name}")
        if description:
            print(f"   {description}")

        print(f"   Columns ({len(columns)}):")
        for col in columns:
            col_name = col["name"]
            col_type = col["type"]

            flags = []
            if col.get("primary_key"):
                flags.append("PK")
            if col.get("unique"):
                flags.append("UNIQUE")
            if col.get("indexed"):
                flags.append("INDEX")
            if not col.get("nullable", True):
                flags.append("NOT NULL")
            if col.get("foreign_key"):
                fk = col["foreign_key"]
                flags.append(f"FK → {fk['references']}")

            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"      • {col_name}: {col_type}{flag_str}")

        # Show indexes
        indexes = table.get("indexes", [])
        if indexes:
            print(f"   Indexes:")
            for idx in indexes:
                cols = ", ".join(idx["columns"])
                unique = " (UNIQUE)" if idx.get("unique") else ""
                print(f"      • {idx['name']}: ({cols}){unique}")

        print()

    # Show relationships
    relationships = schema.get("relationships", [])
    if relationships:
        print("🔗 Relationships:")
        for rel in relationships:
            print(f"  {rel['model']}.{rel['relationship_name']} → {rel['target_model']}")
            print(f"    Type: {rel['relationship_type']}")
        print()


def _show_workers(arch):
    """Show background worker tasks."""
    print("\n" + "=" * 60)
    print("BACKGROUND WORKERS")
    print("=" * 60)

    workers = arch.get("workers", [])

    if not workers:
        print("\nNo background workers configured.")
        return

    print(f"\nTotal workers: {len(workers)}\n")

    for worker in workers:
        name = worker["name"]
        description = worker["description"]
        function_name = worker["function_name"]
        schedule = worker.get("schedule", {})
        schedule_type = schedule.get("type", "on_demand")

        print(f"⚙️  {name}")
        print(f"   {description}")
        print(f"   Function: {function_name}()")
        print(f"   Schedule: {schedule_type}")

        if schedule_type == "periodic":
            if "cron" in schedule:
                print(f"   Cron: {schedule['cron']}")
            elif "interval_seconds" in schedule:
                interval = schedule["interval_seconds"]
                print(f"   Interval: Every {interval} seconds")

        params = worker.get("parameters", [])
        if params:
            print(f"   Parameters:")
            for param in params:
                req = "required" if param.get("required") else "optional"
                print(f"      • {param['name']}: {param['type']} ({req})")

        retry = worker.get("retry_policy", {})
        print(f"   Retry: {retry.get('max_retries', 3)} attempts, {retry.get('retry_delay_seconds', 60)}s delay")

        print()


def _show_security(arch):
    """Show security configuration."""
    print("\n" + "=" * 60)
    print("SECURITY CONFIGURATION")
    print("=" * 60)

    security = arch.get("security", {})

    # Authentication
    auth = security.get("authentication", {})
    print("\n🔐 Authentication:")
    print(f"   Method: {auth.get('method', 'N/A')}")

    if "jwt_config" in auth:
        jwt = auth["jwt_config"]
        print(f"   JWT Algorithm: {jwt.get('algorithm')}")
        print(f"   Access Token Expiry: {jwt.get('access_token_expire_minutes')} minutes")
        print(f"   Refresh Token Expiry: {jwt.get('refresh_token_expire_days')} days")

    if "password_hashing" in auth:
        pw = auth["password_hashing"]
        print(f"   Password Hashing: {pw.get('algorithm')} ({pw.get('rounds')} rounds)")

    if "oauth_providers" in auth:
        providers = auth["oauth_providers"]
        print(f"   OAuth Providers: {', '.join(providers)}")

    # CORS
    cors = security.get("cors", {})
    print("\n🌐 CORS:")
    origins = cors.get("allow_origins", [])
    print(f"   Allowed Origins: {', '.join(origins)}")
    print(f"   Allow Credentials: {cors.get('allow_credentials')}")

    # Rate Limiting
    rate = security.get("rate_limiting", {})
    if rate.get("enabled"):
        print("\n⏱️  Rate Limiting:")
        print(f"   Requests/Minute: {rate.get('requests_per_minute')}")
        print(f"   Burst Size: {rate.get('burst_size', 'N/A')}")

    # Input Validation
    validation = security.get("input_validation", {})
    if validation:
        print("\n✓ Input Validation:")
        print(f"   Sanitize HTML: {validation.get('sanitize_html')}")
        print(f"   Max Request Size: {validation.get('max_request_size_mb')} MB")


def _show_infrastructure(arch):
    """Show infrastructure components."""
    print("\n" + "=" * 60)
    print("INFRASTRUCTURE")
    print("=" * 60)

    infra = arch.get("infrastructure", {})

    print("\n🖥️  Servers:")
    print(f"   Web Server: {infra.get('web_server', 'N/A')}")
    print(f"   App Server: {infra.get('app_server', 'N/A')}")
    print(f"   Workers: {infra.get('workers_per_instance', 'N/A')} per instance")

    redis = infra.get("redis", {})
    if redis.get("enabled"):
        print("\n💾 Redis:")
        use_cases = redis.get("use_cases", [])
        print(f"   Use Cases: {', '.join(use_cases)}")

    ssl = infra.get("ssl", {})
    if ssl.get("enabled"):
        print("\n🔒 SSL/TLS:")
        print(f"   Provider: {ssl.get('provider', 'N/A')}")

    monitoring = infra.get("monitoring", {})
    if monitoring.get("enabled"):
        print("\n📊 Monitoring:")
        tools = monitoring.get("tools", [])
        print(f"   Tools: {', '.join(tools)}")


def _show_frontend(arch):
    """Show frontend architecture."""
    print("\n" + "=" * 60)
    print("FRONTEND ARCHITECTURE")
    print("=" * 60)

    frontend = arch.get("frontend", {})
    framework = frontend.get("framework", 'N/A')

    print(f"\n🎨 Framework: {framework}")

    pages = frontend.get("pages", [])
    print(f"\nPages ({len(pages)}):")

    for page in pages:
        name = page.get("name")
        route = page.get("route")
        template = page.get("template_file", 'N/A')
        auth = "🔒" if page.get("auth_required") else "🌐"

        print(f"\n  {auth} {name}")
        print(f"     Route: {route}")
        print(f"     Template: {template}")

        components = page.get("components", [])
        if components:
            print(f"     Components: {', '.join(components)}")

        api_deps = page.get("api_dependencies", [])
        if api_deps:
            print(f"     APIs: {', '.join(api_deps)}")

    static = frontend.get("static_assets", {})
    if static:
        print(f"\n📦 Static Assets:")
        print(f"   CSS Framework: {static.get('css_framework', 'N/A')}")
        libs = static.get("js_libraries", [])
        print(f"   JS Libraries: {', '.join(libs)}")


def _show_deployment_plan(arch):
    """Show deployment plan."""
    print("\n" + "=" * 60)
    print("DEPLOYMENT PLAN")
    print("=" * 60)

    plan = arch.get("deployment_plan", [])

    if not plan:
        print("\nNo deployment plan generated.")
        return

    print(f"\nTotal steps: {len(plan)}\n")

    total_time = sum(step.get("estimated_duration_seconds", 0) for step in plan)
    print(f"Estimated total time: {total_time // 60} minutes {total_time % 60} seconds\n")

    for step_info in plan:
        step_num = step_info.get("step")
        name = step_info.get("name")
        description = step_info.get("description", "")
        duration = step_info.get("estimated_duration_seconds", 0)

        print(f"[{step_num}] {name} ({duration}s)")
        if description:
            print(f"    {description}")

        commands = step_info.get("commands", [])
        if commands:
            print(f"    Commands:")
            for cmd in commands[:3]:  # Show first 3
                print(f"      $ {cmd}")
            if len(commands) > 3:
                print(f"      ... and {len(commands) - 3} more")

        print()


def _compare_with_requirements(requirements, architecture):
    """Compare architecture with original requirements."""
    print("\n" + "=" * 60)
    print("REQUIREMENTS vs ARCHITECTURE COMPARISON")
    print("=" * 60)

    # Feature coverage
    req_features = requirements.get("features", {})
    print("\n✅ Feature Coverage:")

    if req_features.get("authentication", {}).get("enabled"):
        endpoints = [ep["path"] for ep in architecture.get("api_endpoints", [])]
        has_auth = any("/auth/" in path for path in endpoints)
        status = "✅" if has_auth else "❌"
        print(f"  {status} Authentication endpoints")

    if req_features.get("background_workers", {}).get("enabled"):
        workers = architecture.get("workers", [])
        status = "✅" if workers else "❌"
        print(f"  {status} Background workers ({len(workers)} defined)")

    if req_features.get("llm_chat", {}).get("enabled"):
        # Check for LLM-related endpoints or workers
        print(f"  ℹ️  LLM chat integration (check manually)")

    # Model coverage
    req_models = requirements.get("database", {}).get("models", [])
    arch_tables = architecture.get("database_schema", {}).get("tables", [])

    print(f"\n📊 Database Models:")
    print(f"  Required: {len(req_models)} models")
    print(f"  Generated: {len(arch_tables)} tables")

    # Page coverage
    req_pages = requirements.get("ui_pages", [])
    arch_pages = architecture.get("frontend", {}).get("pages", [])

    print(f"\n🎨 UI Pages:")
    print(f"  Required: {len(req_pages)} pages")
    print(f"  Generated: {len(arch_pages)} pages")


if __name__ == "__main__":
    main()
