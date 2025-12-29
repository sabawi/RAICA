#!/usr/bin/env python3
"""
Comprehensive Dry Test Run for Website Deployment Agent
========================================================

Tests the complete pipeline from natural language to deployment orchestration
without actually deploying to a server.

Phases tested:
1. Requirements Analysis (with real LLM)
2. Architecture Design (with real LLM)
3. Code Generation (real file generation)
4. Deployment Orchestration (logic only, no SSH)

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test results tracking
test_results = {
    "phase_2_requirements": {"status": "pending", "errors": []},
    "phase_3_architecture": {"status": "pending", "errors": []},
    "phase_4_5_code_generation": {"status": "pending", "errors": []},
    "phase_6_7_deployment_logic": {"status": "pending", "errors": []},
}


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_subsection(title: str):
    """Print a formatted subsection header."""
    print(f"\n--- {title} ---")


def test_phase_2_requirements():
    """Test Phase 2: Requirements Analysis."""
    print_section("PHASE 2: REQUIREMENTS ANALYSIS")

    try:
        # Test import
        try:
            from stages import RequirementAnalyzer
            print("✅ RequirementAnalyzer imported successfully")
        except ImportError as e:
            logger.error(f"❌ Import failed: {e}")
            logger.info("   Install dependencies: pip install -r requirements.txt")
            test_results["phase_2_requirements"]["status"] = "failed"
            test_results["phase_2_requirements"]["errors"].append(f"Import error: {e}")
            return None

        # Check API key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("⚠️  ANTHROPIC_API_KEY not set - skipping LLM test")
            logger.info("   Testing imports and structure only...")
            test_results["phase_2_requirements"]["status"] = "skipped"
            return None

        # Simple test specification
        spec = """
        Build a simple task management app where users can:
        - Register and log in
        - Create and edit tasks
        - Mark tasks as complete

        Each task has a title, description, and due date.
        """

        print_subsection("Test Specification")
        print(spec)

        print_subsection("Running Analysis")
        analyzer = RequirementAnalyzer()
        result = analyzer.analyze(spec)

        if not result.success:
            raise Exception(f"Analysis failed: {result.error_message}")

        requirements = result.requirements

        print_subsection("Requirements Summary")
        print(f"✅ Project Name: {requirements.get('project_name', 'N/A')}")
        print(f"✅ Description: {requirements.get('description', 'N/A')[:100]}...")
        print(f"✅ Complexity: {requirements.get('complexity_estimate', 'N/A')}")
        print(f"✅ Models: {len(requirements.get('database', {}).get('models', []))}")
        print(f"✅ Features: {len(requirements.get('features', []))}")

        # Validate schema
        print_subsection("Schema Validation")
        required_keys = ['project_name', 'description', 'features', 'database', 'ui_pages']
        missing_keys = [key for key in required_keys if key not in requirements]

        if missing_keys:
            raise Exception(f"Missing required keys: {missing_keys}")

        print("✅ Schema validation passed")

        test_results["phase_2_requirements"]["status"] = "passed"
        return requirements

    except Exception as e:
        logger.error(f"❌ Phase 2 failed: {e}")
        test_results["phase_2_requirements"]["status"] = "failed"
        test_results["phase_2_requirements"]["errors"].append(str(e))
        import traceback
        traceback.print_exc()
        return None


def test_phase_3_architecture(requirements: Dict[str, Any]):
    """Test Phase 3: Architecture Design."""
    print_section("PHASE 3: ARCHITECTURE DESIGN")

    if not requirements:
        logger.warning("⚠️  Skipping - no requirements from Phase 2")
        test_results["phase_3_architecture"]["status"] = "skipped"
        return None

    try:
        from stages import ArchitectureDesigner

        # Check API key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("⚠️  ANTHROPIC_API_KEY not set - skipping")
            test_results["phase_3_architecture"]["status"] = "skipped"
            return None

        print_subsection("Running Architecture Design")
        designer = ArchitectureDesigner()
        result = designer.design(requirements)

        if not result.success:
            raise Exception(f"Design failed: {result.error_message}")

        architecture = result.architecture

        print_subsection("Architecture Summary")
        print(f"✅ API Endpoints: {len(architecture.get('api_endpoints', []))}")
        print(f"✅ Database Tables: {len(architecture.get('database_schema', {}).get('tables', []))}")
        print(f"✅ Workers: {len(architecture.get('workers', []))}")
        print(f"✅ Security Config: {bool(architecture.get('security'))}")

        # Validate schema
        print_subsection("Schema Validation")
        required_keys = ['api_endpoints', 'database_schema', 'security', 'infrastructure']
        missing_keys = [key for key in required_keys if key not in architecture]

        if missing_keys:
            raise Exception(f"Missing required keys: {missing_keys}")

        # Check API endpoints structure
        if architecture.get('api_endpoints'):
            endpoint = architecture['api_endpoints'][0]
            required_endpoint_keys = ['method', 'path', 'handler_name', 'description']
            missing_endpoint_keys = [key for key in required_endpoint_keys if key not in endpoint]
            if missing_endpoint_keys:
                raise Exception(f"API endpoint missing keys: {missing_endpoint_keys}")

        print("✅ Schema validation passed")

        test_results["phase_3_architecture"]["status"] = "passed"
        return architecture

    except Exception as e:
        logger.error(f"❌ Phase 3 failed: {e}")
        test_results["phase_3_architecture"]["status"] = "failed"
        test_results["phase_3_architecture"]["errors"].append(str(e))
        import traceback
        traceback.print_exc()
        return None


def test_phase_4_5_code_generation(requirements: Dict[str, Any], architecture: Dict[str, Any]):
    """Test Phase 4-5: Code Generation."""
    print_section("PHASE 4-5: CODE GENERATION")

    if not requirements or not architecture:
        logger.warning("⚠️  Skipping - no requirements or architecture")
        test_results["phase_4_5_code_generation"]["status"] = "skipped"
        return None

    try:
        from stages import CodeGenerator

        print_subsection("Running Code Generation")
        output_dir = Path("test_generated_project")
        generator = CodeGenerator(output_base_dir=output_dir)

        result = generator.generate(requirements, architecture)

        if not result.success:
            raise Exception(f"Generation failed: {result.error_message}")

        print_subsection("Code Generation Summary")
        print(f"✅ Output Directory: {result.output_directory}")
        print(f"✅ Files Generated: {result.generation_summary.get('files_generated', 0)}")

        # Verify critical files exist
        print_subsection("File Verification")
        project_dir = result.output_directory

        critical_files = [
            "app/main.py",
            "app/core/config.py",
            "app/models/__init__.py",
            "app/api/__init__.py",
            "requirements.txt",
            "README.md",
        ]

        missing_files = []
        for file_path in critical_files:
            full_path = project_dir / file_path
            if full_path.exists():
                print(f"✅ {file_path}")
            else:
                print(f"❌ {file_path} - MISSING")
                missing_files.append(file_path)

        if missing_files:
            raise Exception(f"Missing critical files: {missing_files}")

        # Check main.py has valid Python syntax
        print_subsection("Python Syntax Check")
        main_py = project_dir / "app" / "main.py"
        with open(main_py, 'r') as f:
            main_content = f.read()

        try:
            compile(main_content, str(main_py), 'exec')
            print("✅ app/main.py has valid Python syntax")
        except SyntaxError as e:
            raise Exception(f"Syntax error in app/main.py: {e}")

        test_results["phase_4_5_code_generation"]["status"] = "passed"
        return result

    except Exception as e:
        logger.error(f"❌ Phase 4-5 failed: {e}")
        test_results["phase_4_5_code_generation"]["status"] = "failed"
        test_results["phase_4_5_code_generation"]["errors"].append(str(e))
        import traceback
        traceback.print_exc()
        return None


def test_phase_6_7_deployment_logic(requirements: Dict[str, Any], architecture: Dict[str, Any], code_result):
    """Test Phase 6-7: Deployment Logic (without actual SSH)."""
    print_section("PHASE 6-7: DEPLOYMENT LOGIC")

    if not requirements or not architecture or not code_result:
        logger.warning("⚠️  Skipping - missing previous phase results")
        test_results["phase_6_7_deployment_logic"]["status"] = "skipped"
        return

    try:
        # Test import of deployment modules
        print_subsection("Import Tests")

        from stages import DeploymentOrchestrator
        print("✅ DeploymentOrchestrator imported")

        from stages.deployment_modules.file_transfer import FileTransfer
        print("✅ FileTransfer imported")

        from stages.deployment_modules.package_installer import PackageInstaller
        print("✅ PackageInstaller imported")

        from stages.deployment_modules.database_setup import DatabaseSetup
        print("✅ DatabaseSetup imported")

        from stages.deployment_modules.nginx_configurator import NginxConfigurator
        print("✅ NginxConfigurator imported")

        from stages.deployment_modules.ssl_setup import SSLSetup
        print("✅ SSLSetup imported")

        from stages.deployment_modules.systemd_service import SystemdService
        print("✅ SystemdService imported")

        # Test class instantiation (without SSH connection)
        print_subsection("Class Instantiation Tests")

        # We can't instantiate DeploymentOrchestrator without SSH manager
        # But we can check the class exists and has required methods
        required_methods = ['deploy', '_setup_virtualenv', '_install_python_dependencies',
                           '_run_migrations', '_start_and_verify']

        for method_name in required_methods:
            if not hasattr(DeploymentOrchestrator, method_name):
                raise Exception(f"DeploymentOrchestrator missing method: {method_name}")
            print(f"✅ DeploymentOrchestrator.{method_name} exists")

        # Check deployment modules have required methods
        print_subsection("Module Method Verification")

        # Map class names to actual class objects (imported locally above)
        classes = {
            'FileTransfer': FileTransfer,
            'PackageInstaller': PackageInstaller,
            'DatabaseSetup': DatabaseSetup,
            'NginxConfigurator': NginxConfigurator,
            'SSLSetup': SSLSetup,
            'SystemdService': SystemdService,
        }

        module_methods = {
            'FileTransfer': ['transfer'],
            'PackageInstaller': ['install'],
            'DatabaseSetup': ['configure'],
            'NginxConfigurator': ['configure'],
            'SSLSetup': ['setup'],
            'SystemdService': ['create'],
        }

        for class_name, methods in module_methods.items():
            cls = classes[class_name]
            for method in methods:
                if not hasattr(cls, method):
                    raise Exception(f"{class_name} missing method: {method}")
                print(f"✅ {class_name}.{method} exists")

        print_subsection("Deployment Result Structure Test")
        from stages.deployment_orchestrator import DeploymentResult

        # Create a test result
        test_result = DeploymentResult(
            success=True,
            deployment_url="http://test.example.com",
            steps_completed=["step1", "step2"],
            error_message=None,
            error_step=None
        )

        print(f"✅ DeploymentResult.success: {test_result.success}")
        print(f"✅ DeploymentResult.deployment_url: {test_result.deployment_url}")
        print(f"✅ DeploymentResult.steps_completed: {len(test_result.steps_completed)}")

        test_results["phase_6_7_deployment_logic"]["status"] = "passed"

    except Exception as e:
        logger.error(f"❌ Phase 6-7 failed: {e}")
        test_results["phase_6_7_deployment_logic"]["status"] = "failed"
        test_results["phase_6_7_deployment_logic"]["errors"].append(str(e))
        import traceback
        traceback.print_exc()


def print_final_report():
    """Print final test report."""
    print_section("TEST SUMMARY")

    total_tests = len(test_results)
    passed = sum(1 for r in test_results.values() if r["status"] == "passed")
    failed = sum(1 for r in test_results.values() if r["status"] == "failed")
    skipped = sum(1 for r in test_results.values() if r["status"] == "skipped")

    print(f"\nTotal Tests: {total_tests}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"⚠️  Skipped: {skipped}")

    print("\nDetailed Results:")
    print("-" * 80)

    for phase_name, result in test_results.items():
        status_icon = {
            "passed": "✅",
            "failed": "❌",
            "skipped": "⚠️",
            "pending": "⏳"
        }.get(result["status"], "❓")

        print(f"\n{status_icon} {phase_name.replace('_', ' ').upper()}: {result['status'].upper()}")

        if result["errors"]:
            print("   Errors:")
            for error in result["errors"]:
                print(f"     - {error}")

    print("\n" + "=" * 80)

    if failed > 0:
        print("\n❌ TEST RUN FAILED - Bugs found!")
        return False
    elif skipped == total_tests:
        print("\n⚠️  ALL TESTS SKIPPED - Set ANTHROPIC_API_KEY to run full tests")
        return False
    else:
        print("\n✅ TEST RUN PASSED - No bugs found!")
        return True


def main():
    """Run complete dry test."""
    print("=" * 80)
    print("WEBSITE DEPLOYMENT AGENT - DRY TEST RUN")
    print("=" * 80)
    print()
    print("This test will exercise all phases of the deployment agent")
    print("without actually deploying to a server.")
    print()
    print("Requirements:")
    print("  - ANTHROPIC_API_KEY environment variable (for LLM phases)")
    print()

    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️  WARNING: ANTHROPIC_API_KEY not set")
        print("   Tests will be limited to import and structure validation")
        print()

    # Skip input if running non-interactively or with --auto flag
    if sys.stdin.isatty() and "--auto" not in sys.argv:
        input("Press Enter to start dry test run...")
    else:
        print("Starting automated test run...")
        print()

    try:
        # Phase 2: Requirements Analysis
        requirements = test_phase_2_requirements()

        # Phase 3: Architecture Design
        architecture = test_phase_3_architecture(requirements)

        # Phase 4-5: Code Generation
        code_result = test_phase_4_5_code_generation(requirements, architecture)

        # Phase 6-7: Deployment Logic
        test_phase_6_7_deployment_logic(requirements, architecture, code_result)

        # Print final report
        success = print_final_report()

        # Exit with appropriate code
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n❌ Test run cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
