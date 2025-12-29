#!/usr/bin/env python3
"""
Test Website Deployer with User Profile Website
=================================================

Tests the full pipeline with the user's specific requirement:
A user profile management website with login/register, sidebar, header, footer layout.

Usage:
    python test_user_profile_website.py --dry-run  # Test without LLM calls
    python test_user_profile_website.py            # Full test with LLM
"""

import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from stages import RequirementAnalyzer, ArchitectureDesigner, IntelligentCodeGeneratorWrapper

# User's specification
USER_SPEC = """
Create a full functioning website with friendly and beautifully designed interface.
The frontend is HTML/JavaScript/CSS while the backend is Apache2/PHP/MySQL.
Security is SSL/HTTPS, landing page is Login or register for new users.
The opening page is made of left sidebar, header bar and footer bar while the main
pane is where the message and input forms are displayed. For this website, it has
only one form: User profile filled by the logged in user (first and last names,
email, phone, address, a short bio).
"""

def test_requirement_analysis():
    """Test Phase 1: Requirements Analysis"""
    print("\n" + "=" * 80)
    print("PHASE 1: REQUIREMENTS ANALYSIS")
    print("=" * 80)
    print(f"\nSpecification:\n{USER_SPEC}\n")

    analyzer = RequirementAnalyzer()
    result = analyzer.analyze(USER_SPEC)

    if not result.success:
        print(f"❌ FAILED: {result.error_message}")
        return None

    print("✅ Requirements extracted successfully!")
    print(f"\nProject: {result.requirements.get('project_name')}")
    print(f"Tech Stack: {result.requirements.get('tech_stack', {}).get('backend')}")
    print(f"Database: {result.requirements.get('tech_stack', {}).get('database')}")
    print(f"Authentication: {result.requirements.get('authentication', {}).get('required')}")

    print(f"\nFeatures:")
    for feature in result.requirements.get('features', []):
        if isinstance(feature, dict):
            print(f"  • {feature.get('name')}")
        else:
            print(f"  • {feature}")

    print(f"\nDatabase Models:")
    for model in result.requirements.get('database_models', []):
        if isinstance(model, dict):
            fields = model.get('fields', [])
            field_names = [f.get('name') if isinstance(f, dict) else str(f) for f in fields]
            print(f"  • {model.get('name')}: {', '.join(field_names)}")
        else:
            print(f"  • {model}")

    print(f"\nUI Pages:")
    for page in result.requirements.get('ui_pages', []):
        if isinstance(page, dict):
            print(f"  • {page.get('name')} - {page.get('route')}")
        else:
            print(f"  • {page}")

    # Save requirements for next phase
    with open('test_requirements.json', 'w') as f:
        json.dump(result.requirements, f, indent=2)
    print(f"\n💾 Saved to: test_requirements.json")

    return result.requirements


def test_architecture_design(requirements):
    """Test Phase 2: Architecture Design"""
    print("\n" + "=" * 80)
    print("PHASE 2: ARCHITECTURE DESIGN")
    print("=" * 80)

    designer = ArchitectureDesigner()
    result = designer.design(requirements)

    if not result.success:
        print(f"❌ FAILED: {result.error_message}")
        return None

    print("✅ Architecture designed successfully!")

    arch = result.architecture
    print(f"\nAPI Endpoints: {len(arch.get('api', {}).get('endpoints', []))}")
    for endpoint in arch.get('api', {}).get('endpoints', [])[:5]:  # Show first 5
        print(f"  • {endpoint.get('method', 'GET')} {endpoint.get('path')}")

    print(f"\nDatabase Tables: {len(arch.get('database', {}).get('tables', []))}")
    for table in arch.get('database', {}).get('tables', []):
        print(f"  • {table.get('name')}")

    print(f"\nFrontend Pages: {len(arch.get('frontend', {}).get('pages', []))}")
    for page in arch.get('frontend', {}).get('pages', []):
        print(f"  • {page.get('name')} - {page.get('file_path')}")

    # Save architecture for next phase
    with open('test_architecture.json', 'w') as f:
        json.dump(arch, f, indent=2)
    print(f"\n💾 Saved to: test_architecture.json")

    return arch


def test_code_generation(requirements, architecture):
    """Test Phase 3: Code Generation"""
    print("\n" + "=" * 80)
    print("PHASE 3: CODE GENERATION")
    print("=" * 80)

    # Add original spec for intelligent generator
    requirements["original_specification"] = USER_SPEC

    generator = IntelligentCodeGeneratorWrapper(
        output_base_dir=Path("test_output"),
        response_cache_path="test_llm_cache.json"
    )

    result = generator.generate(requirements, architecture)

    if not result.success:
        print(f"❌ FAILED: {result.error_message}")
        return None

    print("✅ Code generated successfully!")
    print(f"\nOutput Directory: {result.output_directory}")

    summary = result.generation_summary
    print(f"\nGeneration Summary:")
    print(f"  • Files generated: {summary.get('files_generated', 0)}")
    print(f"  • API endpoints: {summary.get('components', {}).get('api_endpoints', 0)}")
    print(f"  • Database tables: {summary.get('components', {}).get('database_tables', 0)}")
    print(f"  • Frontend pages: {summary.get('components', {}).get('frontend_pages', 0)}")

    # List generated files
    if result.output_directory:
        import os
        print(f"\n📁 Generated Files:")
        for root, dirs, files in os.walk(result.output_directory):
            level = root.replace(str(result.output_directory), '').count(os.sep)
            indent = ' ' * 2 * level
            print(f'{indent}{os.path.basename(root)}/')
            subindent = ' ' * 2 * (level + 1)
            for file in files[:10]:  # Limit to first 10 per directory
                print(f'{subindent}{file}')
            if len(files) > 10:
                print(f'{subindent}... and {len(files) - 10} more files')
            if level > 2:  # Limit depth
                break

    return result


def main():
    """Run complete test pipeline"""
    import argparse

    parser = argparse.ArgumentParser(description="Test Website Deployer with User Profile Website")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls and use cached data")
    parser.add_argument("--phase", choices=["1", "2", "3", "all"], default="all",
                       help="Which phase to test (default: all)")
    args = parser.parse_args()

    print("=" * 80)
    print("WEBSITE DEPLOYER AGENT - USER PROFILE WEBSITE TEST")
    print("=" * 80)

    if args.dry_run:
        print("\n⚠️  DRY-RUN MODE: Using cached data if available")

    requirements = None
    architecture = None

    # Phase 1: Requirements
    if args.phase in ["1", "all"]:
        if args.dry_run and Path("test_requirements.json").exists():
            print("\n📂 Loading cached requirements...")
            with open("test_requirements.json") as f:
                requirements = json.load(f)
            print("✅ Loaded from cache")
        else:
            requirements = test_requirement_analysis()
            if not requirements:
                return 1

    # Phase 2: Architecture
    if args.phase in ["2", "all"]:
        if not requirements:
            if Path("test_requirements.json").exists():
                with open("test_requirements.json") as f:
                    requirements = json.load(f)
            else:
                print("❌ No requirements found. Run phase 1 first.")
                return 1

        if args.dry_run and Path("test_architecture.json").exists():
            print("\n📂 Loading cached architecture...")
            with open("test_architecture.json") as f:
                architecture = json.load(f)
            print("✅ Loaded from cache")
        else:
            architecture = test_architecture_design(requirements)
            if not architecture:
                return 1

    # Phase 3: Code Generation
    if args.phase in ["3", "all"]:
        if not requirements or not architecture:
            if Path("test_requirements.json").exists() and Path("test_architecture.json").exists():
                with open("test_requirements.json") as f:
                    requirements = json.load(f)
                with open("test_architecture.json") as f:
                    architecture = json.load(f)
            else:
                print("❌ Missing requirements or architecture. Run phases 1-2 first.")
                return 1

        result = test_code_generation(requirements, architecture)
        if not result:
            return 1

    print("\n" + "=" * 80)
    print("✅ ALL TESTS PASSED!")
    print("=" * 80)
    print("\nNext steps:")
    print("  1. Review generated code in test_output/")
    print("  2. Run deployment with: python examples/full_deployment_demo.py")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
