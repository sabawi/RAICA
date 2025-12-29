#!/usr/bin/env python3
"""
Complete Pipeline Demo
=======================

Demonstrates the full end-to-end pipeline from natural language
specification to generated production-ready code.

Pipeline:
1. Natural Language Specification → Requirements (Phase 2)
2. Requirements → Architecture (Phase 3)
3. Architecture → Production Code (Phase 4-5)

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python examples/complete_pipeline_demo.py

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from stages import RequirementAnalyzer, ArchitectureDesigner, CodeGenerator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Run complete deployment pipeline demo."""
    print("=" * 80)
    print("WEBSITE DEPLOYMENT AGENT - COMPLETE PIPELINE DEMO")
    print("=" * 80)
    print()
    print("This demo will:")
    print("  1. Analyze a natural language specification")
    print("  2. Design technical architecture")
    print("  3. Generate production-ready code")
    print()

    # Multi-provider LLM system
    print("\nUsing multi-provider LLM system")
    print("Provider: Configured in /config/llm_config.yaml\n")

    # Example specification
    spec = """
    Build a simple blog platform where users can:
    - Register and log in with email/password
    - Create, edit, and publish blog posts
    - Add comments to posts
    - Upload header images for posts

    Each post should have:
    - Title (required)
    - Content (markdown)
    - Author
    - Published date
    - Status (draft/published)

    Users should be able to view all published posts and their own drafts.
    Email notifications when someone comments on their post.
    """

    print("📝 SPECIFICATION:")
    print("-" * 80)
    print(spec)
    print("-" * 80)
    print()

    input("Press Enter to start the pipeline...")

    # Phase 1: Requirements Analysis
    print("\n" + "=" * 80)
    print("PHASE 1: REQUIREMENTS ANALYSIS")
    print("=" * 80)

    analyzer = RequirementAnalyzer()
    req_result = analyzer.analyze(spec)

    if not req_result.success:
        print(f"\n❌ Requirements analysis failed: {req_result.error_message}")
        return

    print("\n✅ Requirements analysis complete!")
    requirements = req_result.requirements
    print(f"   Project: {requirements['project_name']}")
    print(f"   Complexity: {requirements['complexity_estimate']}")
    print(f"   Models: {len(requirements['database']['models'])}")

    # Phase 2: Architecture Design
    print("\n" + "=" * 80)
    print("PHASE 2: ARCHITECTURE DESIGN")
    print("=" * 80)

    designer = ArchitectureDesigner()
    arch_result = designer.design(requirements)

    if not arch_result.success:
        print(f"\n❌ Architecture design failed: {arch_result.error_message}")
        return

    print("\n✅ Architecture design complete!")
    architecture = arch_result.architecture
    print(f"   API Endpoints: {len(architecture['api_endpoints'])}")
    print(f"   Database Tables: {len(architecture['database_schema']['tables'])}")
    print(f"   Workers: {len(architecture.get('workers', []))}")

    # Phase 3: Code Generation
    print("\n" + "=" * 80)
    print("PHASE 3: CODE GENERATION")
    print("=" * 80)

    generator = CodeGenerator(output_base_dir=Path("generated_projects"))
    code_result = generator.generate(requirements, architecture)

    if not code_result.success:
        print(f"\n❌ Code generation failed: {code_result.error_message}")
        return

    print("\n✅ Code generation complete!")
    print(f"   Output: {code_result.output_directory}")
    print(f"   Files Generated: {len(code_result.files_generated)}")

    # Summary
    print("\n" + "=" * 80)
    print("PIPELINE COMPLETE!")
    print("=" * 80)

    summary = code_result.generation_summary
    print(f"\n📦 Project: {summary['project_name']}")
    print(f"📁 Location: {summary['output_directory']}")
    print(f"\n📊 Generated Components:")
    print(f"   • {summary['components']['api_endpoints']} API endpoints")
    print(f"   • {summary['components']['database_tables']} database tables")
    print(f"   • {summary['components']['workers']} background workers")
    print(f"   • {summary['components']['frontend_pages']} frontend pages")
    print(f"   • {summary['files_generated']} total files")

    print(f"\n✨ Features:")
    features = summary['features']
    print(f"   • Authentication: {'✅' if features['authentication'] else '❌'}")
    print(f"   • Background Workers: {'✅' if features['workers'] else '❌'}")
    print(f"   • Frontend: {'✅' if features['frontend'] else '❌'}")

    print(f"\n🚀 Next Steps:")
    project_path = code_result.output_directory
    print(f"\n1. Navigate to project:")
    print(f"   cd {project_path}")
    print(f"\n2. Create virtual environment:")
    print(f"   python -m venv venv")
    print(f"   source venv/bin/activate")
    print(f"\n3. Install dependencies:")
    print(f"   pip install -r requirements.txt")
    print(f"\n4. Configure environment:")
    print(f"   cp .env.example .env")
    print(f"   # Edit .env with your settings")
    print(f"\n5. Setup database:")
    print(f"   alembic upgrade head")
    print(f"\n6. Run development server:")
    print(f"   uvicorn app.main:app --reload")
    print(f"\n7. View API docs:")
    print(f"   http://localhost:8000/docs")

    print("\n" + "=" * 80)
    print("Pipeline completed successfully! 🎉")
    print("=" * 80)


if __name__ == "__main__":
    main()
